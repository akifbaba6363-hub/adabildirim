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

# MİMLİ / DÜŞMAN İTTİFAKLAR LİSTESİ
MIMLI_ITTIFAKLAR = [
    "Grand Alliance",
    "ELITE",
    "DARK OF SOUL",
    "PAYİTAHT",
    "GÖKDOĞAN",
    "VICTORY",
    "SARSILMAZ",
    "WARRIOR",
    "ELITE 2",
]

GECMIS_ITTIFAK_SAYISI = 5

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


def temizle_isim(isim: str) -> str:
  if not isim:
    return ""
  isim = isim.replace("【", "").replace("】", "").replace("~", "")
  return " ".join(isim.split())


def tarihi_formatla(iso_tarih: str) -> str:
  try:
    dt = datetime.strptime(iso_tarih[:10], "%Y-%m-%d")
    return dt.strftime("%d.%m.%Y")
  except (ValueError, TypeError):
    return iso_tarih or "Bilinmiyor"


def mimli_mi(ittifak_adi: str) -> bool:
  temiz = temizle_isim(ittifak_adi).lower()
  for mimli in MIMLI_ITTIFAKLAR:
    mimli_temiz = temizle_isim(mimli).lower()
    if mimli_temiz in temiz or temiz in mimli_temiz:
      return True
  return False


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
      "Selam kaptan! Fırtına Adaları ve İstihbarat Botuna hoş geldin. 🏴‍☠️\n\n"
      "1️⃣ Önce kale koordinatlarını gönder (Örnek: `693:697`)\n"
      "2️⃣ Doğrudan oyuncu aramak için: `/oyuncu OyuncuAdi`" + IMZA
  )
  await update.message.reply_text(text, parse_mode="Markdown")


# Koordinat kaydetme ve yakın adaları listeleme tetikleyicisi
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
        f"Çevrendeki fırtına adalarını listelemek için `/ada` yazabilirsin."
        + IMZA
    )
    await update.message.reply_text(reply_text, parse_mode="Markdown")
  except ValueError:
    pass


# /ada komutu (Fırtına Adaları Yakından Uzağa)
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

  for f in matched_forts[:12]:
    msg += (
        f"🎯 **[{f['x']}, {f['y']}]** — `{f['dist']:.1f} br`\n"
        f"⚔️ Hak: `{f['attacks']}/10` | Durum: {f['status']}\n\n"
    )

  msg += IMZA
  await update.message.reply_text(msg, parse_mode="Markdown")


# İstihbarat Fonksiyonları (/oyuncu komutu için)
def _tek_deneme(player_name: str):
  url = f"{API_BASE}/players/{requests.utils.quote(player_name)}"
  try:
    res = requests.get(url, headers=HEADERS, timeout=15)
  except requests.exceptions.RequestException as e:
    logger.error(f"Bağlantı Hatası: {e}")
    return "baglanti_hatasi", None

  if res.status_code == 200:
    try:
      return "basarili", res.json()
    except ValueError:
      return "gecersiz_json", None
  if res.status_code == 404:
    return "bulunamadi", None
  return "diger_hata", res.status_code


def oyuncuyu_bul(player_name: str):
  player_name = player_name.strip()
  denenecek_isimler = list(
      dict.fromkeys([
          player_name,
          player_name.lower(),
          player_name.upper(),
          player_name.capitalize(),
          player_name.title(),
      ])
  )

  for isim in denenecek_isimler:
    durum, sonuc = _tek_deneme(isim)
    if durum == "basarili":
      return "basarili", sonuc
    if durum == "baglanti_hatasi":
      return "Veri çekilirken bağlantı hatası oluştu.", None
    if durum == "gecersiz_format":
      return "Oyuncu adı geçersiz formatta.", None

  return (
      f"'{player_name}' TR1 sunucusunda bulunamadı. Yazılışını kontrol et reis.",
      None,
  )


def ittifak_gecmisini_getir(player_id: str):
  url = f"{API_BASE}/updates/players/{player_id}/alliances"
  try:
    res = requests.get(url, headers=HEADERS, timeout=15)
    if res.status_code != 200:
      return []
    data = res.json()
  except:
    return []

  updates = data.get("updates", [])
  sonuc = []
  gorulen_isimler = set()

  for kayit in updates:
    yeni_isim = kayit.get("original_new_alliance_name") or kayit.get(
        "new_alliance_name"
    )
    if not yeni_isim:
      continue
    temiz_isim = temizle_isim(yeni_isim)
    if not temiz_isim or temiz_isim in gorulen_isimler:
      continue
    gorulen_isimler.add(temiz_isim)
    sonuc.append({
        "isim": temiz_isim,
        "tarih": tarihi_formatla(kayit.get("date", "")),
    })
    if len(sonuc) >= GECMIS_ITTIFAK_SAYISI:
      break
  return sonuc


def get_player_by_name(player_name: str):
  durum, data = oyuncuyu_bul(player_name)
  if durum != "basarili":
    return durum

  player_id = data.get("player_id")
  level_value = data.get("level", "Bilinmiyor")
  might_value = data.get("might_current", "Bilinmiyor")
  guncel_ittifak = temizle_isim(data.get("alliance_name") or "") or "İttifaksız"

  gecmis = ittifak_gecmisini_getir(player_id) if player_id else []
  if not gecmis:
    gecmis = (
        [{"isim": guncel_ittifak, "tarih": "Bilinmiyor"}]
        if guncel_ittifak != "İttifaksız"
        else []
    )

  mimli_kayitlar = [kayit for kayit in gecmis if mimli_mi(kayit["isim"])]
  profile_link = f"https://gge-tracker.com/players?player={requests.utils.quote(player_name)}&server=TR1"

  return {
      "name": data.get("player_name") or player_name,
      "level": level_value,
      "might": (
          f"{might_value:,}".replace(",", ".")
          if isinstance(might_value, (int, float))
          else might_value
      ),
      "guncel_ittifak": guncel_ittifak,
      "gecmis": gecmis,
      "mimli_kayitlar": mimli_kayitlar,
      "profile_url": profile_link,
  }


# /oyuncu komutu
async def oyuncu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
  if not context.args:
    await update.message.reply_text(
        "Lütfen bir oyuncu adı girin!\nÖrnek: `/oyuncu SirlusBlaCK`" + IMZA,
        parse_mode="Markdown",
    )
    return

  player_name = " ".join(context.args)
  await update.message.reply_text(
      f"🔍 TR1 havuzunda '{player_name}' aranıyor..."
  )

  result = get_player_by_name(player_name)

  if isinstance(result, str):
    await update.message.reply_text(result + IMZA)
    return

  gecmis_text = (
      "\n".join([f"• {k['isim']} — {k['tarih']}" for k in result["gecmis"]])
      or "Kayıt bulunamadı."
  )

  if result["mimli_kayitlar"]:
    satirlar = [
        f"    ⚠️ {k['isim']} — {k['tarih']} tarihinde bu ittifaktaydı"
        for k in result["mimli_kayitlar"]
    ]
    dusman_text = (
        "🚨 **DİKKAT! MİMLİ DÜŞMAN GEÇMİŞİ TESPİT EDİLDİ!**\n"
        + "\n".join(satirlar)
    )
  else:
    dusman_text = "✅ Son kayıtlarında mimli düşman ittifak bulunamadı."

  message = (
      f"🏰 *TR1 İstihbarat Raporu:* `{result['name']}`\n\n"
      f"⭐ *Seviye:* {result['level']}\n"
      f"⚡ *Güç:* {result['might']}\n"
      f"🛡️ *Güncel İttifak:* {result['guncel_ittifak']}\n\n"
      f"📜 *Son {GECMIS_ITTIFAK_SAYISI} İttifak Geçmişi:*\n{gecmis_text}\n\n"
      f"{dusman_text}\n\n"
      f"🔗 *Detaylı Profil:* {result['profile_url']}" + IMZA
  )
  await update.message.reply_text(
      message, parse_mode="Markdown", disable_web_page_preview=True
  )


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
            alert_msg = (
                f"🚨 **DİKKAT! Fırtına Adası Açılıyor!** 🚨\n\n"
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
  application.add_handler(CommandHandler("oyuncu", oyuncu_command))
  application.add_handler(
      MessageHandler(filters.TEXT & ~filters.COMMAND, save_coordinates)
  )

  if application.job_queue:
    job_queue = application.job_queue
    job_queue.run_repeating(check_spawn_timers, interval=60, first=10)

  print("Bot tam sürüm (İstihbarat + Fırtına Adaları) modunda aktif...")
  application.run_polling()


if __name__ == "__main__":
  main()
