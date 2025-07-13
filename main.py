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
    det = requests.get(link, headers=HEADERS, timeout=15).text
    det_soup = BeautifulSoup(det, 'html.parser')
    script = det_soup.find('script', id='__NEXT_DATA__')
    if script:
        data_json = json.loads(script.string)
        ad = data_json.get('props', {}).get('pageProps', {}).get('ad', {})
        vin = ad.get('vin', vin)
        first_reg = ad.get('firstRegistrationDate', first_reg)
        plate = ad.get('registrationNumber', plate)
    # Fallback parsing for registration plate via HTML
    if plate == "❓ brak":
        plate_tag = det_soup.select_one('div[data-testid="registration"] p + p')
        if plate_tag:
            plate = plate_tag.get_text(strip=True)
except Exception:
    pass
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
    price_history = load_json(PRICE_FILE, {})
    sent_links = set(load_json(SENT_FILE, []))
    updated_links = False
    updated_prices = False

    offers = fetch_offers()
    for data, price_val in offers:
        link = data['Link']
        now = datetime.utcnow().isoformat()
        hist = price_history.get(link, [])
        last = hist[-1]['price'] if hist else None
        if last is None or price_val != last:
            entry = {'timestamp': now, 'price': price_val}
            price_history.setdefault(link, []).append(entry)
            updated_prices = True
            if last is not None:
                diff = price_val - last
                pct = abs(diff)/last*100
                change = 'spadła' if diff < 0 else 'wzrosła'
                sign = '-' if diff < 0 else '+'
                msg = (
                    f"<b>{data['Tytuł']}</b>\n"
                    f"Cena {change} z {last:,} zł do {price_val:,} zł ({sign}{pct:.1f}%)\n"
                    f"📍 {data['📍 Lokalizacja']} | 🗺️ {data['🗺️ Odległość']}"
                )
                send_to_telegram(msg, photo_url=data.get('Zdjęcie'), browse_url=link)
        if link not in sent_links:
            msg = '\n'.join([f"<b>{k}</b>: {v}" for k,v in data.items() if k not in ['Zdjęcie','Link']])
            send_to_telegram(msg, photo_url=data.get('Zdjęcie'), browse_url=link)
            sent_links.add(link)
            updated_links = True

    if updated_prices:
        save_json(price_history, PRICE_FILE)
    if updated_links:
        save_json(list(sent_links), SENT_FILE)
