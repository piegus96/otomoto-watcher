# main.py
import requests
from bs4 import BeautifulSoup
import pandas as pd
import json
import os
import time

URL = "https://www.otomoto.pl/osobowe/volvo/v60--v60-cross-country--v90--v90-cross-country/od-2020?search%5Bfilter_enum_damaged%5D=0&search%5Bfilter_enum_fuel_type%5D=diesel&search%5Bfilter_float_engine_power%3Afrom%5D=190&search%5Bfilter_float_mileage%3Ato%5D=140000&search%5Bfilter_float_price%3Ato%5D=140000&search%5Border%5D=relevance_web&search%5Badvanced_search_expanded%5D=true"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/115 Safari/537.36"
    )
}

HISTORY_FILE = "sent_links.json"
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def extract_text(soup, selector: str) -> str:
    tag = soup.select_one(selector)
    return tag.get_text(strip=True) if tag else "❓ brak"

def parse_power_and_capacity(text: str) -> tuple[str, str]:
    km = "❓ brak"
    cm3 = "❓ brak"
    if "KM" in text:
        parts = text.split("•")
        for part in parts:
            part = part.strip()
            if "KM" in part:
                km = part
            elif "cm³" in part or "cm3" in part:
                cm3 = part
    return km, cm3

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
            pagination = soup.select("li.ooa-6ysn8b")
            page_numbers = [int(li.get_text(strip=True)) for li in pagination if li.get_text(strip=True).isdigit()]
            max_pages = max(page_numbers) if page_numbers else 1

        articles = soup.find_all("article")
        if not articles:
            break

        for art in articles:
            h2 = art.find("h2")
            a_tag = h2.find("a", href=True) if h2 else None
            if not a_tag:
                continue

            link = a_tag["href"]
            title = a_tag.get_text(strip=True)
            mileage  = extract_text(art, 'dd[data-parameter="mileage"]')
            fuel     = extract_text(art, 'dd[data-parameter="fuel_type"]')
            gearbox  = extract_text(art, 'dd[data-parameter="gearbox"]')
            year     = extract_text(art, 'dd[data-parameter="year"]')
            location = extract_text(art, 'dd > p')
            price_div = art.find("div", class_=lambda c: c and "rz87wg" in c)
            price_tag = price_div.find("h3") if price_div else None
            price     = price_tag.get_text(strip=True) if price_tag else "❓ brak"
            spec_text = extract_text(art, 'p[class*="w3crlp"]')
            km, cm3 = parse_power_and_capacity(spec_text)
            img = art.find("img", src=True)
            img_url = img["src"] if img else "❓ brak"

            results.append({
                "Tytuł":         title,
                "Cena":          price,
                "Link":          link,
                "Rok produkcji": year,
                "Paliwo":        fuel,
                "Skrzynia":      gearbox,
                "Lokalizacja":   location,
                "Przebieg":      mileage,
                "Pojemność":     cm3,
                "Moc (KM)":      km,
                "Zdjęcie":       img_url
            })

        page += 1
        time.sleep(1)

        if page > max_pages:
            break

    return results

def send_to_telegram(message: str, photo_url: str = None):
    base_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
    if photo_url and photo_url != "❓ brak":
        url = f"{base_url}/sendPhoto"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "caption": message, "photo": photo_url}
    else:
        url = f"{base_url}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    requests.post(url, data=payload)

def load_sent_links() -> set:
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_sent_links(sent_links: set):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(list(sent_links), f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    data = fetch_offers()
    sent_links = load_sent_links()
    new_links = set()

    for item in data:
        if item["Link"] in sent_links:
            continue

        msg = f"{item['Tytuł']}\n{item['Cena']}\n{item['Rok produkcji']} | {item['Paliwo']} | {item['Skrzynia']}\n{item['Przebieg']} | {item['Lokalizacja']}\n\n👉 {item['Link']}"
        send_to_telegram(msg, item['Zdjęcie'])
        new_links.add(item["Link"])

    if new_links:
        sent_links.update(new_links)
        save_sent_links(sent_links)

