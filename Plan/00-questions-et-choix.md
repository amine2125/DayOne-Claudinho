# Étape 0 — Choix à valider

**Constats :** 80 pages uniques (10 patientes × 8 pages), 44 doublons, 5 vraies photos. Le CSV (200 lignes) **ne correspond pas aux images**. Données personnelles sur toutes les pages. Mac M2 avec 8 Go de RAM.

| # | Question | Reco | Décision |
|---|---|---|---|
| 1 | Avec quoi comparer, puisque le CSV ne colle pas ? | Annoter 16 pages à la main (2 patientes) | **Modifié.** Pas de valeurs de référence fournies, donc on annote à la main, seulement les 2 types de pages de la V1. Séparation 80/20 **par patiente** (toutes les pages d'une patiente dans le même groupe) : patientes 1 à 8 pour le développement, patientes 9 et 10 pour le test. Les patientes de test sont **verrouillées** : on ne les regarde pas et on ne règle rien dessus avant la fin. Annotation : patientes 1-2 (développement) et 9-10 (test), soit 8 pages. Les patientes 3 à 8 servent à vérifier à l'œil, sans corrigé. Un humain tape le corrigé à partir d'un modèle vide généré par l'agent, jamais l'IA. |
| 2 | Pages traitées en V1 ? | 2 types : antécédents et accouchement | **OK.** |
| 3 | « RAS » / case non cochée ? | « RAS » = KNOWN « aucun ». Case vide = false si la section est remplie, sinon NOT_PROVIDED | **Modifié.** « RAS » = KNOWN « aucun ». Une case = false seulement si « Non » est explicitement coché. Sinon NOT_PROVIDED. |
| 4 | Confiance ? | Score OCR + accord OCR/modèle + format. Sous 0,7 → NEEDS_REVIEW | **OK.** Seuil de départ 0,7, ajusté ensuite. PaddleOCR et le modèle lisent séparément (voir n° 7). |
| 5 | Texte OCR brut (contient noms, CIN…) ? | Masqué avant toute écriture sur disque | **Modifié.** Le texte OCR brut n'est jamais écrit sur disque ni dans les logs. On garde seulement les champs extraits. |
| 6 | Modèle ? | `qwen3-vl:4b`. `8b` testé une fois, il risque de ne pas tenir en RAM | **OK.** Si la mémoire manque, repli sur `qwen3-vl:2b`. PaddleOCR et Ollama sont lancés l'un après l'autre, jamais en parallèle. |
| 7 | Rôle de PaddleOCR ? | Indice donné au modèle + vérification croisée | **Modifié.** Lecture croisée : PaddleOCR et le modèle lisent la page séparément, puis on compare. Désaccord → NEEDS_REVIEW. La variante « OCR en indice » sera testée à part plus tard. |
| 8 | Outillage ? | brew Ollama, `.venv`, git, sorties dans `outputs/`, Streamlit | **OK.** |

**Note :** le « N° de fiche » est gardé provisoirement. Je confirme avec les organisateurs si c'est le code de la sage-femme ou un identifiant direct.

Réponse rapide : « OK sauf n° X : … »