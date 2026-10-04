# 📱 WhatsApp Bot (Photo → Notre API → Réponse WhatsApp)

Bot WhatsApp officiel basé sur l'**API Meta WhatsApp Cloud** (FastAPI, Uvicorn, httpx).
Il permet aux utilisateurs d'envoyer une photo (ou un message texte) sur WhatsApp, télécharge l'image, la transmet en `multipart/form-data` à notre route API backend, et renvoie la réponse formatée dans la conversation WhatsApp.

---

## 🏗️ Flux d'architecture

```
Utilisateur WhatsApp
       │
       ▼ (1. Envoi photo)
Meta WhatsApp Cloud
       │
       ▼ (2. Webhook POST /webhook)
Notre Serveur FastAPI (whatsapp-bot)
       │  ├── 200 OK immédiat à Meta
       │  ├── Vérification signature X-Hub-Signature-256
       │  ├── Téléchargement média (GET Meta Cloud API)
       │  └── Envoi en arrière-plan (BackgroundTasks)
       ▼ (3. POST multipart/form-data)
Notre Route API Backend (OUR_API_URL)
       │
       ▼ (4. Réponse JSON structurée)
Notre Serveur FastAPI
       │
       ▼ (5. POST messages via Graph API)
Meta WhatsApp Cloud
       │
       ▼ (6. Message texte)
Utilisateur WhatsApp
```

---

## 📂 Structure du projet

```
whatsapp-bot/
├── app/
│   ├── __init__.py
│   ├── main.py            # Routes FastAPI (GET /webhook, POST /webhook, GET /)
│   ├── config.py          # Chargement sécurisé du .env (pydantic-settings)
│   ├── whatsapp.py        # Meta Cloud API : téléchargement média, envoi de texte, mark as read
│   ├── processor.py       # Traitement messages, dédoublonnage, commandes, routage API
│   └── security.py        # Vérification HMAC-SHA256 (X-Hub-Signature-256)
├── tests/
│   ├── test_webhook.py    # Tests unitaires & intégration (couverture complète)
│   └── mock_backend.py    # Serveur mock pour tester le pipeline localement
├── .env                   # Variables d'environnement (NE PAS COMMITTER)
├── .env.example           # Gabarit d'exemple
├── .gitignore
├── requirements.txt       # Dépendances Python
└── README.md              # Documentation
```

---

## 🚀 Étape 1 : Configuration côté Meta Developer

1. Rendez-vous sur [developers.facebook.com](https://developers.facebook.com) → **My Apps** → **Create App**.
2. Sélectionnez le type d'application : **Business** (ou **Other** puis Business).
3. Ajoutez le produit **WhatsApp** à l'application.
4. Dans **WhatsApp** → **API Setup** :
   - Notez le **Phone Number ID** (numéro de test fourni par Meta).
   - Générez un **Temporary Access Token** (valide 24 heures).
   - Dans le champ *To*, ajoutez votre numéro WhatsApp personnel dans la liste des destinataires de test (le numéro de test ne peut contacter que les numéros autorisés).
5. Dans **App Settings** → **Basic** :
   - Affichez et notez l'**App Secret**.
6. Choisissez un token secret arbitraire pour votre webhook (ex: `mon_super_secret_webhook_123`).

---

## ⚙️ Étape 2 : Installation & Configuration locale

### 1. Cloner ou naviguer dans le dossier :
```bash
cd DayOne-Claudinho\whatsapp-bot
```

### 2. Créer un environnement virtuel et installer les dépendances :
```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configurer le fichier `.env` :
Copiez `.env.example` en `.env` :
```bash
cp .env.example .env
```
Renseignez les 4 valeurs obtenues sur Meta :
```ini
WHATSAPP_TOKEN=EAAG...votre_token_meta
PHONE_NUMBER_ID=123456789012345
APP_SECRET=votre_app_secret_meta
VERIFY_TOKEN=mon_super_secret_webhook_123
GRAPH_API_VERSION=v21.0

# URL de notre API qui analyse les photos
OUR_API_URL=http://localhost:8080/analyze
OUR_API_KEY=
OUR_API_TIMEOUT=120   # secondes ; l'analyse DayOne peut dépasser 30 s
```

`APP_SECRET` et `VERIFY_TOKEN` sont obligatoires : sans eux, le webhook refuse toutes les requêtes (pas de mode « sans vérification »).

---

## 🧪 Étape 3 : Lancer les tests automatisés

Tous les critères de validation peuvent être vérifiés immédiatement en exécutant la suite de tests :
```bash
pytest -v
```

Tests couverts :
- [x] Vérification du webhook Meta (`hub.mode=subscribe` + challenge)
- [x] Rejet des requêtes sans signature ou avec fausse signature (`401 Unauthorized`)
- [x] Filtrage silencieux des statuts Meta (`sent`, `delivered`, `read`)
- [x] Dédoublonnage des messages
- [x] Commande `/aide` et routage des textes
- [x] Téléchargement de média et transmission à notre API
- [x] Gestion gracieuse des erreurs API (timeout, 500) sans crash serveur

---

## 🌐 Étape 4 : Déploiement local avec ngrok & Meta

### 1. Démarrer le serveur FastAPI :
```bash
uvicorn app.main:app --reload --port 8000
```

### 2. (Optionnel) Démarrer le backend mock si votre API finale n'est pas encore lancée :
Dans un second terminal :
```bash
uvicorn tests.mock_backend:app --port 8080 --reload
```

### 3. Exposer le port local avec ngrok :
Dans un troisième terminal :
```bash
ngrok http 8000
```
Copiez l'URL HTTPS fournie par ngrok (ex: `https://abcd-1234.ngrok-free.app`).

### 4. Configurer le Webhook dans le Dashboard Meta :
1. Dans le tableau de bord Meta → **WhatsApp** → **Configuration** → **Webhook**.
2. Cliquez sur **Edit** :
   - **Callback URL** : `https://abcd-1234.ngrok-free.app/webhook`
   - **Verify Token** : la valeur configurée dans `VERIFY_TOKEN` (ex: `mon_super_secret_webhook_123`).
3. Cliquez sur **Verify and Save**. Meta envoie un `GET /webhook` et valide instantanément le serveur.
4. Dans **Webhook fields**, cliquez sur **Manage** et cochez **`messages`** (obligatoire pour recevoir les messages et photos entrants).

---

## 💬 Conversation

| L'utilisateur… | Le bot… |
| :--- | :--- |
| envoie une ou plusieurs **photos** | « 📄 Page N reçue » + boutons *Terminé* / *Annuler* |
| appuie sur **Terminé** | envoie chaque photo à `OUR_API_URL`, puis présente la page 1/n |
| répond **1** | confirme la page ; après la dernière : récapitulatif propre (+ envoi JSON à `CONFIRM_URL` si configurée) |
| répond **2** | liste numérotée des champs → numéro → nouvelle valeur (format vérifié : date, nombre, oui/non…) |
| répond **3** | liste des valeurs lues, groupées par section (⚠️ = à vérifier) |
| répond **4** | attend une nouvelle photo et relit la page |
| répond **5** (page illisible seulement) | ignore la page |
| répond autre chose | « ❌ … n'est pas une des options proposées » + menu |
| tape **annuler**, */aide*, */status* | à tout moment |
| envoie un audio / document | « type de message non supporté » |

La réponse attendue de `OUR_API_URL` est la sortie DayOne (`dayone.extract.extract_page`), brute ou dans `{"prediction": …}`. Une erreur 4xx avec `{"detail": "..."}` est relayée telle quelle à l'utilisateur. Les libellés des champs viennent de `schema/*.json`.

Le faux backend (`tests/mock_backend.py`) renvoie une vraie sortie de `outputs/predictions/` ; une légende contenant « flou » simule une page illisible.

Les conversations sont gardées en mémoire (2 h) : un redémarrage du serveur les efface.

--- | :--- |
| **Photo** | « Photo reçue, analyse en cours… », puis envoi à `OUR_API_URL` et résultat renvoyé (découpé si > 4096 caractères) |
| **/aide** | Affiche le guide d'utilisation et les commandes |
| **/status** | Indique si le service est opérationnel |
| *Texte standard* | Message d'accueil incitant à envoyer une photo |
| *Audio / Document / Autre* | Message indiquant que ce format n'est pas supporté |

---

## 🔒 Bonnes pratiques & Sécurité

- **Protection anti-rejeu & dédoublonnage** : Cache en mémoire limitant les rejets ou exécutions multiples d'un même message.
- **Réponse asynchrone** : Traitement via `BackgroundTasks` pour répondre `200 OK` sous 500 ms à Meta.
- **Zéro fuite de données** : Le token d'accès Meta et les octets bruts des photos ne sont jamais loggués dans la console. Les numéros de téléphone sont masqués (`***5678`).
- **Signature obligatoire** : sans `APP_SECRET`, toute requête POST est rejetée (401).
- **Conformité Meta 2026** : Respect strict de l'API Cloud officielle (aucun risque de bannissement de numéro lié à des bibliothèques non-officielles).
