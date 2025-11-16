import discord
from discord.ext import commands, tasks
import logging
import os
import time as py_time
import asyncio
from datetime import datetime, timedelta, time, timezone
from dotenv import load_dotenv
import aiohttp
from typing import Dict, List, Optional
import re

from ai_bot_service import ai_bot_service
from aiohttp import web

print("🚀 Starting Techfour Bot")

# HEALTHCHECK SERVER
async def start_webserver():
    """Webserver dengan endpoint yang benar"""
    async def health(req):
        return web.Response(text="OK")
    
    async def health_check(req):
        return web.Response(text="OK")

    port = int(os.getenv("PORT", 8080))
    app = web.Application()
    
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    app.router.add_get("/kaithhealthcheck", health)
    app.router.add_get("/healthcheck", health)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    print(f"🌐 Healthcheck server running on port {port}")
    print("✅ Endpoints: /, /health, /kaithhealthcheck, /healthcheck")

# LOGGING
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logging.info("=== Techfour Bot Started ===")

# ENVIRONMENT
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

if not DISCORD_TOKEN:
    raise ValueError("❌ Missing DISCORD_TOKEN")

# BOT SETUP
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.presences = True

bot = commands.Bot(command_prefix="!", intents=intents)

# RATE LIMITER
class RateLimiter:
    def __init__(self):
        self.user_cooldowns: Dict[int, float] = {}
        self.user_daily_usage: Dict[int, int] = {}
        self.last_reset_time: float = py_time.time()
        self.DAILY_RESET_INTERVAL = 24 * 60 * 60

    def check_reset(self):
        now = py_time.time()
        if now - self.last_reset_time >= self.DAILY_RESET_INTERVAL:
            self.user_daily_usage.clear()
            self.last_reset_time = now

    def get_daily_limit(self, admin):
        return 10 if admin else 5

    async def can_use_ai(self, user_id, admin):
        self.check_reset()

        now = py_time.time()

        # cooldown
        if user_id in self.user_cooldowns:
            diff = now - self.user_cooldowns[user_id]
            if diff < 60:
                return False, f"⏳ Tunggu {int(60-diff)} detik sebelum menggunakan AI lagi."

        # daily limit
        used = self.user_daily_usage.get(user_id, 0)
        limit = self.get_daily_limit(admin)
        if used >= limit:
            return False, f"🚫 Limit {used}/{limit} habis. Reset 24 jam."

        return True, None

    async def record(self, user_id):
        self.user_cooldowns[user_id] = py_time.time()
        self.user_daily_usage[user_id] = self.user_daily_usage.get(user_id, 0) + 1

rate_limiter = RateLimiter()

# ACTIVITY TRACKER
class ActivityTracker:
    def __init__(self):
        self.last_activity = {}

    def update_activity(self, uid):
        self.last_activity[uid] = datetime.now()

activity_tracker = ActivityTracker()

def is_admin(member: discord.Member):
    if member.guild.owner_id == member.id:
        return True
    for role in member.roles:
        if role.name.lower() in ["admin", "administrator", "owner", "moderator"]:
            return True
    return False

# WEBHOOK LOGGER
class WebhookLogger:
    def __init__(self, url):
        self.url = url
        self.session = None

    async def _session(self):
        if not self.session:
            self.session = aiohttp.ClientSession()
        return self.session

    async def send(self, content):
        if not self.url:
            return
        ses = await self._session()
        try:
            async with ses.post(self.url, json={"content": content}) as r:
                if r.status != 204:
                    logging.error(f"Webhook error: {r.status}")
        except Exception as e:
            logging.error(f"Webhook send failed: {e}")

webhook_logger = WebhookLogger(WEBHOOK_URL)

# JADWAL KULIAH SYSTEM 
WIB = timezone(timedelta(hours=7))

def parse_jadwal_file():
    """Parse file JadwalKuliah.txt dan ekstrak jadwal"""
    jadwal_data = []
    
    try:
        with open('JadwalKuliah.txt', 'r', encoding='utf-8') as file:
            content = file.read()
        
        # Pattern untuk mengekstrak periode
        periods = re.split(r'(?=E-Learning\s+\d{1,2}[A-Za-z]+\s*-\s*\d{1,2}[A-Za-z]+\s*\d{4}|UAS\s*[\r\n]+\d{1,2}[A-Za-z]+\s*-\s*\d{1,2}[A-Za-z]+\s*\d{4})', content)
        
        for period in periods:
            if not period.strip():
                continue
                
            # E-Learning
            if period.startswith('E-Learning'):
                date_match = re.search(r'E-Learning\s+(\d{1,2}[A-Za-z]+\s*-\s*\d{1,2}[A-Za-z]+\s*\d{4})', period)
                if date_match:
                    date_range = date_match.group(1)
                    start_date = extract_start_date(date_range)
                    
                    # Cari konten sampai Tatap Muka atau pemisah berikutnya
                    content_match = re.search(r'(E-Learning\s+[\dA-Za-z\s\-]+[\s\S]*?)(?=Tatap muka|E-Learning|UAS|--------------------------------)', period)
                    content = content_match.group(1).strip() if content_match else period.strip()
                    
                    jadwal_data.append({
                        'type': 'E-Learning',
                        'date_range': date_range,
                        'start_date': start_date,
                        'content': content
                    })
            
            # Tatap Muka
            elif 'Tatap muka' in period:
                date_match = re.search(r'Tatap muka\s+(\d{1,2}[A-Za-z]+\s*-\s*[A-Za-z]+)', period)
                if date_match:
                    date_range = date_match.group(1)
                    start_date = extract_start_date(date_range)
                    
                    content_match = re.search(r'(Tatap muka\s+[\dA-Za-z\s\-]+[\s\S]*?)(?=E-Learning|Tatap muka|UAS|--------------------------------)', period)
                    content = content_match.group(1).strip() if content_match else period.strip()
                    
                    jadwal_data.append({
                        'type': 'Tatap Muka',
                        'date_range': date_range,
                        'start_date': start_date,
                        'content': content
                    })
            
            # UAS
            elif period.startswith('UAS') or 'UAS' in period:
                date_match = re.search(r'UAS\s*[\r\n]+(\d{1,2}[A-Za-z]+\s*-\s*\d{1,2}[A-Za-z]+\s*\d{4})', period)
                if date_match:
                    date_range = date_match.group(1)
                    start_date = extract_start_date(date_range)
                    
                    jadwal_data.append({
                        'type': 'UAS',
                        'date_range': date_range,
                        'start_date': start_date,
                        'content': f"UAS\n{date_range}"
                    })
        
        # Sort by start date
        jadwal_data.sort(key=lambda x: x['start_date'])
        
    except FileNotFoundError:
        print("❌ File JadwalKuliah.txt tidak ditemukan")
        logging.error("File JadwalKuliah.txt tidak ditemukan")
    except Exception as e:
        print(f"❌ Error parsing jadwal file: {e}")
        logging.error(f"Error parsing jadwal file: {e}")
    
    return jadwal_data

def extract_start_date(date_range):
    """Ekstrak tanggal mulai dari range tanggal"""
    try:
        date_part = re.split(r'[-–]', date_range)[0].strip()
        
        # Ekstrak angka tanggal
        date_number = re.findall(r'\d+', date_part)
        if date_number:
            day = int(date_number[0])
            
            # Mapping nama bulan
            month_names = {
                'Januari': 1, 'Februari': 2, 'Maret': 3, 'April': 4, 'Mei': 5, 'Juni': 6,
                'Juli': 7, 'Agustus': 8, 'September': 9, 'Oktober': 10, 'November': 11, 'Desember': 12
            }
            
            for month_name, month_num in month_names.items():
                if month_name.lower() in date_range.lower():
                    year = 2025 if month_num >= 11 else 2026
                    return datetime(year, month_num, day)
        
        return datetime(2030, 1, 1)  # Fallback
    except:
        return datetime(2030, 1, 1)

def get_current_jadwal():
    """Dapatkan jadwal yang sesuai dengan tanggal sekarang"""
    now_wib = datetime.now(WIB).replace(tzinfo=None)
    jadwal_data = parse_jadwal_file()
    
    current_jadwal = []
    
    for jadwal in jadwal_data:
        days_diff = (jadwal['start_date'] - now_wib).days
        if -1 <= days_diff <= 7: 
            current_jadwal.append(jadwal)
    
    return current_jadwal

def get_upcoming_jadwal():
    """Dapatkan jadwal yang akan datang untuk reminder"""
    now_wib = datetime.now(WIB).replace(tzinfo=None) 
    jadwal_data = parse_jadwal_file()
    
    upcoming_jadwal = []
    
    for jadwal in jadwal_data:
        # Kirim reminder 1 hari sebelum jadwal dimulai
        reminder_date = jadwal['start_date'] - timedelta(days=1)
        
        if reminder_date.date() == now_wib.date():
            upcoming_jadwal.append(jadwal)
    
    return upcoming_jadwal

# TASK REMINDER JADWAL OTOMATIS
@tasks.loop(time=time(hour=8, minute=0))  # Jam 08:00 WIB setiap hari
async def daily_jadwal_reminder():
    """Mengirim reminder jadwal setiap hari"""
    now_wib = datetime.now(WIB)
    print(f"🔔 [JADWAL] Checking jadwal for: {now_wib.strftime('%Y-%m-%d %H:%M:%S')}")
    
    upcoming_jadwal = get_upcoming_jadwal()
    
    if upcoming_jadwal:
        for guild in bot.guilds:
            for channel in guild.text_channels:
                if channel.permissions_for(guild.me).send_messages:
                    try:
                        for jadwal in upcoming_jadwal:
                            message = (
                                f"📚 **REMINDER JADWAL KULIAH** 📚\n"
                                f"Besok akan dimulai:\n"
                                f"```\n{jadwal['content']}\n```\n"
                                f"Jangan lupa dipersiapkan! 🎓"
                            )
                            await channel.send(message)
                            print(f"🔔 [JADWAL] Reminder sent for: {jadwal['type']} {jadwal['date_range']}")
                        break
                    except Exception as e:
                        print(f"❌ [JADWAL] Error sending message: {e}")
                        continue
    else:
        print(f"🔔 [JADWAL] No upcoming jadwal for {now_wib.strftime('%Y-%m-%d')}")

# FRIDAY REMINDER 
@tasks.loop(time=time(hour=11, minute=0))
async def friday_reminder():
    now_utc = datetime.now(timezone.utc)
    now_wib = now_utc.astimezone(WIB)
    if now_wib.weekday() == 4:  # 4 = Friday
        message = (
            "Hai @everyone jangan lupa tugas E-learning, tulis tangan, dan lain sebagainya "
            "dikerjakan yah. Besok jam 07:40 kita masuk kelas. Semangat 💪"
        )
        for guild in bot.guilds:
            for channel in guild.text_channels:
                if channel.permissions_for(guild.me).send_messages:
                    try:
                        await channel.send(message)
                        break
                    except:
                        continue

# OCR HANDLER
async def handle_ocr_attachment(attachment, user_id: int):
    """Handle OCR processing dengan Gemini: unduh gambar, kirim sebagai bytes."""
    try:
        if attachment.size > 5_000_000:  # 5MB
            return "❌ File terlalu besar (max 5MB)."
        
        headers = {"Authorization": f"Bot {DISCORD_TOKEN}"}
        async with aiohttp.ClientSession() as session:
            async with session.get(attachment.url, headers=headers, timeout=10) as resp:
                if resp.status != 200:
                    return f"❌ Gagal mengunduh gambar. Status: {resp.status}"
                image_bytes = await resp.read()

        if len(image_bytes) == 0:
            return "❌ Gambar kosong."
        
        ocr_prompt = "Tolong ekstrak semua teks yang terlihat di gambar ini. Jika ada bagian yang tidak bisa dibaca atau tidak ada teks, beri tahu saya."
        ocr_result = await ai_bot_service.get_response(ocr_prompt, user_id, image_bytes=image_bytes)
        return f"📄 **Hasil OCR dari Gambar:**\n{ocr_result}"
    
    except asyncio.TimeoutError:
        return "❌ Timeout saat mengunduh gambar. Coba lagi nanti."
    except Exception as e:
        logging.error(f"OCR attachment error: {e}")
        return f"❌ Gagal memproses gambar. Coba lagi nanti."

# BOT EVENT HANDLERS
@bot.event
async def on_ready():
    print(f"🎉 {bot.user} ONLINE")
    print(f"📊 Connected to {len(bot.guilds)} servers")

    # start tasks
    friday_reminder.start()
    daily_jadwal_reminder.start()

    # start webserver
    asyncio.create_task(start_webserver())

    logging.info("Bot fully operational.")

@bot.event
async def on_message(msg):
    if msg.author == bot.user:
        return

    activity_tracker.update_activity(msg.author.id)

    # Filter kata kasar
    toxic_words = ["kontol", "memek", "bangsat", "ngentod, niki, anjing"]
    if any(word in msg.content.lower() for word in toxic_words):
        try:
            await msg.delete()
            await msg.channel.send(f"{msg.author.mention} jaga bahasanya ya 🙏")
        except Exception as e:
            logging.error(f"Error deleting toxic message: {e}")
        return

    # OCR Handler
    if msg.attachments:
        for attachment in msg.attachments:
            if attachment.filename.lower().endswith((".png", ".jpg", ".jpeg", ".pdf")):
                await msg.channel.typing()
                result = await handle_ocr_attachment(attachment, msg.author.id)
                await msg.channel.send(result)
                return

    # Handler untuk mention bot - jadwal kuliah
    if bot.user.mentioned_in(msg) and not msg.mention_everyone:
        user_prompt = msg.content.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip().lower()
        
        # Cek jika user menanyakan jadwal kuliah
        jadwal_keywords = ['jadwal', 'kuliah', 'elearning', 'e-learning', 'tatap muka', 'uas', 'perkuliahan', 'minggu ini', 'hari ini']
        if any(keyword in user_prompt for keyword in jadwal_keywords):
            await msg.channel.typing()
            current_jadwal = get_current_jadwal()
            
            if current_jadwal:
                response = f"📚 **JADWAL KULIAH TERDEKAT** 📚\n"
                response += f"Hai {msg.author.mention}! Berikut jadwal kuliah untuk minggu ini:\n\n"
                
                for jadwal in current_jadwal:
                    response += f"```\n{jadwal['content']}\n```\n"
                
                response += "🎓 *Jangan lupa dipersiapkan!*"
                
                if len(response) > 2000:
                    parts = [response[i:i+2000] for i in range(0, len(response), 2000)]
                    for part in parts:
                        await msg.channel.send(part)
                else:
                    await msg.channel.send(response)
                    
                print(f"📚 [JADWAL] Sent jadwal to {msg.author.name}")
                return
            else:
                await msg.channel.send(f"{msg.author.mention} 📚 Tidak ada jadwal kuliah dalam 7 hari ke depan. Coba tanya lagi minggu depan!")
                return
        
        # Handler AI biasa untuk mention
        prompt = msg.content.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()
        if not prompt:
            await msg.channel.send("Halo! Ada yang bisa kubantu?")
            return

        admin = is_admin(msg.author)
        can_use, error_msg = await rate_limiter.can_use_ai(msg.author.id, admin)
        if not can_use:
            await msg.channel.send(error_msg)
            return

        await msg.channel.typing()
        await rate_limiter.record(msg.author.id)
        reply = await ai_bot_service.get_response(prompt, msg.author.id)
        await msg.channel.send(reply[:2000])
        return

    await bot.process_commands(msg)

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)