from datetime import datetime, timezone
import logging
import math
import os
import requests
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# --------------------------------------------------------------------------
# AYARLAR
# --------------------------------------------------------------------------

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

API_BASE = "https://api.gge-tracker.com/api/v1"
STORM_URL = f"{API_BASE}/storms/forts"
SERVER_HEADER_NAME = "gge-server"
SERVER_VALUE = "TR1"

HEADERS = {
    SERVER_HEADER_NAME: SERVER_VALUE,
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    ),
}

USER_COORDS = {}
NOTIFIED_FORTS = set()
IMZA = "\n\n(Beyaztaş&Gemini by)"

# Sadece 70 ve 80 level adaların isle_id'leri
TARGET_ISLE_IDS = {8, 9, 13, 14}


def fetch_storm_forts():
  params = {"page": 1, "size": 500, "orderDirection": "asc"}
  try:
    response = requests.get(STORM_URL, headers=HEADERS, params=params, timeout=15)
    response.raise_for_status()
    return response.json()
  except Exception as e:
    logger.error(f"Fırtına adaları çekilemedi: {e}")
    return None


def calculate_distance(x1, y1, x2, y2):
  return math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
  text = (
      "Selam kaptan! 70-80 Level Fırtına Adaları Takip Botuna hoş geldin. 🏴‍☠️\n\n"
      "Öncelikle kale koordinatlarını sohbete gönder (Örnek: `693:697`)\n"
      "Ardından krallıktaki uygun adaları görmek için `/ada` yazabilirsin!"
      + IMZA
  )
  await update.message.reply_text(text, parse_mode="Markdown")


async def save_coordinates(update: Update, context: ContextTypes.DEFAULT_TYPE):
  user_id = update.effective_user.id
  text = update.message.text.strip()

  try:
    if ":" in text:
      parts = text.split(":")
      x, y = int(parts[0]), int(parts[1])
    elif "," in text:
      parts = text.split(",")
      x, y = int(parts[0]), int(parts[1])
    else:
      return

    USER_COORDS[user_id] = (x, y)
    reply_text = (
        f"✅ Kalen X:{x}, Y:{y} olarak kaydedildi!\n\n"
        f"Krallığı tarayıp uygun adaları listelemek için hemen `/ada` yazabilirsin."
        + IMZA
    )
    await update.message.reply_text(reply_text, parse_mode="Markdown")
  except ValueError:
    pass


async def list_islands(update: Update, context: ContextTypes.DEFAULT_TYPE):
  user_id = update.effective_user.id

  if user_id not in USER_COORDS:
    await update.message.reply_text(
        "⚠️ Önce kale koordinatlarını göndermelisin! Örnek: `693:697`" + IMZA,
        parse_mode="Markdown",
    )
    return

  my_x, my_y = USER_COORDS[user_id]
  data = fetch_storm_forts()

  if not data or "forts" not in data:
    await update.message.reply_text(
        "❌ Fırtına adası verileri alınamadı, birazdan tekrar dene." + IMZA
    )
    return

  forts_list = data["forts"]
  now = datetime.now(timezone.utc)
  matched_forts = []

  for fort in forts_list:
    fx = fort.get("position_x", 0)
    fy = fort.get("position_y", 0)
    isle_id = fort.get("isle_id")

    try:
      isle_id_int = int(isle_id) if isle_id is not None else 0
    except:
      isle_id_int = 0

    if isle_id_int not in TARGET_ISLE_IDS:
      continue

    dist = calculate_distance(my_x, my_y, fx, fy)
    attacks_left = fort.get("attacks_left", "Bilinmiyor")
    available_at_str = fort.get("available_at")

    status_text = "Saldırılabilir"
    skip_fort = False

    if available_at_str:
      try:
        avail_time = datetime.fromisoformat(
            available_at_str.replace("Z", "+00:00")
        )
        diff_seconds = (avail_time - now).total_seconds()
        if diff_seconds > 0:
          mins = int(diff_seconds // 60)
          # 10 dakikadan uzun sürecekleri tamamen listeden eliyoruz
          if mins > 10:
            skip_fort = True
          else:
            status_text = f"Yeniden Doğuyor ({mins} dk)"
      except:
        pass

    if skip_fort:
      continue

    matched_forts.append({
        "x": fx,
        "y": fy,
        "dist": dist,
        "level": "Level 70-80",
        "attacks": attacks_left,
        "status": status_text,
    })

  matched_forts.sort(key=lambda k: k["dist"])

  if not matched_forts:
    await update.message.reply_text(
        "⚠️ Krallıkta uygun (10 dk altı veya saldırılabilir) 70-80 level ada bulunamadı."
        + IMZA,
        parse_mode="Markdown",
    )
    return

  msg = (
      f"📍 **Kaleniz:** X:{my_x}, Y:{my_y}\n"
      f"🌍 **Krallıktaki Uygun 70-80 Level Fırtına Adaları:**\n"
      "-----------------------------------\n"
  )

  for f in matched_forts[:15]:
    msg += (
        f"🎯 **[{f['x']}, {f['y']}]** — 🛡️ *{f['level']}* — `{f['dist']:.1f} br`\n"
        f"⚔️ Hak: `{f['attacks']}/10` | Durum: {f['status']}\n\n"
    )

  msg += IMZA
  await update.message.reply_text(msg, parse_mode="Markdown")


async def check_spawn_timers(context: ContextTypes.DEFAULT_TYPE):
  data = fetch_storm_forts()
  if not data or "forts" not in data:
    return

  now = datetime.now(timezone.utc)

  for fort in data["forts"]:
    fx = fort.get("position_x")
    fy = fort.get("position_y")
    fort_key = f"{fx}_{fy}"
    isle_id = fort.get("isle_id")

    try:
      isle_id_int = int(isle_id) if isle_id is not None else 0
    except:
      isle_id_int = 0

    if isle_id_int not in TARGET_ISLE_IDS:
      continue

    available_at_str = fort.get("available_at")
    if not available_at_str:
      continue

    try:
      avail_time = datetime.fromisoformat(
          available_at_str.replace("Z", "+00:00")
      )
      diff_seconds = (avail_time - now).total_seconds()
      mins_left = diff_seconds / 60

      if 0 < mins_left <= 5 and fort_key not in NOTIFIED_FORTS:
        NOTIFIED_FORTS.add(fort_key)
        for user_id in USER_COORDS:
          try:
            alert_msg = (
                f"🚨 **DİKKAT! 70-80 Level Fırtına Adası Açılıyor!** 🚨\n\n"
                f"📍 Konum: `[{fx}, {fy}]`\n"
                f"⏰ Kalan Süre: Yaklaşık **{int(mins_left)} dakika**!\n"
                f"Krallıkta hedef hazır, kaçırma kaptan! ⚔️" + IMZA
            )
            await context.bot.send_message(
                chat_id=user_id, text=alert_msg, parse_mode="Markdown"
            )
          except:
            pass

      elif mins_left <= 0 and fort_key in NOTIFIED_FORTS:
        NOTIFIED_FORTS.remove(fort_key)
    except:
      pass


def main():
  TOKEN = "8835047696:AAHcZgGQczV4Qla20K3EkWmR3d4Axs4Pi4A"

  application = ApplicationBuilder().token(TOKEN).build()

  application.add_handler(CommandHandler("start", start))
  application.add_handler(CommandHandler("ada", list_islands))
  application.add_handler(
      MessageHandler(filters.TEXT & ~filters.COMMAND, save_coordinates)
  )

  if application.job_queue:
    job_queue = application.job_queue
    job_queue.run_repeating(check_spawn_timers, interval=60, first=10)

  print("Bot 70-80 level ve max 10 dk filtreli modda aktif...")
  application.run_polling()


if __name__ == "__main__":
  main()
