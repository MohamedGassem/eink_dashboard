# Dashboard e-ink Lyon — Plan d'implémentation V2

**Date :** 2026-09-03  
**Statut :** prêt à implémenter  
**Base :** V1 existante — FastAPI + providers asyncio + état mémoire + ViewModel pur + Pillow 1 bit 800×480 + protocole TRMNL/BYOS.

> **Pour un agent de développement :** implémenter ce plan task-by-task, en conservant les tests existants verts. Chaque task doit se terminer par les tests ciblés puis `pytest -v && mypy --strict src/ && ruff check . && ruff format --check .`.

## 1. Objectif

Faire évoluer la V1 vers un dashboard plus dense et plus lisible, orienté **décision avant de sortir de chez soi** :

- remplacer les titres répétés `Route de Vienne (vers …)` par deux lignes compactes `T2 → St-Priest` et `T2 → Perrache` ;
- mettre visuellement en avant le **prochain passage**, les suivants restant secondaires ;
- simplifier Vélo'v à **nom court + nombre de vélos disponibles** ;
- ajouter une zone contextuelle pour les **perturbations TCL du T2 et du métro D** ;
- ajouter une météo minimale : **température actuelle + pluie utile à court terme** ;
- ne rien afficher pour une source contextuelle quand il n'y a rien d'actionnable ;
- conserver le panneau comme client passif : **aucune modification firmware requise**.

## 2. Hors périmètre

- calcul d'itinéraire ;
- trafic routier ;
- actualités ;
- agenda personnel ;
- historique des perturbations ;
- qualité de l'air ;
- nombre de places libres Vélo'v sur l'écran principal ;
- météo détaillée (humidité, vent, pression, prévisions sur plusieurs jours) ;
- base de données ou persistance ;
- modification du protocole TRMNL/BYOS.

## 3. Écran cible

État normal :

```text
LYON                                             09:54
──────────────────────────────────────────────────────

T2 → St-Priest        2 min          8   14   20
T2 → Perrache         4 min         12   20   23

VÉLO'V
Blandan                                      1 vélo
Berthelot                                     1 vélo

──────────────────────────────────────────────────────
12°C                                  Pluie vers 15h
```

Avec perturbations :

```text
LYON                                             09:54
──────────────────────────────────────────────────────

T2 → St-Priest        2 min          8   14   20
T2 → Perrache         4 min         12   20   23

VÉLO'V
Blandan                                           0
Berthelot                                          4

──────────────────────────────────────────────────────
⚠ T2 · trafic perturbé — Jean Macé ↔ Perrache
⚠ D  · station non desservie — Guillotière
12°C                                  Pluie vers 15h
```

Règle importante : **absence de perturbation active = aucune ligne “trafic normal”**.  
En revanche, si le flux perturbations est indisponible ou trop ancien, afficher un indicateur discret du type `Info trafic indisponible` afin de ne pas confondre “aucune perturbation” et “aucune donnée”.

---

## 4. Décisions d'architecture

### 4.1 Ne pas fusionner passages TCL et perturbations

La V1 récupère les passages depuis `tcl_sytral.tclpassagearret`. Les perturbations proviennent d'un autre service et ont un cycle de vie différent.

Créer un provider indépendant :

```text
tcl             -> prochains passages
tcl_disruptions -> SIRI Situation Exchange
velov           -> vélos disponibles
weather         -> météo
```

Bénéfices :

- une panne SIRI-SX ne dégrade pas les horaires ;
- cadence de rafraîchissement indépendante ;
- état de fraîcheur indépendant ;
- tests et fixtures isolés ;
- pas de couplage entre deux formats externes TCL différents.

### 4.2 SIRI Situation Exchange : capturer le flux avant de figer le mapping

Endpoint prévu :

```text
https://data.grandlyon.com/siri-lite/2.0/situation-exchange.json
```

Authentification : réutiliser `GRANDLYON_USERNAME` / `GRANDLYON_PASSWORD`.

Le service SIRI Situation Exchange est adapté aux situations planifiées ou non planifiées et permet notamment de porter une période de validité et le périmètre affecté.

**Ne pas supposer que les identifiants SIRI des lignes valent littéralement `T2` et `D`.**

La première étape d'implémentation doit capturer une réponse réelle et relever :

- structure racine exacte du JSON ;
- emplacement de `PtSituationElement` ;
- identifiant de situation ;
- période(s) de validité ;
- texte court / résumé / description ;
- `Affects` ;
- `AffectedLine` / `LineRef` ;
- éventuels champs de sévérité, conséquence ou cause ;
- représentation réelle du T2 ;
- représentation réelle du métro D.

Les identifiants techniques sont ensuite associés aux labels d'affichage `T2` et `D` dans la configuration.

### 4.3 Météo : provider séparé et sans secret

Utiliser Open-Meteo `https://api.open-meteo.com/v1/forecast`.

Données minimales :

- `current=temperature_2m`;
- `hourly=precipitation_probability,precipitation`;
- `timezone=Europe/Paris`;
- horizon limité aux prochaines heures.

Les coordonnées sont configurées dans `dashboard.toml`, pas codées en dur.

Règle métier V2 :

- toujours afficher la température actuelle si la météo est fraîche ;
- chercher la première heure des prochaines `weather.lookahead_hours` où :
  - `precipitation_probability >= weather.rain_probability_threshold`,
  - et `precipitation > 0`;
- afficher `Pluie vers HHh` si une telle heure existe ;
- sinon afficher `Sec` ;
- météo stale/error : afficher uniquement `Météo indisponible`, sans ancienne prévision de pluie présentée comme actuelle.

### 4.4 Le ViewModel reste la frontière d'affichage

Les modèles métier conservent toute l'information utile au debug.

Le ViewModel ne contient que ce qui est réellement affiché. En particulier, retirer `docks` et `capacity` de `BikeBlock` V2.

C'est important pour l'e-ink : une variation du nombre de places libres ne doit **plus modifier le `content_hash()`** et provoquer un redessin alors que cette information n'est plus visible.

---

# 5. Modèles cibles

## 5.1 Perturbations

Créer `src/eink_dashboard/domain/disruptions.py` :

```python
@dataclass(frozen=True, slots=True)
class TransitDisruption:
    source_id: str
    lines: tuple[str, ...]
    summary: str
    description: str
    valid_from: datetime | None
    valid_until: datetime | None
    severity: str | None
    planned: bool | None

    def is_active(self, now: datetime) -> bool: ...
```

Principes :

- `lines` contient les **labels internes normalisés** (`"T2"`, `"D"`), pas nécessairement les `LineRef` bruts ;
- conserver `source_id` pour déduplication ;
- dates timezone-aware ;
- aucune logique Pillow ici.

## 5.2 Météo

Créer `src/eink_dashboard/domain/weather.py` :

```python
@dataclass(frozen=True, slots=True)
class WeatherSnapshot:
    temperature_c: float
    rain_at: datetime | None
    reported_at: datetime
```

Le provider peut parser davantage de données externes, mais le domaine V2 reste volontairement minimal.

## 5.3 ViewModel V2

Faire évoluer `render/viewmodel.py` vers des structures directement orientées layout :

```python
@dataclass(frozen=True, slots=True)
class DepartureRow:
    line: str
    direction: str
    first_wait: str
    next_waits: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class BikeRow:
    label: str
    bikes: int
    stale: bool

@dataclass(frozen=True, slots=True)
class AlertRow:
    line: str
    text: str

@dataclass(frozen=True, slots=True)
class WeatherRow:
    temperature: str
    condition: str

@dataclass(frozen=True, slots=True)
class DashboardView:
    as_of: str
    departures: tuple[DepartureRow, ...]
    bikes: tuple[BikeRow, ...]
    alerts: tuple[AlertRow, ...]
    weather: WeatherRow | None
    traffic_note: str
```

`content_hash()` couvre tout **sauf `as_of`**, comme en V1.

---

# 6. Configuration cible

Faire évoluer `config/dashboard.toml` sans déplacer les secrets hors de `.env`.

Exemple conceptuel :

```toml
[[tcl.stops]]
name = "Route de Vienne"
stop_id = "..."
lines = ["T2"]
directions = ["Saint-Priest", "Hôtel Région"]

[[tcl.direction_aliases]]
match = "Saint-Priest"
label = "St-Priest"

[[tcl.direction_aliases]]
match = "Hôtel Région"
label = "Perrache"

[tcl.disruptions]
lines = ["T2", "D"]

# À renseigner uniquement après capture du vrai flux SIRI-SX.
[[tcl.disruptions.line_refs]]
label = "T2"
refs = ["<LINE_REF_REEL_T2>"]

[[tcl.disruptions.line_refs]]
label = "D"
refs = ["<LINE_REF_REEL_METRO_D>"]

[[velov.stations]]
station_id = "..."
label = "Blandan"

[[velov.stations]]
station_id = "..."
label = "Berthelot"

[weather]
latitude = <LATITUDE>
longitude = <LONGITUDE>
lookahead_hours = 6
rain_probability_threshold = 50
```

Ajouter dans `Settings` :

```text
TCL_DISRUPTIONS_REFRESH_SECONDS=120
WEATHER_REFRESH_SECONDS=600
```

Les aliases de direction doivent rester configurables : pas de règle codée en dur du type `"Hôtel Région" -> "Perrache"` dans le renderer.

---

# 7. Plan d'implémentation

## Task 0 — Baseline et capture SIRI-SX réelle

**But :** partir du code V1 réellement présent et lever l'unique incertitude structurante : le format exact des perturbations TCL.

**Fichiers :**

- Create: `tests/fixtures/tcl_situation_exchange.json`
- Create/Modify: `docs/tcl-api-notes.md`

- [ ] Lancer la suite V1 complète et vérifier qu'elle est verte.
- [ ] Capturer le flux avec les credentials existants :

```bash
curl -s \
  -u "$GRANDLYON_USERNAME:$GRANDLYON_PASSWORD" \
  'https://data.grandlyon.com/siri-lite/2.0/situation-exchange.json' \
  > tests/fixtures/tcl_situation_exchange.json
```

- [ ] Vérifier que la réponse est bien du JSON SIRI-SX exploitable et non une erreur encapsulée.
- [ ] Relever tous les `LineRef` présents.
- [ ] Identifier les références correspondant au T2 et au métro D.
- [ ] Chercher au moins un exemple contenant `ValidityPeriod` et `Affects`.
- [ ] Documenter les chemins JSON réellement observés.
- [ ] Si aucune perturbation T2/D n'est active au moment de la capture, conserver la fixture réelle puis construire une **fixture synthétique minimale dérivée de sa structure**, clairement nommée `tcl_situation_exchange_t2_d.json`.
- [ ] Ne commencer le mapper qu'après cette étape.

**Critère de validation :** on sait extraire sans hypothèse les références de ligne, les périodes de validité et un texte affichable.

---

## Task 1 — Étendre la configuration

**Fichiers :**

- Modify: `src/eink_dashboard/core/config.py`
- Modify: `config/dashboard.toml`
- Modify: `.env.example`
- Modify: `tests/fixtures/dashboard_ok.toml`
- Modify: `tests/unit/test_config.py`

**À produire :**

- modèle `DirectionAlias(match, label)` ;
- modèle `DisruptionLine(label, refs)` ;
- config perturbations avec lignes suivies `T2`, `D` ;
- config météo ;
- `tcl_disruptions_refresh_seconds`;
- `weather_refresh_seconds`.

- [ ] Ajouter les nouveaux modèles Pydantic.
- [ ] Conserver la compatibilité avec un TOML V1 ne contenant ni météo ni perturbations.
- [ ] Valider latitude `[-90, 90]`, longitude `[-180, 180]`.
- [ ] Valider `lookahead_hours >= 1`.
- [ ] Valider `rain_probability_threshold` entre 0 et 100.
- [ ] Refuser deux aliases identiques avec des labels différents.
- [ ] Refuser deux mappings de `LineRef` vers deux labels internes différents.
- [ ] Ajouter `T2` et `D` au fichier réel une fois les `LineRef` connus.

**Critère de validation :** `load_dashboard_config()` charge V1 et V2 ; les valeurs invalides échouent explicitement.

---

## Task 2 — Étendre le domaine et rendre l'état extensible

**Fichiers :**

- Create: `src/eink_dashboard/domain/disruptions.py`
- Create: `src/eink_dashboard/domain/weather.py`
- Modify: `src/eink_dashboard/state.py`
- Modify: `tests/unit/test_state.py`
- Create: `tests/unit/test_disruptions.py`

La V1 initialise seulement `tcl` et `velov`, et `mark_stale_if_old()` parcourt explicitement ces deux noms. Cette logique devient fragile dès l'ajout de deux providers.

- [ ] Ajouter `tcl_disruptions: ProviderResult[tuple[TransitDisruption, ...]]`.
- [ ] Ajouter `weather: ProviderResult[WeatherSnapshot]`.
- [ ] Refactorer la logique de stale pour ne plus coder en dur `("tcl", "velov")`.
- [ ] Conserver la sémantique V1 : un échec garde la dernière bonne donnée mais passe le provider en `error`.
- [ ] Tester `TransitDisruption.is_active()` :
  - sans dates ;
  - avant le début ;
  - pendant la période ;
  - après la fin ;
  - début sans fin ;
  - fin sans début.
- [ ] Vérifier que l'échec d'un provider n'affecte aucun autre slot.

**Critère de validation :** l'état supporte quatre providers indépendants sans branche spéciale dans le scheduler.

---

## Task 3 — Parser et normaliser SIRI Situation Exchange

**Fichiers :**

- Create: `src/eink_dashboard/providers/tcl_sx/__init__.py`
- Create: `src/eink_dashboard/providers/tcl_sx/schemas.py`
- Create: `src/eink_dashboard/providers/tcl_sx/mapper.py`
- Create: `tests/unit/test_tcl_sx_mapper.py`
- Use: `tests/fixtures/tcl_situation_exchange*.json`

**Principe :** rien hors de `providers/tcl_sx/` ne connaît la structure SIRI brute.

- [ ] Écrire les modèles Pydantic à partir de la capture, avec `extra="ignore"`.
- [ ] Tolérer les champs optionnels absents.
- [ ] Mapper les `LineRef` externes vers `T2` / `D` via la configuration.
- [ ] Ignorer toutes les autres lignes.
- [ ] Extraire le meilleur texte disponible avec un ordre de fallback documenté :
  1. résumé court si présent ;
  2. description ;
  3. conséquence / advice si c'est le seul texte utile ;
  4. fallback `Perturbation signalée`.
- [ ] Normaliser les espaces et sauts de ligne.
- [ ] Dédupliquer par `source_id`.
- [ ] Exclure les situations expirées.
- [ ] Garder les situations actives.
- [ ] Pour les perturbations planifiées futures, ne les afficher que si elles commencent dans une fenêtre configurable raisonnable ; défaut V2 : `2 h`.
- [ ] Ne jamais faire de filtrage de ligne par simple recherche de `"D"` dans un texte libre.

**Tests minimaux :**

- [ ] perturbation T2 active ;
- [ ] perturbation métro D active ;
- [ ] même situation affectant T2 et D ;
- [ ] ligne non suivie ignorée ;
- [ ] situation expirée ignorée ;
- [ ] future trop lointaine ignorée ;
- [ ] texte manquant ;
- [ ] période sans `EndTime` ;
- [ ] doublon de `SituationNumber`.

**Critère de validation :** une fixture SIRI brute produit un tuple de `TransitDisruption` stable, indépendant du fournisseur.

---

## Task 4 — Client HTTP SIRI-SX

**Fichiers :**

- Create: `src/eink_dashboard/providers/tcl_sx/client.py`
- Create: `tests/unit/test_tcl_sx_client.py`
- Create: `tests/integration/test_tcl_sx_live.py`

Interface cible :

```python
class TclDisruptionsClient:
    name = "tcl_disruptions"

    async def fetch(self) -> tuple[TransitDisruption, ...]: ...
```

- [ ] Réutiliser le `httpx.AsyncClient` partagé.
- [ ] Réutiliser l'authentification Basic Grand Lyon.
- [ ] `raise_for_status()` sur réponse non 2xx.
- [ ] Laisser timeout / transport errors remonter au scheduler existant.
- [ ] Aucun retry local : le scheduler est déjà la boucle de récupération.
- [ ] Ajouter un test `401`.
- [ ] Ajouter un test timeout.
- [ ] Ajouter un test sur réponse vide valide.
- [ ] Ajouter un test réseau marqué `@pytest.mark.network`.

**Critère de validation :** le provider peut être branché au scheduler générique comme `tcl` et `velov`.

---

## Task 5 — Provider météo Open-Meteo

**Fichiers :**

- Create: `src/eink_dashboard/providers/weather/__init__.py`
- Create: `src/eink_dashboard/providers/weather/schemas.py`
- Create: `src/eink_dashboard/providers/weather/mapper.py`
- Create: `src/eink_dashboard/providers/weather/client.py`
- Create: `tests/fixtures/open_meteo_forecast.json`
- Create: `tests/unit/test_weather_mapper.py`
- Create: `tests/unit/test_weather_client.py`
- Optional: `tests/integration/test_weather_live.py`

Interface cible :

```python
class WeatherClient:
    name = "weather"

    async def fetch(self) -> WeatherSnapshot: ...
```

- [ ] Requête minimale à `/v1/forecast`.
- [ ] `timezone=Europe/Paris`.
- [ ] Température actuelle uniquement.
- [ ] Précipitations horaires uniquement sur la fenêtre utile.
- [ ] Mapper la première pluie actionnable vers `rain_at`.
- [ ] Tester :
  - pas de pluie ;
  - pluie dans 1 h ;
  - pluie sous le seuil de probabilité ;
  - probabilité forte mais précipitation nulle ;
  - heure locale correctement timezone-aware ;
  - données malformées.

**Critère de validation :** le domaine météo ne dépend pas du schéma Open-Meteo.

---

## Task 6 — Câbler les quatre providers et exposer leur santé

**Fichiers :**

- Modify: `src/eink_dashboard/main.py`
- Modify: `src/eink_dashboard/services/dashboard.py`
- Modify: `src/eink_dashboard/api/routes/health.py`
- Modify: `src/eink_dashboard/api/routes/dashboard.py`
- Modify: `tests/unit/test_api_dashboard.py`
- Modify/Create: tests de lifespan si présents

- [ ] Instancier :
  - `VelovClient`;
  - `TclClient`;
  - `TclDisruptionsClient`;
  - `WeatherClient`.
- [ ] Garder une tâche asyncio indépendante par provider.
- [ ] Ajouter `tcl_disruptions` et `weather` au `/health`.
- [ ] Ajouter leur état normalisé à `/api/v1/dashboard`.
- [ ] Vérifier que `weather` peut être désactivé par absence de config sans faire tomber le démarrage.
- [ ] Vérifier que perturbations sans mapping de ligne explicite produisent une erreur de configuration claire, pas un faux “trafic normal”.

**Critère de validation :** couper un fournisseur ne fait pas tomber le conteneur ni les trois autres sources.

---

## Task 7 — ViewModel V2 : simplification et règles contextuelles

**Fichiers :**

- Modify: `src/eink_dashboard/render/viewmodel.py`
- Modify: `tests/unit/test_viewmodel.py`

### 7.1 Passages

- [ ] Supprimer le titre d'arrêt de l'écran principal.
- [ ] Produire une `DepartureRow` par couple ligne/direction.
- [ ] Appliquer les aliases configurés :
  - `Saint-Priest …` → `St-Priest`;
  - direction vers Hôtel de Région / Perrache → `Perrache`.
- [ ] Premier passage dans `first_wait`.
- [ ] Trois passages suivants max dans `next_waits`.
- [ ] `0 min` reste `à quai`.
- [ ] Ne pas fabriquer de départ si la source est vide.

### 7.2 Vélo'v

- [ ] `BikeRow` contient uniquement label, nombre de vélos et état stale.
- [ ] Ne plus inclure `docks` ni `capacity` dans `content_hash()`.
- [ ] Formater correctement `0 vélo`, `1 vélo`, `N vélos`.

### 7.3 Perturbations

- [ ] Garder uniquement les alertes actives/actionnables.
- [ ] Limiter l'affichage à **2 lignes d'alerte**.
- [ ] Priorité :
  1. perturbation active maintenant ;
  2. sévérité la plus forte si exploitable ;
  3. T2 et D à priorité équivalente ;
  4. ordre stable par identifiant pour éviter les changements d'image arbitraires.
- [ ] Si une même situation affecte T2 et D, produire une seule ligne `T2/D`.
- [ ] Tronquer le texte au niveau ViewModel seulement selon une limite de caractères de sécurité ; le layout reste responsable de la largeur pixel réelle.
- [ ] `provider ok + zéro perturbation` → `alerts=()` et `traffic_note=""`.
- [ ] `provider stale/error` → `traffic_note="Info trafic indisponible"`.

### 7.4 Météo

- [ ] Température arrondie à l'entier le plus proche.
- [ ] `rain_at` présent → `Pluie vers HHh`.
- [ ] `rain_at` absent → `Sec`.
- [ ] stale/error → `Météo indisponible`.

### 7.5 Hash

- [ ] Le hash inclut départs, vélos, alertes, météo et notes de disponibilité.
- [ ] `as_of` reste exclu.
- [ ] Un changement de docks Vélo'v seul ne change pas le hash.
- [ ] Une nouvelle perturbation T2 ou D change le hash.
- [ ] Une perturbation expirée retirée change le hash.

**Critère de validation :** le ViewModel décrit exactement l'écran et aucune donnée invisible ne déclenche un refresh e-ink.

---

## Task 8 — Refaire le layout Pillow en zones fixes

**Fichiers :**

- Modify: `src/eink_dashboard/render/layout.py`
- Modify: `tests/unit/test_layout.py`

Répartition indicative sur 800×480 :

```text
y=20..68    Header : LYON + heure
y=82..180   T2 : deux lignes
y=205       Séparateur optionnel
y=220..310  Vélo'v : titre + deux stations
y=330       Séparateur
y=346..425  Zone contextuelle : perturbations
y=440..475  Météo / état source
```

Ne pas figer les valeurs avant validation visuelle ; les constantes de layout doivent être nommées.

### 8.1 Transit

- [ ] Afficher `T2 → destination` à gauche.
- [ ] Utiliser une police bold plus importante pour `first_wait`.
- [ ] Afficher les passages suivants dans une police légèrement plus petite.
- [ ] Aligner les horaires sur une grille stable pour éviter l'impression de “texte qui flotte”.
- [ ] Ne plus dessiner `StopBlock.title`.

### 8.2 Vélo'v

- [ ] Titre `VÉLO'V`.
- [ ] Label station à gauche.
- [ ] Nombre de vélos aligné à droite.
- [ ] Aucun nombre de places.
- [ ] Le `0` doit être très visible sans dépendre de couleur ou de niveaux de gris.

### 8.3 Zone contextuelle

- [ ] Perturbations avant météo.
- [ ] Une ligne par alerte si deux alertes courtes.
- [ ] Si une alerte nécessite deux lignes, elle prend toute la zone et la deuxième alerte est omise.
- [ ] Utiliser `⚠` uniquement après avoir vérifié son rendu correct dans la police embarquée ; sinon utiliser un fallback ASCII ou un petit pictogramme dessiné avec Pillow.
- [ ] Pas de scroll, pas de texte hors canvas.
- [ ] Le renderer doit rester déterministe.

### 8.4 Cas dégradés

Tester des screenshots/fixtures pour :

- [ ] état nominal sans perturbation ;
- [ ] perturbation T2 ;
- [ ] perturbation D ;
- [ ] perturbations T2 + D simultanées ;
- [ ] info trafic indisponible ;
- [ ] météo indisponible ;
- [ ] 0 vélo ;
- [ ] libellé station trop long ;
- [ ] direction trop longue ;
- [ ] quatre horaires de passage ;
- [ ] aucune donnée TCL.

**Critère de validation :** la donnée utile se lit en environ deux secondes à distance d'usage réelle.

---

## Task 9 — API appareil, image cache et cadence e-ink

**Fichiers :**

- Modify si nécessaire: `src/eink_dashboard/api/routes/device.py`
- Modify: tests de `content_hash`, image/cache et `/api/display`

La V1 utilise le hash du ViewModel dans le `filename`. Conserver ce principe.

- [ ] Vérifier que l'ajout des providers ne force pas un nouveau BMP à chaque polling.
- [ ] Vérifier que l'heure seule ne modifie pas le hash.
- [ ] Vérifier qu'un nombre de places Vélo'v seul ne modifie pas le hash.
- [ ] Vérifier qu'un changement de nombre de vélos modifie le hash.
- [ ] Vérifier qu'une perturbation ajoutée/supprimée modifie le hash.
- [ ] Vérifier qu'un passage qui se rapproche et change de libellé minute modifie le hash comme attendu.
- [ ] Conserver le `refresh_rate` existant sauf besoin mesuré.

Option d'amélioration ultérieure, hors V2 : cadence adaptative plus agressive lorsqu'un tram est à moins de 5 minutes.

---

## Task 10 — Validation end-to-end

- [x] `pytest -v` (213 tests, 4 `network` désélectionnés)
- [x] `mypy --strict src/`
- [x] `ruff check .`
- [x] `ruff format --check .`
- [ ] `docker compose up -d --build` — non exécuté ici (pas de Docker dans
      l'environnement) ; à valider par l'utilisateur
- [x] `/health`, `/api/v1/dashboard`, `/preview.png`, `/api/display` + BMP servi :
      couverts par `tests/unit/test_e2e_v2.py` à travers `lifespan`
- [ ] Affichage sur le XIAO + cycle veille→réveil : matériel, à valider par
      l'utilisateur
- [x] Timeout SIRI-SX → `Info trafic indisponible` (viewmodel + e2e)
- [x] Perturbation T2 / métro D, 0 vélo, pluie < 2 h : couverts par les tests
      viewmodel et layout
- [x] Suppression d'infos invisibles → moins de changements de hash
      (`test_device_api.py`)
- [ ] Vérifier `/health`.
- [ ] Vérifier `/api/v1/dashboard`.
- [ ] Vérifier `/preview.png` en 800×480 natif.
- [ ] Vérifier un BMP réellement servi via `/api/display`.
- [ ] Afficher la V2 sur le XIAO.
- [ ] Observer au moins un cycle complet veille → réveil → download → affichage → sommeil.
- [ ] Simuler un timeout SIRI-SX et vérifier `Info trafic indisponible`.
- [ ] Simuler une perturbation T2.
- [ ] Simuler une perturbation métro D.
- [ ] Simuler 0 vélo à Blandan.
- [ ] Simuler pluie dans moins de 2 h.
- [ ] Vérifier que la suppression d'informations invisibles réduit bien les changements de hash inutiles.

**Definition of Done :**

1. L'écran ne répète plus `Route de Vienne`.
2. Les deux directions T2 sont immédiatement identifiables.
3. Le premier tram est visuellement prioritaire.
4. Vélo'v n'affiche que l'information utile au départ.
5. Une perturbation active du T2 apparaît.
6. Une perturbation active du métro D apparaît.
7. L'absence de perturbation n'occupe aucun espace.
8. Une panne du flux SIRI-SX n'est jamais interprétée comme “trafic normal”.
9. Température et pluie court terme sont visibles sans transformer l'écran en widget météo.
10. Le firmware et le protocole TRMNL ne changent pas.
11. Aucun changement de donnée invisible ne déclenche un nouveau hash d'image.
12. Toute la suite de qualité V1 reste verte.

---

# 8. Ordre recommandé des commits

```text
feat: extend dashboard configuration for v2
feat: add disruptions and weather domain state
feat: add TCL SIRI-SX disruption provider
feat: add Open-Meteo provider
feat: expose v2 providers in dashboard state
refactor: simplify dashboard viewmodel
feat: redesign eink layout for compact mobility view
test: cover v2 degraded states and eink refresh behavior
```

Ne pas mélanger la capture/mapping SIRI-SX et le redesign Pillow dans le même commit : si le rendu est mauvais, il doit pouvoir être corrigé sans toucher au parsing transport.

# 9. Risques et points de vigilance

| Risque | Impact | Réponse |
|---|---|---|
| `LineRef` SIRI différent de `T2` / `D` | alertes absentes ou mauvaises | capture réelle obligatoire avant mapping |
| schéma SIRI-SX très imbriqué / champs optionnels | parser fragile | Pydantic permissif aux extras + mapper isolé |
| messages TCL très longs | overflow 800×480 | résumé + troncature pixel + max 2 alertes |
| provider SIRI en erreur interprété comme zéro incident | faux sentiment de normalité | état `traffic_note` explicite |
| docks Vélo'v changent souvent | refresh e-ink inutile | retirer docks/capacity du ViewModel/hash |
| météo trop bavarde | perte de lisibilité | température + pluie uniquement |
| changement de structure de l'état | régression scheduler/health | refactor générique + tests |
| symbole `⚠` mal rendu sur e-ink | carré vide | test police ou pictogramme Pillow |
| deux incidents + météo dépassent la zone | texte coupé | politique de priorité explicite |
| future perturbation planifiée trop lointaine | bruit permanent | fenêtre future limitée, défaut 2 h |

# 10. Améliorations après V2

À ne pas inclure dans cette implémentation, mais l'architecture doit les permettre :

1. **V2.1 — météo conditionnelle** : masquer complètement `Sec` et n'afficher la météo que si pluie, chaleur/froid notable ou autre condition actionnable.
2. **V2.2 — alertes de disponibilité Vélo'v** : afficher une alerte contextuelle seulement si toutes les stations suivies sont à 0 ou hors service.
3. **V2.3 — stratégie de départ** : petit résumé dérivé `T2 dans 2 min · Blandan 0 vélo` sans calcul d'itinéraire complexe.

# 12. Deltas d'implémentation

## Delta phase 9 — configuration V2 (Task 1)

- `core/config.py` : nouveaux modèles `DirectionAlias`, `DisruptionLine`,
  `DisruptionsConfig` (avec `future_window_hours`, défaut 2, et garde-fou
  « un `LineRef` → un seul label interne »), `WeatherConfig` (bornes
  lat/lon/lookahead/seuil). `DashboardConfig` gagne `direction_aliases`,
  `disruptions`, `weather` (tous optionnels → TOML V1 inchangé) et un helper
  `alias_for(direction)`.
- `Settings` : `tcl_disruptions_refresh_seconds` (120), `weather_refresh_seconds`
  (600), tous deux `> 0`.
- `validate_runtime_requirements` refuse une ligne de perturbation suivie sans
  `LineRef` mappé (évite un faux « trafic normal »).
- `config/dashboard.toml` réel : alias St-Priest/Perrache, `[tcl.disruptions]`
  T2+D, `[weather]` proche des arrêts. `LineRef` D confirmé par capture réelle,
  T2 selon la convention T4/T7 (à confirmer sur une vraie perturbation T2).
- `.env.example` et `tests/fixtures/dashboard_ok.toml` étendus.

## Delta phase 10 — domaine et état V2 (Task 2)

- `domain/disruptions.py` : `TransitDisruption` (frozen/slots) + `is_active(now)`
  (période stricte ; dates absentes = actif ; début ou fin seul supporté).
- `domain/weather.py` : `WeatherSnapshot` (température, `rain_at`, `reported_at`).
- `state.py` : `DashboardState` gagne `tcl_disruptions` et `weather`. Aucune
  refonte du stale nécessaire — `Store._slot` est déjà générique (`getattr`), le
  scheduler tourne déjà une tâche par provider. Sémantique V1 conservée : un
  échec garde la dernière bonne donnée et passe le slot en `error`.

## Delta phase 11 — provider SIRI-SX (Tasks 0, 3, 4)

- Capture réelle : `tests/fixtures/tcl_situation_exchange.json` + fixture
  synthétique `tcl_situation_exchange_t2_d.json`. Chemins et champs documentés
  dans `docs/tcl-sx-api-notes.md`. Constat clé : **aucun champ de sévérité ni de
  cause** — le seul texte est `Description` (parfois du HTML). `LineRef` métro D
  confirmé (`ActIV:Line::D:SYTRAL`), T2 par convention T4/T7.
- `providers/tcl_sx/schemas.py` : modèles Pydantic permissifs (`extra="ignore"`,
  branches absentes tolérées), `SiriDocument.situations()` aplatit l'arbre.
- `providers/tcl_sx/mapper.py` : `to_disruptions(document, config, now)` — mappe
  les `LineRef` via la config uniquement (jamais de sous-chaîne dans le texte),
  nettoie le HTML, déduplique par `SituationNumber`, exclut expirées et futures
  au-delà de `future_window_hours`, trie par `source_id`.
- `providers/tcl_sx/client.py` : `TclDisruptionsClient` (Basic auth Grand Lyon,
  `raise_for_status`, aucun retry local — timeouts/erreurs remontent au
  scheduler). Retourne un `ProviderSnapshot` pour se brancher comme `tcl`/`velov`.
- Tests : `test_tcl_sx_mapper.py` (9 scénarios + capture réelle),
  `test_tcl_sx_client.py` (auth, 401, timeout, corps vide),
  `tests/integration/test_tcl_sx_live.py` (`@pytest.mark.network`).

## Delta phase 12 — provider météo Open-Meteo (Task 5)

- `providers/weather/schemas.py` : `ForecastFeed` (`current.temperature_2m`,
  `hourly.time/precipitation_probability/precipitation`), `extra="ignore"`,
  probas nullables tolérées.
- `providers/weather/mapper.py` : `to_weather_snapshot(feed, config, now, tz)` —
  température actuelle + `reported_at` tz-aware ; `rain_at` = première heure dans
  `[heure courante, now + lookahead_hours]` avec `proba >= seuil` **et**
  `precip > 0`.
- `providers/weather/client.py` : `WeatherClient` (sans secret), requête minimale
  `/v1/forecast` (`current=temperature_2m`, `hourly=precipitation_probability,
  precipitation`, `timezone=Europe/Paris`, `forecast_days=2`).
- Tests mapper (pas de pluie, pluie proche, sous le seuil, proba forte sans
  précipitation, tz-aware, payload malformé), client (params, erreur HTTP),
  live `@pytest.mark.network`.

## Delta phase 13 — câblage des 4 providers (Task 6)

- `main.py` : instancie `TclDisruptionsClient` (si `[tcl.disruptions].lines`) et
  `WeatherClient` (si `[weather]`), une tâche asyncio par provider. `tz` partagé.
- `services/dashboard.py` : `dashboard_payload` gagne `tcl_disruptions` (liste des
  perturbations normalisées + santé) et `weather` (snapshot + santé), avec deux
  nouveaux seuils de fraîcheur en kwargs.
- `/health` expose `tcl_disruptions` et `weather`.
- Absence de `[weather]` / `[tcl.disruptions]` → démarrage normal (providers non
  instanciés). Perturbations suivies sans `LineRef` → `validate_runtime_requirements`
  lève au démarrage (pas de faux « trafic normal »).

## Delta phase 14 — ViewModel V2 (Task 7)

- `render/viewmodel.py` réécrit : `DepartureRow` (ligne/direction aliasée,
  `first_wait` + 3 suivants max, pas de titre d'arrêt), `BikeRow` (label, nombre
  de vélos, `stale` — plus de `docks`/`capacity`), `AlertRow`, `WeatherRow`,
  `DashboardView(as_of, departures, bikes, alerts, weather, traffic_note)`.
- `content_hash()` couvre départs + vélos + alertes + météo + `traffic_note`,
  exclut `as_of`. Un changement de `docks` seul ne bouge plus le hash.
- Alertes : actives uniquement, une par jeu de lignes (plus ancienne `source_id`),
  max 2, `T2/D` fusionné, texte tronqué à 110 car. `provider ok + 0` →
  `alerts=()`, `traffic_note=""` ; `provider stale/error` → `traffic_note="Info
  trafic indisponible"` ; provider non configuré → jamais de note.
- Météo : température arrondie, `Pluie vers HHh` / `Sec`, stale/error →
  `Météo indisponible`, non configurée → `weather=None`.
- `build_view` prend désormais la `DashboardConfig` (aliases + activation).
  `app.state.config` + `ConfigDep` ; helper `services.dashboard.view_for`.
  `render/layout.py` adapté aux nouveaux types (le redécoupage en zones fixes
  et les fixtures d'états dégradés sont la phase 15).

## Delta phase 15 — layout Pillow en zones fixes (Task 8)

- `render/layout.py` réécrit avec des constantes de zones nommées
  (`HEADER/TRANSIT/BIKES/CONTEXT/WEATHER _TOP/_BOTTOM`).
- Transit : `T2 → destination` à gauche, `first_wait` en gras 36 px, passages
  suivants en 22 px alignés à droite, plus de titre d'arrêt.
- Vélo'v : titre, label à gauche, nombre de vélos en gras aligné à droite, le
  `0` reste très lisible sans niveaux de gris.
- Zone contextuelle : perturbations avant météo, 1 ligne par alerte courte ; une
  alerte qui déborde sur 2 lignes prend toute la zone et la 2ᵉ est omise ;
  `traffic_note` sinon. `⚠` vérifié présent dans DejaVu Sans, avec repli `!`
  via `_glyph_or`. Pas de scroll, tout tronqué à la largeur pixel, rendu
  déterministe.
- `tests/unit/test_layout.py` : 13 scénarios paramétrés (nominal, T2, D, T2+D,
  info trafic indisponible, météo indisponible, 0 vélo, libellés longs, 4
  passages, aucune donnée TCL, alerte longue) — chacun rend une frame complète,
  déterministe, et toutes distinctes.

## Delta phase 16 — cadence e-ink et validation e2e (Tasks 9, 10)

- `tests/unit/test_device_api.py` : `/api/display` sert une image cachée stable
  tant que l'état ne change pas ; un changement de places Vélo'v seul ne change
  pas le `filename`, un changement de nombre de vélos ou l'ajout/retrait d'une
  perturbation si ; un passage qui franchit une minute change l'image.
  `refresh_rate` inchangé (Task 9 n'ajoute pas de cadence adaptative).
- `tests/unit/test_e2e_v2.py` : les 4 providers câblés via `lifespan`, `/health`
  + `/api/v1/dashboard` + `/preview.png` + `/api/display` + `/image/...`
  servis ; un timeout SIRI-SX laisse `tcl_disruptions` en erreur et n'est jamais
  présenté comme « trafic normal ».
- Non exécuté ici : `docker compose up`, affichage réel sur le XIAO
  (voir Task 10).

## État final

Suite : **213 passés**, `mypy --strict` et `ruff` propres. Les 12 points de la
*Definition of Done* sont couverts par les tests sauf les 2 items matériel/Docker.

# 11. Sources techniques

- Design V1 du projet : `docs/superpowers/specs/2026-09-02-eink-dashboard-lyon-design.md`
- Plan V1 du projet : `docs/superpowers/plans/2026-09-02-eink-dashboard-lyon.md`
- Data Grand Lyon — SIRI Situation Exchange : `https://data.grandlyon.com/siri-lite/2.0/situation-exchange.json`
- Profil SIRI France / Situation Exchange : `https://transport.data.gouv.fr/`
- Open-Meteo Forecast API : `https://open-meteo.com/en/docs`
