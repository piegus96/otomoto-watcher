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
SENT_FILE = "sent_links.json"
PRICE_FILE = "price_history.json"
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Helper to extract text
def extract_text(soup, selector: str) -> str:
    tag = soup.select_one(selector)
    return tag.get_text(strip=True) if tag else "❓ brak"

# Parse power (KM) and capacity (cm3)
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

# Parse price into int
def parse_price(text: str) -> int:
    return int(''.join(filter(str.isdigit, text))) if text else 0

# Format distance from Łódź
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

# Load and save price history
def load_price_history() -> dict:
    if os.path.exists(PRICE_FILE):
        try:
            return json.load(open(PRICE_FILE, 'r', encoding='utf-8'))
        except json.JSONDecodeError:
            return {}
    return {}

def save_price_history(history: dict):
    with open(PRICE_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

# Load and save sent links
def load_sent_links() -> set:
    if os.path.exists(SENT_FILE):
        try:
            data = json.load(open(SENT_FILE, 'r', encoding='utf-8'))
            return set(data if isinstance(data, list) else [])
        except json.JSONDecodeError:
            return set()
    return set()

def save_sent_links(links: set):
    with open(SENT_FILE, 'w', encoding='utf-8') as f:
        json.dump(list(links), f, ensure_ascii=False, indent=2)

# Fetch offers list (with detail page parsing)
def fetch_offers() -> list[tuple[dict,int]]:
    results = []
    page, max_pages = 1, None
    while True:
        url = f"{URL}&page={page}" if page > 1 else URL
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        if page == 1:
            pages = [int(li.get_text(strip=True)) for li in soup.select('li.ooa-6ysn8b') if li.get_text(strip=True).isdigit()]
            max_pages = max(pages) if pages else 1
        articles = soup.find_all('article')
        if not articles:
            break
        for art in articles:
            a = art.select_one('h2 a[href]')
            if not a:
                continue
            title = a.get_text(strip=True)
            link = a['href']
            # Basic fields
            price_text = extract_text(art, 'div[class*=rz87wg] h3')
            price_val = parse_price(price_text)
            spec = extract_text(art, 'p[class*=w3crlp]')
            km, cm3 = parse_power_and_capacity(spec)
            location = extract_text(art, 'dd > p')

                                    # Fetch detail page for VIN, first registration and plate
            vin = first_reg = plate = "❓ brak"
            try:
                det_resp = requests.get(link, headers=HEADERS, timeout=15)
                det_resp.raise_for_status()
                det_soup = BeautifulSoup(det_resp.text, 'html.parser')
                info = det_soup.select_one('div[data-testid="basic_information"]')
                if info:
                    vin_tag = info.select_one('div[data-testid="vin"] p')
                    if vin_tag:
                        vin = vin_tag.get_text(strip=True)
                    reg_tag = info.select_one('div[data-testid="first_registration_date"] p')
                    if reg_tag:
                        first_reg = reg_tag.get_text(strip=True)
                    plate_tag = info.select_one('div[data-testid="registration_number"] p')
                    if plate_tag:
                        plate = plate_tag.get_text(strip=True)
            except Exception:
                pass
            except Exception:
                vin = first_reg = plate = "❓ brak"
            except Exception:
                vin = first_reg = plate = "❓ brak"

            data = {
                'Tytuł': title,
                'Cena': price_text,
                'Link': link,
                'Rok': extract_text(art, 'dd[data-parameter="year"]'),
                '⛽ Paliwo': extract_text(art, 'dd[data-parameter="fuel_type"]'),
                '⚙️ Skrzynia': extract_text(art, 'dd[data-parameter="gearbox"]'),
                '📅 Przebieg': extract_text(art, 'dd[data-parameter="mileage"]'),
                '📍 Lokalizacja': location,
                'Pojemność': cm3,
                'Moc (KM)': km,
                '🔢 VIN': vin,
                '📜 Pierwsza rej.': first_reg,
                '🔖 Tablice': plate,
                '🗺️ Odległość': format_distance(location)
            }
            img = art.find('img', src=True)
            data['Zdjęcie'] = img['src'] if img else None
            results.append((data, price_val))
        page += 1
        time.sleep(1)
        if page > max_pages:
            break
    return results

# Send message to Telegram
def send_to_telegram(msg: str, photo_url: str=None, browse_url: str=None):
    base = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'parse_mode': 'HTML'}
    if browse_url:
        kb = {'inline_keyboard': [[{'text': '🔗 Zobacz', 'url': browse_url}]]}
        payload['reply_markup'] = json.dumps(kb)
    if photo_url:
        payload.update({'photo': photo_url, 'caption': msg})
        requests.post(f"{base}/sendPhoto", data=payload)
    else:
        payload['text'] = msg
        requests.post(f"{base}/sendMessage", data=payload)

if __name__ == '__main__':
    # Load histories
    price_history = load_price_history()
    sent_links = load_sent_links()
    updated_links = False
    updated_prices = False

    offers = fetch_offers()
    for data, price_val in offers:
        link = data['Link']
        now = datetime.utcnow().isoformat()
        # Price history
        hist = price_history.get(link, [])
        last = hist[-1]['price'] if hist else None
        if last is None:
            price_history[link] = [{'timestamp': now, 'price': price_val}]
            updated_prices = True
        elif price_val != last:
            price_history[link].append({'timestamp': now, 'price': price_val})
            updated_prices = True
            # Notify price change
            diff = price_val - last
            pct = abs(diff)/last*100
            change = 'spadła' if diff<0 else 'wzrosła'
            sign = '-' if diff<0 else '+'
            msg = (
                f"<b>{data['Tytuł']}</b>\n"
                f"Cena {change} z {last:,} zł do {price_val:,} zł ({sign}{pct:.1f}%)\n"
                f"📍 {data['📍 Lokalizacja']} | 🗺️ {data['🗺️ Odległość']}"
            )
            send_to_telegram(msg, photo_url=data.get('Zdjęcie'), browse_url=link)
        # New link
        if link not in sent_links:
            msg = '\n'.join([f"<b>{k}</b>: {v}" for k,v in data.items() if k not in ['Zdjęcie','Link']])
            send_to_telegram(msg, photo_url=data.get('Zdjęcie'), browse_url=link)
            sent_links.add(link)
            updated_links = True

    # Save
    if updated_prices:
        save_price_history(price_history)
    if updated_links:
        save_sent_links(sent_links)
