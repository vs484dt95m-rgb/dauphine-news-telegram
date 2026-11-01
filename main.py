import os
import json
import logging
import feedparser
import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

app = Flask(__name__)

# --- VARIABLES D'ENVIRONNEMENT ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID")
FACEBOOK_PAGE_ACCESS_TOKEN = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN")

PIAILLE_INSTANCE = os.getenv("PIAILLE_INSTANCE", "https://piaille.fr")
PIAILLE_TOKEN = os.getenv("PIAILLE_TOKEN")

# --- LISTE DES FLUX RSS ---
RSS_FEEDS = [
    "https://www.ledauphine.com/isere/rss",
    "https://www.francebleu.fr/rss/isere.xml",
    "https://www.placegrenet.fr/feed"
]

# --- GESTION ANTI-DOUBLON VIA FICHIER LOCAL (JSON) ---
HISTORY_FILE = "published.json"

def load_history():
    """Charge la liste des liens déjà publiés depuis le fichier JSON."""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Erreur de lecture de l'historique: {e}")
    return []

def save_history(history):
    """Sauvegarde la liste des liens (limitée aux 100 derniers)."""
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history[-100:], f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Erreur d'écriture de l'historique: {e}")

def is_already_published(link):
    history = load_history()
    return link in history

def mark_as_published(link):
    history = load_history()
    if link not in history:
        history.append(link)
        save_history(history)

# --- DÉTECTION DES CATEGORIES & EMOJIS (Corrigé et priorisé) ---
def categorize_article(title, summary):
    text = f"{title} {summary}".lower()
    
    # 1. FAITS DIVERS / JUSTICE / DRAME (Prioritaire absolu)
    if any(k in text for k in ["jetée", "suicide", "décès", "mort", "meurtre", "police", "gendarmerie", "tribunal", "accident", "enquête", "drame", "violences", "agression", "feu", "incendie"]):
        return "🚨 FAITS DIVERS & JUSTICE"
    # 2. TRANSPORTS & CIRCULATION
    elif any(k in text for k in ["tram", "bus", "tag", "piste cyclable", "a48", "a480", "circulation", "bouchon", "train", "ter", "sncf", "ralentissement"]):
        return "🚌🚗 TRANSPORTS & CIRCULATION"
    # 3. POLITIQUE & SOCIÉTÉ
    elif any(k in text for k in ["maire", "metropole", "grenoble alpes métropole", "conseil", "élections", "manifestation", "grève", "municipales"]):
        return "🏛️ POLITIQUE & LOCAL"
    # 4. SPORTS
    elif any(k in text for k in ["fcg", "gf38", "brûleurs de loups", "rugby", "football", "hockey", "match"]):
        return "⚽ SPORTS"
    # 5. MONTAGNE & NATURE
    elif any(k in text for k in ["chartreuse", "vercors", "belledonne", "station", "ski", "randonnée", "neige", "avalanche"]):
        return "🏔️ MONTAGNE & NATURE"
    
    return "📰 ACTUALITÉ LOCALE"

# --- EXTRACTION D'IMAGE ---
def extract_image_url(entry):
    if 'media_content' in entry and len(entry.media_content) > 0:
        return entry.media_content[0].get('url')
    if 'enclosures' in entry and len(entry.enclosures) > 0:
        for enc in entry.enclosures:
            if enc.get('type', '').startswith('image/'):
                return enc.get('href')
    html_content = entry.get('summary', '') or entry.get('description', '')
    if html_content:
        soup = BeautifulSoup(html_content, 'html.parser')
        img = soup.find('img')
        if img and img.get('src'):
            return img.get('src')
    return None

# --- MODULES DE PUBLICATION ---

def publish_telegram(text, image_url=None):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        if image_url:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
            payload = {"chat_id": TELEGRAM_CHAT_ID, "photo": image_url, "caption": text, "parse_mode": "HTML"}
        else:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        logging.error(f"Erreur Telegram: {e}")

def publish_facebook(text, image_url=None):
    if not FACEBOOK_PAGE_ID or not FACEBOOK_PAGE_ACCESS_TOKEN:
        return
    try:
        if image_url:
            url = f"https://graph.facebook.com/v19.0/{FACEBOOK_PAGE_ID}/photos"
            payload = {"url": image_url, "caption": text, "access_token": FACEBOOK_PAGE_ACCESS_TOKEN}
        else:
            url = f"https://graph.facebook.com/v19.0/{FACEBOOK_PAGE_ID}/feed"
            payload = {"message": text, "access_token": FACEBOOK_PAGE_ACCESS_TOKEN}
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        logging.error(f"Erreur Facebook: {e}")

def publish_piaille(text):
    if not PIAILLE_TOKEN:
        return
    try:
        headers = {"Authorization": f"Bearer {PIAILLE_TOKEN}"}
        url = f"{PIAILLE_INSTANCE.rstrip('/')}/api/v1/statuses"
        requests.post(url, data={"status": text}, headers=headers, timeout=10)
    except Exception as e:
        logging.error(f"Erreur Piaille: {e}")

# --- TRAITEMENT DES FLUX ---
def process_feeds():
    for feed_url in RSS_FEEDS:
        parsed_feed = feedparser.parse(feed_url)
        for entry in parsed_feed.entries[:5]:
            link = entry.link
            
            # Anti-doublon strict basé sur l'historique local
            if is_already_published(link):
                continue

            title = entry.title
            raw_summary = entry.get('summary', '') or entry.get('description', '')
            clean_summary = BeautifulSoup(raw_summary, 'html.parser').get_text().strip()
            if len(clean_summary) > 250:
                clean_summary = clean_summary[:247] + "..."

            source_name = "Le Dauphiné Libéré" if "ledauphine" in link else "France Bleu Isère" if "francebleu" in link else "Place Gre'net"
            category = categorize_article(title, clean_summary)
            image_url = extract_image_url(entry)

            # Mise en forme du message
            msg = (
                f"{category}\n\n"
                f"📌 <b>{title}</b>\n\n"
                f"📝 {clean_summary}\n\n"
                f"via {source_name}\n"
                f"🔗 <a href='{link}'>Lire l'article complet</a>\n\n"
                f"───────────────────\n"
                f"🏔️ Toute l'actu de Grenoble et du Dauphiné !\n"
                f"#Grenoble #Isere #DauphineNews"
            )

            # Publication multi-plateformes (Telegram, Facebook, Piaille)
            publish_telegram(msg, image_url)
            publish_facebook(msg, image_url)
            publish_piaille(f"{category}\n\n📌 {title}\n\n{clean_summary}\n\n🔗 {link}\n#Grenoble #Isere")

            # Enregistrer pour ne plus jamais le republier
            mark_as_published(link)
            logging.info(f"Article publié et mémorisé avec succès : {title}")
            return

@app.route("/")
@app.route("/health")
def health_check():
    process_feeds()
    return jsonify({"status": "ok", "message": "Feed check completed"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
