import discord
import os
import json
import re
import time
from collections import Counter
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from discord import app_commands
from datetime import datetime, timedelta

# --- Keep-alive Server ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

    def do_HEAD(self):
        """Handle HEAD requests from Render's health checker"""
        self.send_response(200)
        self.end_headers()

def run_health_check():
    try:
        server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
        server.serve_forever()
    except OSError as e:
        if e.errno == 98:
            print("Health check server already running, skipping bind.")
        else:
            raise e
# Start the health check in a separate thread
Thread(target=run_health_check, daemon=True).start()


hUIPJ21boH = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
# --- NEW: Enable Invite Tracking Intent ---
intents.invites = True 

bot = discord.Client(intents=intents)

# For slash commands
tree = app_commands.CommandTree(bot)

ANNOUNCE_CHANNEL_ID = 1458464867366342809
REPORT_CHANNEL_ID = 1468224442089079071
WARN_LOG_CHANNEL_ID = 1469023340130861179
INVITE_LOG_CHANNEL_ID = 1469126718425006332

# --- Invite Tracker Cache ---
invites_cache = {}

# --- Swear tracking config ---
# MongoDB connection (set MONGODB_URI environment variable)
MONGO_URI = os.getenv("MONGODB_URI")
# Default words to seed the swear list (lowercase)
DEFAULT_SWEAR_WORDS = ["fuck", "shit", "bitch", "ass", "damn", "gago"]
# Fallback JSON file for swear word list when MongoDB is not available
SWEAR_WORDS_FILE = "swear_words.json"

# Try to connect to MongoDB (pymongo); fall back to local JSON if unavailable
try:
    from pymongo import MongoClient
    if MONGO_URI:
        client = MongoClient(MONGO_URI)
        db = client.get_database(os.getenv("MONGO_DB"))
        coll = db[os.getenv("MONGO_COLLECTION")]
        print("Connected to MongoDB")
    else:
        coll = None
        print("MONGODB_URI not set; using local JSON fallback.")
except ImportError:
    coll = None
    print("pymongo not installed; using local JSON fallback. Run: pip install pymongo")

# Authorized Role IDs
AUTHORIZED_ROLES = [
    1458454264702832792, 
    1458455202892877988, 
    1458490049413906553, 
    1458456130195034251, 
    1458455703638376469
]

RULES_DATA = {
    "ARTICLE 1: Core Conduct": {
        "1.1 Respect Boundaries": "No harassment, unwanted DMs, or 'stalking' behaviors.",
        "1.2 Zero Tolerance": "Instant bans for hate speech, slurs, or discriminatory content.",
        "1.3 No Drama": "Keep personal arguments in DMs; do not disrupt public channels.",
        "1.4 Discord TOS": "All members/user must follow Discord Terms of Service"
    },
    "ARTICLE 2: Communication Etiquette": {
        "2.1 Channel Clarity": "Use channels for their intended purpose (e.g., memes in #memes).",
        "2.2 Ping Policy": "Do not use @everyone or @here without a valid reason or staff permission.",
        "2.3 VC Etiquette": "No ear-rape, screaming, or excessive noise. Use Push-to-Talk if needed.",
        "2.4 Advertising": "No Unauthorized Advertising: Do not post server invites or social media links without staff approval."
    },
    "ARTICLE 3: Safety & Integrity": {
        "3.1 Age Limit": "Users must be 13+ (or 18+ for adult-designated servers).",
        "3.2 NSFW Content": "Forbidden in public areas; only allowed in age-restricted channels.",
        "3.3 Anti-Scam": "Sharing 'Free Nitro' links or suspicious downloads results in an instant ban.",
        "3.4 No Ban Evasion": "Using alternate accounts to bypass bans or timeouts is prohibited.",
        "3.5 Consent First": "Never share a friend's real name, location, or photo without permission.",
        "3.6 Common Sense": "Just because something isn't explicitly written doesn't mean it’s allowed."
    },
    "ARTICLE 4: Admin Authority": {
        "4.1 Staff Discretion": "Moderators have the final say on behavior not explicitly listed.",
        "4.2 Conflict of Interest": "Staff must recuse themselves from cases involving close friends.",
        "4.3 Evidence-Based": "All bans and kicks must be backed by logged evidence.",
        "4.4 Internal Privacy": "Staff-room discussions are strictly confidential.",
        "4.5 Transparency": "Staff must clearly cite the rule violated when taking action.",
        "4.6 Power Tripping": "Avoid using staff-only permissions for jokes or to win arguments."
    }
}

def is_owner(user_id: int):
    """Checks if the User ID is one of the two authorized owners."""
    return user_id in [1394914695600934932, 912385288129622147]

def has_permission(member: discord.Member):
    """Checks if the member has any of the authorized roles."""
    return any(role.id in AUTHORIZED_ROLES for role in member.roles)

DATA_FILE = "swear_data.json"

def load_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# Swear words storage (MongoDB collection or local JSON fallback)
if 'db' in globals() and db is not None:
    swear_words_coll = db[os.getenv("MONGO_SWEAR_COLLECTION")]
else:
    swear_words_coll = None

# In-memory cache to avoid repeated DB reads
_swear_cache = None

def init_swear_words():
    """Ensure swear words storage is seeded with defaults."""
    global _swear_cache
    if swear_words_coll is not None:
        doc = swear_words_coll.find_one({"_id": "words"})
        if not doc:
            swear_words_coll.insert_one({"_id": "words", "words": DEFAULT_SWEAR_WORDS})
            _swear_cache = list(DEFAULT_SWEAR_WORDS)
            print("Seeded swear words in MongoDB")
        else:
            _swear_cache = list(doc.get("words", []))
    else:
        # Ensure local file exists
        try:
            with open(SWEAR_WORDS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                _swear_cache = list(data.get("words", DEFAULT_SWEAR_WORDS))
        except FileNotFoundError:
            with open(SWEAR_WORDS_FILE, "w", encoding="utf-8") as f:
                json.dump({"words": DEFAULT_SWEAR_WORDS}, f, ensure_ascii=False, indent=2)
            _swear_cache = list(DEFAULT_SWEAR_WORDS)
            print("Seeded local swear words file")


def get_swear_words():
    """Return the current list of swear words (lowercase)."""
    global _swear_cache
    if _swear_cache is not None:
        return _swear_cache
    # Cache miss: load from source
    if swear_words_coll is not None:
        doc = swear_words_coll.find_one({"_id": "words"})
        words = doc.get("words", []) if doc else []
        _swear_cache = list(words)
        return _swear_cache
    else:
        try:
            with open(SWEAR_WORDS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                _swear_cache = list(data.get("words", []))
                return _swear_cache
        except FileNotFoundError:
            _swear_cache = list(DEFAULT_SWEAR_WORDS)
            return _swear_cache

def add_swear_word(word: str):
    word = word.lower()
    global _swear_cache
    if swear_words_coll is not None:
        res = swear_words_coll.update_one({"_id": "words"}, {"$addToSet": {"words": word}}, upsert=True)
        # refresh cache
        _swear_cache = None
        get_swear_words()
        return True
    else:
        words = get_swear_words()
        if word in words:
            return False
        words.append(word)
        with open(SWEAR_WORDS_FILE, "w", encoding="utf-8") as f:
            json.dump({"words": words}, f, ensure_ascii=False, indent=2)
        _swear_cache = None
        get_swear_words()
        return True

def remove_swear_word(word: str):
    word = word.lower()
    global _swear_cache
    if swear_words_coll is not None:
        res = swear_words_coll.update_one({"_id": "words"}, {"$pull": {"words": word}})
        _swear_cache = None
        get_swear_words()
        return True
    else:
        words = get_swear_words()
        if word not in words:
            return False
        words = [w for w in words if w != word]
        with open(SWEAR_WORDS_FILE, "w", encoding="utf-8") as f:
            json.dump({"words": words}, f, ensure_ascii=False, indent=2)
        _swear_cache = None
        get_swear_words()
        return True

def clear_user_data(user: discord.User, word: str = None):
    """Clears all counts or a specific word for a user in DB or JSON."""
    uid = str(user.id)
    if coll is not None:
        if word:
            coll.update_one({"_id": uid}, {"$unset": {f"counts.{word.lower()}": ""}})
        else:
            coll.delete_one({"_id": uid})
    else:
        data = load_data()
        if uid in data:
            if word:
                word = word.lower()
                if word in data[uid]:
                    del data[uid][word]
            else:
                del data[uid]
            save_data(data)

# Initialize at startup
init_swear_words()
# --- Classes ---
# --- Appeal UI ---
class AppealModal(discord.ui.Modal):
    def __init__(self, warn_id, reason):
        super().__init__(title=f"Appeal Warning: {warn_id}")
        self.warn_id = warn_id
        self.warn_reason = reason

    defense = discord.ui.TextInput(
        label="Why should this warning be revoked?",
        style=discord.TextStyle.paragraph,
        placeholder="Explain your side of the story here...",
        required=True,
        max_length=1000
    )

    async def on_submit(self, interaction: discord.Interaction):
        # Locate the staff log channel
        channel = interaction.client.get_channel(WARN_LOG_CHANNEL_ID)

        if not channel:
            await interaction.response.send_message("❌ Error: Appeal channel not found.", ephemeral=True)
            return

        embed = discord.Embed(
            title="⚖️ New Warning Appeal",
            description=f"**User:** {interaction.user.mention} (`{interaction.user.id}`)\n**Warning ID:** `{self.warn_id}`",
            color=0x9B59B6,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Original Reason", value=self.warn_reason, inline=True)
        embed.add_field(name="User's Defense", value=self.defense.value, inline=False)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)

        # IMPORTANT: This attaches the Approve/Reject buttons to the STAFF message
        view = AppealActionView(self.warn_id, interaction.user)
        await channel.send(embed=embed, view=view)

        await interaction.response.send_message("✅ Your appeal has been submitted to the staff team.", ephemeral=True)

class AppealView(discord.ui.View):
    def __init__(self, warn_id, reason):
        super().__init__(timeout=None) # Button doesn't expire
        self.warn_id = warn_id
        self.warn_reason = reason

    @discord.ui.button(label="👮 Appeal Warning", style=discord.ButtonStyle.secondary, emoji="⚖️")
    async def appeal_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Open the modal when button is clicked
        await interaction.response.send_modal(AppealModal(self.warn_id, self.warn_reason))

class AppealActionView(discord.ui.View):
    def __init__(self, warn_id, target_user: discord.Member):
        super().__init__(timeout=None)
        self.warn_id = warn_id
        self.target_user = target_user

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, emoji="✅")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Permission Check
        if not any(role.id in [1458454264702832792, 1458455202892877988, 1458490049413906553, 1458456130195034251, 1458455703638376469] for role in interaction.user.roles):
            await interaction.response.send_message("❌ Staff only.", ephemeral=True)
            return

        # 1. Remove warning from MongoDB
        if coll is not None:
            coll.update_one(
                {"_id": str(self.target_user.id)}, 
                {"$pull": {"warnings": {"warn_id": self.warn_id}}, "$inc": {"warn_count": -1}}
            )

        # 2. Notify the User (Approved)
        try:
            await self.target_user.send(f"✅ Your appeal for warning **{self.warn_id}** has been **APPROVED**. The warning has been removed from your record.")
        except discord.Forbidden:
            pass 

        # 3. Update the log message so other staff know it's handled
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.green()
        embed.add_field(name="Status", value=f"✅ Approved by {interaction.user.mention}", inline=False)

        # Remove buttons so no one clicks again
        await interaction.message.edit(embed=embed, view=None)
        await interaction.response.send_message(f"Successfully revoked warning {self.warn_id}.", ephemeral=True)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger, emoji="❌")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Permission Check
        if not any(role.id in [1458454264702832792, 1458455202892877988, 1458490049413906553, 1458456130195034251, 1458455703638376469] for role in interaction.user.roles):
            await interaction.response.send_message("❌ Staff only.", ephemeral=True)
            return

        # 1. Notify the User (Rejected)
        try:
            await self.target_user.send(f"❌ Your appeal for warning **{self.warn_id}** has been **REJECTED**. This decision is final.")
        except discord.Forbidden:
            pass

        # 2. Update the log message
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.red()
        embed.add_field(name="Status", value=f"❌ Rejected by {interaction.user.mention}", inline=False)

        await interaction.message.edit(embed=embed, view=None)
        await interaction.response.send_message(f"Rejected appeal for {self.warn_id}.", ephemeral=True)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} (ID: {bot.user.id})')

    # --- NEW: Cache existing invites on startup ---
    print("Caching invites...")
    for guild in bot.guilds:
        try:
            invs = await guild.invites()
            invites_cache[guild.id] = {invite.code: invite.uses for invite in invs}
            print(f"Cached {len(invs)} invites for {guild.name}")
        except Exception as e:
            print(f"Could not cache invites for {guild.name}: {e}")

    print('------')
    # Sync slash commands with Discord and log registration status
    try:
        synced = await tree.sync()
        names = [c.name for c in synced]
        print(f"Synced {len(synced)} slash command(s): {', '.join(names) if names else 'none'}")
    except Exception as e:
        print("Failed to sync slash commands:", e)

async def send_boost_announcement(member):
    channel = bot.get_channel(ANNOUNCE_CHANNEL_ID)
    if channel:
        embed = discord.Embed(
            title="New Server Boost! 🚀",
            description=f"Thank you so much {member.mention} for boosting the server!",
            color=0xf47fff
        )
        embed.set_image(url="https://media.tenor.com/GTrMJsHKlF8AAAAd/happy-japanese-anime.gif")
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Total Boosts", value=str(member.guild.premium_subscription_count))
        await channel.send(embed=embed)

@bot.event
async def on_member_update(before, after):
    if before.premium_since is None and after.premium_since is not None:
        await send_boost_announcement(after)

# --- NEW: Invite Tracking Events ---

@bot.event
async def on_invite_create(invite):
    """Updates cache when a new invite is created."""
    if invite.guild.id not in invites_cache:
        invites_cache[invite.guild.id] = {}
    invites_cache[invite.guild.id][invite.code] = invite.uses

@bot.event
async def on_invite_delete(invite):
    """Updates cache when an invite is deleted."""
    if invite.guild.id in invites_cache and invite.code in invites_cache[invite.guild.id]:
        del invites_cache[invite.guild.id][invite.code]

@bot.event
async def on_member_join(member):
    """
    Finds who invited the member by checking which invite count increased.
    Logs the result to the specified channel.
    """
    guild = member.guild
    log_channel = bot.get_channel(INVITE_LOG_CHANNEL_ID)

    # If we can't see the log channel, just return (or print error)
    if not log_channel:
        print(f"Invite Tracker: Log channel {INVITE_LOG_CHANNEL_ID} not found.")
        return

    inviter = None
    invite_code = None

    try:
        # Get the current invites from Discord
        current_invites = await guild.invites()

        # Get the old cached invites
        old_invites = invites_cache.get(guild.id, {})

        # Find the invite that has a higher usage count now than before
        for invite in current_invites:
            old_uses = old_invites.get(invite.code, 0)
            if invite.uses > old_uses:
                inviter = invite.inviter
                invite_code = invite.code
                # Update the cache immediately so it's ready for the next person
                invites_cache[guild.id][invite.code] = invite.uses
                break

        # If we loop through everything and didn't find a match, update the whole cache
        # just in case something got desynced.
        if not inviter:
             invites_cache[guild.id] = {invite.code: invite.uses for invite in current_invites}

    except Exception as e:
        print(f"Error checking invites: {e}")

    # --- Create Log Embed ---
    embed = discord.Embed(
        title="📥 Member Joined",
        color=0x2ecc71, # Green
        timestamp=datetime.utcnow()
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="User", value=f"{member.mention}\n`{member.name}`", inline=True)

    if inviter:
        embed.add_field(name="Invited By", value=f"{inviter.mention}\n`{inviter.name}`", inline=True)
        embed.add_field(name="Invite Code", value=f"`{invite_code}`", inline=True)
    else:
        embed.add_field(name="Invited By", value="Unknown / Vanity URL / Bot", inline=True)

    embed.set_footer(text=f"User ID: {member.id}")

    await log_channel.send(embed=embed)


# ---------------- Swear tracking helpers ----------------

def scan_text(content: str):
    """Scan arbitrary text for tracked swear words, allowing for repeated letters."""
    s = content.lower()
    found = {}
    words = get_swear_words()

    for w in words:
        # Create a pattern where each letter can be repeated: 'f+u+c+k+'
        # This catches 'fuck', 'fuuuuuck', 'fuckkkkk', etc.
        pattern = "".join([re.escape(char) + "+" for char in w])

        # Use \b to ensure it's still treated as a word (won't catch 'refucking' unless intended)
        matches = re.findall(r"\b" + pattern + r"\b", s, flags=re.IGNORECASE)

        c = len(matches)
        if c > 0:
            found[w] = c
    return found


def record_swears(message: discord.Message):
    """Scan the message for swear words and update storage (MongoDB or local JSON).
    Returns a dict of {word: count} found in this message."""
    content = message.content
    found = scan_text(content)

    # DEBUG logging
    print(f"[swear_scan] Scanning message from {message.author} ({message.author.id}): {content!r}")
    print(f"[swear_scan] Found: {found}")
import discord
import os
import json
import re
import time
from collections import Counter
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from discord import app_commands

# --- Keep-alive Server ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

    def do_HEAD(self):
        """Handle HEAD requests from Render's health checker"""
        self.send_response(200)
        self.end_headers()

def run_health_check():
    port = int(os.environ.get("PORT", 5000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

# Start the health check in a separate thread
Thread(target=run_health_check, daemon=True).start()


hUIPJ21boH = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = discord.Client(intents=intents)

# For slash commands
tree = app_commands.CommandTree(bot)

ANNOUNCE_CHANNEL_ID = 1458464867366342809

REPORT_CHANNEL_ID = 1468224442089079071

# --- Swear tracking config ---
# MongoDB connection (set MONGODB_URI environment variable)
MONGO_URI = os.getenv("MONGODB_URI")
# Default words to seed the swear list (lowercase)
DEFAULT_SWEAR_WORDS = ["fuck", "shit", "bitch", "ass", "damn", "gago"]
# Fallback JSON file for swear word list when MongoDB is not available
SWEAR_WORDS_FILE = "swear_words.json"

# Try to connect to MongoDB (pymongo); fall back to local JSON if unavailable
try:
    from pymongo import MongoClient
    if MONGO_URI:
        client = MongoClient(MONGO_URI)
        db = client.get_database(os.getenv("MONGO_DB"))
        coll = db[os.getenv("MONGO_COLLECTION")]
        print("Connected to MongoDB")
    else:
        coll = None
        print("MONGODB_URI not set; using local JSON fallback.")
except ImportError:
    coll = None
    print("pymongo not installed; using local JSON fallback. Run: pip install pymongo")

# Authorized Role IDs
AUTHORIZED_ROLES = [
    1458454264702832792, 
    1458455202892877988, 
    1458490049413906553, 
    1458456130195034251, 
    1458455703638376469
]

RULES_DATA = {
    "ARTICLE 1: Core Conduct": {
        "1.1 Respect Boundaries": "No harassment, unwanted DMs, or 'stalking' behaviors.",
        "1.2 Zero Tolerance": "Instant bans for hate speech, slurs, or discriminatory content.",
        "1.3 No Drama": "Keep personal arguments in DMs; do not disrupt public channels.",
        "1.4 Discord TOS": "All members/user must follow Discord Terms of Service"
    },
    "ARTICLE 2: Communication Etiquette": {
        "2.1 Channel Clarity": "Use channels for their intended purpose (e.g., memes in #memes).",
        "2.2 Ping Policy": "Do not use @everyone or @here without a valid reason or staff permission.",
        "2.3 VC Etiquette": "No ear-rape, screaming, or excessive noise. Use Push-to-Talk if needed.",
        "2.4 Advertising": "No Unauthorized Advertising: Do not post server invites or social media links without staff approval."
    },
    "ARTICLE 3: Safety & Integrity": {
        "3.1 Age Limit": "Users must be 13+ (or 18+ for adult-designated servers).",
        "3.2 NSFW Content": "Forbidden in public areas; only allowed in age-restricted channels.",
        "3.3 Anti-Scam": "Sharing 'Free Nitro' links or suspicious downloads results in an instant ban.",
        "3.4 No Ban Evasion": "Using alternate accounts to bypass bans or timeouts is prohibited.",
        "3.5 Consent First": "Never share a friend's real name, location, or photo without permission.",
        "3.6 Common Sense": "Just because something isn't explicitly written doesn't mean it’s allowed."
    },
    "ARTICLE 4: Admin Authority": {
        "4.1 Staff Discretion": "Moderators have the final say on behavior not explicitly listed.",
        "4.2 Conflict of Interest": "Staff must recuse themselves from cases involving close friends.",
        "4.3 Evidence-Based": "All bans and kicks must be backed by logged evidence.",
        "4.4 Internal Privacy": "Staff-room discussions are strictly confidential.",
        "4.5 Transparency": "Staff must clearly cite the rule violated when taking action.",
        "4.6 Power Tripping": "Avoid using staff-only permissions for jokes or to win arguments."
    }
}

def is_owner(user_id: int):
    """Checks if the User ID is one of the two authorized owners."""
    return user_id in [1394914695600934932, 912385288129622147]

def has_permission(member: discord.Member):
    """Checks if the member has any of the authorized roles."""
    return any(role.id in AUTHORIZED_ROLES for role in member.roles)

DATA_FILE = "swear_data.json"

def load_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# Swear words storage (MongoDB collection or local JSON fallback)
if 'db' in globals() and db is not None:
    swear_words_coll = db[os.getenv("MONGO_SWEAR_COLLECTION")]
else:
    swear_words_coll = None

# In-memory cache to avoid repeated DB reads
_swear_cache = None

def init_swear_words():
    """Ensure swear words storage is seeded with defaults."""
    global _swear_cache
    if swear_words_coll is not None:
        doc = swear_words_coll.find_one({"_id": "words"})
        if not doc:
            swear_words_coll.insert_one({"_id": "words", "words": DEFAULT_SWEAR_WORDS})
            _swear_cache = list(DEFAULT_SWEAR_WORDS)
            print("Seeded swear words in MongoDB")
        else:
            _swear_cache = list(doc.get("words", []))
    else:
        # Ensure local file exists
        try:
            with open(SWEAR_WORDS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                _swear_cache = list(data.get("words", DEFAULT_SWEAR_WORDS))
        except FileNotFoundError:
            with open(SWEAR_WORDS_FILE, "w", encoding="utf-8") as f:
                json.dump({"words": DEFAULT_SWEAR_WORDS}, f, ensure_ascii=False, indent=2)
            _swear_cache = list(DEFAULT_SWEAR_WORDS)
            print("Seeded local swear words file")


def get_swear_words():
    """Return the current list of swear words (lowercase)."""
    global _swear_cache
    if _swear_cache is not None:
        return _swear_cache
    # Cache miss: load from source
    if swear_words_coll is not None:
        doc = swear_words_coll.find_one({"_id": "words"})
        words = doc.get("words", []) if doc else []
        _swear_cache = list(words)
        return _swear_cache
    else:
        try:
            with open(SWEAR_WORDS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                _swear_cache = list(data.get("words", []))
                return _swear_cache
        except FileNotFoundError:
            _swear_cache = list(DEFAULT_SWEAR_WORDS)
            return _swear_cache


def add_swear_word(word: str):
    word = word.lower()
    global _swear_cache
    if swear_words_coll is not None:
        res = swear_words_coll.update_one({"_id": "words"}, {"$addToSet": {"words": word}}, upsert=True)
        # refresh cache
        _swear_cache = None
        get_swear_words()
        return True
    else:
        words = get_swear_words()
        if word in words:
            return False
        words.append(word)
        with open(SWEAR_WORDS_FILE, "w", encoding="utf-8") as f:
            json.dump({"words": words}, f, ensure_ascii=False, indent=2)
        _swear_cache = None
        get_swear_words()
        return True


def remove_swear_word(word: str):
    word = word.lower()
    global _swear_cache
    if swear_words_coll is not None:
        res = swear_words_coll.update_one({"_id": "words"}, {"$pull": {"words": word}})
        _swear_cache = None
        get_swear_words()
        return True
    else:
        words = get_swear_words()
        if word not in words:
            return False
        words = [w for w in words if w != word]
        with open(SWEAR_WORDS_FILE, "w", encoding="utf-8") as f:
            json.dump({"words": words}, f, ensure_ascii=False, indent=2)
        _swear_cache = None
        get_swear_words()
        return True

def clear_user_data(user: discord.User, word: str = None):
    """Clears all counts or a specific word for a user in DB or JSON."""
    uid = str(user.id)
    if coll is not None:
        if word:
            coll.update_one({"_id": uid}, {"$unset": {f"counts.{word.lower()}": ""}})
        else:
            coll.delete_one({"_id": uid})
    else:
        data = load_data()
        if uid in data:
            if word:
                word = word.lower()
                if word in data[uid]:
                    del data[uid][word]
            else:
                del data[uid]
            save_data(data)

# Initialize at startup
init_swear_words()

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} (ID: {bot.user.id})')
    print('------')
    # Sync slash commands with Discord and log registration status
    try:
        synced = await tree.sync()
        names = [c.name for c in synced]
        print(f"Synced {len(synced)} slash command(s): {', '.join(names) if names else 'none'}")
        # Debug: check presence of important commands
        expected = ["top_swearer", "userswearcount", "addswear", "remswear", "listswears", "clearcount", "testscan", "report", "rulewarning", "removewarning", "clearwarning", "warnlist"]
        for cmd in expected:
            print(f"/{cmd} registered: {'yes' if cmd in names else 'no'}")
    except Exception as e:
        print("Failed to sync slash commands:", e)

async def send_boost_announcement(member):
    channel = bot.get_channel(ANNOUNCE_CHANNEL_ID)
    if channel:
        embed = discord.Embed(
            title="New Server Boost! 🚀",
            description=f"Thank you so much {member.mention} for boosting the server!",
            color=0xf47fff
        )
        embed.set_image(url="https://media.tenor.com/GTrMJsHKlF8AAAAd/happy-japanese-anime.gif")
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Total Boosts", value=str(member.guild.premium_subscription_count))
        await channel.send(embed=embed)

@bot.event
async def on_member_update(before, after):
    if before.premium_since is None and after.premium_since is not None:
        await send_boost_announcement(after)


# ---------------- Swear tracking helpers ----------------

def scan_text(content: str):
    """Scan arbitrary text for tracked swear words, allowing for repeated letters."""
    s = content.lower()
    found = {}
    words = get_swear_words()
    
    for w in words:
        # Create a pattern where each letter can be repeated: 'f+u+c+k+'
        # This catches 'fuck', 'fuuuuuck', 'fuckkkkk', etc.
        pattern = "".join([re.escape(char) + "+" for char in w])
        
        # Use \b to ensure it's still treated as a word (won't catch 'refucking' unless intended)
        matches = re.findall(r"\b" + pattern + r"\b", s, flags=re.IGNORECASE)
        
        c = len(matches)
        if c > 0:
            found[w] = c
    return found


def record_swears(message: discord.Message):
    """Scan the message for swear words and update storage (MongoDB or local JSON).
    Returns a dict of {word: count} found in this message."""
    content = message.content
    found = scan_text(content)

    # DEBUG logging
    print(f"[swear_scan] Scanning message from {message.author} ({message.author.id}): {content!r}")
    print(f"[swear_scan] Found: {found}")

    if not found:
        return {}

    uid = str(message.author.id)
    if coll is not None:
        # Update counts atomically in MongoDB
        inc = {f"counts.{w}": c for w, c in found.items()}
        res = coll.update_one({"_id": uid}, {"$inc": inc}, upsert=True)
        print(f"[swear_scan] Mongo update acknowledged: {getattr(res, 'acknowledged', None)}")
        # Optionally print the updated doc for debugging
        doc = coll.find_one({"_id": uid})
        print(f"[swear_scan] Updated doc for {uid}: {doc}")
    else:
        data = load_data()
        user_counts = Counter(data.get(uid, {}))
        for w, c in found.items():
            user_counts[w] += c
        data[uid] = dict(user_counts)
        save_data(data)
        print(f"[swear_scan] Local JSON updated for {uid}: {data[uid]}")
    return found


def get_user_top(user: discord.User):
    """Return (word, count, total) for a user's top word and overall total. If none, returns (None, 0, 0)."""
    uid = str(user.id)
    if coll is not None:
        doc = coll.find_one({"_id": uid})
        data = doc.get("counts", {}) if doc else {}
    else:
        data = load_data().get(uid, {})

    if not data:
        return (None, 0, 0)
    counter = Counter(data)
    word, count = counter.most_common(1)[0]
    total = sum(counter.values())
    return (word, count, total)


def get_user_counts(user: discord.User):
    """Return a dict of per-word counts for the user (word -> count)."""
    uid = str(user.id)
    if coll is not None:
        doc = coll.find_one({"_id": uid})
        return doc.get("counts", {}) if doc else {}
    else:
        return load_data().get(uid, {})


def get_leaderboard(guild, limit=10):
    """Returns a list of (member_mention, total_count) for the top users."""
    user_totals = []

    if coll is not None:
        cursor = coll.find({})
        for doc in cursor:
            uid = doc["_id"]
            data = doc.get("counts", {})
            total = sum(data.values())
            if total > 0:
                user_totals.append((uid, total))
    else:
        all_data = load_data()
        for uid, data in all_data.items():
            total = sum(data.values())
            if total > 0:
                user_totals.append((uid, total))

    # Sort by total count descending
    user_totals.sort(key=lambda x: x[1], reverse=True)
    
    leaderboard_lines = []
    for i, (uid, total) in enumerate(user_totals[:limit], 1):
        member = guild.get_member(int(uid))
        display = member.mention if member else f"<@{uid}>"
        leaderboard_lines.append(f"{i}. {display} — **{total}** total swears")
    
    return leaderboard_lines


# ---------------- Slash commands ----------------
@tree.command(name="report", description="Report a user with evidence")
@discord.app_commands.describe(
    suspect="The user you are reporting",
    evidence="Image evidence for the report",
    description="Detailed description of the incident"
)
async def report(
    interaction: discord.Interaction, 
    suspect: discord.Member, 
    evidence: discord.Attachment, 
    description: str
):
    # Check if the attachment is an image
    if not evidence.content_type or not evidence.content_type.startswith("image/"):
        await interaction.response.send_message("The evidence must be an image file.", ephemeral=True)
        return

    report_channel = bot.get_channel(REPORT_CHANNEL_ID)
    if not report_channel:
        await interaction.response.send_message("Report channel not found. Please contact an admin.", ephemeral=True)
        return

    # Create the Embed
    embed = discord.Embed(
        title="🚨 New User Report",
        color=0xFF0000, # Red color for alerts
        timestamp=interaction.created_at
    )
    
    embed.add_field(name="Reporter", value=interaction.user.mention, inline=True)
    embed.add_field(name="Suspect", value=suspect.mention, inline=True)
    embed.add_field(name="Description", value=description, inline=False)
    embed.add_field(name="Timeline", value=f"<t:{int(interaction.created_at.timestamp())}:F>", inline=False)
    
    # Attach the evidence image to the embed
    embed.set_image(url=evidence.url)
    
    await report_channel.send(embed=embed)
    await interaction.response.send_message("Your report has been submitted successfully.", ephemeral=True)


@tree.command(name="top_swearer", description="Show the leaderboard of top swearers")
async def top_swearer(interaction: discord.Interaction):
    leaderboard = get_leaderboard(interaction.guild)
    
    if not leaderboard:
        await interaction.response.send_message("No swears recorded yet.")
        return

    embed = discord.Embed(
        title="🏆 Swear Word Leaderboard",
        description="\n".join(leaderboard),
        color=discord.Color.gold()
    )
    embed.set_footer(text="KALMA MGA GAGO")
    await interaction.response.send_message(embed=embed)

@tree.command(name="userswearcount", description="Show a user's swear breakdown and overall count")
@app_commands.describe(user="User to lookup (defaults to you)")
async def userswearcount(interaction: discord.Interaction, user: discord.Member = None):
    target = user or interaction.user
    counts = get_user_counts(target)
    if not counts:
        await interaction.response.send_message(f"**{target.display_name}**\nOverall : 0")
        return
    lines = [f"**{target.display_name}**"]
    for w, c in sorted(counts.items(), key=lambda x: -x[1]):
        lines.append(f"{w.capitalize()} : {c}")
    lines.append(f"\nOverall : {sum(counts.values())}")
    await interaction.response.send_message("\n".join(lines))


@tree.command(name="testscan", description="Scan a provided string for tracked swear words")
@app_commands.describe(text="Text to scan")
async def testscan(interaction: discord.Interaction, text: str):
    found = scan_text(text)
    if not found:
        await interaction.response.send_message("No tracked words found.")
        return
    parts = ", ".join(f"{w}: {c}" for w, c in found.items())
    await interaction.response.send_message(f"Found: {parts}")


@tree.command(name="addswear", description="Add a swear word to tracking")
@app_commands.describe(word="Word to add")
async def addswear(interaction: discord.Interaction, word: str):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ You do not have the required role to manage swear words.", ephemeral=True)
        return

    word_clean = word.lower().strip()
    if word_clean in get_swear_words():
        await interaction.response.send_message(f"⚠️ **{word_clean}** is already in the list. Duplicate ignored.", ephemeral=True)
        return

    if add_swear_word(word_clean):
        await interaction.response.send_message(f"✅ Added swear word: **{word_clean}**")

@tree.command(name="remswear", description="Remove a swear word from tracking")
@app_commands.describe(word="Word to remove")
async def remswear(interaction: discord.Interaction, word: str):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ You do not have the required role to manage swear words.", ephemeral=True)
        return

    word_clean = word.lower().strip()
    if remove_swear_word(word_clean):
        await interaction.response.send_message(f"🗑️ Removed swear word: **{word_clean}**")
    else:
        await interaction.response.send_message(f"❓ **{word_clean}** was not found in the list.")

@tree.command(name="listswears", description="List currently tracked swear words")
async def listswears(interaction: discord.Interaction):
    words = get_swear_words()
    if not words:
        await interaction.response.send_message("No swear words tracked.")
        return
    await interaction.response.send_message("Tracked words: " + ", ".join(words))

@tree.command(name="clearcount", description="Reset swear counts for a user (Owner Only)")
@app_commands.describe(
    user="The user to clear counts for",
    word="Specific word to clear (leave empty to clear ALL counts)"
)
async def clearcount(interaction: discord.Interaction, user: discord.Member, word: str = None):
    # Strict ID check
    if not is_owner(interaction.user.id):
        await interaction.response.send_message("❌ Access Denied: Only specific bot owners can use this command.", ephemeral=True)
        return

    word_clean = word.lower().strip() if word else None
    
    clear_user_data(user, word_clean)
    
    if word_clean:
        await interaction.response.send_message(
            f"🗑️ Cleared count for **{word_clean}** from {user.mention}.", 
            ephemeral=False
        )
    else:
        await interaction.response.send_message(
            f"🧹 Cleared **all** swear records for {user.mention}.", 
            ephemeral=False
        )

# --- Rule Warning Autocomplete Helpers ---
async def article_autocomplete(interaction: discord.Interaction, current: str):
    return [
        app_commands.Choice(name=art, value=art)
        for art in RULES_DATA.keys() if current.lower() in art.lower()
    ][:25] # Discord limit is 25 choices

async def section_autocomplete(interaction: discord.Interaction, current: str):
    # This gets the current value of the 'article' field in the command
    article = interaction.namespace.article
    if not article or article not in RULES_DATA:
        return []
    return [
        app_commands.Choice(name=sec, value=sec)
        for sec in RULES_DATA[article].keys() if current.lower() in sec.lower()
    ][:25]

# --- The Unified Command ---
@tree.command(name="rulewarning", description="Warn a user and record it in the database")
@app_commands.describe(
    user="The user to warn",
    article="Select the Rule Article",
    section="Select the specific section",
    message="Optional custom staff message"
)
@app_commands.autocomplete(article=article_autocomplete, section=section_autocomplete)
async def rulewarning(
    interaction: discord.Interaction, 
    user: discord.Member, 
    article: str, 
    section: str, 
    message: str = None
):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ Staff only.", ephemeral=True)
        return

    rule_desc = RULES_DATA.get(article, {}).get(section, "Rule description not found.")
    staff_msg = message if message else "this is a warning for you do not try it again"
    
    # Generate a unique Warning ID (Hex timestamp)
    warn_id = hex(int(time.time()))[2:].upper()

    warning_text = (
        f"** {section} **\n\n"
        f"{rule_desc}\n\n"
        f"*{staff_msg}*\n"
        f"**Warning ID:** {warn_id}"
    )

    try:
        # Save to MongoDB
        if coll is not None:
            warn_entry = {
                "warn_id": warn_id,
                "reason": section,
                "staff": str(interaction.user.id),
                "timestamp": interaction.created_at
            }
            coll.update_one(
                {"_id": str(user.id)},
                {"$push": {"warnings": warn_entry}, "$inc": {"warn_count": 1}},
                upsert=True
            )

        await user.send(warning_text)
        await interaction.response.send_message(
            f"✅ Warning **{warn_id}** sent to {user.mention}.", 
            ephemeral=True
        )
    except discord.Forbidden:
        await interaction.response.send_message(f"❌ Could not DM user, but the warning was recorded.", ephemeral=True)
        
@tree.command(name="removewarning", description="Remove a specific warning by ID")
@app_commands.describe(user="The user", warning_id="The ID of the warning to remove")
async def removewarning(interaction: discord.Interaction, user: discord.Member, warning_id: str):
    if not is_owner(interaction.user.id):
        await interaction.response.send_message("❌ Owner only.", ephemeral=True)
        return

    if coll is not None:
        # Pull the specific warning and decrement the count
        res = coll.update_one(
            {"_id": str(user.id)},
            {
                "$pull": {"warnings": {"warn_id": warning_id.upper()}},
                "$inc": {"warn_count": -1}
            }
        )
        
        if res.modified_count > 0:
            await interaction.response.send_message(f"🗑️ Warning **{warning_id}** removed from {user.mention}.")
        else:
            await interaction.response.send_message("❓ Warning ID not found for this user.", ephemeral=True)

@tree.command(name="clearwarning", description="Clear all warnings for a user")
async def clearwarning(interaction: discord.Interaction, user: discord.Member):
    if not is_owner(interaction.user.id):
        await interaction.response.send_message("❌ Owner only.", ephemeral=True)
        return

    if coll is not None:
        coll.update_one(
            {"_id": str(user.id)},
            {"$set": {"warnings": [], "warn_count": 0}}
        )
        await interaction.response.send_message(f"🧹 All warnings cleared for {user.mention}.")

@tree.command(name="warnlist", description="View all warning records for a user")
@app_commands.describe(user="The user to check")
async def warnlist(interaction: discord.Interaction, user: discord.Member):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ Staff only.", ephemeral=True)
        return

    if coll is None:
        await interaction.response.send_message("❌ Database connection not available.", ephemeral=True)
        return

    doc = coll.find_one({"_id": str(user.id)})
    warnings = doc.get("warnings", []) if doc else []

    if not warnings:
        await interaction.response.send_message(f"✅ **{user.display_name}** has a clean record (0 warnings).")
        return

    embed = discord.Embed(
        title=f"Warning Records: {user.display_name}",
        description=f"Total Violations: **{len(warnings)}**",
        color=0xFFCC00
    )
    
    # List the last 10 warnings to keep the embed clean
    for w in warnings[-10:]:
        # Format the timestamp if it exists, else use 'Unknown Date'
        ts = w.get("timestamp")
        date_str = ts.strftime("%Y-%m-%d") if hasattr(ts, 'strftime') else "N/A"
        
        embed.add_field(
            name=f"ID: {w['warn_id']} | {w['reason']}",
            value=f"Date: {date_str} | Staff: <@{w['staff']}>",
            inline=False
        )

    await interaction.response.send_message(embed=embed)

# ---------------- Message-based commands & scanning ----------------
@bot.event
async def on_message(message):
    # ignore bots
    if message.author.bot:
        return

    # keep existing Test behavior
    if message.content == "Test":
        await send_boost_announcement(message.author)

    # Check for swear words (do not delete the message)
    found = record_swears(message)
    # If swear(s) detected, reply with the user's overall cumulative swear count
    if found:
        if not message.content.strip().startswith("/"):
            counts = get_user_counts(message.author)
            overall = sum(counts.values())
            await message.channel.send(f"**{message.author.display_name}** Swear **{overall}** Times")
    # Optionally, you could notify or log, but user requested only counters and commands.

    # Support message-based fallback commands (in case slash commands are not used)
    if message.content.strip().lower() == "/top swearer":
        leaderboard = get_leaderboard(message.guild)
        if not leaderboard:
            await message.channel.send("No swears recorded yet.")
            return
            
        response = "**Users Swearing Board**\n" + "\n".join(leaderboard)
        await message.channel.send(response)
    elif message.content.strip().lower().startswith("/userswearcount"):
        parts = message.content.strip().split()
        target = None
        # If user was mentioned, use first mention
        if message.mentions:
            target = message.mentions[0]
        elif len(parts) >= 2:
            # try to find by name
            name = " ".join(parts[1:])
            target = discord.utils.find(lambda m: m.name == name or m.display_name == name, message.guild.members)
        else:
            target = message.author
        if not target:
            await message.channel.send("User not found.")
            return
        counts = get_user_counts(target)
        if not counts:
            await message.channel.send(f"**{target.display_name}**\nOverall : 0")
            return
        lines = [f"**{target.display_name}**"]
        for w, c in sorted(counts.items(), key=lambda x: -x[1]):
            lines.append(f"{w.capitalize()} : {c}")
        lines.append(f"\nOverall : {sum(counts.values())}")
        await message.channel.send("\n".join(lines))
    elif message.content.strip().lower().startswith("/scan "):
        # message-based scan command for quick testing
        text = message.content.strip()[6:]
        found = scan_text(text)
        if not found:
            await message.channel.send("No tracked words found.")
        else:
            parts = ", ".join(f"{w}: {c}" for w, c in found.items())
            await message.channel.send(f"Found: {parts}")
    elif message.content.strip().lower().startswith("/addswear "):
        if not has_permission(message.author):
            await message.channel.send("You don't have the required role to use this command.")
            return
            
        word = message.content.strip()[10:].lower().strip()
        if not word:
            await message.channel.send("Usage: /addswear <word>")
            return
            
        if word in get_swear_words():
            await message.channel.send(f"**{word}** is already being tracked.")
            return

        ok = add_swear_word(word)
        if ok:
            await message.channel.send(f"Added swear word: **{word}**")
        else:
            await message.channel.send(f"**{word.lower()}** is already tracked.")
    elif message.content.strip().lower().startswith("/remswear "):
        if not has_permission(message.author):
            await message.channel.send("You don't have the required role to use this command.")
            return
        word = message.content.strip()[9:]
        if not word:
            await message.channel.send("Usage: /remswear <word>")
            return
        ok = remove_swear_word(word)
        if ok:
            await message.channel.send(f"Removed swear word: **{word.lower()}**")
        else:
            await message.channel.send(f"**{word.lower()}** is not tracked.")
    elif message.content.strip().lower() == "/listswears":
        words = get_swear_words()
        if not words:
            await message.channel.send("No swear words tracked.")
            return
        await message.channel.send("Tracked words: " + ", ".join(words))

bot.run(hUIPJ21boH)
