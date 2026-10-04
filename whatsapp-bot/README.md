# Agent WhatsApp DayOne

La sage-femme photographie les pages du registre sur WhatsApp, vérifie ce qui a été lu, puis choisit la patiente.
Le bot ne lit rien lui-même : il passe par l'API DayOne (`../api`), qui lit avec `dayone.extract`, garde le
dossier chiffré dans la base et le montre au tableau de bord (`../web`).

API officielle uniquement (Vonage Messages API, fournisseur officiel de WhatsApp Business) : pas de librairie
non officielle, qui ferait bannir le numéro.

```
Téléphone ─▶ Vonage ─▶ POST /webhooks/inbound (ce bot, port 8001) ─▶ API DayOne (port 8000) ─▶ dayone.extract
    ▲                             │                                          │
    └──── réponses ◀── Vonage ◀───┘ (POST /v1/messages)                      └─▶ dayone.db ─▶ tableau de bord
```

## Conversation

| La sage-femme… | Le bot… |
| :--- | :--- |
| envoie une **photo** | l'envoie **tout de suite** à l'API : enregistrée (chiffrée) dans la base, lue en arrière-plan. 1re photo = création du dossier (`POST /api/records`), suivantes = ajout (`POST /api/records/{id}/pages`). « 📄 Page N reçue et enregistrée » + boutons *Terminé* / *Annuler* |
| appuie sur **Terminé** | attend la fin de la lecture, puis demande le **code patiente** (si un « N° de fiche » a été lu sur la page, il est proposé : *1* pour le garder) |
| donne le code | l'enregistre (`POST /api/records/{id}/code`), présente la page 1/n |
| répond **1** | confirme la page. S'il reste des ⚠️ : les liste et demande une 2ᵉ confirmation explicite |
| répond **2** | liste numérotée des champs → numéro → nouvelle valeur (format vérifié : date, nombre, oui/non…), enregistrée dans l'API |
| répond **3** | valeurs lues, groupées par section (⚠️ = à vérifier, ✏️ = corrigé) |
| répond **4** | attend une nouvelle photo ; seule cette page est relue, les corrections des autres pages restent |
| répond **5** (page illisible) | retire la page du dossier |
| a confirmé la dernière page | valide le dossier : l'API **fige et stocke le résultat final** (JSON chiffré). Puis propose les patientes plausibles (même code, code proche…) ou la création |
| choisit la patiente | le résultat final est complété (patiente, visite) ; le bot envoie le récapitulatif **tiré de ce résultat final** (`GET /api/records/{id}/final`) |
| répond autre chose | « ❌ … n'est pas une des options proposées » + le menu |
| tape **annuler**, */aide*, */status* | à tout moment (un dossier déjà créé reste « à vérifier » sur le tableau de bord) |

La sage-femme est identifiée dans la base par `wa-` + un HMAC de son numéro (avec `MIDWIFE_ID_SECRET`) : son numéro n'y est jamais écrit.
Les numéros sont masqués dans les logs (`***5678`).

## Lancer en local

1. **L'API DayOne** (à la racine du repo) : `uvicorn api.main:app --port 8000`.
   Sans PaddleOCR ni Ollama : `DAYONE_DEMO_EXTRACT=1 uvicorn api.main:app --port 8000` (rejoue des sorties enregistrées).
2. **Le bot** (dans ce dossier) :
   ```bash
   pip install -r requirements.txt
   cp .env.example .env        # puis remplir les valeurs Vonage
   uvicorn app.main:app --port 8001
   ```
3. **Une URL publique** vers le port 8001 : `cloudflared tunnel --url http://localhost:8001` (ou `ngrok http 8001`).
4. **Dans Vonage** :
   - **Sandbox** (`VONAGE_SANDBOX=true`) : *Developer Tools → Messages Sandbox*. Envoyer depuis son téléphone le message
     indiqué au numéro du sandbox (sinon Vonage n'écrit pas à ce numéro), puis renseigner
     Inbound = `https://<url-publique>/webhooks/inbound` et Status = `https://<url-publique>/webhooks/status`.
   - **Production** (`VONAGE_SANDBOX=false`) : une application Vonage avec la capacité *Messages*, mêmes URL Inbound et
     Status, et le numéro WhatsApp Business relié à cette application.

L'URL du tunnel change à chaque redémarrage : la remettre dans Vonage. Le sandbox est limité (1 message/s, quota mensuel).

## Configuration (`.env`, jamais commité)

| Variable | Rôle |
| :--- | :--- |
| `VONAGE_API_KEY`, `VONAGE_API_SECRET` | envoyer les messages (Basic auth sur l'API Messages) |
| `VONAGE_SIGNATURE_SECRET` | vérifier le JWT signé par Vonage sur chaque webhook (obligatoire : sans lui, tout est refusé) |
| `VONAGE_WHATSAPP_NUMBER` | numéro WhatsApp d'envoi (celui du sandbox, ou le numéro Business), sans `+` |
| `VONAGE_SANDBOX` | `true` : API du sandbox ; `false` : production (`VONAGE_API_HOST`, `https://api.nexmo.com` par défaut) |
| `MIDWIFE_ID_SECRET` | clé du HMAC qui identifie la sage-femme ; la changer change ses identifiants |
| `DAYONE_API_URL` | API DayOne (`http://localhost:8000`) |
| `READ_TIMEOUT_PER_PAGE` | attente maximale de la lecture, par page (300 s) |

## Tests

```bash
python -m pytest -q
```

Les parcours de conversation tournent contre la **vraie API** (`../api`), lancée dans le test avec une base temporaire
et la lecture de démo : seul Vonage est simulé.

## Sécurité

- Signature Vonage vérifiée sur chaque POST : JWT HS256 dans `Authorization`, dont le `payload_hash` doit correspondre
  au corps reçu, émis il y a moins d'une heure. Réponse 200 immédiate, traitement en arrière-plan ; messages dédoublonnés.
- Les photos sont téléchargées depuis l'URL Vonage (gardée 48 h), sans envoyer d'identifiants. Avec « Enhanced Inbound
  Media Security » activé sur l'application Vonage, ce téléchargement est refusé (le bot ne sait pas encore signer cet accès).
- Les refus d'envoi (numéro non autorisé, message rejeté par WhatsApp…) arrivent sur `/webhooks/status` et sont journalisés.
- Ni les secrets, ni les photos, ni les numéros complets ne sont écrits dans les logs.
- Le bot reste centré sur le registre (WhatsApp interdit les chatbots généralistes sur l'API Business).
