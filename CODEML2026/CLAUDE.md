# CODEML2026 — digitalisation des registres obstétricaux (hackathon)

Photo d'un registre papier → JSON (valeur, statut, confiance par champ), 100 % local, coût 0 $.
Architecture complète et décisions : `docs/ARCHITECTURE.md`. Démarrage : `README.md`.

## Contraintes non négociables
- Aucune API payante, aucun envoi de données patientes à un tiers ; tout tourne en local.
- Statuts : CONNU, INCONNU, NON_FOURNI, ILLISIBLE, NON_APPLICABLE, A_REVISER. Dans le doute → A_REVISER.
- Jamais stocker nom, téléphone, adresse, CIN, conjoint, date de naissance (liste blanche de champs + zones + regex).
- Les règles de vraisemblance détectent des erreurs d'extraction, jamais de diagnostic ni de triage.
- Le VLM local (Ollama/Qwen2.5-VL) transcrit un crop ; Python parse. Il ne voit pas la lecture OCR. Une valeur
  lue seulement par le VLM n'est jamais CONNU. Sa confiance n'est jamais utilisée.
- Le message à la sage-femme ne montre jamais le JSON brut.

## État (3 oct. 2026)
- Fait : prétraitement OpenCV, wrapper PaddleOCR 3.x (+ moteur fake), mapping formulaire/tableau par bboxes,
  parseurs, statuts, confiance, redaction, rendu du message, `/extract`, page de test `/`, `eval/evaluate.py`,
  61 tests (`.venv/bin/python -m pytest -q`).
- Le serveur tourne en mode fake : `REGISTRE_OCR_ENGINE=fake .venv/bin/uvicorn app.main:app --port 8000`.
- Dataset du hackathon copié dans `data/` (130 images `Paper Registry/`, `maternal_registry_synthetic.csv`,
  consignes + dossier technique en PDF). Pas encore analysé.

## Prochaines étapes (demandées par l'utilisateur)
1. Installer Python 3.11 (`brew install python@3.11` ; la machine n'a que 3.14, incompatible avec PaddlePaddle),
   créer `.venv-ocr` avec `requirements-ocr.txt`, valider PaddleOCR fr + ar sur quelques images.
2. Lire `data/consignes-fr-en.pdf`, `data/dossier-technique.pdf`, le CSV et des images ; adapter
   `app/schemas/form_spec.py` (libellés réels, champs, mise en page fixe → envisager le recalage sur gabarit).
3. Adapter `COLS` dans `eval/evaluate.py` au CSV, lancer l'éval, calibrer `REGISTRE_TAU_KNOWN`.
4. V2 : file offline SQLite (`app/offline/`, schéma dans ARCHITECTURE §9) + liaison patiente
   (`app/patient_linking/`, §10) + dialogue Confirmer/Corriger.

## Conventions
- Code et commentaires en français, réponses à l'utilisateur en français.
- Seuils dans `app/settings.py` (env `REGISTRE_*`), à calibrer sur le dataset, pas à l'intuition.
- Machine : macOS arm64, Python 3.14 système, OpenCV 5 (HoughLinesP renvoie (N,4) : utiliser `reshape(-1, 4)`).
