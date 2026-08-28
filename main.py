import asyncio
import math
from datetime import datetime, timezone
import requests
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Kullanıcıların koordinatları ve bildirim giden adaların takibi
USER_COORDS = {}
NOTIFIED_FORTS = set()

BASE_URL = "https://api.gge-tracker.com/api/v1/storms/forts"


def fetch_storm_forts():
  params = {"page": 1, "size": 50, "orderDirection": "asc"}
  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
      ),
      "Accept": "application/json",
  }
  try:
    response = requests.get(BASE_URL, headers=headers, params=params, timeout=10)
    response.raise_for_status()
    return response.json()
  except:
    return None


def calculate_distance(x1, y1, x2, y2):
  return math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)


# /start komutu
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
  user_name = update.effective_user.first_name
  await update.message.reply_text(
      f"Selam {user_name}! Fırtına Adaları Takip Botuna hoş geldin.\n\n"
      "Öncelikle kale koordinatlarını şu formatta gönder (Örnek: `645:897`)",
      parse_mode="Markdown",
  )


# Koordinat kaydetme mesajı
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
    await update.message.reply_text(
        f"✅ Kalen X:{x}, Y:{y} olarak kaydedildi!\n\nArtık çevrendeki adaları"
        " listelemek için `/ada` yazabilirsin. Ayrıca son 5 dakika kala otomatik"
        " bildirim alacaksın!"
    )
  except ValueError:
    pass


# /ada komutu (Yakından uzağa liste)
async def list_islands(update: Update, context: ContextTypes.DEFAULT_TYPE):
  user_id = update.effective_user.id

  if user_id not in USER_COORDS:
    await update.message.reply_text(
        "⚠️ Önce kale koordinatlarını göndermelisin! Örnek: `645:897`",
        parse_mode="Markdown",
    )
    return

  my_x, my_y = USER_COORDS[user_id]
  data = fetch_storm_forts()

  if not data or "forts" not in data:
    await update.message.reply_text(
        "❌ Veriler alınamadı, birazdan tekrar dene."
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
        "attacks": attacks_left,
        "status": status_text,
    })

  matched_forts.sort(key=lambda k: k["dist"])

  msg = (
      f"📍 **Kaleniz:** X:{my_x}, Y:{my_y}\n"
      f"📊 **En Yakın Fırtına Adaları:**\n"
      "-----------------------------------\n"
  )

  for f in matched_forts[:15]:
    msg += (
        f"🎯 **[{f['x']}, {f['y']}]** — `{f['dist']:.1f} br`\n"
        f"⚔️ Hak: `{f['attacks']}/10` | Durum: {f['status']}\n\n"
    )

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
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    f"🚨 **DİKKAT! Fırtına Adası Açılıyor!** 🚨\n\n"
                    f"📍 Konum: `[{fx}, {fy}]`\n"
                    f"⏰ Kalan Süre: Yaklaşık **{int(mins_left)} dakika**!\n"
                    f"Hazırlıklarını yap, ada spamlanmak üzere! ⚔️"
                ),
                parse_mode="Markdown",
            )
          except:
            pass

      elif mins_left <= 0 and fort_key in NOTIFIED_FORTS:
        NOTIFIED_FORTS.remove(fort_key)
    except:
        pass


def main():
  # 🔥 BOTFATHER'DAN ALDIĞIN YENİ TOKEN'I BURAYA YAPIŞTIRacaksın:
  TOKEN = "8835047696:AAHcZgGQczV4Qla20K3EkWmR3d4Axs4Pi4A "

  application = ApplicationBuilder().token(TOKEN).build()

  application.add_handler(CommandHandler("start", start))
  application.add_handler(CommandHandler("ada", list_islands))
  application.add_handler(
      MessageHandler(filters.TEXT & ~filters.COMMAND, save_coordinates)
  )

  # Arka plan kontrolü (Her 60 saniyede bir tetiklenir)
  job_queue = application.job_queue
  job_queue.run_repeating(check_spawn_timers, interval=60, first=10)

  application.run_polling()


if __name__ == "__main__":
  main()
