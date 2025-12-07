import discord
from discord.ext import commands, tasks
import logging
import os
import time as py_time
import asyncio
from datetime import datetime, timedelta, time as dt_time, timezone 
from dotenv import load_dotenv
import aiohttp
from typing import Dict, List, Optional
import re
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import json

try:
    from ai_bot_service import ai_bot_service
except ImportError:
    class MockAIBotService:
        async def get_response(self, prompt, user_id, image_bytes=None):
            return f"AI Response untuk: {prompt}"
    ai_bot_service = MockAIBotService()

print("🚀 Starting Techfour Bot")

# HEALTH SERVER
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ['/', '/health', '/kaithhealthcheck', '/healthcheck']:
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'OK')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass

def run_health_server():
    """Jalankan health server di thread terpisah"""
    port = 8080
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    print(f"🌐 Health server running on port {port}")
    try:
        server.serve_forever()
    except Exception as e:
        print(f"❌ Health server error: {e}")

health_thread = threading.Thread(target=run_health_server, daemon=True)
health_thread.start()

py_time.sleep(5) 

# LOGGING
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

# ENVIRONMENT
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# Webhook Logger
class WebhookLogger:
    def __init__(self, webhook_url: Optional[str]):
        self.webhook_url = webhook_url
        self.session = None

    async def get_session(self):
        if self.session is None:
            self.session = aiohttp.ClientSession()
        return self.session

    async def send_log(self, content: str):
        if not self.webhook_url:
            logger.debug("WEBHOOK_URL tidak diatur — log dilewati")
            return
        try:
            session = await self.get_session()
            payload = {"content": content}
            async with session.post(self.webhook_url, json=payload) as resp:
                if resp.status not in (200, 204):
                    logger.error(f"❌ Webhook gagal: {resp.status} - {await resp.text()}")
        except Exception as e:
            logger.error(f"💥 Gagal kirim log ke Discord: {e}")

webhook_logger = WebhookLogger(WEBHOOK_URL)

# VALIDASI TOKEN
if not DISCORD_TOKEN:
    logger.error("❌ DISCORD_TOKEN tidak ditemukan di environment variables")
    print("❌ DISCORD_TOKEN tidak ditemukan!")
    # Tetap jalankan health server
    try:
        while True:
            py_time.sleep(60)
    except KeyboardInterrupt:
        exit(0)
else:
    # Cek format token
    if not DISCORD_TOKEN.startswith('MT') or len(DISCORD_TOKEN) < 50:
        logger.error(f"❌ Format DISCORD_TOKEN tidak valid: {DISCORD_TOKEN[:10]}...")
        print("❌ Format token tidak valid!")
        try:
            while True:
                py_time.sleep(60)
        except KeyboardInterrupt:
            exit(0)
    else:
        print(f"✅ Token ditemukan, panjang: {len(DISCORD_TOKEN)} karakter")

# BOT Hanling error
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.presences = True

class MyBot(commands.Bot):
    async def on_ready(self):
        print(f'🎉 {self.user} berhasil login dan ONLINE!')
        print(f'📊 Connected to {len(self.guilds)} guilds')

        # Set status bot
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name="!help | Mentions"
            )
        )

        # Start background tasks
        try:
            daily_jadwal_reminder.start()
            print("✅ Background tasks started")
        except Exception as e:
            print(f"⚠️ Error starting tasks: {e}")

        logger.info(f"Bot {self.user} fully operational")

    async def on_connect(self):
        print("🔗 Connected to Discord gateway")

    async def on_disconnect(self):
        print("🔌 Disconnected from Discord gateway")

    async def on_error(self, event, *args, **kwargs):
        print(f"❌ Error in event {event}: {args} {kwargs}")
        logger.error(f"Error in event {event}: {args} {kwargs}")

bot = MyBot(command_prefix="!", intents=intents)

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

        if user_id in self.user_cooldowns:
            diff = now - self.user_cooldowns[user_id]
            if diff < 60:
                return False, f"⏳ Tunggu {int(60-diff)} detik sebelum menggunakan AI lagi."

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

# JADWAL KULIAH
WIB = timezone(timedelta(hours=7))

def parse_jadwal_file():
    """Parse file JadwalKuliah.txt menjadi struktur data"""
    try:
        with open('JadwalKuliah.txt', 'r', encoding='utf-8') as file:
            content = file.read()
        
        print("📖 Membaca file JadwalKuliah.txt...")
        
        # Split by separators (---)
        sections = re.split(r'-{3,}\s*\n', content)
        jadwal_list = []
        
        for section in sections:
            section = section.strip()
            if not section:
                continue
                
            # Split header and content
            lines = section.split('\n', 1)
            if len(lines) < 2:
                continue
                
            header = lines[0].strip()
            content = lines[1].strip()
            
            jadwal_list.append({
                "header": header, 
                "content": content,
                "raw": f"{header}\n{content}"
            })
        
        print(f"✅ Ditemukan {len(jadwal_list)} jadwal")
        for jadwal in jadwal_list:
            print(f"   - {jadwal['header']}")
        
        return jadwal_list
    except FileNotFoundError:
        logger.error("File JadwalKuliah.txt tidak ditemukan")
        return [{"header": "Error", "content": "File JadwalKuliah.txt tidak ditemukan", "raw": "Error"}]
    except Exception as e:
        logger.error(f"Error parsing jadwal: {e}")
        return [{"header": "Error", "content": f"Error parsing: {e}", "raw": "Error"}]

def parse_date_from_header(header):
    """Parse tanggal dari header jadwal"""
    try:
        print(f"🔍 Parsing header: {header}")
        
        # Extract dates using regex
        date_pattern = r'(\d{1,2})\s+([A-Za-z]+)\s*-\s*(\d{1,2})\s+([A-Za-z]+)'
        match = re.search(date_pattern, header)
        
        if match:
            start_day = int(match.group(1))
            start_month_name = match.group(2).lower()
            end_day = int(match.group(3))
            end_month_name = match.group(4).lower()
            
            month_map = {
                'januari': 1, 'februari': 2, 'maret': 3, 'april': 4, 'mei': 5, 'juni': 6,
                'juli': 7, 'agustus': 8, 'september': 9, 'oktober': 10, 'november': 11, 'desember': 12,
                'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
                'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12
            }
            
            year_match = re.search(r'(\d{4})', header)
            year = int(year_match.group(1)) if year_match else 2025
            
            start_month = month_map.get(start_month_name, 11)
            end_month = month_map.get(end_month_name, 11)
            
            start_date = datetime(year, start_month, start_day).date()
            end_date = datetime(year, end_month, end_day).date()
            
            print(f"📅 Parsed: {start_date} to {end_date}")
            return start_date, end_date
        
        # Handle case where end date is a day of week (like "Sabtu")
        if " - " in header:
            parts = header.split(" - ", 1)
            start_part = parts[0]
            end_part = parts[1]
            
            # Parse start date
            start_date_match = re.search(r'(\d{1,2})\s+([A-Za-z]+)', start_part)
            if start_date_match:
                start_day = int(start_date_match.group(1))
                start_month_name = start_date_match.group(2).lower()
                
                year_match = re.search(r'(\d{4})', header)
                year = int(year_match.group(1)) if year_match else 2025
                
                start_month = month_map.get(start_month_name, 11)
                start_date = datetime(year, start_month, start_day).date()
                
                # If end part is a day name, calculate the date
                day_map = {'senin': 0, 'selasa': 1, 'rabu': 2, 'kamis': 3, 'jumat': 4, 'sabtu': 5, 'minggu': 6}
                end_day_name = end_part.lower().strip()
                
                if end_day_name in day_map:
                    target_day = day_map[end_day_name]
                    days_diff = (target_day - start_date.weekday()) % 7
                    if days_diff == 0:
                        days_diff = 7
                    end_date = start_date + timedelta(days=days_diff)
                    print(f"📅 Parsed with day name: {start_date} to {end_date}")
                    return start_date, end_date
        
        return None, None
    except Exception as e:
        print(f"❌ Error parsing date: {e}")
        return None, None

def get_jadwal_for_date(target_date):
    """Mendapatkan jadwal berdasarkan tanggal tertentu"""
    jadwal_list = parse_jadwal_file()
    
    print(f"🔍 Mencari jadwal untuk: {target_date}")
    
    for jadwal in jadwal_list:
        if jadwal['header'] == 'Error':
            continue
            
        start_date, end_date = parse_date_from_header(jadwal['header'])
        
        if start_date and end_date:
            print(f"   📋 Checking: {start_date} - {end_date}")
            if start_date <= target_date <= end_date:
                print(f"   ✅ DITEMUKAN: {jadwal['header']}")
                return jadwal
    
    print("   ❌ Tidak ditemukan jadwal")
    return None

def get_jadwal_tomorrow():
    """Mendapatkan jadwal yang dimulai besok"""
    tomorrow = datetime.now(WIB).date() + timedelta(days=1)
    return get_jadwal_for_date(tomorrow)

def get_current_jadwal():
    """Mendapatkan jadwal untuk hari ini"""
    today = datetime.now(WIB).date()
    return get_jadwal_for_date(today)

def get_jadwal_this_week():
    """Mendapatkan semua jadwal untuk minggu ini (hari ini + 6 hari ke depan)"""
    jadwal_list = parse_jadwal_file()
    result_jadwal = []
    
    print("🔍 Mencari jadwal minggu ini...")
    
    # Get today's date
    today = datetime.now(WIB).date()
    
    # Search for all jadwal that overlap with this week
    for jadwal in jadwal_list:
        if jadwal['header'] == 'Error':
            continue
            
        start_date, end_date = parse_date_from_header(jadwal['header'])
        
        if start_date and end_date:
            # Check if this jadwal overlaps with this week (today to today + 6 days)
            week_end = today + timedelta(days=6)
            if start_date <= week_end and end_date >= today:
                print(f"   ✅ Found overlapping jadwal: {jadwal['header']}")
                result_jadwal.append(jadwal)
    
    print(f"✅ Ditemukan {len(result_jadwal)} jadwal untuk minggu ini")
    return result_jadwal

def get_jadwal_next_week():
    """Mendapatkan semua jadwal untuk minggu depan (7-13 hari dari sekarang)"""
    jadwal_list = parse_jadwal_file()
    result_jadwal = []
    
    print("🔍 Mencari jadwal minggu depan...")
    
    # Get today's date
    today = datetime.now(WIB).date()
    
    # Define next week range
    next_week_start = today + timedelta(days=7)
    next_week_end = today + timedelta(days=13)
    
    # Search for all jadwal that overlap with next week
    for jadwal in jadwal_list:
        if jadwal['header'] == 'Error':
            continue
            
        start_date, end_date = parse_date_from_header(jadwal['header'])
        
        if start_date and end_date:
            # Check if this jadwal overlaps with next week
            if start_date <= next_week_end and end_date >= next_week_start:
                print(f"   ✅ Found overlapping jadwal: {jadwal['header']}")
                result_jadwal.append(jadwal)
    
    print(f"✅ Ditemukan {len(result_jadwal)} jadwal untuk minggu depan")
    return result_jadwal

# BACKGROUND TASKS
@tasks.loop(time=dt_time(hour=8, minute=0, tzinfo=WIB))
async def daily_jadwal_reminder():
    print("🔔 Daily jadwal reminder check")
    guild = bot.guilds[0] if bot.guilds else None
    if not guild:
        print("❌ Tidak ada guild untuk mengirim reminder.")
        return

    channel = guild.system_channel or guild.text_channels[0]

    today = datetime.now(WIB).date()
    day_of_week = today.weekday()

    target_days = [4, 6]

    if day_of_week not in target_days:
        print(f"✅ Bukan hari Jumat/Minggu ({today.strftime('%A')}). Skipping...")
        return  
    jadwal_tomorrow = get_jadwal_tomorrow()

    if jadwal_tomorrow:
        response = f"⏰ **Pengingat Jadwal Kuliah Besok ({jadwal_tomorrow['header']}):**\n\n```{jadwal_tomorrow['content']}```"
        try:
            await channel.send(response)
            print("✅ Pengingat jadwal dikirim.")
        except discord.Forbidden:
            print("❌ Bot tidak memiliki izin untuk mengirim pesan di channel ini.")
        except Exception as e:
            print(f"❌ Gagal mengirim pengingat: {e}")
    else:
        print("✅ Tidak ada jadwal untuk besok.")

# OCR HANDLER
async def handle_ocr_attachment(attachment, user_id: int, channel):
    try:
        if attachment.size > 5_000_000:
            await channel.send("❌ File terlalu besar (max 5MB).")
            return

        headers = {"Authorization": f"Bot {DISCORD_TOKEN}"}
        async with aiohttp.ClientSession() as session:
            async with session.get(attachment.url, headers=headers, timeout=10) as resp:
                if resp.status != 200:
                    await channel.send(f"❌ Gagal mengunduh gambar. Status: {resp.status}")
                    return
                image_bytes = await resp.read()

        await channel.typing()
        ocr_result = await ai_bot_service.get_response(
            "Tolong ekstrak semua teks yang terlihat di gambar ini.", # ocr
            user_id,
            image_bytes=image_bytes
        )
        await channel.send(f"📄 **Hasil OCR:**\n{ocr_result}")

    except Exception as e:
        logger.error(f"OCR error: {e}")
        await channel.send("❌ Gagal memproses gambar.")

# JADWAL COMMAND HANDLER
async def handle_jadwal_request(msg, user_prompt):
    """Handler khusus untuk request jadwal kuliah"""
    print(f"🎯 Handling jadwal request: {user_prompt}")
    
    jadwal_keywords_today = ['jadwal hari ini', 'kuliah hari ini', 'hari ini']
    if any(keyword in user_prompt for keyword in jadwal_keywords_today):
        await msg.channel.typing()
        current_jadwal = get_current_jadwal()

        if current_jadwal:
            response = f"📚 **JADWAL KULIAH HARI INI**\n**Periode:** {current_jadwal['header']}\nHai {msg.author.mention}!\n\n```{current_jadwal['content']}```"
            await msg.channel.send(response)
            return True
        else:
            await msg.channel.send(f"{msg.author.mention} 📚 Tidak ada jadwal kuliah yang ditemukan untuk hari ini.")
            return True

    jadwal_keywords_this_week = ['minggu ini', 'jadwal minggu ini', 'kuliah minggu ini', 'jadwal kuliah minggu ini']
    if any(keyword in user_prompt for keyword in jadwal_keywords_this_week):
        await msg.channel.typing()
        this_week_jadwal = get_jadwal_this_week()

        if this_week_jadwal:
            response = f"📚 **JADWAL KULIAH MINGGU INI** 📚\nHai {msg.author.mention}!\n\n"
            for jadwal in this_week_jadwal:
                response += f"**{jadwal['header']}**\n```{jadwal['content']}```\n\n"
            await msg.channel.send(response[:2000])
            return True
        else:
            await msg.channel.send(f"{msg.author.mention} 📚 Tidak ada jadwal kuliah yang ditemukan untuk minggu ini.")
            return True

    jadwal_keywords_next_week = ['minggu depan', 'next week', 'jadwal minggu depan', 'kuliah minggu depan']
    if any(keyword in user_prompt for keyword in jadwal_keywords_next_week):
        await msg.channel.typing()
        next_week_jadwal = get_jadwal_next_week()

        if next_week_jadwal:
            response = f"📚 **JADWAL KULIAH MINGGU DEPAN** 📚\nHai {msg.author.mention}!\n\n"
            for jadwal in next_week_jadwal:
                response += f"**{jadwal['header']}**\n```{jadwal['content']}```\n\n"
            await msg.channel.send(response[:2000])
            return True
        else:
            await msg.channel.send(f"{msg.author.mention} 📚 Tidak ada jadwal kuliah yang ditemukan untuk minggu depan.")
            return True

    jadwal_keywords_general = ['jadwal', 'kuliah', 'elearning', 'e-learning', 'tatap muka', 'uas']
    if any(keyword in user_prompt for keyword in jadwal_keywords_general):
        await msg.channel.typing()
        this_week_jadwal = get_jadwal_this_week()

        if this_week_jadwal:
            response = f"📚 **JADWAL KULIAH MINGGU INI** 📚\nHai {msg.author.mention}!\n\n"
            for jadwal in this_week_jadwal:
                response += f"**{jadwal['header']}**\n```{jadwal['content']}```\n\n"
            response += "💡 *Ketik '@Techfour jadwal hari ini' atau '@Techfour jadwal minggu depan' untuk periode tertentu*"
            await msg.channel.send(response[:2000])
            return True
        else:
            await msg.channel.send(f"{msg.author.mention} 📚 Tidak ada jadwal kuliah yang ditemukan. Coba tanyakan untuk periode tertentu seperti 'hari ini' atau 'minggu depan'.")
            return True

    return False

# MESSAGE HANDLER
@bot.event
async def on_message(msg):
    if msg.author == bot.user:
        return

    activity_tracker.update_activity(msg.author.id)

    # Filter kata kasar
    toxic_words = ["kontol", "memek", "bangsat", "ngentod", "jembut ", "anjing","brengsek","tai","tolol","babi","goblok","ngewe"]
    if any(word in msg.content.lower() for word in toxic_words):
        try:
            await msg.delete()
            await msg.channel.send(f"{msg.author.mention} jaga bahasanya ya 🙏")
        except Exception as e:
            logger.error(f"Error deleting message: {e}")
        return

    # Handler untuk mention bot
    if bot.user.mentioned_in(msg) and not msg.mention_everyone:
        user_prompt = msg.content.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip().lower()

        print(f"📩 Received message: {user_prompt}")

        # Handler OCR - priority
        if msg.attachments:
            for attachment in msg.attachments:
                if attachment.filename.lower().endswith((".png", ".jpg", ".jpeg", ".pdf")):
                    await handle_ocr_attachment(attachment, msg.author.id, msg.channel)
                    return

        jadwal_handled = await handle_jadwal_request(msg, user_prompt)
        if jadwal_handled:
            return  
        
        # Handler AI
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
        reply = await ai_bot_service.get_response(prompt, msg.author.id, image_bytes=None)
        await msg.channel.send(reply[:2000])
        return

    await bot.process_commands(msg)

#Run bot error handling
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("❌ Tidak ada DISCORD_TOKEN, hanya menjalankan health server")
        try:
            while True:
                py_time.sleep(60)
        except KeyboardInterrupt:
            print("Server dihentikan")
    else:
        print("🤖 Starting Discord bot dengan token yang valid...")
        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            try:
                bot.run(DISCORD_TOKEN)
            except discord.LoginFailure:
                print("❌ Gagal login: Token tidak valid!")
                break
            except discord.ConnectionClosed as e:
                print(f"❌ Koneksi terputus: {e}. Retry {retry_count + 1}/{max_retries}")
                retry_count += 1
                py_time.sleep(5)
            except Exception as e:
                print(f"❌ Error tidak terduga: {e}")
                logger.error(f"Unexpected error: {e}")
                break
            else:
                break

        if retry_count >= max_retries:
            print("❌ Gagal connect setelah beberapa percobaan")