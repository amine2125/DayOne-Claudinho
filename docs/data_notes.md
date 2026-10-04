# Notes sur les données

## Inventaire (`outputs/index.csv`)

- 129 images : 124 pages PNG (dont 44 doublons exacts, même sha256) + 5 vraies photos `1-*.jpg`.
- 80 pages uniques = 10 patientes × 8 pages. Numéro de page n → patiente `(n-1)//8 + 1`, position `(n-1)%8 + 1`.
- Split : patientes 1–8 = `dev` (64 pages), 9–10 = `test` (16 pages, verrouillées), photos = `photo` (5).
- Les PNG font 1654×2339 px (A4 à 200 dpi). Les photos font 900×1600 px.

## Les 8 types de page (vus sur la patiente 1)

| Pos. | `page_type` | Titre imprimé |
|---|---|---|
| 1 | `fiche_surveillance` | Fiche de surveillance de la grossesse et du post-partum |
| 2 | `identification_antecedents` | Identification et antécédents |
| 3 | `grossesse_actuelle` | Grossesse actuelle (tableau des visites par trimestre) |
| 4 | `accouchement` | Déroulement de l'accouchement |
| 5 | `postpartum_precoce_mere` | Consultation du post-partum précoce — mère |
| 6 | `postpartum_precoce_nouveau_ne` | Consultation du post-partum précoce — nouveau-né |
| 7 | `postpartum_tardif_mere` | Consultation du post-partum tardif — mère |
| 8 | `postpartum_tardif_nouveau_ne` | Consultation du post-partum tardif — nouveau-né |

Les types V1 sont les positions 2 et 4.

## PDF `dossiers_specimen_10_patientes.pdf`

- 80 pages, dans le même ordre que les PNG (titres identiques sur les pages 1–8).
- **Le PDF a une couche texte** : les valeurs « manuscrites » y sont du texte. Ce texte contient aussi les données personnelles.
- Il n'est pas utilisé pour l'instant (décision n° 1 : le corrigé est tapé par un humain). À rediscuter.

## Machine et temps mesurés

Apple M2, 8 Go de RAM.

Test de fumée sur la page n° 2 (patiente 1), image en pleine résolution (3 827 tokens d'image).

| Composant | Temps / page | RAM | Titre lu |
|---|---|---|---|
| PaddleOCR (det mobile + rec latin mobile) | ~15 s | 1,8 Go (pic) | oui |
| Ollama `qwen3-vl:4b` | 100 s | 3,7 Go selon Ollama, ~5 Go dans le Moniteur d'activité | oui |
| Ollama `qwen3-vl:2b` | 38 s | 1,8 Go selon Ollama | oui |

Le 4b fait trop chauffer la machine (8 Go) → **2b par défaut**.

## Constats pendant l'implémentation

- `qwen3-vl:2b` « réfléchit » même avec `think=False` : tout le budget de tokens y passe et la réponse est vide. On utilise donc **`qwen3-vl:2b-instruct`** (même taille, ~1,7 Go). Coût mesuré sur un M4 : ~4 s par zone, ~1 150 tokens quelle que soit la taille de la zone.
- Toutes les pages dev s'alignent sur la page de la patiente 1 (décalage ≤ 17 px, 355 à 1 000 points d'accord). Les photos `1-*.jpg` ne s'alignent pas (< 10 points) : c'est un autre registre, avec une autre mise en page.
- Encre : bleue pour la plupart des patientes, **noire et fine** pour les patientes 2 et 7. Le masque d'encre combine le bleu et « sombre mais absent du gabarit imprimé ».
- Cases : part d'encre de 0 si vide, d'au moins 0,08 si cochée, sur les 16 pages dev. Seuils retenus : 0,02 et 0,06.
- PaddleOCR lit mieux la zone **brute** agrandie ×2 qu'une zone nettoyée (le nettoyage casse les traits fins).
- La police manuscrite synthétique n'a pas certains glyphes accentués : « Commer ante », « Maternit » sont réellement écrits ainsi sur la page.

## Passage à la lecture sans gabarit

- Objectif : lire n'importe quelle fiche, pas seulement la mise en page du jeu de données.
- Les 5 photos `1-*.jpg` viennent d'un vrai carnet : mise en page différente, photo de travers, écriture très libre.
- Modèles comparés sur une bande de page (photo `1-2`, page dev 26) :

| Modèle | Lecture | Temps par bande (M4) |
|---|---|---|
| `qwen3-vl:2b-instruct` | Étiquettes justes, valeurs souvent fausses (« QNams », « N/A » pour RAS) | ~8 s |
| `qwen3-vl:4b-instruct` | Valeurs justes sur les pages nettes, « 21ans » sur la photo | ~20 s |
| `qwen3-vl:8b-instruct` | Pas mieux que le 4b sur la photo difficile | ~30 s |

  → **4b par défaut**.
- Ce que le modèle fait mal, et ce qui le remplace :
  - cases à cocher : le modèle se trompe souvent → OpenCV (4 côtés du carré + encre dedans) ;
  - tableaux lus par bandes : la ligne se perd → tableau entier, consigne « ligne | colonne » ;
  - étiquettes inventées (« row label - column label ») → supprimées si leurs mots ne sont pas sur la page.
- Comparaison aux anciens résultats du gabarit (pages 2 et 26) : aucune valeur différente sur les champs lus des deux côtés.
- Photos refusées : image sans texte, page de texte qui n'est pas une fiche de santé.

## Version finale : « OCR d'abord »

- Le modèle lisait toute la page (2 à 3 min par page, Mac qui chauffe). Inversion : PaddleOCR lit tout, les valeurs
  sont reliées aux étiquettes par la position, le modèle ne relit que les valeurs douteuses sur un petit morceau.
- Temps mesuré : ~45 à 75 s par page (dont ~10 s d'OCR).
- Page 26 : 45 valeurs justes, 2 « à vérifier ». Page 2 et page 4 : quasi complètes, cases cochées justes.
- Fuite trouvée et corrigée : un morceau d'image envoyé au modèle débordait sur la ligne « Adresse ».
  Les zones des champs personnels sont maintenant effacées avant tout envoi au modèle.

## Photos réelles (photo `1-1`)

- Encre bleue invisible au seuil fixe : sous lampe chaude, tout tire vers le rose (imprimé B−R ≈ −50, stylo ≈ −25).
  Correction : balance des couleurs sur le papier, puis « plus bleu que l'imprimé de la même page » (`blue_map`).
- L'OCR lit souvent « Étiquette : écriture » d'un bloc : la ligne est coupée là où commence l'encre bleue.
- Écriture grande → hauteur de texte de référence prise sur l'imprimé seulement (sinon les cases sont jugées trop petites).
- Cases : texte le plus proche (gauche ou droite) ; intitulé de groupe ajouté (« Mode de la couverture | Fixe »).
  Lettres de titre écartées : il faut un espace vide autour de la case.
- Le modèle lit mieux une valeur manuscrite quand le morceau d'image inclut l'étiquette
  (« Casa - Sittat » au lieu de « Cax - S - T H T »).
- Limite : sur cette photo, l'OCR ne détecte pas la ligne « Nom de l'établissement sanitaire ».
