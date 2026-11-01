import os
import threading
import time
import logging
import re
import feedparser
import requests
from flask import Flask

# Configuration des logs
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

app = Flask(__name__)

@app.route('/')
def home():
    return "Le bot Dauphiné News est actif et publie toutes les 15 minutes !"

@app.route('/health')
def health():
    return "OK", 200

# -------------------------------------------------------------------
# 1. SOURCES RSS LOCALE (GRENOBLE & DAUPHINÉ)
# -------------------------------------------------------------------

FLUX_RSS = {
    "https://www.ledauphine.com/isere/rss": "Le Dauphiné Libéré",
    "https://www.francebleu.fr/rss/isere.xml": "France Bleu Isère",
    "https://www.placegrenet.fr/feed/": "Place Gre'net"
}

# Mot-clés impératifs pour s'assurer que c'est de l'actu locale
MOTS_CLES_LOCALES = [
    "grenoble", "isère", "isere", "dauphiné", "dauphine", "échirolles", "echirolles",
    "saint-martin-d'hères", "meylan", "voiron", "voironnais", "fontaine", "voreppe",
    "vercors", "chartreuse", "belledonne", "grédivaudan", "gresivaudan", "gf38", "fcg",
    "brûleurs de loups", "tag", "a480", "n201"
]

POSTS_DEJA_PUBLIES = set()

# -------------------------------------------------------------------
# 2. FILTRAGE ET CLASSIFICATION INTELLIGENTE
# -------------------------------------------------------------------

def est_actualite_locale(titre, resume):
    texte = (titre + " " + resume).lower()
    # Retourne True si au moins un mot-clé local est présent
    return any(mot in texte for mot in MOTS_CLES_LOCALES)

def obtenir_emojis_par_sujet(titre, resume):
    texte = (titre + " " + resume).lower()
    
    if any(m in texte for m in ["accident", "incendie", "police", "gendarmerie", "justice", "tribunal", "vol", "agression", "drame"]):
        return "🚨🚔", "FAITS DIVERS & JUSTICE"
    elif any(m in texte for m in ["tram", "bus", "tag", "circulation", "a480", "travaux", "bouchon", "route", "sncf", "train"]):
        return "🚌🚗", "TRANSPORTS & CIRCULATION"
    elif any(m in texte for m in ["neige", "montagne", "vercors", "chartreuse", "belledonne", "station", "ski", "météo", "alerte"]):
        return "🏔️❄️", "MONTAGNE & MÉTÉO"
    elif any(m in texte for m in ["gf38", "fcg", "brûleurs de loups", "match", "victoire", "défaite", "stade", "sport"]):
        return "⚽🏉", "SPORTS ISÈRE"
    elif any(m in texte for m in ["maire", "mairie", "métropole", "conseil", "piolle", "élections", "politique"]):
        return "🏛️📜", "POLITIQUE LOCALE"
    elif any(m in texte for m in ["concert", "festival", "exposition", "culture", "sortie", "spectacle", "foire"]):
        return "🎭🎟️", "CULTURE & SORTIES"
    else:
        return "📰🏔️", "ACTU GRENOBLE & DAUPHINÉ"

# -------------------------------------------------------------------
# 3. BOUCLE DE PUBLICATION (TOUTES LES 15 MINUTES)
# -------------------------------------------------------------------

def boucle_verification_flux():
    logging.info("--- DÉMARRAGE DU BOT DAUPHINÉ NEWS (15 MIN) ---")
    time.sleep(5)

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHANNEL_ID")
    invite_link = os.getenv("TELEGRAM_INVITE_LINK", "https://t.me/dauphine_news")
    
    if not token or not chat_id:
        logging.error("ERREUR CRITIQUE : TELEGRAM_BOT_TOKEN ou TELEGRAM_CHANNEL_ID manquant !")
        return

    url_api = f"https://api.telegram.org/bot{token}/sendMessage"

    while True:
        try:
            logging.info("Recherche d'actualités locales récentes...")
            article_a_publier = None
            nom_source_active = "Dauphiné News"
            
            # Parcours des flux RSS
            for url_rss, nom_src in FLUX_RSS.items():
                feed = feedparser.parse(url_rss)
                for entry in feed.entries:
                    art_id = entry.get("id", entry.get("link"))
                    titre = entry.get("title", "")
                    resume = entry.get("summary", "")
                    
                    # Vérification 1 : Non publié + Vérification 2 : 100% Local
                    if art_id not in POSTS_DEJA_PUBLIES and est_actualite_locale(titre, resume):
                        article_a_publier = entry
                        nom_source_active = nom_src
                        break
                if article_a_publier:
                    break

            # Envoi de l'article sur le canal Telegram
            if article_a_publier:
                art_id = article_a_publier.get("id", article_a_publier.get("link"))
                POSTS_DEJA_PUBLIES.add(art_id)
                
                titre = article_a_publier.get("title", "Actualité locale")
                lien = article_a_publier.get("link", "#")
                resume = article_a_publier.get("summary", "Toute l'actualité de Grenoble et du Dauphiné.")
                
                resume_propre = re.sub('<.*?>', '', resume)[:240] + "..."
                emojis, nom_theme = obtenir_emojis_par_sujet(titre, resume)

                texte_pub = (
                    f"{emojis} **{nom_theme}**\n\n"
                    f"📌 **{titre}**\n\n"
                    f"📝 {resume_propre}\n\n"
                    f"via {nom_source_active}\n"
                    f"🔗 [Lire l'article complet]({lien})\n\n"
                    f"───────────────────\n"
                    f"🏔️ **Toute l'actu de Grenoble et du Dauphiné en direct !**\n"
                    f"👉 [S'abonner au canal]({invite_link})\n\n"
                    f"#Grenoble #Isere #DauphineNews"
                )
                
                payload = {
                    "chat_id": chat_id,
                    "text": texte_pub,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": False
                }
                
                response = requests.post(url_api, json=payload)
                if response.status_code == 200:
                    logging.info(f"Article publié : {titre}")
                else:
                    logging.error(f"Erreur API Telegram : {response.text}")

        except Exception as e:
            logging.error(f"Erreur dans la boucle de publication : {e}")

        # Pause d'exactement 15 minutes (900 secondes)
        time.sleep(900)

# -------------------------------------------------------------------
# 4. DÉMARRAGE AUTOMATIQUE
# -------------------------------------------------------------------
thread_bot = threading.Thread(target=boucle_verification_flux, daemon=True)
thread_bot.start()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
