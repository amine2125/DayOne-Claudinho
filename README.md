# DayOne — V1

Photo d'une page du registre de santé maternelle → champs structurés → comparaison à une référence tapée par un humain.
Hackathon CodeML 2026, défi 17. Tout tourne en local.

## Ce que fait le logiciel

| Étape | Outil | Résultat |
|---|---|---|
| 1. Aligner la photo sur le gabarit de la page | OpenCV | page redressée, type de page détecté |
| 2. Lire les cases cochées | OpenCV (part d'encre dans la case) | `true` ou NOT_PROVIDED |
| 3. Repérer les zones vides | OpenCV (encre bleue ou noire hors imprimé) | NOT_PROVIDED |
| 4. Lire les zones écrites | PaddleOCR (processus séparé) | valeur + score |
| 5. Relire les zones douteuses | `qwen3-vl:2b-instruct` via Ollama | accord → KNOWN, sinon NEEDS_REVIEW |
| 6. Remettre les lettres accentuées absentes | lexique `schema/lexique.txt` | « Commer ante » → « Commerçante » (lecture d'origine gardée) |
| 7. Comparer à la référence | `scripts.evaluate` | exactitude, erreurs silencieuses |

Pages traitées : **Identification et antécédents** (79 champs) et **Déroulement de l'accouchement** (34 champs). Les champs sont listés dans `schema/*.json`.

Chaque champ sort sous la forme `{"value", "status", "confidence"}`. Les statuts possibles sont KNOWN, UNKNOWN, NOT_PROVIDED, ILLEGIBLE, NOT_APPLICABLE et NEEDS_REVIEW.

## Installation

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
# Ollama : https://ollama.com (ou brew install ollama), puis
ollama serve &
ollama pull qwen3-vl:2b-instruct
```

## Utilisation

**Le plus simple : double-cliquer sur `DayOne.command`.** Ollama et l'interface démarrent, et le navigateur s'ouvre sur http://localhost:8501. Fermer la fenêtre noire arrête tout.

(Au premier lancement, macOS peut bloquer le fichier : clic droit → Ouvrir → Ouvrir.)

Dans l'interface : choisir une photo ou une page, cliquer sur **Lire la page**, corriger dans le tableau si besoin, puis **Télécharger le résultat**.

En ligne de commande :

| Je veux… | Commande |
|---|---|
| L'interface | `.venv/bin/streamlit run app.py` |
| Lire toutes les pages dev | `.venv/bin/python -m scripts.run_extraction` |
| Lire une photo | `.venv/bin/python -m scripts.run_extraction --image photo.jpg --page-type identification_antecedents` |
| Créer les fichiers de référence à remplir | `.venv/bin/python -m scripts.make_annotation_templates` (voir `annotations/LISEZMOI.md`) |
| Évaluer | `.venv/bin/python -m scripts.evaluate` |
| Évaluation finale (patientes 9-10) | ajouter `--split test --final` aux deux commandes ci-dessus |
| Vérifier que `data/` est intact | `.venv/bin/python -m scripts.check_integrity` |
| Tests | `.venv/bin/python -m pytest -q` |

## Règles respectées

- **100 % local** : un `OLLAMA_HOST` distant ou un modèle `*cloud*` est refusé.
- **Aucune donnée personnelle** : le nom, le conjoint, le CIN, le téléphone et l'adresse n'ont pas de zone dans le gabarit, donc ils ne sont jamais lus. Le texte OCR brut ne quitte pas la mémoire.
- **Ne jamais inventer** : un seul lecteur ou deux lectures en désaccord donnent NEEDS_REVIEW. Une case non cochée donne NOT_PROVIDED, jamais `false`.
- **Test verrouillé** : les patientes 9 et 10 ne sont lues qu'avec `--final`.
- **Aucune logique clinique.**

## Limites connues

- Le gabarit ne couvre que la mise en page des pages du dossier specimen. Les vraies photos (`1-*.jpg`) ont une autre mise en page : elles passent en mode « modèle seul », où tous les champs sont NEEDS_REVIEW. Le 2b y est peu fiable.
- Dans les données synthétiques, certaines lettres accentuées manquent sur la page (« Commer ante »). Le lexique les remet, mais seulement pour les mots qu'il contient : ajouter les mots manquants dans `schema/lexique.txt`.
- Les chiffres isolés (parité, enfants vivants) sont souvent lus par un seul lecteur, donc NEEDS_REVIEW.
- Pas de valeurs de référence fournies : l'évaluation attend les fichiers remplis à la main dans `annotations/`.
