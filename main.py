import requests
from bs4 import BeautifulSoup
import json
import os
import time
import re
from datetime import datetime

URL = (
    "https://www.otomoto.pl/osobowe/volvo/v60--v60-cross-country--"
    "v90--v90-cross-country/od-2020?search%5Bfilter_enum_damaged%5D=0&"
    "search%5Bfilter_enum_fuel_type%5D=diesel&"
    "search%5Bfilter_float_engine_power%3Afrom%5D=190&"
    "search%5Bfilter_float_mileage%3Ato%5D=140000&"
    "search%5Bfilter_float_price%3Ato%5D=140000&search%5Border%5D=relevance_web&"
    "search%5Badvanced_search_expanded%5D=true"
)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/115 Safari/537.36"
    )
}

HISTORY_FILE = "sent_links.json"
PRICE_HISTORY_FILE = "price_history.json"
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


def parse_price(text: str) -> int:
    digits = ''.join(filter(str.isdigit, text))
    return int(digits) if digits else 0


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
            page_numbers = [
                int(li.get_text(strip=True))
                for li in pagination
                if li.get_text(strip=True).isdigit()
            ]
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
                "Zdjęcie": img_url
            })

        page += 1
        time.sleep(1)
        if page > max_pages:
            break

    return results


def send_to_telegram(message: str, photo_url: str = None):
    base_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
    if photo_url and photo_url != "❓ brak":
        requests.post(
            f"{base_url}/sendPhoto",
            data={"chat_id": TELEGRAM_CHAT_ID, "photo": photo_url, "caption": message}
        )
    else:
        requests.post(
            f"{base_url}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": message}
        )


def load_sent_links() -> set:
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_sent_links(sent_links: set):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(list(sent_links), f, ensure_ascii=False, indent=2)


def load_price_history() -> dict:
    # Wczytaj historię z pliku lub zainicjalizuj przy pierwszym uruchomieniu
    if os.path.exists(PRICE_HISTORY_FILE):
        with open(PRICE_HISTORY_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        # Migracja ze starego formatu {link: int}
        migrated = {}
        now = datetime.utcnow().isoformat()
        for link, entry in raw.items():
            if isinstance(entry, int):
                # Stary wpis: tylko cena -> zamień na listę z jednym wpisem
                migrated[link] = [{"timestamp": now, "price": entry}]
            elif isinstance(entry, list):
                migrated[link] = entry
            else:
                # Nieoczekiwany format, pomiń
                continue
        return migrated
    # Brak pliku: inicjalizacja pełnej historii
    offers = fetch_offers()
    history = {
        o["Link"]: [{"timestamp": datetime.utcnow().isoformat(), "price": parse_price(o["Cena"]) }]
        for o in offers
    }
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
        link = item["Link"]
        current_price = parse_price(item["Cena"])
        now = datetime.utcnow().isoformat()

        if link in price_history:
            last_entry = price_history[link][-1]
            last_price = last_entry["price"]
            if current_price != last_price:
                diff = current_price - last_price
                pct = abs(diff) / last_price * 100
                change = "spadła" if diff < 0 else "wzrosła"
                sign = "-" if diff < 0 else "+"
                msg = (
                    f"{item['Tytuł']}\nCena {change} z {last_price:,} zł do {current_price:,} zł ({sign}{pct:.1f}%)\n"
                    f"{item['Rok produkcji']} | {item['Paliwo']} | {item['Skrzynia']}\n"
                    f"{item['Lokalizacja']} | {item['Przebieg']}\n\n👉 {link}"
                )
                send_to_telegram(msg, item['Zdjęcie'])
                price_history[link].append({"timestamp": now, "price": current_price})
                updated = True
        else:
            # Nowa oferta
            msg = (
                f"{item['Tytuł']}\n{item['Cena']}\n"
                f"{item['Rok produkcji']} | {item['Paliwo']} | {item['Skrzynia']}\n"
                f"{item['Lokalizacja']} | {item['Przebieg']}\n\n👉 {link}"
            )
            send_to_telegram(msg, item['Zdjęcie'])
            price_history[link] = [{"timestamp": now, "price": current_price}]
            sent_links.add(link)
            updated = True

    if updated:
        save_sent_links(sent_links)
        save_price_history(price_history)
