import requests
from bs4 import BeautifulSoup
import json
import os
import time
import pandas as pd
import re
from datetime import datetime

# Opcjonalne geokodowanie odległości
try:
    from geopy.geocoders import Nominatim
    from geopy.distance import geodesic
    geopy_available = True
    geolocator = Nominatim(user_agent="otomoto_bot")
    LODZ_COORDS = (51.759248, 19.456999)
    location_cache = {}
except ImportError:
    geopy_available = False

# Stałe
URL = (
    "https://www.otomoto.pl/osobowe/volvo/v60--v60-cross-country--"
    "v90--v90-cross-country/od-2020?search%5Bfilter_enum_damaged%5D=0&"
    "search%5Bfilter_enum_fuel_type%5D=diesel&"
    "search%5Bfilter_float_engine_power%3Afrom%5D=190&"
    "search%5Bfilter_float_mileage%3Ato%5D=140000&"
    "search%5Bfilter_float_price%3Ato%5D=140000&search%5Border%5D=relevance_web&"
    "search%5Badvanced_search_expanded%5D=true"
)
HEADERS = {"User-Agent": "Mozilla/5.0"}
HISTORY_FILE = "sent_links.json"
PRICE_HISTORY_FILE = "price_history.json"
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Parsowanie tekstu pomocnicze
def extract_text(soup, selector: str) -> str:
    tag = soup.select_one(selector)
    return tag.get_text(strip=True) if tag else "❓ brak"

# Poprawione parsowanie mocy i pojemności
def parse_power_and_capacity(text: str) -> tuple[str, str]:
    km = "❓ brak"
    cm3 = "❓ brak"
    cm3_match = re.search(r"(\d{2,5})\s?cm(?:3|³)", text)
    if cm3_match:
        cm3 = f"{cm3_match.group(1)} cm3"
    km_match = re.search(r"(\d{2,4})\s?KM", text)
    if km_match:
        km = f"{km_match.group(1)} KM"
    return km, cm3

# Parsowanie ceny na int
def parse_price(text: str) -> int:
    digits = ''.join(filter(str.isdigit, text))
    return int(digits) if digits else 0

# Formatowanie dystansu
def format_distance(loc_str: str) -> str:
    if not geopy_available or not loc_str:
        return "❓ odległość"
    if loc_str in location_cache:
        coords = location_cache[loc_str]
    else:
        try:
            loc = geolocator.geocode(f"{loc_str}, Poland", timeout=10)
            coords = (loc.latitude, loc.longitude) if loc else None
        except:
            coords = None
        location_cache[loc_str] = coords
    if not coords:
        return "❓ odległość"
    dist_km = int(geodesic(LODZ_COORDS, coords).km)
    emoji = "🟢" if dist_km <= 100 else ("🟡" if dist_km <= 300 else "🔴")
    return f"{emoji} {dist_km} km"

# Pobieranie ofert
def fetch_offers() -> list[dict]:
    results, page, max_pages = [], 1, None
    while True:
        url = f"{URL}&page={page}" if page > 1 else URL
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        if page == 1:
            nums = [int(li.get_text(strip=True)) for li in soup.select("li.ooa-6ysn8b") if li.get_text(strip=True).isdigit()]
            max_pages = max(nums) if nums else 1
        articles = soup.find_all("article")
        if not articles:
            break
        for art in articles:
            a = art.select_one("h2 a[href]")
            if not a:
                continue
            title = a.get_text(strip=True)
            link = a["href"]
            spec = extract_text(art, 'p[class*=w3crlp]')
            km, cm3 = parse_power_and_capacity(spec)
            data = {
                "Tytuł": title,
                "Link": link,
                "Cena": extract_text(art, 'div[class*=rz87wg] h3'),
                "Rok": extract_text(art, 'dd[data-parameter="year"]'),
                "⛽ Paliwo": extract_text(art, 'dd[data-parameter="fuel_type"]'),
                "⚙️ Skrzynia": extract_text(art, 'dd[data-parameter="gearbox"]'),
                "📅 Przebieg": extract_text(art, 'dd[data-parameter="mileage"]'),
                "📍 Lokalizacja": extract_text(art, 'dd > p'),
                "Pojemność": cm3,
                "Moc (KM)": km,
                "🗺️ Odległość": format_distance(extract_text(art, 'dd > p'))
            }
            img = art.find("img", src=True)
            data["Zdjęcie"] = img["src"] if img else None
            results.append(data)
        page += 1
        time.sleep(1)
        if page > max_pages:
            break
    return results

# Wysyłka do Telegrama
def send_to_telegram(msg: str, photo_url: str = None, browse_url: str = None):
    base = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "parse_mode": "HTML"}
    if browse_url:
        kb = {"inline_keyboard": [[{"text": "🔗 Zobacz", "url": browse_url}]]}
        payload["reply_markup"] = json.dumps(kb)
    if photo_url:
        payload.update({"photo": photo_url, "caption": msg})
        requests.post(f"{base}/sendPhoto", data=payload)
    else:
        payload["text"] = msg
        requests.post(f"{base}/sendMessage", data=payload)

# Historia
def load_json_set(path):
    if os.path.exists(path):
        try:
            data = json.load(open(path, encoding="utf-8"))
            return set(data) if isinstance(data, list) else set()
        except:
            return set()
    return set()


def save_json(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

# Raport dzienny
def send_daily_report(offers: list[dict]):
    df = pd.DataFrame(offers)
    df["Cena_num"] = df["Cena"].apply(parse_price)
    avg, mn, mx = df["Cena_num"].mean(), df["Cena_num"].min(), df["Cena_num"].max()
    summary = (
        f"📊 <b>Raport dzienny</b>\nLiczba ofert: {len(df)}\n"
        f"Średnia cena: {avg:,.0f} zł\nNajniższa: {mn:,.0f} zł, Najwyższa: {mx:,.0f} zł"
    )
    csv_path = "report.csv"
    df.to_csv(csv_path, index=False)
    send_to_telegram(summary)
    with open(csv_path, 'rb') as file:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument",
            data={"chat_id": TELEGRAM_CHAT_ID},
            files={"document": file}
        )

if __name__ == "__main__":
    offers = fetch_offers()
    sent_links = load_json_set(HISTORY_FILE)
    updated = False
    for o in offers:
        link = o.get("Link")
        if link and link not in sent_links:
            msg = "\n".join([f"<b>{k}</b>: {v}" for k, v in o.items() if k not in ["Zdjęcie", "Link"]])
            send_to_telegram(msg, photo_url=o.get("Zdjęcie"), browse_url=link)
            sent_links.add(link)
            updated = True
    if updated:
        save_json(list(sent_links), HISTORY_FILE)
    if offers:
        send_daily_report(offers)
