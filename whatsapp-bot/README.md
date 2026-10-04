# Agent WhatsApp DayOne

La sage-femme photographie les pages du registre sur WhatsApp, vérifie ce qui a été lu, puis choisit la patiente.
Le bot ne lit rien lui-même : il passe par l'API DayOne (`../api`), qui lit avec `dayone.extract`, garde le
dossier chiffré dans la base et le montre au tableau de bord (`../web`).

API officielle uniquement (Meta WhatsApp Cloud API) : pas de librairie non officielle, qui ferait bannir le numéro.

```
Téléphone ─▶ Meta ─▶ POST /webhook (ce bot, port 8001) ─▶ API DayOne (port 8000) ─▶ dayone.extract
    ▲                         │                                   │
    └──── réponses ◀── Meta ◀─┘                                   └─▶ dayone.db ─▶ tableau de bord
```

## Conversation

| La sage-femme… | Le bot… |
| :--- | :--- |
| envoie une ou plusieurs **photos** | « 📄 Page N reçue » + boutons *Terminé* / *Annuler* |
| appuie sur **Terminé** | demande le **code patiente** écrit sur le registre |
| donne le code | crée le dossier (`POST /api/records`), attend la lecture, présente la page 1/n |
| répond **1** | confirme la page. S'il reste des ⚠️ : les liste et demande une 2ᵉ confirmation explicite |
| répond **2** | liste numérotée des champs → numéro → nouvelle valeur (format vérifié : date, nombre, oui/non…), enregistrée dans l'API |
| répond **3** | valeurs lues, groupées par section (⚠️ = à vérifier, ✏️ = corrigé) |
| répond **4** | attend une nouvelle photo ; seule cette page est relue, les corrections des autres pages restent |
| répond **5** (page illisible) | retire la page du dossier |
| a confirmé la dernière page | valide le dossier, propose les patientes plausibles (même code, code proche…) ou la création |
| choisit la patiente | récapitulatif propre ; le dossier est « envoyé » sur le tableau de bord |
| répond autre chose | « ❌ … n'est pas une des options proposées » + le menu |
| tape **annuler**, */aide*, */status* | à tout moment (un dossier déjà créé reste « à vérifier » sur le tableau de bord) |

La sage-femme est identifiée dans la base par `wa-` + un HMAC de son numéro (avec `APP_SECRET`) : son numéro n'y est jamais écrit.
Les numéros sont masqués dans les logs (`***5678`).

## Lancer en local

1. **L'API DayOne** (à la racine du repo) : `uvicorn api.main:app --port 8000`.
   Sans PaddleOCR ni Ollama : `DAYONE_DEMO_EXTRACT=1 uvicorn api.main:app --port 8000` (rejoue des sorties enregistrées).
2. **Le bot** (dans ce dossier) :
   ```bash
   pip install -r requirements.txt
   cp .env.example .env        # puis remplir les valeurs Meta
   uvicorn app.main:app --port 8001
   ```
3. **Une URL publique** vers le port 8001 : `cloudflared tunnel --url http://localhost:8001` (ou `ngrok http 8001`).
4. **Dans Meta** (*WhatsApp → Configuration → Webhook*) : Callback URL = `https://<url-publique>/webhook`,
   Verify token = `VERIFY_TOKEN`, puis abonner le champ **messages**. Le compte WhatsApp Business doit être abonné à l'app
   (`POST /{WABA_ID}/subscribed_apps`), sinon Meta ne transmet rien.

L'URL du tunnel change à chaque redémarrage : la remettre dans Meta. Le token temporaire Meta expire après 24 h.

## Configuration (`.env`, jamais commité)

| Variable | Rôle |
| :--- | :--- |
| `WHATSAPP_TOKEN`, `PHONE_NUMBER_ID` | envoyer les messages, télécharger les photos |
| `APP_SECRET` | vérifier la signature `X-Hub-Signature-256` (obligatoire : sans lui, tout est refusé) |
| `VERIFY_TOKEN` | mot de passe choisi pour la vérification du webhook (obligatoire) |
| `DAYONE_API_URL` | API DayOne (`http://localhost:8000`) |
| `READ_TIMEOUT_PER_PAGE` | attente maximale de la lecture, par page (300 s) |

## Tests

```bash
python -m pytest -q
```

Les parcours de conversation tournent contre la **vraie API** (`../api`), lancée dans le test avec une base temporaire
et la lecture de démo : seul Meta est simulé.

## Sécurité

- Signature Meta vérifiée sur chaque POST ; réponse 200 immédiate, traitement en arrière-plan ; messages dédoublonnés.
- Ni le token, ni les photos, ni les numéros complets ne sont écrits dans les logs.
- Le bot reste centré sur le registre (Meta interdit les chatbots généralistes sur l'API Business).
