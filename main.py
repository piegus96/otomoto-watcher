import requests
from bs4 import BeautifulSoup
import json
import os
import time
import re
from datetime import datetime
from geopy.geocoders import Nominatim
from geopy.distance import geodesic

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
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115 Safari/537.36"}

HISTORY_FILE = "sent_links.json"
PRICE_HISTORY_FILE = "price_history.json"
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Geolocator i baza Łódź
geolocator = Nominatim(user_agent="otomoto_bot")
LODZ_COORDS = (51.759248, 19.456999)
location_cache = {}


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


def geocode_location(loc_str: str) -> tuple[float, float] | None:
    """Zwraca współrzędne dla lokalizacji lub None."""
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
    dist = geodesic(LODZ_COORDS, coords).km
    dist_km = int(dist)
    # wybór koloru emoji
    if dist_km <= 100:
        emoji = "🟢"
    elif dist_km <= 300:
        emoji = "🟡"
    else:
        emoji = "🔴"
    return f"{emoji} {dist_km} km od Łodzi"


def fetch_offers() -> list[dict]:
    results = []
    page = 1
    max_pages = None
    while True:
        paged_url = f"{URL}&page={page}" if page > 1 else URL
        resp = requests.get(paged_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        if page == 1:
            pages = [int(li.get_text(strip=True)) for li in soup.select("li.ooa-6ysn8b") if li.get_text(strip=True).isdigit()]
            max_pages = max(pages) if pages else 1
        articles = soup.find_all("article")
        if not articles:
            break
        for art in articles:
            a = art.find("h2") and art.find("h2").find("a", href=True)
            if not a: continue
            link = a["href"]
            title = a.get_text(strip=True)
            mileage = extract_text(art, 'dd[data-parameter="mileage"]')
            fuel = extract_text(art, 'dd[data-parameter="fuel_type"]')
            gearbox = extract_text(art, 'dd[data-parameter="gearbox"]')
            year = extract_text(art, 'dd[data-parameter="year"]')
            location = extract_text(art, 'dd > p')
            price = extract_text(art, 'div[class*=rz87wg] h3')
            spec_text = extract_text(art, 'p[class*=w3crlp]')
            km, cm3 = parse_power_and_capacity(spec_text)
            img = art.find("img", src=True)
            img_url = img["src"] if img else "❓ brak"
            results.append({
                "Link": link,
                "Tytuł": title,
                "Cena": price,
                "Rok produkcji": year,
                "Paliwo": fuel,
                "Skrzynia": gearbox,
                "Lokalizacja": location,
                "Przebieg": mileage,
                "Moc (KM)": km,
                "Pojemność": cm3,
                "Odległość": format_distance(location),
                "Zdjęcie": img_url
            })
        page += 1
        time.sleep(1)
        if page > max_pages:
            break
    return results


def send_to_telegram(message: str, photo_url: str = None):
    base_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
    payload = {"chat_id": TELEGRAM_CHAT_ID}
    if photo_url and photo_url != "❓ brak":
        payload.update({"photo": photo_url, "caption": message, "parse_mode": "HTML"})
        requests.post(f"{base_url}/sendPhoto", data=payload)
    else:
        payload.update({"text": message, "parse_mode": "HTML"})
        requests.post(f"{base_url}/sendMessage", data=payload)

# reszta kodu pozostaje bez zmian...
