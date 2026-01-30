import discord
import os
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

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

ANNOUNCE_CHANNEL_ID = 1458464867366342809

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} (ID: {bot.user.id})')
    print('------')
    
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


@bot.event
async def on_message(message):
    if message.content == "Test":
        await send_boost_announcement(message.author)

bot.run(hUIPJ21boH)