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

# Veri saklama alanları ve imza
USER_COORDS = {}
NOTIFIED_FORTS = set()
IMZA = "\n\n(Beyaztaş&Gemini by)"


def fetch_storm_forts():
  params = {"page": 1, "size": 50, "orderDirection": "asc"}
  try:
    response = requests.get(STORM_URL, headers=HEADERS, params=params, timeout=10)
    response.raise_for_status()
    return response.json()
  except Exception as e:
    logger.error(f"Fırtına adaları çekilemedi: {e}")
    return None


def calculate_distance(x1, y1, x2, y2):
  return math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)


# /start komutu
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
  text = (
      "Selam kaptan! Fırtına Adaları Takip Botuna hoş geldin. 🏴‍☠️\n\n"
      "Öncelikle kale koordinatlarını doğrudan sohbete gönder (Örnek: `693:697`)\n"
      "Ardından çevrendeki adaları görmek için `/ada` yazabilirsin!" + IMZA
  )
  await update.message.reply_text(text, parse_mode="Markdown")


# Doğrudan koordinat kaydetme ve onay mesajı
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
        f"Çevrendeki fırtına adalarını listelemek için hemen `/ada` yazabilirsin."
        + IMZA
    )
    await update.message.reply_text(reply_text, parse_mode="Markdown")
  except ValueError:
    pass


# /ada komutu (Fırtına Adaları Seviye + Mesafe Listesi)
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
    dist = calculate_distance(my_x, my_y, fx, fy)
    attacks_left = fort.get("attacks_left", "Bilinmiyor")

    # Adanın seviyesini API'den çekiyoruz (Farklı anahtar ihtimallerine karşı kontrol)
    fort_level = (
        fort.get("level")
        or fort.get("fort_level")
        or fort.get("guard_level")
        or "?"
    )

    available_at_str = fort.get("available_at")

    status_text = "Saldırılabilir"
    if available_at_str:
      try:
        avail_time = datetime.fromisoformat(
            available_at_str.replace("Z", "+00:00")
        )
        diff_seconds = (avail_time - now).total_seconds()
        if diff_seconds > 0:
          mins = int(diff_seconds // 60)
          status_text = f"Yeniden Doğuyor ({mins} dk)"
      except:
        pass

    matched_forts.append({
        "x": fx,
        "y": fy,
        "dist": dist,
        "level": fort_level,
        "attacks": attacks_left,
        "status": status_text,
    })

  matched_forts.sort(key=lambda k: k["dist"])

  msg = (
      f"📍 **Kaleniz:** X:{my_x}, Y:{my_y}\n"
      f"📊 **En Yakın Fırtına Adaları:**\n"
      "-----------------------------------\n"
  )

  for f in matched_forts[:12]:
    msg += (
        f"🎯 **[{f['x']}, {f['y']}]** — 🛡️ *{f['level']} Seviye* — `{f['dist']:.1f} br`\n"
        f"⚔️ Hak: `{f['attacks']}/10` | Durum: {f['status']}\n\n"
    )

  msg += IMZA
  await update.message.reply_text(msg, parse_mode="Markdown")


# Arka planda 5 dakika kala bildirim atan döngü
async def check_spawn_timers(context: ContextTypes.DEFAULT_TYPE):
  data = fetch_storm_forts()
  if not data or "forts" not in data:
    return

  now = datetime.now(timezone.utc)

  for fort in data["forts"]:
    fx = fort.get("position_x")
    fy = fort.get("position_y")
    fort_key = f"{fx}_{fy}"
    available_at_str = fort.get("available_at")
    fort_level = (
        fort.get("level")
        or fort.get("fort_level")
        or fort.get("guard_level")
        or "?"
    )

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
                f"🚨 **DİKKAT! {fort_level} Seviye Fırtına Adası Açılıyor!** 🚨\n\n"
                f"📍 Konum: `[{fx}, {fy}]`\n"
                f"⏰ Kalan Süre: Yaklaşık **{int(mins_left)} dakika**!\n"
                f"Hazırlıklarını yap, ada spamlanmak üzere! ⚔️" + IMZA
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

  print("Bot sadeleştirilmiş fırtına adaları modunda aktif...")
  application.run_polling()


if __name__ == "__main__":
  main()
