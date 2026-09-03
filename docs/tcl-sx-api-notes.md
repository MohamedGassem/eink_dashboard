# API TCL — SIRI Situation Exchange (`siri-lite/2.0/situation-exchange.json`)

Capture réelle du 2026-09-03 vers 10:19 UTC via :

```bash
curl -s -u "$GRANDLYON_USERNAME:$GRANDLYON_PASSWORD" \
  'https://data.grandlyon.com/siri-lite/2.0/situation-exchange.json' \
  > tests/fixtures/tcl_situation_exchange.json
```

Authentification **HTTP Basic**, mêmes identifiants que `tclpassagearret`.
Réponse : `200`, JSON SIRI-Lite exploitable (858 situations dans la capture).

## Chemins JSON réellement observés

```text
Siri
└── ServiceDelivery
    ├── ResponseTimestamp, ProducerRef.value, ...
    └── SituationExchangeDelivery[]            (liste ; 1 élément dans la capture)
        └── Situations
            └── PtSituationElement[]           (liste ; 858 éléments)
```

Chaque `PtSituationElement` observé :

| Champ | Présence | Contenu |
|---|---|---|
| `SituationNumber.value` | 858/858 | identifiant de situation, ex. `ACTIV_5906148837875616863_2` |
| `ValidityPeriod[]` | 858/858, toujours 1 entrée | `StartTime` (858/858) + `EndTime` (858/858, ISO 8601 UTC) |
| `Description[].value` | 858/858, toujours 1 entrée | texte libre, **parfois du HTML** (`<span style=…>`) et des entités |
| `Summary` | 0/858 | absent — modélisé quand même, `extra="ignore"` |
| `Consequences.Consequence[].Affects.Networks.AffectedNetwork[]` | 858/858 | `NetworkRef.value` (ex. `ActIV:Operator::RATPML:SYTRAL`) + `AffectedLine[]` |
| `AffectedLine[].LineRef.value` | 850 à 1 ligne, 4 à 2 lignes, 4 à 0 ligne | identifiant de ligne |
| `Affects…StopPoints` | présent, souvent `{}` | non exploité en V2 |
| `MiscellaneousReason` | 858/858 | toujours `UNKNOWN` → pas de sévérité exploitable |
| `ReportType` | 858/858 | toujours `incident` |
| `Keywords` | 858/858 | toujours `["Perturbation"]` |
| `Planned` | 0/858 | absent — `planned` reste `None` |

Aucun champ de **sévérité**, **cause** ou **conséquence textuelle** exploitable :
le seul texte affichable est `Description`. Ordre de fallback retenu par le
mapper : `Summary` (jamais présent aujourd'hui) → `Description` → constante
`Perturbation signalée`.

## Identifiants de ligne (`LineRef`)

Format : `ActIV:Line::<code>:SYTRAL`.

- **Bus** : `<code>` = numéro / lettre commerciale (`36`, `C17`, `C12`…) ou code
  interne SYTRAL (`JD450`, `N80`, `ZI3`…).
- **Tram** : `<code>` = libellé commercial. Confirmés dans la capture :
  `ActIV:Line::T4:SYTRAL`, `ActIV:Line::T7:SYTRAL`.
- **Métro** : `<code>` = lettre. Confirmé : `ActIV:Line::D:SYTRAL` (2 situations
  « travaux modernisation ligne D »).

**T2 :** aucune perturbation T2 active au moment de la capture, donc `LineRef`
T2 **non observé directement**. Par cohérence avec T4/T7 (libellé commercial),
la config utilise `ActIV:Line::T2:SYTRAL`. À confirmer sur une vraie
perturbation T2.

## Fixtures

- `tests/fixtures/tcl_situation_exchange.json` — capture réelle intégrale.
- `tests/fixtures/tcl_situation_exchange_t2_d.json` — **fixture synthétique**
  dérivée de la structure réelle, couvrant : T2 active, D active, situation
  T2+D, ligne non suivie, situation expirée, future lointaine (ignorée),
  future proche (gardée), texte manquant, `ValidityPeriod` sans `EndTime`,
  doublon de `SituationNumber`.
