# DayOne

Photo d'une fiche de santé maternelle → champs structurés → comparaison à une référence tapée par un humain.
Hackathon CodeML 2026, défi 17. Tout tourne en local. **Aucun gabarit** : le logiciel lit une fiche qu'il n'a jamais vue.

## Lancer

**Double-cliquer sur `DayOne.command`.** Ollama et l'interface démarrent, et le navigateur s'ouvre sur http://localhost:8501. Fermer la fenêtre noire arrête tout.

- Au premier lancement, les modèles se téléchargent une seule fois : Ollama (~3,3 Go) et PaddleOCR français/anglais/arabe (~20 Mo). Ensuite, tout marche hors ligne.
- Interface en **français ou en anglais** (choix en haut de la barre latérale). La fiche peut être en français, en arabe ou en anglais.
- Si macOS bloque le fichier : clic droit → Ouvrir → Ouvrir.

Dans l'interface :

1. Importer une photo, ou choisir une page du jeu de données.
2. Cliquer sur **Lire la fiche** (environ 1 minute).
3. Corriger dans le tableau si besoin.
4. Cliquer sur **Télécharger le résultat**.

## Tableau de bord, API et WhatsApp

Trois briques se branchent sur la lecture ci-dessus, sans la modifier :

```
WhatsApp (sage-femme) ──▶ whatsapp-bot/ ──▶ api/ ──▶ dayone.extract (lecture)
                                              │
                                              └──▶ dayone.db (chiffrée) ──▶ web/ (tableau de bord)
```

| Brique | Dossier | Lancer |
|---|---|---|
| API locale (dossiers, lecture, base) | `api/` | `.venv/bin/uvicorn api.main:app --port 8000`, puis http://localhost:8000/docs |
| Tableau de bord web | `web/` | `cd web && npm install && npm run dev` (voir [web/README.md](web/README.md)) |
| Agent WhatsApp | `whatsapp-bot/` | voir [whatsapp-bot/README.md](whatsapp-bot/README.md) (port 8001) |

- **L'API** lit les photos avec `dayone.extract` et garde les dossiers dans `dayone.db` (SQLite, créé au premier lancement, rien à installer). Les valeurs lues et les photos (`captures/`) sont chiffrées avec `.device_secure_key`. L'image affichée est la page redressée avec les zones personnelles noircies (`zones_masquees`) ; l'original n'est jamais servi. État : `/health`.
- **Rangement des champs** : la lecture n'a pas de gabarit. L'API compare les libellés lus à ceux des deux fiches de référence (`schema/*.json`) : une page qui en partage au moins 3 prend leur type (« Identification et antécédents », « Accouchement »), et chaque champ reconnu prend la clé et la section de référence (`age`, « Identification »). Les autres champs sont gardés tels quels dans « Autres champs lus ».
- **L'agent WhatsApp** : chaque photo est enregistrée dans la base dès sa réception, puis lue en arrière-plan. La sage-femme donne le code patiente (proposé s'il est lu sur la page), vérifie chaque page (confirmer, corriger, voir, reprendre la photo), puis choisit la patiente. Tout passe par l'API : le tableau de bord voit le dossier en direct.
- **Base de données** : patiente (id aléatoire + code) → visites → dossiers (une capture, son cycle de vie et son historique) → pages (photo d'origine et vue masquée chiffrées, champs lus et corrigés chiffrés, titre, erreur de lecture). À la validation, le **résultat final** approuvé est figé dans le dossier (JSON chiffré, `GET /api/records/{id}/final`, téléchargeable depuis la page du dossier sur le tableau de bord).
- **Sous Windows** : `.venv\Scripts\python -m uvicorn api.main:app --port 8000`. L'API coupe l'accélération oneDNN de Paddle (`PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT=False`), qui plante sous Windows ; la lecture marche sans Ollama (environ 40 s par page).
- **Sans PaddleOCR ni Ollama** sur la machine (démo, développement) : `DAYONE_DEMO_EXTRACT=1 .venv/bin/uvicorn api.main:app --port 8000` rejoue les sorties enregistrées dans `outputs/predictions/`. Jamais en production.

Tests : `.venv/bin/python -m pytest -q` (lecture et API), `cd whatsapp-bot && python -m pytest -q` (agent WhatsApp), `cd web && npm run build` (tableau de bord).

## Suivi d'une visite à l'autre (courbes, cohérence, rendez-vous, agrégats)

Le registre est longitudinal : la page « Grossesse actuelle » porte jusqu'à 9 visites (poids, TA, HU, BCF, examens). DayOne s'en sert à trois choses, **sans aucune logique clinique** (hors périmètre du défi : ni seuil, ni risque, ni triage).

| Brique | Où | Ce qu'elle fait |
|---|---|---|
| Tableau des visites lu colonne par colonne | `dayone/extract.py`, `dayone/imaging.py` | Les bandeaux sombres (« EXAMEN CLINIQUE ») coupaient les traits verticaux : le tableau était rejeté, toutes les valeurs sortaient « non rattachées », sans visite (BCF dans le désordre). Les morceaux de traits alignés sont recollés ; l'en-tête sur deux rangées donne « 2ème trimestre - Visite 2 » ; chaque cellule garde sa **colonne** (une visite). Poids de la mère en kg (« 58.8 » → 58 800 g, et non 59 g). « \|51/97 » (1 au stylo fin) → 151/97 si c'est la seule lecture possible. Pages de référence 2, 4, 26 : sortie identique à avant. |
| Mesures suivies | `dayone/suivi.py` | Champs → visites (date, SA, rendez-vous écrit) et valeurs (poids, TA, HU, BCF, T°, pouls, Hb, tests). Reconnaît aussi les pages post-partum (mère / nouveau-né). Une valeur sans colonne sûre n'est jamais placée. |
| Contrôles de cohérence de la **lecture** | `dayone/coherence.py` | Une valeur qui contredit le reste du registre est probablement mal lue : rendez-vous avant la visite (« 29/1/2025 » pour 29/11), dates qui reculent, SA qui ne colle pas avec la DDR, chiffre isolé loin des deux visites voisines (6 lu 8), DPA ≠ DDR + 280 j, parité > gestité, voie basse et césarienne cochées ensemble, valeur physiquement impossible (BCF 52, HU 127). Le champ lu par l'IA passe « à vérifier » avec l'explication ; l'agent WhatsApp la donne (« ↳ Rendez-vous 29/01/2025 : avant la visite du 01/11/2025 : à vérifier sur le papier »). Une correction relance les contrôles ; un champ confirmé par la sage-femme n'est plus jamais signalé. |
| Onglet « Évolution » | `web/src/components/PatientTrends.tsx` | Courbes poids / TA / HU / BCF selon la SA, poids du nouveau-né (naissance → J7 → J42), tableau des visites, examens notés. Chaque point ouvre la page du registre ; un point « à vérifier » est creux. Aucune zone de norme dessinée. |
| Onglet « Rendez-vous » et écran « Aujourd'hui » | `web/src/services/trends.ts`, `followup.ts` | Le rendez-vous **écrit** sur le registre passe avant la règle des 28 jours ; liste des rendez-vous donnés et du retard au retour (des dates, rien d'autre). |
| Agrégats anonymes (bonus du défi) | `api/aggregates.py`, `GET /api/aggregates?source=registry\|synthetic` | TA, T°, Hb, VIH / syphilis / hépatite, suivi prénatal, accouchements, complétude. Calculés sur le serveur (le navigateur ne reçoit que des comptes), valeurs sûres ou vérifiées seulement, **toute case de moins de 5 femmes masquée**. Source « synthetic » : le CSV fourni (200 femmes). |

Base de démonstration (vraies pages dev lues par le pipeline, vérifiées, rattachées ; un dossier avec une incohérence reste « à vérifier ») : `.venv/bin/python -m scripts.seed_demo --patients 1 2 3 --cache outputs/demo_cache`, puis `DAYONE_DB=demo.db DAYONE_CAPTURES=demo_captures DAYONE_KEY_FILE=.demo_key .venv/bin/uvicorn api.main:app --port 8000`. La base de travail `dayone.db` n'est pas touchée.

## Comment une fiche est lue (OCR d'abord)

| Étape | Outil | Rôle |
|---|---|---|
| 1. Redresser la photo | OpenCV | Trouve la feuille, corrige la perspective |
| 2. Lire tout le texte | PaddleOCR (processus séparé) | Chaque ligne de texte, avec sa position. 2ᵉ passe : l'encre que l'OCR n'a pas lue est découpée et relue seule (imprimé et écriture bleue à part). **Multilingue** : une ligne mal lue par le modèle latin (français, anglais) est relue par le modèle arabe ; la meilleure lecture est gardée. Presque aucun texte → refusée |
| 3. Relier valeurs et étiquettes, par la position | OpenCV + règles | Tableaux : « ligne \| colonne ». Écriture bleue non lue par l'OCR à côté d'une étiquette → champ « à vérifier » relu par le modèle. Cases : carré + encre dedans ; cases d'un même groupe → un seul champ (« Mode de la couverture = Fixe »). « Étiquette : valeur ». Écriture isolée → texte imprimé à sa gauche |
| 4. Masquer les données personnelles | Filtre + rectangles noirs | Nom, conjoint, CIN, téléphone, adresse, nom du soignant : retirés des champs et masqués en noir jusqu'au bout de la ligne. Seule l'image masquée est affichée ou envoyée au modèle |
| 5. Refuser ce qui n'est pas une fiche | Modèle (image masquée) ; sans modèle : mots médicaux et mots du registre | Pas une fiche de santé (ex. bulletin de notes) → refusée |
| 6. Relire les valeurs douteuses et les oublis | Modèle, sur un petit morceau d'image | Accord avec l'OCR → KNOWN ; désaccord ou un seul lecteur → NEEDS_REVIEW. Écriture rattachée à aucun champ : gardée, toujours NEEDS_REVIEW |
| 7. Accents absents de la page | Lexique `schema/lexique.txt` | « Commer ante » → « Commerçante » (lecture d'origine gardée) |

Les étiquettes viennent toujours du texte imprimé lu par l'OCR : le logiciel ne peut pas inventer un champ.
Environ 1 minute par page.

Modèle : `qwen3-vl:4b-instruct` via Ollama. Pour une machine à peu de mémoire, choisir `qwen3-vl:2b-instruct` dans les réglages (moins fiable).

Chaque champ sort sous la forme `{id, label, kind, value, status, confidence, source}`, plus `raison` quand il y a un doute :

| Raison | Quand |
|---|---|
| `champ_nouveau` | Étiquette dont les mots ne sont pas dans `schema/vocabulaire.txt` (« Patate ») |
| `etiquette_douteuse` | Étiquette mal lue (« 33A$A-11 ») |
| `choix_nouveau` | Case dont le nom est inconnu du registre |
| `non_rattache` | Écriture rattachée à aucun champ |
| `valeur_douteuse` | Désaccord OCR / modèle, format bizarre, un seul lecteur |

Le vocabulaire **ne sert pas à lire** : un champ inconnu est lu quand même, mais n'est jamais KNOWN. Il est généré depuis le texte **imprimé** du PDF du registre et des photos (jamais l'écriture, jamais un nom) : `.venv/bin/python -m scripts.build_vocabulary`. Les mêmes mots en **arabe et en anglais** sont dans `schema/vocabulaire_ar_en.txt` (écrit à la main). Il ne se remplit jamais tout seul ; on peut y ajouter un mot à la main.

| Statut | Quand |
|---|---|
| KNOWN | Valeur sûre pour l'OCR (bon score, bon format), ou confirmée par le modèle ; case cochée vue par OpenCV |
| NEEDS_REVIEW | Un seul lecteur, désaccord, confiance < 0,7, ou étiquette inconnue du registre / mal lue (même si la valeur est bien lue) |
| NOT_PROVIDED | Champ présent sur la fiche mais vide, ou case non cochée |
| UNKNOWN / ILLEGIBLE | « ? », « inconnu » / écrit mais illisible |

## En ligne de commande

| Je veux… | Commande |
|---|---|
| Lire une ou plusieurs photos | `.venv/bin/python -m scripts.run_extraction --image photo1.jpg photo2.jpg` |
| Lire les pages dev annotables | `.venv/bin/python -m scripts.run_extraction` |
| Créer les fichiers de référence à remplir | `.venv/bin/python -m scripts.make_annotation_templates` (voir `annotations/LISEZMOI.md`) |
| Évaluer | `.venv/bin/python -m scripts.evaluate` |
| Évaluation finale (patientes 9-10) | ajouter `--split test --final` |
| Vérifier que `data/` est intact | `.venv/bin/python -m scripts.check_integrity` |
| Tests | `.venv/bin/python -m pytest -q` |
| Regénérer le vocabulaire des étiquettes | `.venv/bin/python -m scripts.build_vocabulary` |

## Installation (si besoin)

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
# Ollama : https://ollama.com, puis
ollama pull qwen3-vl:4b-instruct
```

Les modèles PaddleOCR (détection, latin, arabe) se téléchargent au premier lancement de `DayOne.command` (ou : `.venv/bin/python -m dayone.ocr --download`) ; ensuite tout marche hors ligne.

## Règles respectées

- **100 % local** : un `OLLAMA_HOST` distant ou un modèle `*cloud*` est refusé. Les statistiques Streamlit sont coupées.
- **Aucune donnée personnelle en sortie** : filtrée par étiquette et par forme de valeur (téléphone, CIN), et masquée en noir sur l'image affichée. Le N° de fiche est gardé (code qui relie les visites), sauf s'il recopie un CIN de la page. Le texte OCR brut ne quitte jamais la mémoire.
- **Ne jamais inventer** : étiquettes prises dans le texte imprimé, valeurs douteuses relues par un second lecteur.
- **Test verrouillé** : les patientes 9 et 10 ne sont lues qu'avec `--final`.
- **Aucune logique clinique.**

## Limites connues

- Arabe : lu par un modèle OCR dédié, mais moins fiable que le français, surtout à la main et sur photo floue : beaucoup de champs restent « à vérifier ». Aucune fiche arabe dans le jeu fourni : testé sur des fiches arabes et anglaises fabriquées.
- Poids en kg converti en grammes (« 68 kg » → 68000), comme les poids de naissance du registre.

- Écriture très libre (ex. « RAS » en grand, en travers de plusieurs lignes) : souvent illisible pour les deux lecteurs → NEEDS_REVIEW.
- Tableaux très denses aux traits pâles : une partie des cellules peut manquer.
- Écriture au stylo noir : distinguée de l'imprimé seulement par la position, donc un peu moins fiable.
- Photo où l'OCR fusionne deux rangées : le masque noir peut déborder sur la rangée voisine (on préfère trop masquer).
- Fiches en tableau très libre (visites) : beaucoup d'« Écriture non rattachée », toujours à vérifier.
- L'évaluation attend les fichiers de référence remplis à la main dans `annotations/`.
