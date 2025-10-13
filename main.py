import discord
from discord.ext import commands, tasks
import logging
import os
import requests
import time
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
import aiohttp

#  Clean up old logs & prepare new logging
if os.path.exists("discord.log"):
    os.remove("discord.log")

logging.basicConfig(
    filename="discord.log",
    filemode="w",
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.info("=== Bot dimulai fresh ===")

# Load token & API key from .env
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not DISCORD_TOKEN:
    raise ValueError("❌ Pastikan DISCORD_TOKEN sudah diisi di file .env")

#  Discord bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Rate Limiting & Monitoring System
user_cooldowns = {}  # {user_id: last_request_time}
user_daily_usage = {}  # {user_id: count}
last_reset_time = time.time()

# Cache for efficient batching
response_cache = {}
CACHE_DURATION = 300  # 5 minutes

# 🔧 Utility Functions
def reset_daily_limits():
    """Reset daily usage setiap 24 jam"""
    global user_daily_usage, last_reset_time
    user_daily_usage.clear()
    last_reset_time = time.time()
    logging.info("Daily limits reset")

def can_user_request(user_id):
    """Cek apakah user bisa membuat request"""
    current_time = time.time()
    
    # Check 1 minute cooldown
    if user_id in user_cooldowns:
        time_since_last = current_time - user_cooldowns[user_id]
        if time_since_last < 60:
            return False, f"⏳ Maaf {get_user_mention(user_id)}, kamu harus menunggu {int(60 - time_since_last)} detik lagi sebelum bisa menggunakan AI."
    
# Check daily limit 30 requests
    daily_count = user_daily_usage.get(user_id, 0)
    if daily_count >= 30:
        return False, f"🚫 Maaf {get_user_mention(user_id)}, limit harianmu (30 prompt) sudah habis. Limit akan direset dalam 24 jam."
    
    return True, None

def update_user_usage(user_id):
    """Update usage tracking untuk user"""
    user_cooldowns[user_id] = time.time()
    user_daily_usage[user_id] = user_daily_usage.get(user_id, 0) + 1

def get_user_mention(user_id):
    """Dapatkan user mention string"""
    return f"<@{user_id}>"

async def send_error_message(channel, user_mention=None):
    """Kirim pesan error standar"""
    error_msg = "🤖 Maaf, saat ini Anda tidak bisa menggunakan AI. Silahkan menghubungi developer - Jundi Lesmana (@jonjon1227)"
    if user_mention:
        error_msg = f"{user_mention} {error_msg}"
    await channel.send(error_msg)

#  Groq AI Service with Efficient Batching
class GroqAIService:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.groq.com/openai/v1/chat/completions"
        self.session = None
        
    async def get_session(self):
        if self.session is None:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def close_session(self):
        if self.session:
            await self.session.close()
            self.session = None
    
    async def get_response(self, user_prompt, user_id):
        """Dapatkan response dari Groq AI dengan caching"""
        # Check cache
        cache_key = f"{user_id}_{user_prompt[:50]}"
        if cache_key in response_cache:
            cached_data = response_cache[cache_key]
            if time.time() - cached_data['timestamp'] < CACHE_DURATION:
                return cached_data['response']
        
        try:
            session = await self.get_session()
            
            async with session.post(
                url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "llama3-8b-8192",  # Model Ai
                    "messages": [
                        {
                            "role": "system", 
                            "content": "Kamu adalah ARC-0104, AI asisten ramah di Discord server Teknik Informatika 01TPLE004. Jawablah dengan singkat dan jelas."
                        },
                        {"role": "user", "content": user_prompt}
                    ],
                    "max_tokens": 150,
                    "temperature": 0.7
                },
                timeout=30
            ) as response:
                
                if response.status != 200:
                    error_detail = await response.text()
                    logging.error(f"Groq API error: {response.status} - {error_detail}")
                    return None
                
                data = await response.json()
                reply = data["choices"][0]["message"]["content"].strip()
                
                # Save to cache
                response_cache[cache_key] = {
                    'response': reply,
                    'timestamp': time.time()
                }
                
                return reply
                
        except asyncio.TimeoutError:
            logging.error("Groq API timeout")
            return None
        except Exception as e:
            logging.error(f"Groq API error: {e}")
            return None

# Initialize Groq service
groq_service = GroqAIService(GROQ_API_KEY) if GROQ_API_KEY else None

# Background Tasks
@tasks.loop(hours=24)
async def reset_daily_task():
    """Reset daily limits setiap 24 jam"""
    reset_daily_limits()
    logging.info("Daily limits reset via background task")

@tasks.loop(minutes=5)
async def keep_alive_ping():
    """Ping untuk menjaga Replit tetap hidup"""
    try:
        # Clean up old cache
        current_time = time.time()
        expired_keys = [
            key for key, data in response_cache.items() 
            if current_time - data['timestamp'] > CACHE_DURATION
        ]
        for key in expired_keys:
            del response_cache[key]
            
        logging.info(f"Cache cleaned. Remaining: {len(response_cache)} items")
    except Exception as e:
        logging.error(f"Keep alive error: {e}")

# Event: Bot Ready
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user.name} (ID: {bot.user.id})")
    logging.info(f"Bot siap dengan PID: {os.getpid()}")
    
    # Start background tasks
    reset_daily_task.start()
    keep_alive_ping.start()
    
    # Set bot status
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.listening, 
            name="!ping | @ARC-0104"
        )
    )

# List of prohibited words
CARIAMAN_KEYWORDS = ["prabowo", "jokowi", "megawati", "sukarno", "luhut", "puan"]
TOXIC_KEYWORDS = ["kontol", "memek", "titit", "mmk", "jembut", "bangsat", "ngentod", "peler"]

# Event: Incoming messages with Rate Limitation
@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    content_lower = message.content.lower()
    
    # Forbidden word filter
    if any(word in content_lower for word in CARIAMAN_KEYWORDS + TOXIC_KEYWORDS):
        try:
            await message.delete()
            await message.channel.send(f"{message.author.mention}, jaga obrolannya ya 🙏")
        except discord.Forbidden:
            pass
        return

    # If the bot is mentioned (and not mention everyone)
    if bot.user.mentioned_in(message) and not message.mention_everyone:
        user_prompt = message.content.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()
        
        if not user_prompt:
            await message.channel.send(
                f"Halo {message.author.mention}! Ketik pesan setelah mention saya untuk bicara 🤖"
            )
            return

        # Check rate limiting
        can_request, error_msg = can_user_request(message.author.id)
        if not can_request:
            await message.channel.send(error_msg)
            return

        await message.channel.typing()
        
        # If Groq is not available
        if not groq_service or not GROQ_API_KEY:
            await send_error_message(message.channel, message.author.mention)
            return

        try:
            # Get response from Groq
            reply = await groq_service.get_response(user_prompt, message.author.id)
            
            if reply:
                # Update usage only if successful
                update_user_usage(message.author.id)
                await message.channel.send(reply)
            else:
                await send_error_message(message.channel, message.author.mention)
                
        except Exception as e:
            logging.exception(f"Error processing AI request: {e}")
            await send_error_message(message.channel, message.author.mention)

        return

    await bot.process_commands(message)

#  Command: Ping with info status
@bot.command()
async def ping(ctx):
    latency = round(bot.latency * 1000)
    daily_usage = user_daily_usage.get(ctx.author.id, 0)
    
    embed = discord.Embed(
        title="🏓 Pong!",
        color=discord.Color.green()
    )
    embed.add_field(name="Latency", value=f"{latency}ms", inline=True)
    embed.add_field(name="Daily Usage", value=f"{daily_usage}/30", inline=True)
    embed.add_field(name="AI Status", value="✅ Active" if groq_service else "❌ Offline", inline=True)
    
    await ctx.send(embed=embed)

# Command: Check usage
@bot.command()
async def usage(ctx):
    daily_usage = user_daily_usage.get(ctx.author.id, 0)
    remaining = 30 - daily_usage
    
    embed = discord.Embed(
        title="📊 Usage Stats",
        color=discord.Color.blue()
    )
    embed.add_field(name="Used Today", value=f"{daily_usage} prompts", inline=True)
    embed.add_field(name="Remaining", value=f"{remaining} prompts", inline=True)
    embed.add_field(name="Reset In", value="24 hours", inline=True)
    
    await ctx.send(embed=embed)

#  Command: Assign Role
@bot.command()
async def assign(ctx, *, role_name: str):
    role = discord.utils.get(ctx.guild.roles, name=role_name)
    if role is None:
        await ctx.send(f"Role '{role_name}' tidak ditemukan.")
        return
    try:
        await ctx.author.add_roles(role)
        await ctx.send(f"✅ Role '{role_name}' berhasil diberikan ke {ctx.author.mention}!")
    except discord.Forbidden:
        await ctx.send("Bot tidak punya izin untuk assign role ini.")
    except Exception as e:
        await ctx.send(f"Terjadi error: {e}")

#  Command: Admin - Reset limits
@bot.command()
@commands.has_permissions(administrator=True)
async def reset_limits(ctx, user: discord.Member = None):
    if user:
        user_daily_usage.pop(user.id, None)
        user_cooldowns.pop(user.id, None)
        await ctx.send(f"✅ Limits untuk {user.mention} telah direset!")
    else:
        reset_daily_limits()
        await ctx.send("✅ Semua daily limits telah direset!")

# Running bot with error handling
async def main():
    try:
        await bot.start(DISCORD_TOKEN)
    except Exception as e:
        logging.exception(f"Bot crashed: {e}")
    finally:
        await groq_service.close_session()
        await bot.close()

if __name__ == "__main__":
    # running bot
    asyncio.run(main())
