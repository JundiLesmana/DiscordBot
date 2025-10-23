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
from ai_bot_service import ai_bot_service
import google.generativeai as genai

print("✅ [DEBUG] Google Generative AI Version:", genai.__version__)
# 🚀 WEB SERVER FOR RENDER
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
OCR_API_KEY = os.getenv("OCR_API_KEY")
WOLFRAM_APP_ID = os.getenv("WOLFRAM_APP_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
HF_TOKEN = os.getenv("HF_TOKEN")

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
        self.active_ai_requests: int = 0
        self.ai_request_lock = asyncio.Lock()

    def reset_daily_limits(self):
        self.user_daily_usage.clear()
        self.last_reset_time = py_time.time()
        logging.info("Daily limits reset")

    def get_daily_limit(self, is_admin: bool) -> int:
        return 50 if is_admin else 30

    async def can_use_ai(self, user_id: int, is_admin: bool) -> tuple[bool, Optional[str]]:
        current_time = py_time.time()
        daily_limit = self.get_daily_limit(is_admin)
        async with self.ai_request_lock:
            if self.active_ai_requests >= 2:
                return False, "⏳ Sedang ada 2 orang menggunakan AI. Tunggu 5 detik ya!"
            if user_id in self.user_cooldowns:
                time_since_last = current_time - self.user_cooldowns[user_id]
                if time_since_last < 15:
                    return False, f"⏳ Tunggu {int(15 - time_since_last)} detik lagi sebelum menggunakan AI."
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

# ✅ FRIDAY REMINDER
WIB = timezone(timedelta(hours=7))

@tasks.loop(time=time(hour=11, minute=0))
async def friday_reminder():
    now_utc = datetime.now(timezone.utc)
    now_wib = now_utc.astimezone(WIB)
    if now_wib.weekday() == 4:
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

# 🎯 EVENT HANDLERS
@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return

    activity_tracker.update_activity(message.author.id)

    # 🔕 Censor kata kasar
    TOXIC_KEYWORDS = ["kontol", "memek", "bangsat", "ngentod"]
    if any(k in message.content.lower() for k in TOXIC_KEYWORDS):
        try:
            await message.delete()
            await message.channel.send(f"{message.author.mention}, jaga bahasanya ya 🙏")
        except:
            pass
        return

# 🖼️ EVENT HANDLER: on_message
@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return

    activity_tracker.update_activity(message.author.id)

    # 🔕 Censor kata kasar
    TOXIC_KEYWORDS = ["kontol", "memek", "bangsat", "ngentod"]
    if any(k in message.content.lower() for k in TOXIC_KEYWORDS):
        try:
            await message.delete()
            await message.channel.send(f"{message.author.mention}, jaga bahasanya ya 🙏")
        except:
            pass
        return

    # 🖼️ OCR HANDLER
    if message.attachments:
        attachment = message.attachments[0]
        if any(attachment.filename.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".pdf"]):
            import requests
            try:
                # Pastikan OCR_API_KEY tersedia
                if not OCR_API_KEY:
                    await message.channel.send("❌ OCR tidak tersedia: API key belum dikonfigurasi.")
                    return

                # Perbaiki URL: HAPUS SPASI DI AKHIR!
                ocr_url = "https://api.ocr.space/parse/image"

                # Kirim permintaan ke OCR.Space
                response = requests.post(
                    ocr_url,
                    data={"apikey": OCR_API_KEY, "OCREngine": 2, "language": "eng"},
                    files={"file": await attachment.read()},
                    timeout=15  
                )

                # Cek status HTTP
                if response.status_code != 200:
                    await message.channel.send(f"❌ OCR gagal: status {response.status_code}")
                    return

                result = response.json()

                # Cek apakah ada error dari OCR.Space
                if not result.get("IsSuccessful", False):
                    error_msg = result.get("ErrorMessage", ["Tidak diketahui"])[0]
                    await message.channel.send(f"❌ OCR error: {error_msg}")
                    return

                # Check parsed results
                parsed_results = result.get("ParsedResults", [])
                if not parsed_results:
                    await message.channel.send("❌ Tidak ada teks yang ditemukan di gambar.")
                    return

                parsed_text = parsed_results[0].get("ParsedText", "").strip()
                if not parsed_text:
                    await message.channel.send("❌ Teks terdeteksi, tetapi kosong.")
                    return

                # send result OCR
                await message.channel.send("📄 **Hasil OCR:**\n" + parsed_text[:1500])

                # send AI
                reply = await ai_bot_service.get_response(parsed_text, message.author.id)
                await message.channel.send(reply[:2000])

            except requests.exceptions.Timeout:
                await message.channel.send("❌ OCR timeout: gambar terlalu besar atau server lambat.")
            except requests.exceptions.RequestException as e:
                await message.channel.send(f"❌ Gagal menghubungi layanan OCR: {e}")
            except KeyError as e:
                await message.channel.send(f"❌ Struktur respons OCR tidak sesuai: key {e} tidak ditemukan.")
            except Exception as e:
                import logging
                logging.exception("OCR error detail:")
                await message.channel.send(f"❌ Gagal membaca gambar: {e}")
            return

    # 🤖 Handle Mention
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
            await rate_limiter.start_ai_request(message.author.id)
            reply = await ai_bot_service.get_response(user_prompt, message.author.id)
            await message.channel.send(reply[:2000])
        except Exception as e:
            logging.exception(f"Error processing AI request: {e}")
            await message.channel.send(f"{message.author.mention} 🤖 Maaf, terjadi error.")
        finally:
            await rate_limiter.end_ai_request()

    await bot.process_commands(message)


# 🚀 BOT STARTUP — HANYA SATU on_ready
@bot.event
async def on_ready():
    # Debug: cek versi Google Generative AI
    import google.generativeai as genai
    print("✅ [DEBUG] Google Generative AI Version:", genai.__version__)

    keep_alive()
    print(f"✅ {bot.user} online di {len(bot.guilds)} server!")
    reset_daily_task.start()
    clean_cache_task.start()
    check_inactive_members.start()
    friday_reminder.start()
    await bot.change_presence(activity=discord.Game(name="!ping | @Techfour"))