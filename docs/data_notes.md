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

Le 4b fait trop chauffer la machine (8 Go) → **2b par défaut**. Prochaine piste : réduire l'image envoyée.
