# Dashboard e-ink Lyon — Design V1

Date : 2026-09-02
Statut : approuvé
Cible matérielle : Seeed Studio XIAO 7.5" ePaper Panel (ESP32-C3, 800x480 monochrome, batterie 2000 mAh)

## 1. Objectif

Afficher sur un panneau e-ink mural, en continu et sans intervention, les prochains
passages TCL d'un ensemble d'arrêts configurables et la disponibilité de deux stations
Vélo'v de la Métropole de Lyon.

Un conteneur Docker sur le serveur domestique porte l'intégralité de la logique.
Le panneau reste un client passif.

## 2. Décisions structurantes

### 2.1 Rendu image côté serveur, pull par le panneau

Le backend génère une image BMP 1 bit 800x480 et l'expose. Le panneau la télécharge
et l'affiche.

Les trois options envisagées (pull JSON, push, image) mélangeaient deux axes
indépendants : qui initie la connexion, et ce qui transite. La décision retenue est
pull sur le premier axe, image sur le second.

| Critère | Pull JSON | Push | Image pull |
|---|---|---|---|
| Firmware à écrire | Mise en page en C++ | Oui | Aucun |
| Boucle de développement | Flash ~20 s par essai | Idem | Ouvrir un PNG |
| Sommeil profond | Compatible | Incompatible | Compatible |
| Panneau injoignable | Sans effet | Casse le flux | Sans effet |
| Logique métier embarquée | Beaucoup | Beaucoup | Nulle |

Le push est éliminé par la physique : le panneau dort plus de 99 % du temps, le maintenir
joignable épuise la batterie en quelques jours.

Le pull JSON imposerait d'écrire la mise en page en C++ sur ESP32-C3, avec un cycle de
test de vingt secondes par itération.

### 2.2 Protocole TRMNL

Le firmware TRMNL, officiellement supporté par Seeed sur ce panneau, implémente déjà
le comportement voulu. Le backend implémente son contrat serveur (BYOS, Bring Your Own
Server) :

| Endpoint | Méthode | En-têtes reçus | Réponse |
|---|---|---|---|
| `/api/setup` | GET | `ID` (MAC) | `status`, `api_key`, `friendly_id`, `image_url`, `filename` |
| `/api/display` | GET | `ID`, `Access-Token`, `Refresh-Rate`, `Battery-Voltage`, `FW-Version`, `RSSI` | `status`, `image_url`, `filename`, `refresh_rate`, `update_firmware`, `firmware_url`, `reset_firmware` |
| `/api/log` | POST | `ID`, `Access-Token` | 204 |
| `/image/{name}.bmp` | GET | — | BMP 1 bit 800x480 |

Implémentation de référence : `usetrmnl/byos_fastapi` (FastAPI, Pillow, httpx).

Deux champs du protocole servent directement les contraintes e-ink :

- `refresh_rate` est décidé par le serveur à chaque appel. La cadence de réveil devient
  de la logique Python testable.
- `filename` identifie le contenu. En y plaçant un hachage du ViewModel, un état inchangé
  produit le même nom, ce qui évite un redessin inutile.

Risque ouvert, à lever en phase 6 : la documentation ne confirme pas que le firmware
saute effectivement le redessin sur `filename` identique, ni qu'une URL de serveur
personnalisée soit configurable depuis le portail captif sans recompilation.

### 2.3 Aucune base de données, aucun volume

L'état tient dans une dataclass en mémoire, reconstruite en quelques secondes au
démarrage. Le registre des appareils TRMNL, que l'implémentation de référence stocke en
SQLite, se réduit à deux variables d'environnement puisqu'il n'y a qu'un seul panneau.

Les mesures de batterie et de RSSI sont journalisées, pas stockées.

## 3. Sources de données vérifiées

### 3.1 Vélo'v — ouvert

Flux GBFS v3 public, sans authentification. Vérifié en direct le 2026-09-02.

| Flux | URL | TTL |
|---|---|---|
| Statut | `https://api.cyclocity.fr/contracts/lyon/gbfs/v3/station_status.json` | 1 s |
| Référentiel | `https://api.cyclocity.fr/contracts/lyon/gbfs/v3/station_information.json` | 300 s |

Champs utiles du statut : `station_id`, `num_vehicles_available`, `num_docks_available`,
`vehicle_types_available` (répartition mécanique / électrique), `is_renting`,
`is_returning`, `last_reported`.

Champs utiles du référentiel : `station_id`, `name`, `address`, `capacity`, `lat`, `lon`.

Le référentiel est appelé beaucoup plus rarement que le statut.

### 3.2 TCL — authentification requise

Compte data.grandlyon.com obligatoire, authentification HTTP Basic. Licence Mobilités.
Vérifié : les deux endpoints renvoient 401 sans identifiants.

Jeu retenu : `tcl_sytral.tclpassagearret`, via
`https://download.data.grandlyon.com/ws/rdata/tcl_sytral.tclpassagearret/all.json`.

Paramètres de requête disponibles : `maxfeatures`, `start`, `field` / `value`,
filtres `field__operator` (`eq`, `gt`, `gte`, `lt`, `lte`, `in`), `compact`.

Ce jeu est filtrable par identifiant de point d'arrêt, contrairement au service
SIRI-Lite `estimated-timetables` qui déverse l'intégralité du réseau. Il n'existe pas
de service SIRI stop-monitoring sur cette plateforme.

Réseau unifié le 1er septembre 2025 : les jeux Libellule et Cars du Rhône ont fusionné
dans les jeux TCL, les URLs sont inchangées, et l'attribut `coursetheorique` contient
désormais l'identifiant de route GTFS exact.

Aucun quota chiffré n'est publié.

### 3.3 Sources différées

- Perturbations : `https://data.grandlyon.com/siri-lite/2.0/situation-exchange.json`
  (même authentification).
- Météo, qualité de l'air, événements : non traités en V1.

## 4. Architecture

```text
   TCL (Basic auth)        Vélo'v GBFS v3 (ouvert)
   tclpassagearret         station_status + station_information
          |                          |
          |   60 s                   |   60 s
          v                          v
   +----------------------------------------------+
   |            Conteneur Docker                  |
   |                                              |
   |  boucles asyncio  -->  clients + mappers     |
   |                            |                 |
   |                            v                 |
   |                    DashboardState            |
   |                  (mémoire, daté par source)  |
   |                            |                 |
   |            +---------------+-----------+     |
   |            v               v           v     |
   |       ViewModel      /api/v1/      /preview  |
   |            |         dashboard      .png     |
   |            v          (debug)       (dev)    |
   |       Pillow --> BMP 1-bit 800x480           |
   |            |                                 |
   |       FastAPI: /api/setup /api/display       |
   |                /api/log  /image/*.bmp        |
   +--------------------+-------------------------+
                        |  le panneau appelle
                        v
              +----------------------+
              |  XIAO 7.5" ePaper    |
              |  firmware TRMNL      |
              |  réveil -> GET -> BMP|
              |  -> affiche -> dort  |
              +----------------------+
```

## 5. Structure du repository

```text
eink-dashboard/
├── pyproject.toml
├── Dockerfile
├── compose.yaml
├── .env.example
├── config/
│   └── dashboard.toml
├── src/eink_dashboard/
│   ├── main.py
│   ├── core/
│   │   ├── config.py
│   │   └── logging.py
│   ├── providers/
│   │   ├── base.py
│   │   ├── tcl/          client.py · schemas.py · mapper.py
│   │   └── velov/        client.py · schemas.py · mapper.py
│   ├── domain/
│   │   ├── transit.py
│   │   ├── bikes.py
│   │   └── dashboard.py
│   ├── services/dashboard.py
│   ├── state.py
│   ├── scheduler.py
│   ├── render/
│   │   ├── viewmodel.py
│   │   ├── layout.py
│   │   └── fonts/
│   └── api/
│       ├── deps.py
│       └── routes/       health.py · dashboard.py · device.py
├── tests/                unit/ · integration/ · fixtures/
└── docs/
```

Responsabilités :

- `core/` — configuration Pydantic et logs structurés. Aucune dépendance vers le reste.
- `providers/` — un package par fournisseur, trois fichiers : appel HTTP (`client.py`),
  modèles du format externe (`schemas.py`), transformation vers le domaine (`mapper.py`).
  Rien en dehors de ce package ne connaît le JSON du fournisseur.
- `providers/base.py` — un `Protocol` à trois membres : `name`, `interval`, `fetch()`.
  Seule abstraction créée d'avance, justifiée par l'exigence d'ajout facile de sources.
- `domain/` — modèles métier internes, indépendants des fournisseurs.
- `services/dashboard.py` — assemblage de l'état et construction du ViewModel.
- `state.py` — l'état en mémoire et les `ProviderResult`.
- `scheduler.py` — les boucles asyncio, une par fournisseur.
- `render/` — `viewmodel.py` est pur et testable sans Pillow ; `layout.py` dessine.
- `api/routes/` — santé, JSON de debug, protocole appareil.

Écarts assumés par rapport à la structure initialement envisagée :

1. `display/transport.py` supprimé. En modèle pull il n'y a pas de transport vers le
   panneau, donc un mode de panne de moins.
2. `src/` devient `src/eink_dashboard/`, pour un empaquetage et des imports propres.
3. `clients/` devient `providers/`, avec la séparation format externe / domaine rendue
   visible dans l'arborescence.
4. `services/mobility.py` supprimé : les mappers font déjà la normalisation.
5. `infrastructure/` aplati en `state.py` et `scheduler.py`.

## 6. Configuration

Secrets et infrastructure par variables d'environnement, via `pydantic-settings` :

| Variable | Rôle |
|---|---|
| `GRANDLYON_USERNAME` / `GRANDLYON_PASSWORD` | Authentification Basic TCL |
| `DEVICE_MAC` | Adresse MAC du panneau, attendue en en-tête `ID` |
| `DEVICE_API_KEY` | Jeton pré-partagé rendu par `/api/setup` |
| `PUBLIC_BASE_URL` | Base des URLs d'image renvoyées au panneau |
| `TZ` | `Europe/Paris` |
| `LOG_LEVEL` | Niveau de journalisation |
| `TCL_REFRESH_SECONDS` / `VELOV_REFRESH_SECONDS` | Intervalles de récupération |
| `CONFIG_PATH` | Chemin du fichier TOML |

Contenu du dashboard par fichier TOML, chargé avec `tomllib` (stdlib) et validé par
Pydantic. Justification : la liste des arrêts est une structure imbriquée, illisible en
variables d'environnement.

```toml
[[tcl.stops]]
name = "Bellecour"
stop_id = "..."
lines = ["A", "D"]
directions = ["Vaulx-en-Velin", "Gare de Vénissieux"]

[[velov.stations]]
station_id = "1032"
label = "Pizay"
```

Aucun secret n'est versionné. `.env.example` documente les variables sans valeurs.

## 7. Flux de données

Cycle Vélo'v, de bout en bout :

1. La boucle asyncio du fournisseur se réveille au bout de son intervalle.
2. Le client appelle les deux flux GBFS avec l'`AsyncClient` partagé
   (timeout connect 5 s, read 10 s).
3. Les réponses sont validées par des modèles Pydantic qui reflètent le JSON de JCDecaux
   sans l'interpréter.
4. Le mapper croise statut et référentiel sur `station_id`, filtre sur les stations
   configurées, produit des `BikeStation` du domaine.
5. Le service écrit un `ProviderResult` dans l'état, statut `ok`, horodaté.

TCL suit le même chemin dans une boucle indépendante.

Cycle d'affichage :

1. Le panneau se réveille et appelle `/api/display`.
2. Le service construit un ViewModel à partir de l'état. Toutes les chaînes affichées
   y sont calculées : minutes restantes, marqueurs de fraîcheur, libellés tronqués.
3. Le ViewModel est haché, ce qui donne `filename`.
4. Si l'image correspondante n'existe pas, Pillow la dessine en 800x480 monochrome.
5. La réponse renvoie l'URL du BMP et le `refresh_rate` adapté à l'heure courante.
6. Le panneau télécharge, affiche, se rendort.

Le hachage porte sur le ViewModel et non sur l'état : l'état contient des horodatages
qui changent à chaque cycle, le ViewModel contient « 3 min », qui ne change que quand
l'affichage change réellement.

## 8. Gestion des erreurs

| Situation | Comportement |
|---|---|
| TCL injoignable | Un réessai immédiat, puis abandon jusqu'au tick suivant. Dernier bon état conservé, statut `stale`. Vélo'v intact. |
| Vélo'v injoignable | Symétrique. TCL continue de s'afficher. |
| Les deux injoignables | Image quand même servie : en-tête, heure, dernières données connues, marqueur de fraîcheur par bloc. Jamais d'écran blanc, jamais d'erreur HTTP vers l'appareil. |
| Panneau injoignable | Rien à faire. En modèle pull le backend ne s'en aperçoit pas. |
| Format d'API modifié | `ValidationError` attrapée par la boucle, extrait du payload brut journalisé en erreur, statut `error`, dernier bon état conservé, boucle vivante. |
| Données anciennes | Au-delà de trois fois l'intervalle, bascule en `stale` même sans échec. L'heure de dernière mise à jour s'affiche à côté du bloc. |

Pas de backoff exponentiel ni de bibliothèque de retry : le tick suivant est à soixante
secondes, c'est déjà le backoff.

## 9. Observabilité

`/health` expose, par fournisseur, le statut (`ok` / `stale` / `error`), l'horodatage de
la dernière récupération réussie, et l'âge des données.

```json
{
  "tcl":   { "status": "ok",    "updated_at": "...", "age_seconds": 42 },
  "velov": { "status": "stale", "updated_at": "...", "age_seconds": 310 }
}
```

Logs structurés JSON via structlog. Les mesures de batterie et RSSI reçues sur
`/api/display` sont journalisées.

## 10. Cadence de rafraîchissement

Deux horloges découplées.

Données : 60 secondes pour les deux fournisseurs.

Écran, piloté par `refresh_rate` :

| Période | `refresh_rate` |
|---|---|
| 7h00–9h30 et 17h00–19h30 | 120 s |
| Reste de la journée | 300 s |
| 23h00–6h00 | 3600 s |

Le constructeur annonce environ 78 jours à 15 minutes d'intervalle, soit un budget de
l'ordre de 7 500 cycles. Ce profil consomme environ 300 cycles par jour, donc autour de
trois semaines sur batterie. Passer partout à 300 secondes double l'autonomie. Sur
secteur USB la question ne se pose pas.

## 11. Stack

| Besoin | Technologie | Justification |
|---|---|---|
| API HTTP | FastAPI | Protocole TRMNL en HTTP simple ; ASGI héberge le scheduler dans le même process |
| Client HTTP | httpx | Async, timeouts connect et read séparés, `AsyncClient` réutilisé |
| Modèles | Pydantic v2 | Valide les payloads ; un changement de format échoue proprement |
| Config secrets | pydantic-settings | Variables d'environnement typées |
| Config contenu | `tomllib` (stdlib) | Structure imbriquée, zéro dépendance |
| Scheduler | asyncio + lifespan FastAPI | ~40 lignes ; APScheduler apporterait du cron inutile |
| Cache | dataclass en mémoire | Un seul état, reconstruit en quelques secondes |
| Rendu | Pillow | BMP 1 bit natif, polices TrueType |
| Logs | structlog | JSON en une ligne de config |
| Tests | pytest, pytest-asyncio, respx | respx intercepte httpx au niveau transport |
| Lint et format | ruff | Un seul outil |
| Typage | mypy strict sur `src/` | Projet petit, strict tenable |
| Conteneur | Docker, compose | Serveur domestique |

Explicitement exclus : PostgreSQL, Redis, Celery, Kafka, Airflow, SQLite, APScheduler,
pandas, bibliothèque de retry.

## 12. Stratégie de tests

Aucun test unitaire ne fait d'appel réseau réel. respx intercepte httpx.

- Fixtures JSON capturées sur les flux réels, versionnées dans `tests/fixtures/`.
- Tests de parsing : les modèles fournisseurs acceptent les fixtures.
- Tests de normalisation : mappers vers le domaine, y compris cas limites (station absente
  du référentiel, station hors service, aucun passage à venir).
- Tests d'erreur réseau : timeout, 401, 500, JSON malformé, schéma modifié.
- Tests d'état : transitions `ok` / `stale` / `error`, isolation entre fournisseurs.
- Tests de ViewModel : purs, sans Pillow.
- Tests de layout : une ou deux images de référence.
- Tests d'intégration marqués `network`, exclus par défaut, exécutés à la demande.

## 13. Périmètre V1

À faire : phases 0 à 7 ci-dessous, deux sources, un appareil, pas de base de données,
pas de volume.

Différé : perturbations SIRI-Lite, météo, qualité de l'air, événements, persistance,
multi-appareil, distribution de firmware OTA, niveaux de gris.

## 14. Phases

Deux inversions par rapport au découpage initial : Vélo'v avant TCL, parce qu'il est
ouvert et valide le patron de client sans se battre avec l'authentification ; le rendu
avant le protocole appareil, parce qu'on itère sur l'image dans un navigateur sans
matériel.

| Phase | Objectif | Critère de validation |
|---|---|---|
| 0 | Squelette, config, logs, `/health`, Docker | `docker compose up` et `/health` répond 200 |
| 1 | Client Vélo'v, domaine, fixtures, tests | Les stations configurées remontent |
| 2 | Client TCL avec Basic auth, filtrage ligne et direction | Les prochains passages remontent |
| 3 | État, scheduler, service dashboard | `/health` reflète la réalité ; couper le réseau ne fait pas tomber le conteneur |
| 4 | `/api/v1/dashboard` | JSON contenant les deux sources et leurs statuts |
| 5 | ViewModel, layout Pillow, `/preview.png` | Page lisible à trois mètres dans le navigateur |
| 6 | `/api/setup`, `/api/display`, `/api/log`, service des BMP | Le panneau affiche le dashboard |
| 7 | Hachage du ViewModel dans `filename`, `refresh_rate` adaptatif | À contenu identique, le panneau ne clignote pas |

## 15. Sources

- Wiki Seeed XIAO 7.5" ePaper Panel — https://wiki.seeedstudio.com/xiao_075inch_epaper_panel/
- Firmware TRMNL — https://github.com/usetrmnl/trmnl-firmware
- BYOS FastAPI de référence — https://github.com/usetrmnl/byos_fastapi
- Documentation BYOS — https://docs.trmnl.com/go/diy/byos
- Authentification Data Grand Lyon — https://rdata-grandlyon.readthedocs.io/fr/latest/authentification.html
- Services Data Grand Lyon — https://rdata-grandlyon.readthedocs.io/fr/latest/services.html
- Réseau TCL sur transport.data.gouv.fr — https://transport.data.gouv.fr/datasets/horaires-theoriques-du-reseau-transports-en-commun-lyonnais
- GBFS Vélo'v — https://transport.data.gouv.fr/datasets/stations-velov-de-la-metropole-de-lyon-disponibilites-temps-reel
