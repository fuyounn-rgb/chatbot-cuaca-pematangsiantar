
from flask import Flask, render_template, request, jsonify
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import re

app = Flask(__name__)
WIB = ZoneInfo("Asia/Jakarta")

KECAMATAN_DATA = {
    "siantar barat": {"adm4": "12.72.01.1001", "lat": 2.9564, "lon": 99.0558},
    "siantar timur": {"adm4": "12.72.02.1001", "lat": 2.9612, "lon": 99.0811},
    "siantar utara": {"adm4": "12.72.03.1001", "lat": 2.9781, "lon": 99.0701},
    "siantar selatan": {"adm4": "12.72.04.1001", "lat": 2.9421, "lon": 99.0610},
    "siantar marihat": {"adm4": "12.72.05.1001", "lat": 2.9231, "lon": 99.0734},
    "siantar martoba": {"adm4": "12.72.06.1001", "lat": 2.9841, "lon": 99.0621},
    "siantar sitalasari": {"adm4": "12.72.07.1001", "lat": 2.9511, "lon": 99.0289},
    "siantar marimbun": {"adm4": "12.72.08.1001", "lat": 2.9051, "lon": 99.0512}
}

WEATHER_CODES_HISTORIC = {
    0: "Cerah", 1: "Cerah Berawan", 2: "Berawan",
    3: "Berawan Tebal", 51: "Gerimis",
    61: "Hujan Ringan", 63: "Hujan Sedang",
    65: "Hujan Lebat", 95: "Hujan Petir"
}


def parse_hour(text):
    text = text.lower()
    match = re.search(r'(\d{1,2})[:.](\d{2})', text)

    if match:
        return int(match.group(1))

    match = re.search(r'jam\s+(\d{1,2})', text)

    if match:
        hour = int(match.group(1))

        if ("malam" in text or "siang" in text or "sore" in text) and hour < 12:
            hour += 12
        elif "pagi" in text and hour == 12:
            hour = 0

        return hour

    return None


def get_today_bmkg_json(adm4_code, target_hour):
    url = f"https://api.bmkg.go.id/publik/prakiraan-cuaca?adm4={adm4_code}"

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json"
    }

    try:
        res = requests.get(url, headers=headers, timeout=15)
        res.raise_for_status()
        data = res.json()

        cuaca_list = []

        if isinstance(data, list) and data:
            lokasi = data[0]
            raw_cuaca = lokasi.get("cuaca", []) if isinstance(lokasi, dict) else []

            if raw_cuaca and isinstance(raw_cuaca[0], list):
                cuaca_list = raw_cuaca[0]
            else:
                cuaca_list = raw_cuaca

        elif isinstance(data, dict):
            data_field = data.get("data", [])

            if data_field and isinstance(data_field[0], dict):
                raw_cuaca = data_field[0].get("cuaca", [])

                if raw_cuaca and isinstance(raw_cuaca[0], list):
                    cuaca_list = raw_cuaca[0]
                else:
                    cuaca_list = raw_cuaca

        if not cuaca_list:
            return "Data cuaca tidak ditemukan dalam respon BMKG."

        best_item = cuaca_list[0]
        min_diff = 24

        for item in cuaca_list:
            if not isinstance(item, dict):
                continue

            time_str = item.get("local_datetime", "")

            if time_str:
                dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                diff = abs(dt.hour - target_hour)

                if diff < min_diff:
                    min_diff = diff
                    best_item = item

        if not isinstance(best_item, dict):
            return "Format data prakiraan BMKG tidak sesuai."

        return (
            f"Sumber: API Publik BMKG\n"
            f"Waktu Perkiraan: {best_item.get('local_datetime', '-')}\n"
            f"Kondisi: {best_item.get('weather_desc', 'Tidak Diketahui')}\n"
            f"Suhu: {best_item.get('t', '-')}°C\n"
            f"Kelembapan: {best_item.get('hu', '-')}%"
        )

    except Exception as e:
        return f"Error BMKG API: {e}"


def get_history_open_meteo_hourly(lat, lon, date_str, target_hour):
    url = (
        "https://archive-api.open-meteo.com/v1/archive?"
        f"latitude={lat}&longitude={lon}"
        f"&start_date={date_str}&end_date={date_str}"
        "&hourly=temperature_2m,relative_humidity_2m,weather_code"
        "&timezone=Asia%2FJakarta"
    )

    try:
        res = requests.get(url, timeout=15)
        res.raise_for_status()

        hourly = res.json().get("hourly", {})
        times = hourly.get("time", [])

        if not times:
            return "Data cuaca historis tidak ditemukan."

        target_idx = -1

        for idx, time_str in enumerate(times):
            if time_str.endswith(f"T{target_hour:02d}:00"):
                target_idx = idx
                break

        if target_idx == -1:
            target_idx = min(target_hour, len(times) - 1)

        code = hourly["weather_code"][target_idx]
        temp = hourly["temperature_2m"][target_idx]
        humidity = hourly["relative_humidity_2m"][target_idx]

        condition = WEATHER_CODES_HISTORIC.get(code, "Berawan")

        return (
            "Sumber: Open-Meteo (Arsip Historis)\n"
            f"Kondisi: {condition}\n"
            f"Suhu: {temp}°C\n"
            f"Kelembapan: {humidity}%"
        )

    except Exception as e:
        return f"Error Historis: {e}"


def process_query(user_input):
    text = user_input.lower().strip()

    matched_kec = None

    for kec in KECAMATAN_DATA:
        if kec in text or kec.replace("siantar ", "") in text:
            matched_kec = kec
            break

    if not matched_kec:
        return (
            "Mohon sebutkan nama kecamatan di Pematangsiantar. "
            "Contoh: Siantar Barat, Marihat, atau Martoba."
        )

    today = datetime.now(WIB)
    target_hour = parse_hour(text)

    if target_hour is None:
        target_hour = today.hour

    if "kemarin" in text or "semalam" in text:
        target_date = (today - timedelta(days=1)).strftime("%Y-%m-%d")
        is_today = False

    elif "hari ini" in text or "sekarang" in text:
        target_date = today.strftime("%Y-%m-%d")
        is_today = True

    else:
        target_date = None

        for word in text.split():
            try:
                dt = datetime.strptime(word, "%Y-%m-%d")
                target_date = word
                is_today = dt.date() == today.date()
                break
            except ValueError:
                continue

        if not target_date:
            target_date = today.strftime("%Y-%m-%d")
            is_today = True

    kec_info = KECAMATAN_DATA[matched_kec]

    if is_today:
        details = get_today_bmkg_json(
            kec_info["adm4"], target_hour
        )
    else:
        details = get_history_open_meteo_hourly(
            kec_info["lat"],
            kec_info["lon"],
            target_date,
            target_hour
        )

    return (
        f"--- Info Cuaca {matched_kec.title()} "
        f"({target_date} Jam {target_hour:02d}:00 WIB) ---\n"
        f"{details}"
    )


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    message = data.get("message", "").strip()

    if not message:
        return jsonify({"reply": "Silakan tulis pertanyaan terlebih dahulu."}), 400

    reply = process_query(message)

    return jsonify({"reply": reply})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
