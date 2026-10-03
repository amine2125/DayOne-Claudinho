# Étape 1 — Données et environnement

**But :** savoir exactement ce qu'on a, verrouiller le test, et avoir un environnement qui tourne.

## Tâches

| # | Tâche | Détail |
|---|---|---|
| 1 | Contrôle d'intégrité | Comparer le sha256 de chaque fichier de `data/` au `manifest.json`. Le script est relancé à chaque étape |
| 2 | Index des pages | fichier, sha256, n° de patiente (pages 1–8 → patiente 1, etc.), position 1–8, type de page, doublon oui/non |
| 3 | Types de page | Nommer les 8 types à partir de la **patiente 1 uniquement**. Vérifier si le PDF reprend les mêmes 80 pages |
| 4 | Séparation dev / test | Colonne `split` dans l'index : patientes 1–8 = `dev`, 9–10 = `test`. Les scripts refusent `test` sans option `--final` |
| 5 | Environnement | `.venv` Python 3.12, `requirements.txt`, Ollama via brew, `qwen3-vl:4b` et `qwen3-vl:2b` |
| 6 | Test de fumée | Sur 1 page dev : PaddleOCR, **puis** Ollama (jamais en parallèle). On affiche seulement le temps, la RAM et le nombre de lignes lues, jamais le texte |

## Fichiers

- `scripts/check_integrity.py`
- `scripts/build_index.py` → `outputs/index.csv`
- `scripts/smoke_test.py`
- `docs/data_notes.md` (8 types de page, RAM et temps mesurés)
- `requirements.txt`

## C'est fini quand

- [ ] 132 fichiers sur 132 conformes au manifest.
- [ ] `index.csv` : 80 pages uniques, chacune avec patiente, type et `split`.
- [ ] Aucune page `test` lue sans `--final`.
- [ ] Le test de fumée passe, et la RAM et le temps sont notés.

Git : hors périmètre, géré par toi.
