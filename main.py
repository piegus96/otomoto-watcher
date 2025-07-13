import requests
from bs4 import BeautifulSoup
import json
import os
import time
import pandas as pd
import re
from datetime import datetime

# Optional geocoding of distance
try:
    from geopy.geocoders import Nominatim
    from geopy.distance import geodesic
    geopy_available = True
    geolocator = Nominatim(user_agent="otomoto_bot")
    LODZ_COORDS = (51.759248, 19.456999)
    location_cache = {}
except ImportError:
    geopy_available = False

# Constants
URL = (
    "https://www.otomoto.pl/osobowe/volvo/v60--v60-cross-country--"
    "v90--v90-cross-country/od-2020?" 
    "search%5Bfilter_enum_damaged%5D=0&" 
    "search%5Bfilter_enum_fuel_type%5D=diesel&" 
    "search%5Bfilter_float_engine_power%3Afrom%5D=190&" 
    "search%5Bfilter_float_mileage%3Ato%5D=140000&" 
    "search%5Bfilter_float_price%3Ato%5D=140000&" 
    "search%5Border%5D=relevance_web&" 
    "search%5Badvanced_search_expanded%5D=true"
)
HEADERS = {"User-Agent": "Mozilla/5.0"}
SENT_FILE = "sent_links.json"
PRICE_FILE = "price_history.json"
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Helpers

def extract_text(soup, selector: str) -> str:
    tag = soup.select_one(selector)
    return tag.get_text(strip=True) if tag else "❓ brak"

def parse_price(text: str) -> int:
    digits = ''.join(filter(str.isdigit, text))
    return int(digits) if digits else 0

def parse_power_and_capacity(text: str) -> tuple[str, str]:
    km = cm3 = "❓ brak"
    cm3_match = re.search(r"(\d{2,5})\s?cm(?:3|³)", text)
    if cm3_match:
        cm3 = f"{cm3_match.group(1)} cm3"
    km_match = re.search(r"(\d{2,4})\s?KM", text)
    if km_match:
        km = f"{km_match.group(1)} KM"
    return km, cm3

def format_distance(loc: str) -> str:
    if not geopy_available or not loc:
        return "❓ odległość"
    if loc in location_cache:
        coords = location_cache[loc]
    else:
        try:
            geo = geolocator.geocode(f"{loc}, Poland", timeout=10)
            coords = (geo.latitude, geo.longitude) if geo else None
        except:
            coords = None
        location_cache[loc] = coords
    if not coords:
        return "❓ odległość"
    dist = int(geodesic(LODZ_COORDS, coords).km)
    emoji = "🟢" if dist <= 100 else ("🟡" if dist <= 300 else "🔴")
    return f"{emoji} {dist} km"

# JSON load/save

def load_json(path: str, default):
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return default
    return default


def save_json(obj, path: str):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

# Fetch offers including detail page parsing from embedded JSON

def fetch_offers() -> list[tuple[dict, int]]:
    offers = []
    page, max_pages = 1, None
    while True:
        page_url = f"{URL}&page={page}" if page > 1 else URL
        resp = requests.get(page_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        if page == 1:
            nums = [int(li.get_text(strip=True)) for li in soup.select('li.ooa-6ysn8b') if li.get_text(strip=True).isdigit()]
            max_pages = max(nums) if nums else 1
        articles = soup.find_all('article')
        if not articles:
            break
        for art in articles:
            a = art.select_one('h2 a[href]')
            if not a:
                continue
            title = a.get_text(strip=True)
            link = a['href']
            price_text = extract_text(art, 'div[class*=rz87wg] h3')
            price_val = parse_price(price_text)
            spec = extract_text(art, 'p[class*=w3crlp]')
            km, cm3 = parse_power_and_capacity(spec)
            location = extract_text(art, 'dd > p')
            # Default detail fields
            vin = first_reg = plate = "❓ brak"
            # Parse embedded JSON for details
            try:
                detail_txt = requests.get(link, headers=HEADERS, timeout=15).text
                det_soup = BeautifulSoup(detail_txt, 'html.parser')
                script = det_soup.find('script', id='__NEXT_DATA__')
                if script:
                    data_json = json.loads(script.string)
                    ad = data_json.get('props', {}).get('pageProps', {}).get('ad', {})
                    vin = ad.get('vin', vin)
                    first_reg = ad.get('firstRegistrationDate', first_reg)
                    plate = ad.get('registrationNumber', plate)
            except:
                pass
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
            if img:
                data['Zdjęcie'] = img['src']
            offers.append((data, price_val))
        page += 1
        time.sleep(1)
        if page > max_pages:
            break
    return offers

# Send to Telegram

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
    price_history = load_json(PRICE_FILE, {})
    sent_links = set(load_json(SENT_FILE, []))
    updated_prices = False
    updated_links = False
    offers = fetch_offers()
    for data, price_val in offers:
        link = data['Link']
        now = datetime.utcnow().isoformat()
        hist = price_history.get(link, [])
        last_price = hist[-1]['price'] if hist else None
        if last_price is None or price_val != last_price:
            entry = {'timestamp': now, 'price': price_val}
            price_history.setdefault(link, []).append(entry)
            updated_prices = True
            if last_price is not None:
                diff = price_val - last_price
                pct = abs(diff)/last_price*100
                change = 'spadła' if diff < 0 else 'wzrosła'
                sign = '-' if diff < 0 else '+'
                msg = (
                    f"<b>{data['Tytuł']}</b>\n"
                    f"Cena {change} z {last_price:,} zł do {price_val:,} zł ({sign}{pct:.1f}%)\n"
                    f"📍 {data['📍 Lokalizacja']} | 🗺️ {data['🗺️ Odległość']}"
                )
                send_to_telegram(msg, photo_url=data.get('Zdjęcie'), browse_url=link)
        if link not in sent_links:
            text = '\n'.join([f"<b>{k}</b>: {v}" for k,v in data.items() if k not in ['Zdjęcie','Link']])
            send_to_telegram(text, photo_url=data.get('Zdjęcie'), browse_url=link)
            sent_links.add(link)
            updated_links = True
    if updated_prices:
        save_json(price_history, PRICE_FILE)
    if updated_links:
        save_json(list(sent_links), SENT_FILE)
