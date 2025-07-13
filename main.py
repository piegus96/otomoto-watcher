import requests
from bs4 import BeautifulSoup
import json
import os
import time
import re
from datetime import datetime

URL = "https://www.otomoto.pl/osobowe/volvo/v60--v60-cross-country--v90--v90-cross-country/od-2020?search%5Bfilter_enum_damaged%5D=0&search%5Bfilter_enum_fuel_type%5D=diesel&search%5Bfilter_float_engine_power%3Afrom%5D=190&search%5Bfilter_float_mileage%3Ato%5D=140000&search%5Bfilter_float_price%3Ato%5D=140000&search%5Border%5D=relevance_web&search%5Badvanced_search_expanded%5D=true"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115 Safari/537.36"}

HISTORY_FILE = "sent_links.json"
PRICE_HISTORY_FILE = "price_history.json"
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def extract_text(soup, selector: str) -> str:
    tag = soup.select_one(selector)
    return tag.get_text(strip=True) if tag else "❓ brak"


def parse_power_and_capacity(text: str) -> tuple[str, str]:
    km = cm3 = "❓ brak"
    if "KM" in text:
        for part in text.split("•"): part = part.strip();
            if "KM" in part: km = part
            elif "cm³" in part or "cm3" in part: cm3 = part
    return km, cm3


def parse_price(text: str) -> int:
    nums = ''.join(filter(str.isdigit, text))
    return int(nums) if nums else 0


def fetch_offers() -> list[dict]:
    results, page, max_pages = [], 1, None
    while True:
        resp = requests.get(f"{URL}&page={page}" if page>1 else URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        if page==1:
            pages = [int(li.get_text(strip=True)) for li in soup.select("li.ooa-6ysn8b") if li.get_text(strip=True).isdigit()]
            max_pages = max(pages) if pages else 1
        articles = soup.find_all("article")
        if not articles: break
        for art in articles:
            a = art.find("h2") and art.find("h2").find("a", href=True)
            if not a: continue
            link = a["href"]; title = a.get_text(strip=True)
            mileage = extract_text(art, 'dd[data-parameter="mileage"]')
            fuel = extract_text(art, 'dd[data-parameter="fuel_type"]')
            gearbox = extract_text(art, 'dd[data-parameter="gearbox"]')
            year = extract_text(art, 'dd[data-parameter="year"]')
            loc = extract_text(art, 'dd > p')
            price = extract_text(art, 'div[class*=rz87wg] h3')
            spec = extract_text(art, 'p[class*=w3crlp]'); km, cm3 = parse_power_and_capacity(spec)
            img = art.find("img", src=True);
            img_url = img["src"] if img else "❓ brak"
            results.append({"Link":link, "Tytuł":title, "Cena":price,
                            "Rok produkcji":year, "Paliwo":fuel, "Skrzynia":gearbox,
                            "Przebieg":mileage, "Lokalizacja":loc,
                            "Moc (KM)":km, "Pojemność":cm3, "Zdjęcie":img_url})
        page += 1; time.sleep(1)
        if page>max_pages: break
    return results


def send_to_telegram(msg: str, photo: str=None):
    base = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
    if photo and photo!="❓ brak":
        requests.post(f"{base}/sendPhoto", data={"chat_id":TELEGRAM_CHAT_ID, "photo":photo, "caption":msg})
    else:
        requests.post(f"{base}/sendMessage", data={"chat_id":TELEGRAM_CHAT_ID, "text":msg})


def load_sent_links() -> set:
    return set(json.load(open(HISTORY_FILE, encoding='utf-8'))) if os.path.exists(HISTORY_FILE) else set()

def save_sent_links(s: set): json.dump(list(s), open(HISTORY_FILE,'w',encoding='utf-8'), ensure_ascii=False, indent=2)


def load_price_history() -> dict:
    if os.path.exists(PRICE_HISTORY_FILE): return json.load(open(PRICE_HISTORY_FILE,encoding='utf-8'))
    # init with first-run history
    offers = fetch_offers()
    hist = {o['Link']:[{"timestamp":datetime.utcnow().isoformat(), "price":parse_price(o['Cena'])}] for o in offers}
    json.dump(hist, open(PRICE_HISTORY_FILE,'w',encoding='utf-8'), ensure_ascii=False, indent=2)
    return hist


def save_price_history(h: dict):
    json.dump(h, open(PRICE_HISTORY_FILE,'w',encoding='utf-8'), ensure_ascii=False, indent=2)


if __name__=="__main__":
    data = fetch_offers()
    sent = load_sent_links()
    price_hist = load_price_history()
    updated = False
    for item in data:
        link = item['Link']; price = parse_price(item['Cena'])
        now = datetime.utcnow().isoformat()
        if link in price_hist:
            last = price_hist[link][-1]['price']
            if price!=last:
                diff = price - last
                pct = abs(diff)/last*100
                change = 'spadła' if diff<0 else 'wzrosła'
                sign = '-' if diff<0 else '+'
                msg = f"{item['Tytuł']}\nCena {change} z {last:,} zł do {price:,} zł ({sign}{pct:.1f}%)"
                msg += f"\n{item['Rok produkcji']} | {item['Paliwo']} | {item['Skrzynia']}"
                msg += f"\n{item['Przebieg']} | {item['Lokalizacja']}\n\n👉 {link}"
                send_to_telegram(msg, item['Zdjęcie'])
                price_hist[link].append({"timestamp":now, "price":price})
                updated = True
        else:
            # new offer
            msg = f"{item['Tytuł']}\n{item['Cena']}" + f"\n{item['Rok produkcji']} | {item['Paliwo']} | {item['Skrzynia']}"
            msg += f"\n{item['Przebieg']} | {item['Lokalizacja']}\n\n👉 {link}"
            send_to_telegram(msg, item['Zdjęcie'])
            price_hist[link] = [{"timestamp":now, "price":price}]
            sent.add(link)
            updated = True
    if updated:
        save_sent_links(sent)
        save_price_history(price_hist)
