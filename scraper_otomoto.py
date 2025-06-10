# scrape_otomoto.py
import os, json, time
from playwright.sync_api import sync_playwright
import requests

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
HISTORY_FILE = "history.json"

def load_history():
    try:
        with open(HISTORY_FILE, "r") as f:
            return set(json.load(f))
    except:
        return set()

def save_history(seen):
    with open(HISTORY_FILE, "w") as f:
        json.dump(list(seen), f)

def scrape():
    seen = load_history()
    new_seen = set(seen)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto("https://otomoto.pl/osobowe/volvo/v60--v90/od-2020?search[filter_enum_damaged]=0&...&search[order]=relevance_web")
        page.wait_for_load_state("networkidle")
        items = page.query_selector_all("article.offer-item")
        for el in items:
            link = el.query_selector("a").get_attribute("href")
            url = link.split("?")[0]
            if url in seen:
                continue
            title = el.query_selector("h2.offer-item__title").inner_text().strip()
            page.goto(url)
            page.wait_for_load_state("networkidle")
            price = page.query_selector("span.offer-price__number").inner_text().strip()
            data = {
                "url": url,
                "title": title,
                "price": price
            }
            send_telegram(data)
            new_seen.add(url)
            time.sleep(2)
        browser.close()

    save_history(new_seen)

def send_telegram(data):
    text = f"🚗 {data['title']}\n💰 {data['price']}\n🔗 {data['url']}"
    resp = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={
        "chat_id": CHAT_ID, "text": text
    })
    print("Sent:", resp.json())

if __name__ == "__main__":
    scrape()
