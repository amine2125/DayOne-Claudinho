# DayOne — interface web

Tableau de bord de DayOne, **en lecture seule** : qui voir en premier, et le dossier de chaque patiente.
La sage-femme envoie les photos, vérifie les cases douteuses et choisit la patiente **sur WhatsApp** ; cette interface ne modifie rien, elle montre ce qui se passe.
Elle lit directement `../schema/*.json` (gabarits des pages du registre).

**Elle démarre vide** : aucune donnée de démo. Les patientes et les dossiers viendront du backend, une fois l'agent WhatsApp branché.

```bash
cd web
npm install
npm run dev        # http://localhost:5173
npm run build      # build statique dans dist/
```

Seuls tes réglages (rôle, langue, identifiant sage-femme) sont gardés dans le navigateur.

## Brancher le backend

Les écrans ne lisent que l'interface `DayOneApi` ([src/services/api.ts](src/services/api.ts)). Aujourd'hui elle est servie par un store local vide ([src/services/localApi.ts](src/services/localApi.ts)). Pour afficher les vraies données, il suffit d'écrire une classe qui implémente `DayOneApi` en appelant le backend, et de la brancher dans [src/services/index.ts](src/services/index.ts).

## Calendrier de suivi

`src/contract/followup.ts` décide quand la prochaine visite est attendue, uniquement à partir des dates et des pages photographiées. Aucune donnée clinique n'intervient :

| Situation | Prochaine visite attendue |
|---|---|
| Pas encore de page « Accouchement » | 28 jours après la dernière visite (prénatale) |
| Accouchée, pas de page post-partum précoce | 7 jours après l'accouchement |
| Post-partum précoce fait, pas de post-partum tardif | 42 jours après l'accouchement |
| Toutes les pages post-partum présentes | Suivi terminé |

« Cette semaine » = dans les 7 jours ; « À recontacter » = plus de 30 jours de retard. **Ces délais sont provisoires, à valider avec le protocole national** ; ils ne se changent qu'à cet endroit.

## Où se trouve quoi

| Dossier | Rôle |
|---|---|
| `src/contract/` | **Le contrat de données.** `followup.ts` (calendrier de suivi), `enums.ts` (6 statuts de champ, cycle de vie, rôles), `types.ts` (Field, Page, RegistryRecord, Visit, Patient), `lifecycle.ts` (transitions permises et les 5 étapes montrées à la sage-femme), `registry.ts` (sections et champs lus depuis `schema/*.json`) |
| `src/services/` | `api.ts` est l'interface `DayOneApi` (le backend). `localApi.ts` en est la version locale, vide, en attendant le backend. `followup.ts` calcule le prochain rendez-vous. `linking.ts` propose les correspondances patiente |
| `src/components/` | Briques réutilisables : `StatusBadge`, `ConfidenceMeter`, `FieldRow`, `SectionCard`, `LifecycleStepper`, `PageImage` / `FieldCrop`, `VisitTimeline`, `ConnectivityToggle` / `ConnectivityBanner`, `PatientCode` |
| `src/screens/` | Un fichier par écran : `HomeScreen` (Aujourd'hui), `PatientsScreen`, `PatientScreen`, `PageScreen` (un dossier, lecture seule), `DashboardScreen` (superviseur / épidémiologiste), `SettingsScreen` |
| `src/i18n/` | Textes FR / EN (`fr.ts`, `en.ts`, mêmes clés vérifiées par TypeScript) et libellés EN des champs |
| `src/auth/roles.ts` | La table des permissions. On l'interroge avec `useCan('original_image')` |

Un `Field` correspond exactement à ce qu'écrit `dayone/extract.py` (`value`, `status`, `confidence`, `source` → `method`). S'y ajoutent `origin` (AI / CONFIRMED / CORRECTED / MANUAL), `history`, `aiValue` (la valeur de l'IA reste gardée après une correction), `bbox` et `alerts`, ce dernier réservé aux futures règles de cohérence.

## Ajouter une feature

| Je veux… | Je touche |
|---|---|
| Un champ ou une section du registre | `schema/*.json`, puis éventuellement son libellé EN dans `i18n/fields.en.ts` |
| Une page du registre lue par l'IA | Ajouter son gabarit dans `SCHEMAS` (`contract/registry.ts`) |
| Un onglet du profil patiente (Stocks, Rendez-vous…) | Une entrée dans `MODULES` (`screens/PatientScreen.tsx`) |
| Un écran | Une entrée dans `NAV` (`components/AppShell.tsx`) et une route dans `App.tsx` |
| Une transition de cycle de vie | `TRANSITIONS` (`contract/lifecycle.ts`). Le service refuse toute transition qui n'y figure pas |
| Une permission ou un rôle | `PERMISSIONS` (`auth/roles.ts`) |
| Le vrai backend | Une classe qui implémente `DayOneApi`, branchée dans `services/index.ts`. Les écrans ne changent pas |

## Choix de conception

- **Une patiente, c'est un code.** Il est grand, en police monospace avec un zéro barré, pour se lire comme sur le papier. L'identifiant interne est aléatoire.
- **Le statut n'est jamais montré par la couleur seule.** Chaque statut a une icône, un mot simple (« Vide sur le papier » plutôt que `NOT_PROVIDED`) et une explication au survol.
- **La confiance est affichée en 3 barres et un mot.** Le pourcentage reste disponible au survol.
- **Lecture seule.** Aucune correction ici : tout se fait sur WhatsApp, et le tableau de bord se met à jour seul.
- **L'urgence est une question de date, pas de santé.** Les couleurs d'« Aujourd'hui » disent *quand* voir la patiente, jamais *si elle va mal*.
- **Les cases vides sont repliées.** On voit d'abord ce qui est écrit.
- **Le mode hors ligne est un état normal.** Le message rassure (« Rien n'est perdu ») et ne présente pas la situation comme une erreur.
- **Les zones personnelles sont toujours masquées.** C'est le cas du nom, du téléphone, de l'adresse et du CIN. Une photo dont la mise en page est inconnue est floutée par défaut.
- **L'application ne fait aucune interprétation clinique.** « Noté sur le registre » montre ce qui est écrit, sans couleur de risque ni triage, ce qui reste hors du périmètre du défi.
- **La police Atkinson Hyperlegible est embarquée.** Elle est conçue pour la lisibilité et fonctionne sans internet.

## Limites

- Pas encore de backend branché : l'interface est vide tant que l'agent WhatsApp n'envoie pas de dossiers.
- Tableau de bord : les emplacements sont prêts, mais il n'y a encore ni graphique ni calcul.
