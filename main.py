import discord
from discord.ext import commands
import logging
import os
import requests
from dotenv import load_dotenv

# ============================================
# 🔧 Bersihkan log lama & siapkan logging baru
# ============================================
if os.path.exists("discord.log"):
    os.remove("discord.log")

logging.basicConfig(
    filename="discord.log",
    filemode="w",
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.info("=== Bot dimulai fresh ===")

# ============================================
# 🔑 Load token & API key dari .env
# ============================================
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

if not DISCORD_TOKEN or not OPENROUTER_API_KEY:
    raise ValueError("❌ Pastikan DISCORD_TOKEN dan OPENROUTER_API_KEY sudah diisi di file .env")

# ============================================
# ⚙️ Discord bot setup
# ============================================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ============================================
# 🚀 Event: Bot siap
# ============================================
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user.name} (ID: {bot.user.id})")
    logging.info(f"Bot siap dengan PID: {os.getpid()}")

# ============================================
# 🧹 Daftar kata yang dilarang
# ============================================
CARIAMAN_KEYWORDS = ["prabowo", "jokowi", "megawati", "sukarno", "luhut", "puan"]
TOXIC_KEYWORDS = ["kontol", "memek", "titit", "mmk", "jembut", "bangsat", "ngentod", "peler"]

# ============================================
# 💬 Event: Pesan masuk
# ============================================
@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    content_lower = message.content.lower()
    if any(word in content_lower for word in CARIAMAN_KEYWORDS + TOXIC_KEYWORDS):
        try:
            await message.delete()
            await message.channel.send(f"{message.author.mention}, jaga obrolannya ya 🙏")
        except discord.Forbidden:
            pass
        return

    # 🤖 Jika bot di-mention (dan bukan mention everyone)
    if bot.user.mentioned_in(message) and not message.mention_everyone:
        user_prompt = message.content.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()
        if not user_prompt:
            await message.channel.send(
                f"Halo {message.author.mention}! Ketik pesan setelah mention saya untuk bicara 🤖"
            )
            return

        await message.channel.typing()
        try:
            response = requests.post(
                url="https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/JundiLesmana/DiscordBot",
                    "X-Title": "ARC-0104 Discord Bot"
                },
                json={
                    "model": "openrouter/auto",  # typo diperbaiki
                    "messages": [
                        {"role": "system", "content": "Kamu adalah ARC-0104, AI asisten ramah di Discord server Teknik Informatika 01TPLE004."},
                        {"role": "user", "content": user_prompt}
                    ],
                    "max_tokens": 200,
                    "temperature": 0.7
                },
                timeout=30
            )

            if response.status_code != 200:
                error_detail = response.json().get("error", {}).get("message", "Unknown error")
                await message.channel.send(f"⚠️ OpenRouter error ({response.status_code}): {error_detail}")
                logging.error(f"OpenRouter error: {response.status_code} - {error_detail}")
                return

            data = response.json()
            reply = data["choices"][0]["message"]["content"].strip()

            if not reply:
                reply = "Maaf, saya tidak bisa memberikan jawaban saat ini."

            await message.channel.send(reply)

        except requests.exceptions.Timeout:
            await message.channel.send("⏳ Request ke OpenRouter timeout. Coba lagi nanti.")
        except requests.exceptions.RequestException as e:
            await message.channel.send(f"⚠️ Error koneksi ke OpenRouter: {e}")
            logging.error(f"Request error: {e}")
        except Exception as e:
            await message.channel.send(f"⚠️ Error tak terduga: {e}")
            logging.exception("Unexpected error in on_message")

        return

    await bot.process_commands(message)

# ============================================
# 📡 Command: Ping
# ============================================
@bot.command()
async def ping(ctx):
    await ctx.send(f"Pong! {ctx.author.mention}")

# ============================================
# 🧩 Command: Assign Role
# ============================================
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

# ============================================
# 🚀 Jalankan bot
# ============================================
if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)