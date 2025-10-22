import discord
from discord.ext import commands, tasks
import logging
import os
import time as py_time 
import asyncio
from datetime import datetime, timedelta, time, timezone 
from dotenv import load_dotenv
import aiohttp
from flask import Flask
from threading import Thread
from typing import Dict, List, Optional
from huggingface_service import huggingface_service as ai_service

# 🚀 WEB SERVER FOR RAILWAY
app = Flask('')

@app.route('/')
def home():
    return "🤖 Techfour Bot is Alive! Powered by Groq"
def run_webserver():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

def keep_alive():
    t = Thread(target=run_webserver)
    t.daemon = True
    t.start()

# 📊 LOGGING SETUP
if os.path.exists("discord.log"):
    os.remove("discord.log")

logging.basicConfig(
    filename="discord.log",
    filemode="w",
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.info("=== Bot dimulai fresh ===")

# 🔐 ENVIRONMENT VARIABLES
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL") 

if not DISCORD_TOKEN:
    raise ValueError("❌ Pastikan DISCORD_TOKEN sudah diisi di file .env")

# 🤖 BOT SETUP
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.presences = True  # tracking activity member

bot = commands.Bot(command_prefix="!", intents=intents)

# 📈 RATE LIMITING & TRACKING SYSTEM

class RateLimiter:
    def __init__(self):
        self.user_cooldowns: Dict[int, float] = {}
        self.user_daily_usage: Dict[int, int] = {}
        self.last_reset_time: float = py_time.time()
        self.active_ai_requests: int = 0
        self.ai_request_lock = asyncio.Lock()
        
    def reset_daily_limits(self):
        """Reset daily usage setiap 24 jam"""
        self.user_daily_usage.clear()
        self.last_reset_time = py_time.time()
        logging.info("Daily limits reset")
    
    def get_daily_limit(self, is_admin: bool) -> int:
        return 50 if is_admin else 30
    
    async def can_use_ai(self, user_id: int, is_admin: bool) -> tuple[bool, Optional[str]]:
        current_time = py_time.time()
        daily_limit = self.get_daily_limit(is_admin)
        
        # Cek concurrent requests (maximal 2)
        async with self.ai_request_lock:
            if self.active_ai_requests >= 2:
                return False, "⏳ Sedang ada 2 orang menggunakan AI. Tunggu 5 detik ya!"
            
            # Cek cooldown 15 detik (kamu ubah jadi 15, oke!)
            if user_id in self.user_cooldowns:
                time_since_last = current_time - self.user_cooldowns[user_id]
                if time_since_last < 15:
                    return False, f"⏳ Tunggu {int(15 - time_since_last)} detik lagi sebelum menggunakan AI."
            
            # Cek daily limit
            daily_count = self.user_daily_usage.get(user_id, 0)
            if daily_count >= daily_limit:
                return False, f"🚫 Limit harianmu sudah habis ({daily_count}/{daily_limit}). Reset dalam 24 jam."
            
            return True, None
    
    async def start_ai_request(self, user_id: int):
        async with self.ai_request_lock:
            self.active_ai_requests += 1
        self.user_cooldowns[user_id] = py_time.time()
        self.user_daily_usage[user_id] = self.user_daily_usage.get(user_id, 0) + 1
    
    async def end_ai_request(self):
        async with self.ai_request_lock:
            self.active_ai_requests -= 1

rate_limiter = RateLimiter()

# 🔄 ACTIVITY TRACKING SYSTEM
class ActivityTracker:

    def __init__(self):
        self.last_activity: Dict[int, datetime] = {}
    
    def update_activity(self, user_id: int):
        """Update last activity untuk user"""
        self.last_activity[user_id] = datetime.now()
    
    def get_inactive_members(self, guild: discord.Guild, days_threshold: int = 3) -> List[discord.Member]:
        """Dapatkan member yang tidak aktif selama X hari"""
        inactive_members = []
        now = datetime.now()
        
        for member in guild.members:
            if member.bot:
                continue
                
            user_id = member.id
            if user_id not in self.last_activity:
                self.last_activity[user_id] = now
                continue
            
            last_active = self.last_activity[user_id]
            days_inactive = (now - last_active).days
            
            if days_inactive >= days_threshold:
                inactive_members.append((member, days_inactive))
        
        return inactive_members

activity_tracker = ActivityTracker()

def is_admin(member: discord.Member) -> bool:
    """Cek apakah member adalah admin berdasarkan role atau owner server"""

    if member.guild.owner_id == member.id:
        return True
    
    admin_roles = ["Admin", "Administrator", "Owner", "Moderator"]
    
    for role in member.roles:
        if role.name in admin_roles:
            return True
    
    return False
# 🔗 WEBHOOK LOGGER
class WebhookLogger:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def get_session(self):
        if self.session is None:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def close_session(self):
        if self.session:
            await self.session.close()
            self.session = None
    
    async def send_log(self, content: str):
        """Kirim pesan text ke webhook"""
        if not self.webhook_url:
            return
        
        try:
            session = await self.get_session()
            async with session.post(
                self.webhook_url,
                json={"content": content}
            ) as response:
                if response.status != 204:
                    logging.error(f"Webhook error: {response.status}")
        except Exception as e:
            logging.error(f"Webhook send error: {e}")

webhook_logger = WebhookLogger(WEBHOOK_URL)

# ✅ FIXED: FRIDAY REMINDER 18:00 WIB
WIB = timezone(timedelta(hours=7))  # Jakarta = UTC+7

@tasks.loop(time=time(hour=11, minute=0))  # 11:00 UTC = 18:00 WIB
async def friday_reminder():
    now_utc = datetime.now(timezone.utc)
    now_wib = now_utc.astimezone(WIB)
    
    # Log untuk verifikasi
    logging.info(f"[FRIDAY REMINDER] Triggered at UTC: {now_utc.strftime('%Y-%m-%d %H:%M')} | WIB: {now_wib.strftime('%A, %Y-%m-%d %H:%M')}")
    
# Check if today is FRIDAY in WIB
    if now_wib.weekday() == 4:  # 4 = Jumat (Senin=0, ..., Jumat=4)
        try:
            message = (
                "Hai @everyone jangan lupa tugas E-learning, tulis tangan, dan lain "
                "sebagainya dikerjakan yh, karena besok jam 07:40 kita masuk kelas, "
                "persiapkan dirimu untuk hari esok 😊"
            )
            
            for guild in bot.guilds:
                for channel in guild.text_channels:
                    if channel.permissions_for(guild.me).send_messages:
                        try:
                            await channel.send(message)
                            logging.info(f"✅ Friday reminder sent to {channel.name} in {guild.name} at {now_wib.strftime('%Y-%m-%d %H:%M WIB')}")
                            break
                        except Exception as e:
                            logging.error(f"❌ Failed to send reminder to {channel.name}: {e}")
        except Exception as e:
            logging.error(f"❌ Error in Friday reminder: {e}")
    else:
        logging.info(f"⏭️ Bukan hari Jumat di WIB ({now_wib.strftime('%A')}), lewati pengiriman.")


# 🎯 EVENT HANDLERS
@bot.event
async def on_member_join(member: discord.Member):
    try:
        activity_tracker.update_activity(member.id)
        channel = None
        for ch in member.guild.text_channels:
            if ch.permissions_for(member.guild.me).send_messages:
                channel = ch
                break
        
        if channel:
            welcome_message = f"🎉 Selamat datang di server **{member.guild.name}** {member.display_name}! Semoga betah ya!"
            await channel.send(welcome_message)
            await webhook_logger.send_log(f"🟢 {member.display_name} bergabung ke server")
            logging.info(f"Welcome message sent for {member.display_name}")
            
    except Exception as e:
        logging.error(f"Error sending welcome message: {e}")

@bot.event
async def on_member_remove(member: discord.Member):
    try:
        channel = None
        for ch in member.guild.text_channels:
            if ch.permissions_for(member.guild.me).send_messages:
                channel = ch
                break
        
        if channel:
            goodbye_message = f"👋 {member.display_name} meninggalkan server! Semoga sukses di mana pun!"
            await channel.send(goodbye_message)
            await webhook_logger.send_log(f"🔴 {member.display_name} meninggalkan server")
            logging.info(f"Goodbye message sent for {member.display_name}")
            
    except Exception as e:
        logging.error(f"Error sending goodbye message: {e}")

@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return

    activity_tracker.update_activity(message.author.id)

    CARIAMAN_KEYWORDS = ["prabowo", "jokowi", "megawati", "sukarno", "luhut", "puan"]
    TOXIC_KEYWORDS = ["kontol", "memek", "titit", "mmk", "jembut", "bangsat", "ngentod", "peler"]
    
    content_lower = message.content.lower()
    
    if any(word in content_lower for word in CARIAMAN_KEYWORDS + TOXIC_KEYWORDS):
        try:
            await message.delete()
            await message.channel.send(f"{message.author.mention}, jaga obrolannya ya 🙏")
        except discord.Forbidden:
            pass
        return

    if bot.user.mentioned_in(message) and not message.mention_everyone:
        user_prompt = message.content.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()
        
        if not user_prompt:
            await message.channel.send(
                f"Halo {message.author.mention}! Ketik pesan setelah mention saya untuk bicara 🤖"
            )
            return

        user_is_admin = is_admin(message.author)
        
        can_request, error_msg = await rate_limiter.can_use_ai(message.author.id, user_is_admin)
        
        if not can_request:
            await message.channel.send(error_msg)
            return

        await message.channel.typing()
        
        try:
            await rate_limiter.start_ai_request(message.author.id)
            
            reply = await groq_service.get_response(user_prompt, message.author.id)
            
            if reply:
                await message.channel.send(reply)
            else:
                await message.channel.send(
                    f"{message.author.mention} 🤖 Maaf, AI Bot sedang sibuk. Coba lagi sebentar ya!"
                )
                
        except Exception as e:
            logging.exception(f"Error processing AI request: {e}")
            await message.channel.send(f"{message.author.mention}🤖 Maaf, terjadi error. silahkan hubungi developer @jonjon1227")
            
        finally:
            await rate_limiter.end_ai_request()

        return

    await bot.process_commands(message)

@bot.event
async def on_presence_update(before: discord.Member, after: discord.Member):
    if after.status != discord.Status.offline:
        activity_tracker.update_activity(after.id)

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if after.channel is not None:
        activity_tracker.update_activity(member.id)

@bot.command()
async def ping(ctx):
    latency = round(bot.latency * 1000)
    daily_usage = rate_limiter.user_daily_usage.get(ctx.author.id, 0)
    active_requests = rate_limiter.active_ai_requests
    
    embed = discord.Embed(title="🏓 Pong!", color=discord.Color.green())
    embed.add_field(name="Latency", value=f"{latency}ms", inline=True)
    embed.add_field(name="Daily Usage", value=f"{daily_usage}/50", inline=True)
    embed.add_field(name="Active AI Requests", value=f"{active_requests}/2", inline=True)
    embed.add_field(name="AI Provider", value="🤖 Groq + Llama 3.1", inline=True)
    embed.add_field(name="Status", value="✅ Unlimited & Smart", inline=True)
    
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def reset_limits(ctx: commands.Context, user: discord.Member = None):
    if user:
        rate_limiter.user_daily_usage.pop(user.id, None)
        rate_limiter.user_cooldowns.pop(user.id, None)
        await ctx.send(f"✅ Limits untuk {user.mention} telah direset!")
    else:
        rate_limiter.reset_daily_limits()
        await ctx.send("✅ Semua daily limits telah direset!")

@tasks.loop(hours=24)
async def check_inactive_members():
    try:
        for guild in bot.guilds:
            inactive_members = activity_tracker.get_inactive_members(guild, days_threshold=3)
            
            for member, days_inactive in inactive_members:
                try:
                    await member.send(
                        f"👋 Hai {member.mention}, Anda sudah tidak aktif "
                        f"selama {days_inactive} hari di server **{guild.name}**!\n\n"
                        f"💬 Ayo kembali berkontribusi di server!"
                    )
                    
                    last_active = activity_tracker.last_activity[member.id]
                    await webhook_logger.send_log(
                        f"⚪ {member.display_name} tidak aktif selama {days_inactive} hari. "
                        f"Terakhir aktif: {last_active.strftime('%Y-%m-%d %H:%M')}"
                    )
                    
                    logging.info(f"Notified inactive member: {member.name} ({days_inactive} days)")
                    
                except discord.Forbidden:
                    logging.warning(f"Cannot DM inactive member: {member.name}")
                except Exception as e:
                    logging.error(f"Error handling inactive member {member.name}: {e}")
                    
    except Exception as e:
        logging.error(f"Error in inactive members check: {e}")

# 🚀 BOT STARTUP
@bot.event
async def on_ready():
    logging.info(f"✅ Logged in as {bot.user.name} (ID: {bot.user.id})")
    print(f"🌐 Connected to {len(bot.guilds)} servers")
    logging.info(f"Bot siap dengan PID: {os.getpid()}")
    
    keep_alive()
    print("🌐 Web server started for Railway deployment")
    
    for guild in bot.guilds:
        for member in guild.members:
            if not member.bot:
                activity_tracker.update_activity(member.id)
    
    reset_daily_task.start()
    clean_cache_task.start()
    check_inactive_members.start()
    friday_reminder.start()
    
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.listening, 
            name="!ping | @Techfour"
        )
    )

async def main():
    try:
        keep_alive()
        print("🚀 Starting Techfour Discord Bot...")
        await bot.start(DISCORD_TOKEN)
    except Exception as e:
        logging.exception(f"Bot crashed: {e}")
    finally:
        # Tidak perlu close Groq session lagi
        if webhook_logger:
            await webhook_logger.close_session()
        await bot.close()

if __name__ == "__main__":
    asyncio.run(main())
