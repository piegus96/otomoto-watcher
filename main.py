import requests
from bs4 import BeautifulSoup
import json
import os
import time
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


def extract_text(soup, selector: str) -> str:
    tag = soup.select_one(selector)
    return tag.get_text(strip=True) if tag else "❓ brak"


def parse_power_and_capacity(text: str) -> tuple[str, str]:
    km = cm3 = "❓ brak"
    if "KM" in text:
        for part in text.split("•"):
            part = part.strip()
            if "KM" in part:
                km = part
            elif "cm³" in part or "cm3" in part:
                cm3 = part
    return km, cm3


def parse_price(text: str) -> int:
    digits = ''.join(filter(str.isdigit, text))
    return int(digits) if digits else 0

if geopy_available:
    def geocode_location(loc_str: str):
        if loc_str in location_cache:
            return location_cache[loc_str]
        try:
            loc = geolocator.geocode(f"{loc_str}, Poland", timeout=10)
            coords = (loc.latitude, loc.longitude) if loc else None
        except Exception:
            coords = None
        location_cache[loc_str] = coords
        return coords

    def format_distance(loc_str: str) -> str:
        coords = geocode_location(loc_str)
        if not coords:
            return "❓ odległość"
        dist_km = int(geodesic(LODZ_COORDS, coords).km)
        emoji = "🟢" if dist_km <= 100 else ("🟡" if dist_km <= 300 else "🔴")
        return f"{emoji} {dist_km} km od Łodzi"
else:
    def format_distance(loc_str: str) -> str:
        return "❓ odległość"

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


def fetch_offers() -> list[dict]:
    results = []
    page = 1
    max_pages = None
    while True:
        url = f"{URL}&page={page}" if page > 1 else URL
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        if page == 1:
            pages = [int(li.get_text(strip=True)) for li in soup.select("li.ooa-6ysn8b") if li.get_text(strip=True).isdigit()]
            max_pages = max(pages) if pages else 1
        articles = soup.find_all("article")
        if not articles: break
        for art in articles:
            h2 = art.find("h2")
            a = h2.find("a", href=True) if h2 else None
            if not a: continue
            link = a["href"]; title = a.get_text(strip=True)
            mileage = extract_text(art, 'dd[data-parameter="mileage"]')
            fuel = extract_text(art, 'dd[data-parameter="fuel_type"]')
            gearbox = extract_text(art, 'dd[data-parameter="gearbox"]')
            year = extract_text(art, 'dd[data-parameter="year"]')
            location = extract_text(art, 'dd > p')
            price = extract_text(art, 'div[class*=rz87wg] h3')
            spec = extract_text(art, 'p[class*=w3crlp]')
            km, cm3 = parse_power_and_capacity(spec)
            img = art.find("img", src=True); img_url = img["src"] if img else "❓ brak"
            results.append({
                "Link": link, "Tytuł": title, "Cena": price,
                "Rok produkcji": year, "Paliwo": fuel, "Skrzynia": gearbox,
                "Lokalizacja": location, "Przebieg": mileage,
                "Pojemność": cm3, "Moc (KM)": km,
                "Odległość": format_distance(location), "Zdjęcie": img_url
            })
        page += 1; time.sleep(1)
        if page > max_pages: break
    return results


def send_to_telegram(message: str, photo_url: str = None):
    base = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "parse_mode": "HTML"}
    if photo_url and photo_url != "❓ brak":
        payload.update({"photo": photo_url, "caption": message})
        requests.post(f"{base}/sendPhoto", data=payload)
    else:
        payload.update({"text": message})
        requests.post(f"{base}/sendMessage", data=payload)


def load_sent_links() -> set:
    # obsługa pustego lub nieprawidłowego pliku
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return set(data) if isinstance(data, list) else set()
        except (json.JSONDecodeError, ValueError):
            return set()
    return set()


def save_sent_links(links: set):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(list(links), f, ensure_ascii=False, indent=2)


def load_price_history() -> dict:
    # obsługa pustego lub nieprawidłowego pliku
    if os.path.exists(PRICE_HISTORY_FILE):
        try:
            with open(PRICE_HISTORY_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, ValueError):
            raw = {}
        # migracja formatu
        migrated = {}
        now = datetime.utcnow().isoformat()
        for link, entry in raw.items():
            if isinstance(entry, int):
                migrated[link] = [{"timestamp": now, "price": entry}]
            elif isinstance(entry, list):
                migrated[link] = entry
        return migrated
    # inicjalizacja historii
    offers = fetch_offers()
    history = {o['Link']: [{"timestamp": datetime.utcnow().isoformat(), "price": parse_price(o['Cena'])}] for o in offers}
    with open(PRICE_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    return history


def save_price_history(history: dict):
    with open(PRICE_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    data = fetch_offers()
    sent_links = load_sent_links()
    price_history = load_price_history()
    updated = False

    for item in data:
        link = item['Link']
        price = parse_price(item['Cena'])
        now = datetime.utcnow().isoformat()

        if link in price_history:
            last_price = price_history[link][-1]['price']
            if price != last_price:
                diff = price - last_price
                pct = abs(diff) / last_price * 100
                change = "spadła" if diff < 0 else "wzrosła"
                sign = "-" if diff < 0 else "+"
                msg = (
                    f"<b>{item['Tytuł']}</b>\n"
                    f"Cena {change} z {last_price:,} zł do {price:,} zł ({sign}{pct:.1f}%)\n"
                    f"{item['Rok produkcji']} | {item['Paliwo']} | {item['Skrzynia']}\n"
                    f"{item['Pojemność']} | {item['Moc (KM)']}\n"
                    f"{item['Przebieg']} | {item['Lokalizacja']}\n"
                    f"{item['Odległość']}\n\n"
                    f"👉 {link}"
                )
                send_to_telegram(msg, item['Zdjęcie'])
                price_history[link].append({"timestamp": now, "price": price})
                updated = True
        else:
            msg = (
                f"<b>{item['Tytuł']}</b>\n"
                f"{item['Cena']}\n"
                f"{item['Rok produkcji']} | {item['Paliwo']} | {item['Skrzynia']}\n"
                f"{item['Pojemność']} | {item['Moc (KM)']}\n"
                f"{item['Przebieg']} | {item['Lokalizacja']}\n"
                f"{item['Odległość']}\n\n"
                    f"👉 {link}"
            )
            send_to_telegram(msg, item['Zdjęcie'])
            sent_links.add(link)
            price_history[link] = [{"timestamp": now, "price": price}]
            updated = True

    if updated:
        save_sent_links(sent_links)
        save_price_history(price_history)
