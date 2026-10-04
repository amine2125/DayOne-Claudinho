# Remplir une référence (à la main, jamais par l'IA)

Un fichier par page : `page_NN_<type>.csv`. Ouvrir la page dans `data/Paper Registry/`, puis remplir les colonnes `value` et `status`.

| Ce que montre la page | `value` | `status` |
|---|---|---|
| Texte ou nombre écrit | le recopier tel quel (« 3626 g », « 12/11/2022 ») | vide (= KNOWN) |
| « RAS » | RAS | vide |
| Case cochée | x | vide |
| Case vide, zone vide | vide | vide (= NOT_PROVIDED) |
| Écrit mais illisible | vide | ILLEGIBLE |
| « ? », « inconnu » | vide | UNKNOWN |
| Champ sans objet (ex. indication de césarienne si voie basse) | vide | NOT_APPLICABLE |

- Recopier ce qui est écrit. Si une lettre accentuée manque sur la page (« Commer ante »), taper le mot voulu (« Commerçante »).
- Pages de test (patientes 9-10) : `python -m scripts.make_annotation_templates --final`, à faire seulement pour l'évaluation finale.
- Ensuite : `python -m scripts.evaluate`.
