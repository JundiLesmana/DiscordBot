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

# VALIDASI TOKEN
if not DISCORD_TOKEN:
    logger.error("❌ DISCORD_TOKEN tidak ditemukan di environment variables")
    print("❌ DISCORD_TOKEN tidak ditemukan!")
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
        pattern = r'---+\n([E-Learning|Tatap Muka]+ \d{1,2}[a-zA-Z]* - .*?\d{4})\n(.*?)(?=---|$)'
        matches = re.findall(pattern, content, re.DOTALL)
        jadwal_list = []
        for match in matches:
            header, detail = match
            jadwal_list.append({"header": header.strip(), "content": detail.strip()})
        return jadwal_list
    except FileNotFoundError:
        logger.error("File JadwalKuliah.txt tidak ditemukan")
        return [{"header": "Error", "content": "File JadwalKuliah.txt tidak ditemukan"}]

def get_jadwal_for_date(target_date_str: str):
    """Mendapatkan jadwal berdasarkan tanggal tertentu (YYYY-MM-DD)"""
    jadwal_list = parse_jadwal_file()
    target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()

    for jadwal in jadwal_list:
        header = jadwal['header']
        dates_part = header.split(" - ")
        if len(dates_part) < 2:
            continue

        start_date_str = dates_part[0].split(" ", 1)[1]
        end_date_str = dates_part[1]
        year_match = re.search(r'(\d{4})', header)
        year = year_match.group(1) if year_match else None

        # Format tanggal awal
        try:
            start_full = start_date_str + (" " + year if year else "")
            start_date = datetime.strptime(start_full, "%d%B %Y").date()
        except ValueError:
            try:
                start_date = datetime.strptime(start_date_str, "%d%B").date().replace(year=int(year))
            except ValueError:
                continue

        # Format tanggal akhir
        if re.match(r'^[A-Za-z]+$', end_date_str.strip()):
            day_name = end_date_str.strip()
            day_map = {
                'Senin': 0, 'Selasa': 1, 'Rabu': 2, 'Kamis': 3, 'Jumat': 4,
                'Sabtu': 5, 'Minggu': 6
            }
            target_day = day_map.get(day_name.capitalize())
            if target_day is not None:
                days_diff = (target_day - start_date.weekday()) % 7
                if days_diff == 0:
                    days_diff = 7
                end_date = start_date + timedelta(days=days_diff)
            else:
                continue
        else:
            try:
                end_full = end_date_str + (" " + year if year else "")
                end_date = datetime.strptime(end_full, "%d%B %Y").date()
            except ValueError:
                try:
                    end_date = datetime.strptime(end_date_str, "%d%B").date().replace(year=int(year))
                except ValueError:
                    continue
        if start_date <= target_date <= end_date:
            return jadwal

    return None

def get_jadwal_tomorrow():
    """Mendapatkan jadwal yang dimulai besok"""
    tomorrow = datetime.now(WIB).date() + timedelta(days=1)
    tomorrow_str = tomorrow.strftime("%Y-%m-%d")
    return get_jadwal_for_date(tomorrow_str)

def get_current_jadwal():
    """Mendapatkan jadwal untuk hari ini"""
    today_str = datetime.now(WIB).date().strftime("%Y-%m-%d")
    return get_jadwal_for_date(today_str)

def get_jadwal_next_week():
    """Mendapatkan jadwal untuk minggu depan (7 hari dari sekarang)"""
    next_week = datetime.now(WIB).date() + timedelta(days=7)
    next_week_str = next_week.strftime("%Y-%m-%d")
    return get_jadwal_for_date(next_week_str)

def get_all_jadwal_next_week():
    """Mendapatkan semua jadwal untuk minggu depan (7 hari ke depan)"""
    jadwal_list = parse_jadwal_file()
    result_jadwal = []
    
    # Searching for each day in the next 7 days
    for i in range(7):
        target_date = datetime.now(WIB).date() + timedelta(days=i+1)
        target_date_str = target_date.strftime("%Y-%m-%d")
        
        jadwal = get_jadwal_for_date(target_date_str)
        if jadwal and jadwal not in result_jadwal:
            result_jadwal.append(jadwal)
    
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
            "Tolong ekstrak semua teks yang terlihat di gambar ini.", # Prompt default OCR
            user_id,
            image_bytes=image_bytes
        )
        await channel.send(f"📄 **Hasil OCR:**\n{ocr_result}")

    except Exception as e:
        logger.error(f"OCR error: {e}")
        await channel.send("❌ Gagal memproses gambar.")

# MESSAGE HANDLER
@bot.event
async def on_message(msg):
    if msg.author == bot.user:
        return

    activity_tracker.update_activity(msg.author.id)

    # Filter kata kasar
    toxic_words = ["kontol", "memek", "bangsat", "ngentod", "jembut", "anjing"]
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

        # Cek jadwal kuliah hari ini
        jadwal_keywords_today = ['jadwal', 'kuliah', 'elearning', 'e-learning', 'tatap muka', 'hari ini']
        if any(keyword in user_prompt for keyword in jadwal_keywords_today):
            await msg.channel.typing()
            current_jadwal = get_current_jadwal()

            if current_jadwal:
                response = f"📚 **JADWAL KULIAH HARI INI ({current_jadwal['header']})** 📚\nHai {msg.author.mention}!\n\n```{current_jadwal['content']}```"
                await msg.channel.send(response)
                return
            else:
                await msg.channel.send(f"{msg.author.mention} 📚 Tidak ada jadwal kuliah yang ditemukan untuk hari ini.")
                return

        # Cek jadwal kuliah minggu depan
        jadwal_keywords_next_week = ['minggu depan', 'next week', 'jadwal minggu depan']
        if any(keyword in user_prompt for keyword in jadwal_keywords_next_week):
            await msg.channel.typing()
            next_week_jadwal = get_all_jadwal_next_week()

            if next_week_jadwal:
                response = f"📚 **JADWAL KULIAH MINGGU DEPAN** 📚\nHai {msg.author.mention}!\n\n"
                for jadwal in next_week_jadwal:
                    response += f"**{jadwal['header']}**\n```{jadwal['content']}```\n\n"
                await msg.channel.send(response[:2000])  # Batasi panjang pesan
                return
            else:
                await msg.channel.send(f"{msg.author.mention} 📚 Tidak ada jadwal kuliah yang ditemukan untuk minggu depan.")
                return

        # Handler OCR
        if msg.attachments:
            for attachment in msg.attachments:
                if attachment.filename.lower().endswith((".png", ".jpg", ".jpeg", ".pdf")):
                    await handle_ocr_attachment(attachment, msg.author.id, msg.channel)
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
        reply = await ai_bot_service.get_response(prompt, msg.author.id, image_bytes=None) # ocr
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