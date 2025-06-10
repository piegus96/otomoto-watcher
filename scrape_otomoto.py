import os
import json
import time
from playwright.sync_api import sync_playwright
import requests

# Zmienne środowiskowe (dodajesz je jako Secrets w GitHub Actions)
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

def send_telegram(data):
    text = f"🚗 {data['title']}\n💰 {data['price']}\n🔗 {data['url']}"
    print("🔔 Wysyłanie wiadomości na Telegram...")
    print("📝 Treść wiadomości:", text)

    response = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text}
    )

    print("📨 Odpowiedź z Telegrama:", response.text)

def scrape():
    print("🚀 Skrypt uruchomiony!")
    seen = load_history()
    new_seen = set(seen)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        
        url = "https://www.otomoto.pl/osobowe/volvo/v60--v90/od-2020?search%5Bfilter_enum_damaged%5D=0&search%5Bfilter_enum_fuel_type%5D%5B0%5D=diesel&search%5Bfilter_enum_fuel_type%5D%5B1%5D=plugin-hybrid&search%5Bfilter_enum_gearbox%5D=automatic&search%5Bfilter_float_engine_power%3Afrom%5D=190&search%5Bfilter_float_mileage%3Ato%5D=120000&search%5Bfilter_float_price%3Ato%5D=120000&search%5Border%5D=relevance_web"
        
        page.goto(url)
        page.wait_for_load_state("networkidle")
        time.sleep(3)  # dla bezpieczeństwa

        items = page.query_selector_all("a[data-testid='listing-ad']")
        print(f"🔍 Liczba ogłoszeń znalezionych: {len(items)}")

        for el in items:
            try:
                link = el.get_attribute("href")
                if not link:
                    continue

                full_url = "https://www.otomoto.pl" + link.split("?")[0]

                if full_url in seen:
                    continue

                title = el.inner_text().split("\n")[0].strip()
                price_el = el.query_selector("span.e1b25f6f12")
                price = price_el.inner_text().strip() if price_el else "Brak ceny"

                print("🆕 Nowe ogłoszenie:", title)
                send_telegram({
                    "title": title,
                    "price": price,
                    "url": full_url
                })

                new_seen.add(full_url)
                time.sleep(2)

            except Exception as e:
                print("⚠️ Błąd w przetwarzaniu ogłoszenia:", e)

        browser.close()
    save_history(new_seen)

if __name__ == "__main__":
    scrape()
