# Registre obstétrical — extraction locale

Photo d'un registre papier → JSON structuré (valeur, statut, confiance par champ), 100 % local et gratuit.
Architecture détaillée et plan : [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Démarrage rapide (sans PaddleOCR, 2 minutes)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/make_synthetic_form.py          # crée examples/synthetic_form.jpg + fake_tokens.json
.venv/bin/python -m pytest -q                            # 61 tests
REGISTRE_OCR_ENGINE=fake .venv/bin/uvicorn app.main:app --reload
```

Ouvrir http://localhost:8000 et déposer `examples/synthetic_form.jpg`.
En mode `fake`, l'OCR rejoue `examples/fake_tokens.json` quelle que soit l'image envoyée : c'est fait pour
développer le mapping, les règles et l'interface. Le contrôle qualité image, lui, est réel.

## Avec le vrai OCR (PaddleOCR)

PaddlePaddle ne supporte pas Python 3.14 : utiliser **Python 3.11**.

```bash
brew install python@3.11            # ou : pip install uv && uv venv -p 3.11 .venv-ocr
python3.11 -m venv .venv-ocr && .venv-ocr/bin/pip install -r requirements-ocr.txt
.venv-ocr/bin/uvicorn app.main:app  # 1er démarrage : téléchargement des modèles fr + ar (~quelques centaines de Mo)
```

Vérifier dans les logs que les modèles `PP-OCRv5` latin/arabe sont bien chargés.

## Second lecteur local (optionnel)

```bash
ollama serve &
ollama pull qwen2.5vl:3b            # ~3 Go ; 7b plus précis mais lent sur CPU
REGISTRE_VLM_ENABLED=true .venv-ocr/bin/uvicorn app.main:app
```

Il n'est appelé que sur les champs douteux (8 appels max par page), uniquement sur le crop du champ.

## API

| Méthode | Route      | Description |
|---------|------------|-------------|
| GET     | `/`        | Page de test : dépôt de photos, zones colorées par statut, JSON, message WhatsApp |
| GET     | `/health`  | État du moteur OCR et du VLM |
| POST    | `/extract` | `file` (image), `use_vlm` (bool, optionnel), `debug` (bool) → `ExtractionResponse` |

Exemple de sortie : [examples/sample_output.json](examples/sample_output.json).

## Évaluation et calibration

```bash
python -m eval.evaluate --csv data/reference.csv --images data/images --target 0.98
```

Le script affiche l'exactitude par champ, langue et écriture, le **taux de faux CONNU** et les seuils
`REGISTRE_TAU_KNOWN` / `REGISTRE_TAU_KNOWN_VLM_AGREE` à exporter.

## Configuration

Tous les seuils sont dans [app/settings.py](app/settings.py), surchargeables via `REGISTRE_<NOM>`.
Les champs, libellés (FR/AR/EN) et bornes de vraisemblance sont dans [app/schemas/form_spec.py](app/schemas/form_spec.py).
C'est le premier fichier à adapter quand on reçoit les vrais registres.
