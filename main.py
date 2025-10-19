import discord
from discord.ext import commands, tasks
import logging
import os
import time as py_time  # renamed to avoid conflict with datetime.time
import asyncio
from datetime import datetime, timedelta, time, timezone 
from dotenv import load_dotenv
import aiohttp
from flask import Flask
from threading import Thread
from typing import Dict, List, Optional

# 🚀 WEB SERVER FOR RAILWAY
app = Flask('')

@app.route('/')
def home():
    return "🤖 Techfour Bot is Alive! Powered by Groq AI"
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
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
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

# 🤖 GROQ AI SERVICE
class GroqAIService:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.groq.com/openai/v1/chat/completions"  # removed trailing spaces
        self.session: Optional[aiohttp.ClientSession] = None
        self.response_cache: Dict[str, dict] = {}
        self.CACHE_DURATION = 300  # 5 menit
        
    async def get_session(self):
        if self.session is None:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def close_session(self):
        if self.session:
            await self.session.close()
            self.session = None
    
    async def get_response(self, user_prompt: str, user_id: int) -> Optional[str]:
        """Dapatkan response dari Groq AI dengan caching"""
        cache_key = f"{user_id}_{user_prompt[:50]}"
        if cache_key in self.response_cache:
            cached_data = self.response_cache[cache_key]
            if py_time.time() - cached_data['timestamp'] < self.CACHE_DURATION:
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
                    "model": "llama-3.1-8b-instant",
                    "messages": [
                        {
                            "role": "system", 
                        "content": 
    "Kamu adalah Techfour, asisten AI resmi untuk kelas Teknik Informatika 01TPLE004. "
    "Kamu hanya boleh menggunakan informasi dari DATA RESMI berikut:\n\n"
    
    "=== DATA RESMI (UPDATE: Oktober 2025) ===\n"
    "- Pembuat kamu: Mahasiswa Universitas Pamulang kelas 01TPLE104\n"
    "- Jadwal Kelas: Sabtu, pukul 07:40-15:20 WIB, Gedung A- UNPAM VIKTOR Lt1 Ruang 104\n"
    "- Jadwal Ujian Online: 27 Oktober hingga 01 November. Matakuliah = Pendidikan Pancasila, Pendidikan Agama, Logika Informatika, Fisika Dasar \n"
    "- Jadwal Ujian Offline: Hari Sabtu, 01 November di UNPAM VIKTOR GEDUNG A LT1 RUANG 104. Matakuliah = Kalkulus, Algoritma&Pemograman, Basic English, Pengantar Teknologi\n"
    "- Jadwal E-Learning: Senin hingga Jum'at Mata kuliah = Pendidikan Pancasila, Pendidikan Agama, Logika Informatika, Fisika Dasar \n"
    "- Server Discord: Techfour\n"
    "- Aturan Server: Dilarang bahas politik, SARA, dan konten toxic\n"
    "========================================\n\n"
    
    "ATURAN MUTLAK:\n"
    "1. JIKA PERTANYAAN TERKAIT UJIAN,UTS,UAS BERIKAN DATA RESMI Jadwal Ujian Online dan Jadwal Ujian Offline.\n"
    "2. JIKA PERTANYAAN TERKAIT E-LEARNING, MENTARI, KELAS ONLINE BERIKAN DATA RESMI Jadwal E-Learning.\n"
    "3. JIKA PERTANYAAN TERKAIT KALKULUS,MATEMATIKA,FISIKA HARUS BERDASARKAN RUMUS DAN PERHITUNGAN YANG AKURAT.\n"
    "4. JIKA PERTANYAAN TERKAIT BAHASA INGGRIS SEPERTI PATERN TENSE,PERFECT TENSE,DAN LAIN SEBAGAINYA YANG TERKAIT, BERIKAN JAWABAN YANG TEPAT BERDASARKAN SUMBER RESMI.\n"
    "5. JAWAB DENGAN TEPAT BERDASARKAN DATA ACTUAL DAN DARI SUMBER RESMI.\n"
    "6. JIKA PERTANYAAN TIDAK ADA DI DATA RESMI DI ATAS, katakan: \"Maaf, saya tidak tahu informasi itu.\"\n"
    "7. JANGAN PERNAH MENGARANG, MENEBAK, ATAU MEMBERI CONTOH FIKTIF.\n"
    "8. Gunakan bahasa Indonesia santai, seperti teman sekelas (pakai 'kamu', bukan 'Anda').\n"
    "9. Jika ditanya tanggal/hari, Jawab dengan valid dihari saat ini .\n"
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
                
                self.response_cache[cache_key] = {
                    'response': reply,
                    'timestamp': py_time.time()
                }
                
                return reply
                
        except asyncio.TimeoutError:
            logging.error("Groq API timeout")
            return None
        except Exception as e:
            logging.error(f"Groq API error: {e}")
            return None
    
    def clean_old_cache(self):
        """Bersihkan cache yang sudah expired"""
        current_time = py_time.time()
        expired_keys = [
            key for key, data in self.response_cache.items() 
            if current_time - data['timestamp'] > self.CACHE_DURATION
        ]
        for key in expired_keys:
            del self.response_cache[key]

groq_service = GroqAIService(GROQ_API_KEY) if GROQ_API_KEY else None

# ⏰ BACKGROUND TASKS
@tasks.loop(hours=24)
async def reset_daily_task():
    rate_limiter.reset_daily_limits()
    logging.info("Daily limits reset via background task")

@tasks.loop(minutes=5)
async def clean_cache_task():
    if groq_service:
        groq_service.clean_old_cache()
    logging.info("Cache cleaned")

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
        
        if not groq_service or not GROQ_API_KEY:
            await message.channel.send(
                f"{message.author.mention} 🤖 Maaf, saat ini Anda tidak bisa menggunakan AI. Silahkan menghubungi developer - Jundi Lesana @jonjon1227"
            )
            return

        try:
            await rate_limiter.start_ai_request(message.author.id)
            reply = await groq_service.get_response(user_prompt, message.author.id)
            
            if reply:
                await message.channel.send(reply)
            else:
                await message.channel.send(
                    f"{message.author.mention} 🤖 Maaf, terjadi error. Coba lagi nanti."
                )
                
        except Exception as e:
            logging.exception(f"Error processing AI request: {e}")
            await message.channel.send(
                f"{message.author.mention} 🤖 Maaf, terjadi error. Coba lagi nanti."
            )
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

# 🎮 BOT COMMANDS
@bot.command()
async def usage(ctx: commands.Context):
    is_user_admin = is_admin(ctx.author)
    daily_limit = 50 if is_user_admin else 30
    daily_usage = rate_limiter.user_daily_usage.get(ctx.author.id, 0)
    remaining = daily_limit - daily_usage
    
    embed = discord.Embed(title="📊 Usage Stats", color=discord.Color.blue())
    embed.add_field(name="Used Today", value=f"{daily_usage} prompts", inline=True)
    embed.add_field(name="Limit", value=f"{daily_limit} prompts", inline=True)
    embed.add_field(name="Remaining", value=f"{remaining} prompts", inline=True)
    embed.add_field(name="Reset In", value="24 hours", inline=True)
    
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

@bot.command()
@commands.has_permissions(administrator=True)
async def check_inactive(ctx: commands.Context):
    inactive_members = activity_tracker.get_inactive_members(ctx.guild, days_threshold=3)
    
    if not inactive_members:
        await ctx.send("✅ Tidak ada member yang tidak aktif selama 3 hari.")
        return
    
    inactive_list = "\n".join([f"• {member.display_name} ({days} hari)" for member, days in inactive_members[:10]])
    await ctx.send(f"**Member Tidak Aktif (3+ hari):**\n{inactive_list}")

# 🚀 BOT STARTUP
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user.name} (ID: {bot.user.id})")
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
        if groq_service:
            await groq_service.close_session()
        if webhook_logger:
            await webhook_logger.close_session()
        await bot.close()

if __name__ == "__main__":
    asyncio.run(main())
