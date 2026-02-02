import discord
import os
import json
import re
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

def run_health_check():
    # Render provides a PORT environment variable
    port = int(os.environ.get("PORT", 8080))
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
        expected = ["top_swearer", "userswearcount", "addswear", "remswear", "listswears", "testscan"]
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
            
        response = "**🏆 Swear Word Leaderboard**\n" + "\n".join(leaderboard)
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