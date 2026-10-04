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
