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
from ai_bot_service import ai_bot_service  # Pastikan ini mengimpor instance yang benar
import re  

print("✅ [DEBUG] Starting Techfour Bot...")

app = Flask('')

@app.route('/')
def home():
    return "🤖 Techfour Bot is Alive! Powered by JundiLesmana"

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
# OCR_API_KEY = os.getenv("OCR_API_KEY") # Tidak digunakan lagi

if not DISCORD_TOKEN:
    raise ValueError("❌ Pastikan DISCORD_TOKEN sudah diisi di file .env")

# 🤖 BOT SETUP
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.presences = True

bot = commands.Bot(command_prefix="!", intents=intents)

# 📈 RATE LIMITER
class RateLimiter:
    def __init__(self):
        self.user_cooldowns: Dict[int, float] = {}
        self.user_daily_usage: Dict[int, int] = {}
        self.last_reset_time: float = py_time.time()
        self.DAILY_RESET_INTERVAL = 24 * 60 * 60  # 24 jam dalam detik

    def check_reset(self):
        """Cek dan reset limit harian jika waktunya tiba."""
        current_time = py_time.time()
        if current_time - self.last_reset_time >= self.DAILY_RESET_INTERVAL:
            self.reset_daily_limits()

    def reset_daily_limits(self):
        self.user_daily_usage.clear()
        self.last_reset_time = py_time.time()
        logging.info("Daily limits reset")

    def get_daily_limit(self, is_admin: bool) -> int:
        return 10 if is_admin else 5

    async def can_use_ai(self, user_id: int, is_admin: bool) -> tuple[bool, Optional[str]]:
        self.check_reset() # Periksa reset sebelum cek limit
        
        current_time = py_time.time()
        daily_limit = self.get_daily_limit(is_admin)
        
        # Cek cooldown 60 detik
        if user_id in self.user_cooldowns:
            time_since_last = current_time - self.user_cooldowns[user_id]
            if time_since_last < 60:
                return False, f"⏳ Tunggu {int(60 - time_since_last)} detik lagi sebelum menggunakan AI."

        # Cek limit harian
        daily_count = self.user_daily_usage.get(user_id, 0)
        if daily_count >= daily_limit:
            return False, f"🚫 Limit harianmu sudah habis ({daily_count}/{daily_limit}). Reset dalam 24 jam."

        return True, None

    async def record_ai_request(self, user_id: int):
        """Catat penggunaan AI oleh user."""
        self.user_cooldowns[user_id] = py_time.time()
        self.user_daily_usage[user_id] = self.user_daily_usage.get(user_id, 0) + 1


rate_limiter = RateLimiter()

# 🕓 ACTIVITY TRACKER
class ActivityTracker:
    def __init__(self):
        self.last_activity: Dict[int, datetime] = {}

    def update_activity(self, user_id: int):
        self.last_activity[user_id] = datetime.now()

    def get_inactive_members(self, guild: discord.Guild, days_threshold: int = 3) -> List[discord.Member]:
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
    if member.guild.owner_id == member.id:
        return True
    for role in member.roles:
        if role.name.lower() in ["admin", "administrator", "owner", "moderator"]:
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
        if not self.webhook_url:
            return
        try:
            session = await self.get_session()
            async with session.post(self.webhook_url, json={"content": content}) as response:
                if response.status != 204:
                    logging.error(f"Webhook error: {response.status}")
        except Exception as e:
            logging.error(f"Webhook send error: {e}")

webhook_logger = WebhookLogger(WEBHOOK_URL)

# 🎓 JADWAL KULIAH SYSTEM 
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

# ✅ TASK REMINDER JADWAL OTOMATIS
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

# ✅ FRIDAY REMINDER 
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

# 🖼️ OCR HANDLER
async def handle_ocr_attachment(attachment, user_id: int):
    """Handle OCR processing dengan Gemini: unduh gambar, kirim sebagai bytes."""
    try:
        if attachment.size > 5_000_000:  # 5MB
            return "❌ File terlalu besar (max 5MB)."
        image_url = attachment.url
        headers = {
            "Authorization": f"Bot {DISCORD_TOKEN}" 
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(image_url, headers=headers, timeout=10) as resp:
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

@bot.event
async def on_ready():
    print(f'✅ {bot.user.name} berhasil login!')
    print(f'📊 Connected to {len(bot.guilds)} guilds')
    
    # Start semua tasks
    friday_reminder.start()
    daily_jadwal_reminder.start()  
    keep_alive()
    
    logging.info("Bot fully operational with jadwal system")

@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return

    activity_tracker.update_activity(message.author.id)

    # sensor kata kasar
    TOXIC_KEYWORDS = ["kontol", "memek", "bangsat", "ngentod"]
    if any(k in message.content.lower() for k in TOXIC_KEYWORDS):
        try:
            await message.delete()
            await message.channel.send(f"{message.author.mention}, jaga bahasanya ya 🙏")
        except:
            pass
        await bot.process_commands(message)
        return

    # 🎓 JADWAL KULIAH HANDLER
    if bot.user.mentioned_in(message) and not message.mention_everyone:
        user_prompt = message.content.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip().lower()
        
        # Cek jika user menanyakan jadwal kuliah
        jadwal_keywords = ['jadwal', 'kuliah', 'elearning', 'e-learning', 'tatap muka', 'uas', 'perkuliahan', 'minggu ini', 'hari ini']
        if any(keyword in user_prompt for keyword in jadwal_keywords):
            await message.channel.typing()
            current_jadwal = get_current_jadwal()
            
            if current_jadwal:
                response = f"📚 **JADWAL KULIAH TERDEKAT** 📚\n"
                response += f"Hai {message.author.mention}! Berikut jadwal kuliah untuk minggu ini:\n\n"
                
                for jadwal in current_jadwal:
                    response += f"```\n{jadwal['content']}\n```\n"
                
                response += "🎓 *Jangan lupa dipersiapkan!*"
                
                if len(response) > 2000:
                    parts = [response[i:i+2000] for i in range(0, len(response), 2000)]
                    for part in parts:
                        await message.channel.send(part)
                else:
                    await message.channel.send(response)
                    
                print(f"📚 [JADWAL] Sent jadwal to {message.author.name}")
                return 
            else:
                await message.channel.send(f"{message.author.mention} 📚 Tidak ada jadwal kuliah dalam 7 hari ke depan. Coba tanya lagi minggu depan!")
                return 
            
    # 🖼️ OCR HANDLER
    if message.attachments:
        for attachment in message.attachments:
            if any(attachment.filename.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".pdf"]):
                try:
                    await message.channel.typing()
                    ocr_result = await handle_ocr_attachment(attachment, message.author.id)
                    await message.channel.send(ocr_result)
                    
                    if "**Hasil OCR dari Gambar:**" in ocr_result and not ocr_result.startswith("❌"):
                        ai_prompt = f"Berikut adalah teks yang diekstrak dari gambar: {ocr_result}\n\nApa yang bisa kamu bantu dengan teks ini?"
                        try:
                            reply = await ai_bot_service.get_response(ai_prompt, message.author.id)
                            await message.channel.send(reply[:2000])
                        except Exception as e:
                            logging.error(f"AI processing error after OCR: {e}")
                            await message.channel.send("🤖 Berhasil membaca gambar, tapi AI sedang sibuk memproses permintaan lanjutan.")
                    
                except Exception as e:
                    logging.error(f"OCR attachment error: {e}")
                    await message.channel.send("❌ Gagal memproses gambar. Coba lagi nanti.")
                return

    # 🤖 Handle Mention Reguler
    if bot.user.mentioned_in(message) and not message.mention_everyone:
        user_prompt = message.content.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()
        if not user_prompt:
            await message.channel.send(f"Halo {message.author.mention}! Ketik pesan setelah mention saya 🤖")
            return

        user_is_admin = is_admin(message.author)
        can_request, err = await rate_limiter.can_use_ai(message.author.id, user_is_admin)
        if not can_request:
            await message.channel.send(err)
            return

        await message.channel.typing()
        try:
            # Record the request before processing
            await rate_limiter.record_ai_request(message.author.id)
            reply = await ai_bot_service.get_response(user_prompt, message.author.id)
            await message.channel.send(reply[:2000])
        except Exception as e:
            logging.exception(f"Error processing AI request: {e}")
            await message.channel.send(f"{message.author.mention} 🤖 Maaf, terjadi error.")
        return

    await bot.process_commands(message)

# START BOT
if __name__ == "__main__":
    try:
        bot.run(DISCORD_TOKEN)
    except Exception as e:
        print(f"❌ Failed to start bot: {e}")
        logging.critical(f"Bot startup failed: {e}")