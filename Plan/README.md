# Plan DayOne — V1

**But de la V1 :** photo d'une page du registre → données structurées (value, status, confidence) → comparaison à des valeurs de référence.
Hors V1 : WhatsApp, hors-ligne, liaison patiente.

## Étapes

| # | Fichier | Contenu | État |
|---|---|---|---|
| 0 | [00-questions-et-choix.md](00-questions-et-choix.md) | Choix validés | Fait |
| 1 | [01-donnees-et-environnement.md](01-donnees-et-environnement.md) | Inventaire, séparation dev/test, environnement | Fait |

Les étapes suivantes seront ajoutées au fur et à mesure.

## Règles valables à chaque étape

- 100 % local : aucune API cloud (ni Claude, ni Gemini, ni GPT, ni Ollama Cloud).
- Chaque champ a `value`, `status` et `confidence`. Jamais de `null` seul.
- Ne jamais inventer : en cas de doute, NEEDS_REVIEW ou ILLEGIBLE.
- Ne jamais stocker : nom, conjoint, numéro national (CIN), téléphone, adresse.
- Ne jamais modifier `data/` (images et CSV de référence).
- Aucune logique clinique (pas de diagnostic, de risque ou de triage).
- Une étape à la fois. On ne passe à la suivante qu'avec ton accord.
