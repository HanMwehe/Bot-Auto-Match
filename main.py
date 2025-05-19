import re
import logging
import aiohttp
from geopy.distance import geodesic
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

# ====== CONFIGURATION ======
BOT_TOKEN = '7986856741:AAEKV8gn5JueY_MAXZmXHAwkBmZ05E70uDs'
SHEETDB_API = 'https://sheetdb.io/api/v1/hccwdgspz6ql5'

# Lokasi teknisi tetap
LOKASI_KITA = (-7.465944, 112.441778)

# ====== LOGGING ======
logging.basicConfig(level=logging.INFO)

# ====== PARSING FUNCTION ======
def parse_tele_data(text: str):
    data = {}
    pattern_latlong = re.compile(r'LAT_LONG_PELANGGAN\s*:\s*([-\d.,\s]+)')
    match_latlong = pattern_latlong.search(text)

    if match_latlong:
        raw_latlong = match_latlong.group(1)
        cleaned = raw_latlong.strip().replace('\u200e', '').replace('\xa0', '').replace(' ', '')
        if ',' in cleaned:
            parts = cleaned.split(',')
        else:
            parts = re.split(r'\s*[\s;]+\s*', cleaned)
        if len(parts) >= 2:
            lat = parts[0]
            lon = parts[1]
            data['LAT_LONG_PELANGGAN'] = f"{lat},{lon}"
        else:
            data['LAT_LONG_PELANGGAN'] = cleaned

    fields = [
        ('SC', r'SC\s*:\s*(\S+)'),
        ('KONTAK_PELANGGAN_1', r'KONTAK_PELANGGAN_1\s*:\s*(\S+)'),
    ]
    for key, pattern in fields:
        match = re.search(pattern, text)
        if match:
            data[key] = match.group(1).replace(" ", "")

    data['IS_KENDALA'] = '/kendala' in text.lower()
    return data

# ====== JARAK FUNCTION ======
def get_distance(latlong1, latlong2):
    try:
        latlong1 = latlong1.strip().replace(" ", "")
        lat1, lon1 = map(float, latlong1.split(','))
        return geodesic((lat1, lon1), latlong2).meters
    except Exception as e:
        logging.error(f"Error menghitung jarak dari input '{latlong1}': {e}")
        return None

# ====== MAIN HANDLER ======
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if not text.lower().startswith('/psb') and '/kendala' not in text.lower():
        return

    parsed = parse_tele_data(text)
    logging.info(f"Parsed data: {parsed}")
    await update.message.reply_text(f"Parsed LAT_LONG_PELANGGAN: {parsed.get('LAT_LONG_PELANGGAN')}")

    if not parsed.get('SC'):
        await update.message.reply_text("⚠️ SC tidak ditemukan di teks.")
        return

    ao = parsed['SC']

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{SHEETDB_API}/search?AO={ao}") as res:
                res.raise_for_status()
                rows = await res.json()
        except Exception as e:
            logging.error(f"Error ambil data dari SheetDB: {e}")
            await update.message.reply_text("❌ Gagal mengambil data dari spreadsheet.")
            return

        if not rows:
            await update.message.reply_text(f"⚠️ AO (SC) {ao} tidak ditemukan di spreadsheet.")
            return

        row = rows[0]
        cp_bima = row.get('CP BIMA', '')
        cp_real = cp_bima
        tagging_real = parsed.get('LAT_LONG_PELANGGAN', '')

        if not tagging_real:
            await update.message.reply_text("⚠️ Data LAT_LONG_PELANGGAN tidak lengkap.")
            return

        distance = get_distance(tagging_real, LOKASI_KITA)
        if distance is None:
            await update.message.reply_text(f"❌ Gagal menghitung jarak dari '{tagging_real}'.")
            return

        verifikasi_tagging = "<100m" if distance < 100 else ">100m"
        status = "kendala" if parsed['IS_KENDALA'] else "PS"

        if parsed['IS_KENDALA']:
            await update.message.reply_text("🚨 Ini /kendala, pastikan data benar sebelum submit.")

        # === Data yang akan dikirimkan untuk update ===
        data_update = {
            "CP Real": cp_real,
            "Tagging Real": tagging_real,
            "Verifikasi Tagging": verifikasi_tagging,
            "STATUS": status
        }

        # === PATCH ke SheetDB ===
        try:
            patch_url = f"{SHEETDB_API}/AO/{ao}"
            async with session.patch(patch_url, json=data_update) as patch_res:
                patch_res.raise_for_status()
        except Exception as e:
            try:
                error_text = await patch_res.text()
            except:
                error_text = "<Tidak bisa baca response text>"
            logging.error(f"Error update data SheetDB: {e}")
            logging.error(f"Response content: {error_text}")
            await update.message.reply_text("❌ Gagal update data ke spreadsheet.")
            return

        await update.message.reply_text(
            f"✅ Data SC {ao} berhasil diupdate!\nStatus: {status}\nJarak: {distance:.2f} meter ({verifikasi_tagging})"
        )

# ====== BOT START ======
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT, handle_message))
    print("Bot jalan bre...")
    app.run_polling()
