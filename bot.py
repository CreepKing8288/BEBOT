import discord
import os
import json
import re
import time
import asyncio
from collections import Counter
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from discord import app_commands
from datetime import datetime, timedelta
from discord.ext import tasks


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
# --- NEW: Enable Invite Tracking Intent ---
intents.invites = True 

bot = discord.Client(intents=intents)

# For slash commands
tree = app_commands.CommandTree(bot)

ANNOUNCE_CHANNEL_ID = 1458464867366342809
REPORT_CHANNEL_ID = 1468224442089079071
WARN_LOG_CHANNEL_ID = 1469023340130861179
INVITE_LOG_CHANNEL_ID = 1469126718425006332
LOG_CHANNEL_ID = 1469332387539325044

# Authorized Role IDs
AUTHORIZED_ROLES = [
    1458454264702832792, 
    1458455202892877988, 
    1458490049413906553, 
    1458456130195034251, 
    1458455703638376469
]

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
    # Existing counts collection
    swear_words_coll = db[os.getenv("MONGO_COLLECTION")]
    # NEW: Dedicated Profile collection for points and referral codes
    profile_coll = db["Profile"]
    # NEW: Tracker to prevent re-using referrals on rejoin
    ref_tracker_coll = db["ReferralTracker"] 
    
else:
    profile_coll = None
    ref_tracker_coll = None

def update_points(user_id: int, amount: int):
    """Adds or subtracts points in the Profile collection."""
    uid = str(user_id)
    if profile_coll is not None:
        profile_coll.update_one({"_id": uid}, {"$inc": {"points": amount}}, upsert=True)
    else:
        # Local JSON Fallback
        data = load_data()
        user = data.get(uid, {})
        user["points"] = user.get("points", 0) + amount
        data[uid] = user
        save_data(data)
        
def has_used_referral(new_member_id: int):
    """Checks if a user has ever triggered a referral point before."""
    if ref_tracker_coll is not None:
        return ref_tracker_coll.find_one({"_id": str(new_member_id)}) is not None
    return False # Fallback if DB is down

def mark_referral_used(new_member_id: int):
    """Logs that a user has used a referral so they can't give points again."""
    if ref_tracker_coll is not None:
        ref_tracker_coll.insert_one({"_id": str(new_member_id), "used_at": datetime.utcnow()})

# --- Status Management ---
status_coll = db["status"] if 'db' in globals() and db is not None else None

async def get_custom_statuses():
    """Fetch status list from MongoDB or return defaults."""
    if status_coll is not None:
        doc = status_coll.find_one({"_id": "status_list"})
        if doc and "messages" in doc:
            return doc["messages"]
    
    # Default statuses if DB is empty or unavailable
    return ["Watching for swears...", "Type /report to help", "Kalma mga gago!"]

@tasks.loop(minutes=5)
async def change_status():
    """Cycles through statuses fetched from MongoDB."""
    messages = await get_custom_statuses()
    for msg in messages:
        # Change the 'ActivityType' to watching, listening, or playing as you like
        await bot.change_presence(activity=discord.Game(name=msg))
        await asyncio.sleep(30) # Wait 30 seconds before switching to the next message

@change_status.before_loop
async def before_change_status():
    await bot.wait_until_ready()

# In-memory cache to avoid repeated DB reads
_swear_cache = None

def init_swear_words():
    """Ensure swear words storage is seeded with defaults."""
    global _swear_cache
    # Change 'swear_words_coll' to 'coll'
    if coll is not None:
        doc = coll.find_one({"_id": "words"})
        if not doc:
            coll.insert_one({"_id": "words", "words": DEFAULT_SWEAR_WORDS})
            _swear_cache = list(DEFAULT_SWEAR_WORDS)
            print("Seeded swear words in MongoDB")
        else:
            _swear_cache = list(doc.get("words", []))
    else:
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
    
    if not change_status.is_running():
        change_status.start()
    
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
        update_points(after.id, 50)

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
    guild = member.guild
    log_channel = bot.get_channel(INVITE_LOG_CHANNEL_ID)
    await asyncio.sleep(1.5)

    inviter = None
    invite_code = "Unknown"

    try:
        current_invites = await guild.invites()
        old_invites = invites_cache.get(guild.id, {})
        
        for invite in current_invites:
            if invite.code in old_invites and invite.uses > old_invites[invite.code]:
                invite_code = invite.code
                # Check if this code belongs to a user in our referral system
                ref_owner_id = get_inviter_by_code(invite_code)
                if ref_owner_id:
                    inviter = guild.get_member(ref_owner_id) or await bot.fetch_user(ref_owner_id)
                else:
                    # Fallback to standard discord inviter if not in referral system
                    inviter = invite.inviter
                break
        
        invites_cache[guild.id] = {invite.code: invite.uses for invite in current_invites}
    except Exception as e:
        print(f"Invite tracking error: {e}")

    # Award Point (Lowered to 1 as requested)
    if inviter:
        update_points(inviter.id, 1)

    if log_channel:
        embed = discord.Embed(title="📥 Referral Joined", color=0x2ecc71, timestamp=datetime.utcnow())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="New Member", value=member.mention, inline=True)
        embed.add_field(name="Referrer", value=inviter.mention if inviter else "Unknown", inline=True)
        embed.add_field(name="Code Used", value=f"`{invite_code}`", inline=True)
        if inviter:
            embed.set_footer(text="Verified Referral: +1 Point awarded")
        await log_channel.send(embed=embed)

# ---------------- User Data Helpers ----------------
def get_user_data(user_id: int):
    """Fetch full user document."""
    uid = str(user_id)
    if coll is not None:
        doc = coll.find_one({"_id": uid})
        return doc if doc else {}
    else:
        return load_data().get(uid, {})

def update_points(user_id: int, amount: int):
    """Adds or subtracts points for a user."""
    uid = str(user_id)
    if coll is not None:
        coll.update_one({"_id": uid}, {"$inc": {"points": amount}}, upsert=True)
    else:
        data = load_data()
        user = data.get(uid, {})
        user["points"] = user.get("points", 0) + amount
        data[uid] = user
        save_data(data)

def get_inviter_by_code(code: str):
    """Finds the user ID associated with a custom referral code."""
    if coll is not None:
        doc = coll.find_one({"referral_code": code})
        return int(doc["_id"]) if doc else None
    else:
        data = load_data()
        for uid, udata in data.items():
            if udata.get("referral_code") == code:
                return int(uid)
    return None

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

@tree.command(name="referral", description="Get your unique invite link to earn points")
async def referral(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    # Check database for existing code
    if coll is not None:
        doc = coll.find_one({"_id": user_id})
        saved_code = doc.get("referral_code") if doc else None
    else:
        saved_code = load_data().get(user_id, {}).get("referral_code")

    if saved_code:
        # Check if the invite still exists in the guild
        invites = await interaction.guild.invites()
        if any(i.code == saved_code for i in invites):
            await interaction.response.send_message(f"Your referral link: https://discord.gg/{saved_code}", ephemeral=True)
            return

    # Create new permanent invite if none exists or old one was deleted
    invite = await interaction.channel.create_invite(max_age=0, max_uses=0, unique=True, reason=f"Referral for {interaction.user.name}")
    
    if coll is not None:
        coll.update_one({"_id": user_id}, {"$set": {"referral_code": invite.code}}, upsert=True)
    else:
        data = load_data()
        user = data.get(user_id, {})
        user["referral_code"] = invite.code
        data[user_id] = user
        save_data(data)
    
    # Update cache
    if interaction.guild.id not in invites_cache:
        invites_cache[interaction.guild.id] = {}
    invites_cache[interaction.guild.id][invite.code] = invite.uses

    await interaction.response.send_message(f"Your unique referral link: {invite.url}", ephemeral=True)
        
        
@tree.command(name="refremove", description="Remove a specific referral/invite code")
@app_commands.describe(code="The invite code to remove")
async def refremove(interaction: discord.Interaction, code: str):
    if not has_permission(interaction.user):
        await interaction.response.defer(ephemeral=True)
    
    try:
        invite = await bot.fetch_invite(code)
        if invite.guild.id != interaction.guild.id:
            return await interaction.followup.send("That invite belongs to another server.")
        
        await invite.delete(reason=f"Removed by {interaction.user.name} via /refremove")
        
        # Clean from database
        if profile_coll is not None:
            profile_coll.update_one({"referral_code": code}, {"$unset": {"referral_code": ""}})
        
        await interaction.followup.send(f"✅ Successfully removed invite code: `{code}`")
    except discord.NotFound:
        await interaction.followup.send("❌ Invite code not found or already expired.")
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {e}")

@tree.command(name="reloadreferral", description="Create a new referral code (Points are kept)")
async def reloadreferral(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    uid = str(interaction.user.id)
    
    # 1. Delete old invite if it exists
    user_data = get_user_data(interaction.user.id)
    old_code = user_data.get("referral_code")
    
    if old_code:
        try:
            invs = await interaction.guild.invites()
            for i in invs:
                if i.code == old_code:
                    await i.delete(reason="User reloaded their referral link")
        except: pass

    # 2. Create new invite
    invite = await interaction.channel.create_invite(max_age=0, max_uses=0, unique=True)
    
    # 3. Update Profile collection (Points are untouched because we use $set for code only)
    if profile_coll is not None:
        profile_coll.update_one({"_id": uid}, {"$set": {"referral_code": invite.code}}, upsert=True)
    
    # Update cache
    invites_cache[interaction.guild.id][invite.code] = invite.uses
    await interaction.followup.send(f"✅ New referral link generated: {invite.url}\n(Your points remain safe!)")
    
@tree.command(name="profile", description="Check stats")
async def profile(interaction: discord.Interaction, user: discord.Member = None):
    target = user or interaction.user
    uid = str(target.id)
    
    if coll is not None:
        doc = coll.find_one({"_id": uid}) or {}
        counts = doc.get("counts", {})
        points = doc.get("points", 0)
        warns = doc.get("warn_count", 0)
    else:
        data = load_data().get(uid, {})
        counts = data.get("counts", {}) # Adjust based on your JSON structure
        points = data.get("points", 0)
        warns = data.get("warn_count", 0)

    total_swears = sum(counts.values()) if isinstance(counts, dict) else 0

    embed = discord.Embed(title=f"Profile: {target.display_name}", color=target.color)
    embed.add_field(name="💰 Points", value=str(points))
    embed.add_field(name="⚠️ Warnings", value=str(warns))
    embed.add_field(name="🤬 Swears", value=str(total_swears))
    await interaction.response.send_message(embed=embed)
    
@tree.command(name="givepoints", description="Give points to a user (Owner Only)")
async def givepoints(interaction: discord.Interaction, user: discord.Member, value: int):
    if not is_owner(interaction.user.id):
        await interaction.response.send_message("❌ Access Denied.", ephemeral=True)
        return

    update_points(user.id, value)
    await interaction.response.send_message(f"✅ Gave **{value}** points to {user.mention}.")

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

async def send_warn_log(action, staff, user, reason=None, warn_id=None, extra=None):
    """Sends a formatted embed to the warning logs channel."""
    channel = bot.get_channel(WARN_LOG_CHANNEL_ID)
    if not channel:
        return

    # Color coding for different actions
    color = 0xFFA500  # Orange for Issue
    if "Removed" in action: color = 0x3498DB # Blue
    if "Cleared" in action: color = 0xE74C3C # Red

    embed = discord.Embed(title=f"📋 {action}", color=color, timestamp=datetime.utcnow())
    embed.add_field(name="Target User", value=f"{user.mention} (`{user.id}`)", inline=True)
    embed.add_field(name="Staff Member", value=f"{staff.mention}", inline=True)
    
    if warn_id:
        embed.add_field(name="Warning ID", value=f"`{warn_id}`", inline=True)
    if reason:
        embed.add_field(name="Reason", value=reason, inline=False)
    if extra:
        embed.add_field(name="Penalty/Notes", value=extra, inline=False)
        
    embed.set_thumbnail(url=user.display_avatar.url)
    await channel.send(embed=embed)

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

# --- The Rule Warn Command ---
@tree.command(name="rulewarning", description="Warn a user and record it in the database")
@app_commands.describe(user="The user to warn", article="Select the Rule Article", section="Select the specific section", message="Optional custom staff message")
@app_commands.autocomplete(article=article_autocomplete, section=section_autocomplete)
async def rulewarning(interaction: discord.Interaction, user: discord.Member, article: str, section: str, message: str = None):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ Staff only.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    rule_desc = RULES_DATA.get(article, {}).get(section, "Rule description not found.")
    staff_msg = message if message else "this is a warning for you do not try it again"
    warn_id = hex(int(time.time()))[2:].upper()

    try:
        current_warns = 0
        if profile_coll is not None:
            warn_entry = {"warn_id": warn_id, "reason": section, "staff": str(interaction.user.id), "timestamp": datetime.utcnow()}
            res = profile_coll.find_one_and_update({"_id": str(user.id)}, {"$push": {"warnings": warn_entry}, "$inc": {"warn_count": 1}}, upsert=True, return_document=True)
            current_warns = res.get("warn_count", 0)

        # Punishment Logic
        penalty_text = "None"
        timeout_duration = None
        if current_warns >= 5:
            timeout_duration = timedelta(hours=12)
            penalty_text = "12 Hour Timeout"
        elif current_warns >= 3:
            timeout_duration = timedelta(hours=5)
            penalty_text = "5 Hour Timeout"

        if timeout_duration:
            try:
                await user.timeout(timeout_duration, reason=f"Reached {current_warns} warnings.")
            except Exception as e:
                penalty_text += f" (Failed: {e})"

        # Send DM with Appeal Button
        dm_text = f"⚠️ **Warning Issued**\n**Rule:** {section}\n{rule_desc}\n\n*Note: {staff_msg}*\n**Warning ID:** {warn_id}"
        if timeout_duration:
            dm_text += f"\n\n**Penalty:** You have been timed out for {penalty_text}."
        
        try:
            # THIS IS THE CHANGED PART: We attach the AppealView here
            view = AppealView(warn_id, section)
            await user.send(dm_text, view=view)
        except discord.Forbidden:
            # If user has DMs off, we can't send the button
            pass
        except Exception as e:
            print(f"Failed to send DM: {e}")

        # Send LOG
        await send_warn_log("Warning Issued", interaction.user, user, reason=section, warn_id=warn_id, extra=f"Total Warnings: {current_warns}\nPenalty: {penalty_text}")
        
        await interaction.response.send_message(f"✅ Warning **{warn_id}** recorded. (Total: {current_warns})", ephemeral=True)

    except Exception as e:
        await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)

@tree.command(name="removewarning", description="Remove a specific warning by ID")
async def removewarning(interaction: discord.Interaction, user: discord.Member, warning_id: str):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ Staff only.", ephemeral=True)
        return

    if coll is not None:
        res = coll.update_one({"_id": str(user.id)}, {"$pull": {"warnings": {"warn_id": warning_id.upper()}}, "$inc": {"warn_count": -1}})
        if res.modified_count > 0:
            await send_warn_log("Warning Removed", interaction.user, user, warn_id=warning_id.upper())
            await interaction.response.send_message(f"🗑️ Removed warning **{warning_id}**.")
        else:
            await interaction.response.send_message("ID not found.", ephemeral=True)

@tree.command(name="clearwarning", description="Clear all warnings for a user")
async def clearwarning(interaction: discord.Interaction, user: discord.Member):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ Staff only.", ephemeral=True)
        return

    if coll is not None:
        coll.update_one({"_id": str(user.id)}, {"$set": {"warnings": [], "warn_count": 0}})
        await send_warn_log("Warnings Cleared", interaction.user, user, extra="All warning data wiped.")
        await interaction.response.send_message(f"🧹 Cleared all records for {user.mention}.")

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
    
@tree.command(name="customrole", description="Create a custom role (Costs 50 Points)")
@app_commands.describe(name="Role Name", color="Hex code (e.g. #ff0000)")
async def customrole(interaction: discord.Interaction, name: str, color: str):
    user_data = get_user_data(interaction.user.id)
    points = user_data.get("points", 0)

    if points < 50:
        await interaction.response.send_message(f"❌ You need 50 points (Current: {points})", ephemeral=True)
        return

    try:
        # Convert hex to discord color
        clean_color = int(color.replace("#", ""), 16)
        new_role = await interaction.guild.create_role(name=name, color=discord.Color(clean_color))
        await interaction.user.add_roles(new_role)
        
        # Deduct Points
        update_points(interaction.user.id, -50)
        
        await interaction.response.send_message(f"✅ Created role **{name}**! 50 points deducted.")
    except Exception as e:
        await interaction.response.send_message(f"❌ Error: {e}. Ensure the color is a valid Hex code.", ephemeral=True)

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

@bot.event
async def on_message_delete(message):
    if message.author.bot:
        return
    
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if not channel:
        return

    embed = discord.Embed(
        title="🗑️ Message Deleted",
        color=discord.Color.red(),
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="Author", value=f"{message.author.mention} (`{message.author.id}`)", inline=True)
    embed.add_field(name="Channel", value=message.channel.mention, inline=True)
    
    # Handle Text Content
    content = message.content or "[No text content]"
    embed.add_field(name="Content", value=content, inline=False)
    
    # --- NEW: Handle Image/Attachment Logging ---
    if message.attachments:
        # Get the first attachment URL
        attachment = message.attachments[0]
        if any(attachment.filename.lower().endswith(ext) for ext in ['png', 'jpg', 'jpeg', 'gif', 'webp']):
            embed.set_image(url=attachment.proxy_url)
            embed.add_field(name="Attachments", value=f"Image: {attachment.filename}", inline=False)
        else:
            embed.add_field(name="Attachments", value=f"File: {attachment.filename}", inline=False)

    embed.set_footer(text=f"Message ID: {message.id}")
    
    await channel.send(embed=embed)
    
@bot.event
async def on_bulk_message_delete(messages):
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if not channel:
        return

    # Count which users had messages deleted
    authors = Counter(f"{m.author.name}#{m.author.discriminator}" for m in messages)
    author_summary = "\n".join([f"**{name}**: {count} messages" for name, count in authors.items()])

    embed = discord.Embed(
        title="🧹 Mass Message Deletion (Purge)",
        description=f"**{len(messages)}** messages were deleted in {messages[0].channel.mention}",
        color=discord.Color.dark_red(),
        timestamp=datetime.utcnow()
    )
    
    if author_summary:
        embed.add_field(name="Affected Users", value=author_summary[:1024], inline=False)
    
    await channel.send(embed=embed)

@bot.event
async def on_message_edit(before, after):
    if before.author.bot or before.content == after.content:
        return

    channel = bot.get_channel(LOG_CHANNEL_ID)
    if not channel:
        return

    embed = discord.Embed(
        title="📝 Message Edited",
        color=discord.Color.blue(),
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="Author", value=f"{before.author.mention} (`{before.author.id}`)", inline=True)
    embed.add_field(name="Channel", value=before.channel.mention, inline=True)
    embed.add_field(name="Before", value=before.content or "[No text content]", inline=False)
    embed.add_field(name="After", value=after.content or "[No text content]", inline=False)
    
    await channel.send(embed=embed)

# --- Voice Channel Logs ---

@bot.event
async def on_voice_state_update(member, before, after):
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if not channel:
        return

    embed = discord.Embed(timestamp=datetime.utcnow())
    embed.set_author(name=f"{member.name}#{member.discriminator}", icon_url=member.display_avatar.url)

    # User Joined VC
    if before.channel is None and after.channel is not None:
        embed.title = "🔊 Joined Voice Channel"
        embed.color = discord.Color.green()
        embed.description = f"{member.mention} joined **{after.channel.name}**"
    
    # User Left VC
    elif before.channel is not None and after.channel is None:
        embed.title = "🔇 Left Voice Channel"
        embed.color = discord.Color.red()
        embed.description = f"{member.mention} left **{before.channel.name}**"
    
    # User Switched VC
    elif before.channel is not None and after.channel is not None and before.channel.id != after.channel.id:
        embed.title = "↔️ Switched Voice Channel"
        embed.color = discord.Color.gold()
        embed.description = f"{member.mention} moved from **{before.channel.name}** to **{after.channel.name}**"
    
    else:
        # Ignore mute/deafen updates
        return

    await channel.send(embed=embed)

bot.run(hUIPJ21boH)
