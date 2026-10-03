# Architecture — digitalisation des registres obstétricaux

> Principe directeur : **le système préfère dire « je ne sais pas » plutôt que se tromper.**
> Un faux `CONNU` coûte plus cher qu'un `A_REVISER` : c'est la métrique qu'on optimise.

## 0. Vue d'ensemble

```
PHOTO (téléphone)
  │
  ▼
[1] Contrôle qualité + prétraitement OpenCV ──► REJET immédiat (flou, sombre, surexposé) → « reprenez la photo »
  │  page → perspective → inclinaison → CLAHE
  ▼
[2] PaddleOCR (fr = modèle latin, + ar) ──► tokens {texte, bbox, confiance}
  │
  ▼
[3] Mapping géométrique vers le SCHÉMA (form_spec.py)
  │  libellés FR/AR/EN → zones de valeur (droite / gauche si arabe / dessous / cellule de tableau)
  │  zones nominatives (Nom, Tél, CIN...) → exclues + noircies
  ▼
[4] Parseurs Python déterministes + vraisemblance (erreur d'extraction uniquement)
  │
  ▼
[5] Statut + confiance (règles explicites)
  │        └── si douteux ET budget ──► [5b] VLM local sur le CROP (transcription seulement)
  │                                       └─ reparsé par les MÊMES parseurs, comparé à l'OCR
  ▼
[6] Redaction (liste blanche + regex) → JSON final
  │
  ▼
[7] Message lisible (WhatsApp / interface simulée) ── Confirmer / Corriger / Reprendre la photo
  │
  ▼
[8] File offline SQLite → liaison patiente → ENREGISTRE → SYNCHRONISE
```

| Étape | Module | État |
|---|---|---|
| 1 | `app/vision/preprocess.py` | ✅ |
| 2 | `app/ocr/engine.py`, `app/ocr/types.py` | ✅ (testé en mode fake ; Paddle à valider en Python 3.11) |
| 3 | `app/mapping/labels.py`, `app/mapping/mapper.py` | ✅ formulaire + tableau |
| 4 | `app/validators/` | ✅ |
| 5 | `app/scoring/confidence.py`, `app/scoring/status.py` | ✅ |
| 5b | `app/vlm/ollama_client.py` | ✅ (à tester avec Ollama) |
| 6 | `app/privacy/redact.py` | ✅ |
| 7 | `app/messaging/render.py` | ✅ rendu ; dialogue = V2 |
| 8 | `app/offline/`, `app/patient_linking/` | 📝 conçu ici, à implémenter (V2) |

### Ce que je change dans l'architecture proposée (et pourquoi)

1. **Le VLM ne produit jamais la valeur finale.** Il *transcrit* un crop ; Python parse. Sinon impossible de garantir
   le format, et la comparaison avec l'OCR n'aurait pas de sens.
2. **On ne montre pas la lecture OCR au VLM.** Sinon il la recopie (biais d'ancrage) et « l'accord » ne vaut rien.
3. **Une valeur proposée par le VLM seul n'est jamais CONNU.** Elle est pré-remplie en `A_REVISER` : la sage-femme
   confirme d'un tap. Même ergonomie, zéro risque d'invention silencieuse.
4. **Pas de vrai WhatsApp pour la démo.** WhatsApp Business API = passage par Meta (tiers), vérification business,
   délais. Interface simulée + adaptateur de canal ; le vrai canal se branche plus tard derrière la même interface.
5. **SQLite d'abord, SQLCipher ensuite.** `sqlcipher3` s'installe mal sur macOS ARM. MVP = SQLite (WAL) + photos chiffrées
   avec `cryptography.Fernet` ; SQLCipher en V2, avec le même schéma.
6. **Si les registres ont une mise en page fixe** (probable : un modèle imprimé par le ministère), le plus robuste est
   le **recalage sur gabarit** : homographie (ORB + RANSAC) vers une image de référence, puis zones de champs en
   coordonnées fixes. C'est le V2 le plus rentable une fois le dataset vu. Le mapping par libellés actuel reste le repli
   pour les mises en page inconnues.
7. **PaddleOCR est faible sur le manuscrit.** C'est exactement là que le VLM est utile : il est déclenché par la
   confiance OCR basse ou par « encre présente mais rien lu ».

---

## 1. Prétraitement image (`app/vision/preprocess.py`)

| Étape | Méthode | Seuil par défaut (à calibrer) |
|---|---|---|
| Netteté | variance du Laplacien sur une version 1000 px | `< 35` rejet, `< 90` qualité MOYENNE |
| Sombre | luminosité moyenne | `< 45` rejet |
| Surexposé | 1er percentile de gris (il ne reste plus d'encre sombre) | `> 150` rejet |
| Contraste | plage dynamique p99 − p1 | `< 60` rejet |
| Page | Canny → plus grand contour convexe à 4 coins, ≥ 25 % de l'image | sinon test « papier plein cadre » |
| Perspective | `getPerspectiveTransform` + `warpPerspective` | — |
| Rotation 90/180° | classifieur d'orientation intégré à PaddleOCR | — |
| Inclinaison fine | médiane des angles HoughLinesP (lignes du registre) | corrigée si 0,5° < \|a\| ≤ 15° |
| Contraste | CLAHE sur le canal L (LAB) | — |
| Débruitage | `fastNlMeansDenoisingColored` | désactivé (lent, peu utile pour Paddle) |
| Encre | ombres compensées (division par fond flouté) + Otsu − lignes horizontales/verticales | sert à NON_FOURNI vs ILLISIBLE |

- PaddleOCR reçoit l'image **couleur améliorée**, pas binarisée : la binarisation dégrade la reconnaissance.
- **Refus avant OCR** : statut `REJETEE` → réponse immédiate avec un conseil précis (« tenez le téléphone immobile… »).
- **Refus après OCR** (page masquée ou mal cadrée) : moins de 30 % des champs attendus localisés → `needs_retake`.
- Calibrer les seuils : prendre ~30 photos du dataset, les classer à la main en exploitable / non exploitable, et
  choisir le seuil de netteté qui sépare les deux groupes.

## 2. PaddleOCR (`app/ocr/engine.py`)

- **Version** : PaddleOCR ≥ 3.1 (PP-OCRv5). `lang="fr"` charge le modèle **latin** (couvre aussi l'anglais),
  `lang="ar"` le modèle arabe. Aucun modèle ne lit à la fois le latin et l'arabe : on lance les deux et on fusionne
  boîte par boîte (IoU ≥ 0,5), en gardant la lecture la plus confiante.
- **Paramètres clés** : `use_doc_orientation_classify=True`, `use_doc_unwarping=False` (OpenCV s'en charge),
  `use_textline_orientation=True`, `text_rec_score_thresh=0.0`. On **garde** les lectures peu sûres : elles
  servent à distinguer ILLISIBLE de NON_FOURNI.
- **Piège** : si Paddle pivote l'image, les bboxes sont dans le repère pivoté. On récupère
  `doc_preprocessor_res.output_img` comme image de référence (mesure d'encre, crops VLM).
- **Structure** (`app/ocr/types.py`) : `OCRToken(text, confidence, bbox: BBox, script, engine)` et
  `OCRPage(tokens, width, height)`. `BBox` fournit `v_overlap`, `h_overlap`, `iou`, `union`.
- **Moteur fake** : rejoue un JSON de tokens. Toute l'équipe peut travailler sur le mapping sans Paddle.
- Chiffres arabes orientaux (٠١٢…) et persans (۰۱۲…) → ASCII dans `normalize.py`.
- Limite connue : selon la version, le texte arabe peut sortir en ordre visuel inversé. À vérifier sur 2–3 images ;
  si c'est le cas, inverser les tokens `script == "arabic"` dans `_run_one`.

## 3. Mapping vers le schéma (`app/mapping/`)

Le schéma (`form_spec.py`) déclare pour chaque champ : type, **libellés FR/AR/EN et abréviations** (TA, HU, BCF, GS,
VB…), unité, bornes. Les composites (`TA 120/80`, `O+`, `G3P2`) produisent plusieurs champs de sortie.

**Détection des libellés** (`labels.py`), du plus fiable au moins fiable :
1. préfixe exact après normalisation : `Poids : 68 kg` → libellé `poids` + valeur inline `68 kg` ;
   les alias longs sont testés d'abord (`tension` avant `t`), et `G3P2` n'est pas pris pour le libellé `g` ;
2. `68 : الوزن` → formulaire arabe, libellé à droite ;
3. correspondance floue (rapidfuzz ≥ 85) pour les libellés de 5 caractères ou plus (`Temperatnre`).

**Choix de la mise en page** : une ligne contenant ≥ 3 libellés distincts sans valeur à côté = **en-tête de tableau**
(registre). Sinon : **formulaire**.

**Formulaire** — pour chaque libellé :
- valeur inline → localisation `inline` ;
- sinon tokens **sur la même ligne** (recouvrement vertical ≥ 50 %) **à droite** (à gauche si le libellé est en arabe),
  jusqu'au prochain libellé de la ligne → `droite` ;
- sinon le token juste **dessous** (recouvrement horizontal ≥ 30 %, à moins de 2,5 hauteurs de ligne) → `dessous` ;
- un token ne sert qu'à un seul champ ;
- repli par **motif** sans libellé (`G3P2`, `120/80`, `32 SA`), seulement si un unique token correspond → `motif`.

**Tableau** — colonnes = intervalles x entre les milieux des en-têtes ; lignes = regroupement des tokens par
recouvrement vertical ; chaque cellule (même vide) donne un candidat avec sa zone. Une colonne absente du registre
donne `NON_FOURNI` / `absent_du_registre`, pas une alerte.

**Sortie du mapper** : des candidats `{texte brut, tokens, localisation, zone}`. Aucune interprétation à ce stade.

## 4. Score de confiance (`app/scoring/confidence.py`)

```
score = c_ocr × f_qualité × f_localisation × f_validation
```

| Facteur | Valeur | Justification |
|---|---|---|
| `c_ocr` | **min** des confiances PaddleOCR des tokens | un seul chiffre douteux rend la valeur douteuse |
| `f_qualité` | 1,0 BONNE / 0,9 MOYENNE | une image moyenne augmente les erreurs non détectées |
| `f_localisation` | 1,0 inline / droite / cellule, 0,95 dessous, 0,85 motif ; × score du libellé si flou | plus le rattachement est indirect, plus le risque de mauvais champ augmente |
| `f_validation` | 0,8 par avertissement (2 au plus) | virgule supposée, cmHg converti, valeur inhabituelle, caractère corrigé |

- **Le VLM ne modifie pas le score.** L'accord est un signal binaire qui abaisse le seuil
  (`tau_known_vlm_agree`) ; le désaccord force `A_REVISER`. Aucune confiance auto-déclarée par un LLM n'est utilisée.
- Les facteurs sont renvoyés dans `signals` pour l'audit (« pourquoi à vérifier ? »).
- Pour les statuts sans valeur (NON_FOURNI, ILLISIBLE), la confiance exprime la confiance **dans le statut**
  (qualité × localisation).
- **Calibration** (`eval/evaluate.py`) : sur le jeu de dev, pour chaque seuil t, mesurer la précision des valeurs
  avec `score ≥ t`. `tau_known` = plus petit t où la précision ≥ 98 % (cible à discuter avec le jury). Même calcul
  séparé pour le sous-ensemble « accord VLM ». `tau_illegible` = sous ce score, les valeurs sont justes moins d'une
  fois sur trois.
- Ce score n'est **pas** une probabilité. Bonus : régression isotone score → précision observée, pour afficher
  « 97 % des valeurs à ce niveau étaient justes sur le jeu de dev ».

## 5. VLM local (`app/vlm/ollama_client.py`)

**Quand le déclencher** : seulement si la règle a donné `A_REVISER` ou `ILLISIBLE`, que le champ est localisé
(on connaît la zone), que `send_to_vlm` est vrai (pas pour le texte libre) et qu'il reste du budget
(8 appels par page). Concrètement : confiance OCR basse, encre sans lecture, format non reconnu, valeur impossible.

**Ce qu'on lui envoie** : le **crop** de la zone (un peu de marge pour inclure le libellé, agrandi à 64 px de haut
minimum), le nom du champ et le format attendu (« deux nombres séparés par / »). Ni la page, ni la lecture OCR,
ni d'autres champs.

**Sortie stricte** : `format` = schéma JSON (structured outputs d'Ollama), `temperature: 0`, `num_predict: 64` :
```json
{"transcription": "12/8", "legible": true, "empty": false}
```

**Anti-invention** :
- consigne « copie exactement, ne devine jamais ; au moindre doute legible=false » ;
- validation Pydantic (longueur ≤ 60 caractères), toute erreur → lecture ignorée ;
- la transcription repasse par **les mêmes parseurs** que l'OCR ;
- `legible=false` → lecture ignorée.

**Comparaison** (après parsing) :

| OCR | VLM | Résultat |
|---|---|---|
| valide | même valeur | seuil abaissé, source `ocr+vlm` → souvent CONNU |
| valide | autre valeur | `A_REVISER`, valeur OCR + alternative VLM affichées |
| rien / invalide | valide | `A_REVISER`, valeur VLM pré-remplie, confiance 0, source `vlm` |
| rien | illisible / vide | inchangé (ILLISIBLE / NON_FOURNI) |

Modèle : `qwen2.5vl:3b` par défaut (CPU : ~5–20 s par crop). `7b` si GPU. Le nom est configurable
(`REGISTRE_VLM_MODEL`) : tester aussi les VLM plus récents disponibles dans `ollama list`.

## 6. Statuts (`app/scoring/status.py`)

Table de décision évaluée dans cet ordre :

| # | Condition | Statut |
|---|---|---|
| 0 | libellé introuvable | `A_REVISER` (`champ_non_localise`), ou `NON_FOURNI` si la colonne n'existe pas dans le registre |
| 1 | zone sans encre | `NON_FOURNI` |
| 2 | encre mais aucune lecture | `ILLISIBLE` (ou `A_REVISER` si le VLM propose) |
| 3 | « inconnu », « ? », « NSP », « غير معروف » | `INCONNU` |
| 4 | « N/A », « sans objet », « لا ينطبق » | `NON_APPLICABLE` |
| 5 | « non fait » | `NON_FOURNI` (`examen_non_fait`) |
| 6 | texte non interprétable | `ILLISIBLE` si score < τ_illisible, sinon `A_REVISER` ; « - » ou « / » seul → `A_REVISER` (`tiret_ambigu`) |
| 7 | valeur hors bornes physiques | `A_REVISER` |
| 8 | VLM en désaccord | `A_REVISER` |
| 9 | VLM seul | `A_REVISER` |
| 10 | texte libre (complications) | `A_REVISER`, sauf « RAS » / « néant » |
| 11 | score ≥ seuil | `CONNU` ; score < τ_illisible → `ILLISIBLE` ; sinon `A_REVISER` |

Puis contrôles **inter-champs** (systolique > diastolique, parité ≤ gestité) : en cas d'incohérence, les deux champs
passent en `A_REVISER`.

`NON_APPLICABLE` par règle métier (ex. champs d'accouchement sur une fiche de consultation prénatale) : à ajouter
une fois le type de document connu. Rien n'est inféré à partir de la clinique.

Format d'un champ :
```json
{"value": 68.0, "status": "CONNU", "confidence": 0.97, "source": "ocr", "raw_text": "68 kg",
 "reasons": [], "alternatives": [], "signals": {"ocr": 0.97, "quality": 1.0, "localisation": 1.0,
 "validation": 1.0, "vlm_agreement": null}, "bbox": [440, 332, 530, 376]}
```

## 7. Validation Python (`app/validators/`)

- `normalize.py` : NFKC, chiffres arabes → ASCII, accents latins retirés, diacritiques arabes retirés, `أإآ → ا`.
- `parsers.py` : nombres et unités (`68 kg`, `68,5`, `٦٨ كغ`), virgule oubliée (`375` → 37,5 **avec avertissement**),
  tension (`120/80`, `12/8` → 120/80 avertissement cmHg), sérologies (`NEG`, `négatif`, `negative`, `سلبي`, `-`
  avec avertissement « symbole »), groupe + rhésus (`O+`, `AB Rh-`, `0+` → O avec avertissement), âge gestationnel
  (`32 SA`, `32SA+3j`, `32+3` ; les mois sont refusés car la conversion serait une interprétation), dates
  (jj/mm/aaaa, aaaa-mm-jj, pas dans le futur, pas avant 2000), G/P (`G3P2`, `3/2`), modes d'accouchement FR/AR/EN.
- `plausibility.py` : bornes **dures** (impossible physiquement → erreur d'extraction) et **souples** (rare →
  avertissement). **Aucun diagnostic, aucun triage, aucune recommandation** : une TA à 190 n'est pas « grave »
  pour le système, elle est « à relire ».

## 8. Confidentialité (`app/privacy/redact.py`)

1. **Liste blanche** : seuls les champs de `OUTPUT_FIELDS` existent. Aucun champ nom ou téléphone n'existe, il est
   donc impossible d'en persister un par erreur. Les tokens OCR bruts ne sont **jamais** stockés ni journalisés.
2. **Zones** : les libellés nominatifs (`Nom`, `Prénom`, `Tél`, `CIN`, `Adresse`, `Époux`, `Date de naissance`,
   `الاسم`, `العنوان`, `الهاتف`, `رقم البطاقة`, `الزوج`…) sont reconnus, leur valeur est consommée sans être extraite,
   et la zone est noircie sur toute image conservée ou renvoyée.
3. **Regex** (filet de sécurité) sur `raw_text` et le texte libre : téléphones, suites de 9 chiffres ou plus,
   CIN (`AB123456`), emails, « Mme X ».
4. **Photo** : chiffrée (Fernet) dans la file offline, **supprimée** à l'état `VALIDE` (le registre papier fait foi).
5. **Code patiente** : pseudonyme fourni par la sage-femme, stocké en local uniquement.

## 9. Offline-first (V2, `app/offline/`)

```sql
PRAGMA journal_mode=WAL;            -- écriture atomique, lecture concurrente
CREATE TABLE jobs (
  id TEXT PRIMARY KEY,              -- UUID généré CÔTÉ CLIENT → rejouable sans doublon (idempotence)
  state TEXT NOT NULL CHECK (state IN ('CAPTURE','EN_ATTENTE_IA','TRAITE_IA','A_REVISER','VALIDE',
                                       'PATIENTE_LIEE','ENREGISTRE','SYNCHRONISE','ECHEC')),
  photo_path TEXT,                  -- fichier chiffré, supprimé après VALIDE
  extraction_json TEXT,             -- ExtractionResponse SANS debug
  validated_json TEXT,              -- après corrections de la sage-femme
  patient_id TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  next_attempt_at TEXT,
  last_error TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE job_events (job_id TEXT, from_state TEXT, to_state TEXT, at TEXT, actor TEXT);  -- audit
CREATE TABLE patients (id TEXT PRIMARY KEY, code TEXT NOT NULL, age INTEGER, gestite INTEGER, parite INTEGER,
                       ddr TEXT, created_at TEXT);   -- aucun identifiant direct
CREATE INDEX idx_jobs_state ON jobs(state, next_attempt_at);
```

- **Pas de perte** : la photo est écrite (tmp → fsync → rename) **avant** la réponse « reçu » ; l'état `CAPTURE` est
  committé dans la même transaction.
- **Worker** : boucle qui prend `EN_ATTENTE_IA` avec `next_attempt_at <= now`, en une transaction
  `UPDATE … WHERE state = ?` (compare-and-set). En cas d'erreur, backoff exponentiel `30 s × 2^attempts`, et `ECHEC`
  après 5 tentatives (saisie manuelle proposée).
- Transitions autorisées, codées en dur dans un dict, et chacune tracée dans `job_events`.
- `SYNCHRONISE` : rejouable grâce à l'UUID ; la synchronisation n'envoie que `validated_json` et `patients`.

## 10. Liaison patiente (V2, `app/patient_linking/`)

1. La sage-femme donne le **code** (numéro du registre). Correspondance exacte → candidate forte.
2. Candidates proches : code à distance d'édition ≤ 1 (faute de frappe), et cohérence âge (±1 an), gestité/parité,
   DDR (±14 jours).
3. Score = critères concordants ; **aucune création automatique** dès qu'une candidate plausible existe.
4. Message :
   ```
   Cette fiche correspond-elle à :
   1. Patiente P-0142 — 28 ans, G3P2, DDR 02/09/2025
   2. Patiente P-0124 — 29 ans, G3P2
   3. Aucune, créer une nouvelle patiente
   4. Je ne sais pas (la fiche reste en attente)
   ```
5. « Je ne sais pas » → le job reste `VALIDE` non lié et revient dans la liste des fiches en attente.

## 11. Conversation (`app/messaging/render.py`)

```
J'ai extrait :
✅ Poids : 68 kg
⚠️ TA : 120/80 mmHg ? (à vérifier)
⚠️ Température : 37,5 °C ? (à vérifier)
❓ Hauteur utérine : illisible
➖ BCF : non renseigné

4 champ(s) à vérifier. Le registre papier fait foi.
[Confirmer]   [Corriger]   [Reprendre la photo]
```

- **Corriger** : le bot demande les champs `⚠️` / `❓` un par un (« Température ? Répondez avec la valeur, ou
  *passer* »). Chaque réponse passe par le même parseur, et une valeur saisie devient `source: manuel`, `CONNU`.
- **Photo rejetée** : conseil précis (flou, lumière, cadrage) + « saisir à la main ».
- Machine à états de dialogue simple (V2) : `ATTENTE_PHOTO → RESULTAT → CORRECTION(champ) → LIAISON → FIN`.
- Canal : interface simulée (page web façon WhatsApp). Un adaptateur `Channel.send(text, buttons)` permettra de
  brancher un vrai canal plus tard.

## 12. Évaluation (`eval/evaluate.py`)

| Métrique | Définition |
|---|---|
| Exactitude champ | statut identique ET valeur identique (après parsing des deux côtés) |
| Exactitude statut | matrice de confusion référence → prédiction |
| Exactitude valeur | parmi les références avec valeur, même si la prédiction est `A_REVISER` |
| Numériques | exactes (tolérance : T° ±0,1, poids ±0,5, AG ±0,5) + erreur absolue moyenne |
| Taux A_REVISER | charge de relecture pour la sage-femme |
| **Taux de faux CONNU** | CONNU alors que la valeur est fausse ou absente : **la métrique de sécurité** |
| Automatisation | CONNU et juste / références avec valeur |
| Par langue / écriture / champ | colonnes `langue`, `ecriture` du CSV (sinon annoter ~50 lignes à la main) |

À présenter au jury comme un compromis : « à 0,5 % de faux CONNU, on automatise X % des champs ».

## 13. Structure du projet

```
registre-ocr/
├── app/
│   ├── main.py                 # FastAPI : /, /health, /extract
│   ├── pipeline.py             # orchestration
│   ├── settings.py             # seuils (env REGISTRE_*)
│   ├── schemas/  models.py (Pydantic), form_spec.py (champs, libellés, bornes)
│   ├── vision/   preprocess.py
│   ├── ocr/      types.py, engine.py (Paddle + fake)
│   ├── mapping/  labels.py, mapper.py
│   ├── validators/ normalize.py, parsers.py, plausibility.py
│   ├── scoring/  confidence.py, status.py
│   ├── vlm/      ollama_client.py
│   ├── privacy/  redact.py
│   ├── messaging/ render.py
│   ├── static/   index.html    # page de test
│   ├── offline/                # V2
│   └── patient_linking/        # V2
├── eval/evaluate.py
├── scripts/make_synthetic_form.py
├── examples/                   # image synthétique, tokens fake, sample_output.json
├── tests/                      # 61 tests, sans Paddle
└── docs/ARCHITECTURE.md
```

## 14. Stack

| Brique | Choix | Remarque |
|---|---|---|
| Langage | Python **3.11** | PaddlePaddle n'a pas de build pour 3.14 |
| API | FastAPI + Uvicorn | endpoints synchrones (CPU) → threadpool ; verrou autour de l'OCR |
| OCR | PaddleOCR 3.x (PP-OCRv5 latin + arabe) | Apache-2.0 |
| Vision | OpenCV | |
| Matching flou | **rapidfuzz** (ajout) | MIT, rapide |
| Modèles | Pydantic v2 | |
| VLM | Ollama + Qwen2.5-VL 3B | uniquement sur des crops, avec un budget par page |
| Stockage | SQLite WAL → SQLCipher | + `cryptography` pour les photos |
| Front démo | HTML statique servi par FastAPI | pas de framework, pas de build |

À éviter pendant le hackathon : fine-tuning OCR, LangChain, base vectorielle, React, Docker multi-services.

## 15. Plan d'implémentation

**MVP (J1 — démo fiable)** ✅ en grande partie fait
1. ✅ Schéma, parseurs, statuts, confiance, mapping formulaire + tableau, API, page de test, tests.
2. ⏳ Installer Python 3.11 + PaddleOCR, passer 10 images du dataset, **adapter `form_spec.py`** (libellés réels).
3. ⏳ Lancer `eval/evaluate.py` sur le CSV, regarder les erreurs champ par champ, calibrer `tau_known`.
4. ⏳ Créer 3 images de démo : une parfaite, une floue (rejet), une avec des champs douteux.

**V2 (J2)**
5. VLM Ollama activé et mesuré : son apport sur le taux d'automatisation **à faux CONNU constant**.
6. File offline SQLite + worker + retries.
7. Dialogue Confirmer / Corriger champ par champ dans la page simulée.
8. Liaison patiente par code.
9. Recalage sur gabarit si le formulaire est fixe (gros gain de robustesse).

**Bonus**
10. SQLCipher, calibration isotone, surlignage de la zone à vérifier dans le message, vocal (Whisper local) pour la
    correction, vrai canal WhatsApp derrière l'adaptateur.

## 16. Risques et parades

| Risque | Parade |
|---|---|
| PaddleOCR rate le manuscrit | VLM sur le crop + `A_REVISER` par défaut |
| Libellés du dataset différents | tout est dans `form_spec.py` ; ajouter des alias prend 5 minutes |
| Paddle lent sur CPU | `max_image_side=2000`, modèles mobiles, chargement au démarrage |
| VLM lent | 8 appels max par page, crops seulement, désactivable |
| Démo qui plante | mode `fake` + image synthétique : la démo tourne sans aucun modèle |
