# Dashboard e-ink Lyon — Plan d'implémentation ESPHome + Home Assistant

**Date :** 2026-09-03
**Révision :** v2 — Home Assistant comme orchestrateur
**Statut :** en cours sur la branche `feat/ha-esphome-migration`
**Cible matérielle :** Seeed Studio XIAO 7.5" ePaper Panel — ESP32-C3, 800×480 monochrome
**Firmware cible :** ESPHome (Native API chiffrée)
**Backend conservé :** Python 3.12 + FastAPI + Pillow
**Alimentation cible :** secteur USB-C permanent (deep sleep repoussé, voir §16)

> Cette révision remplace la couche appareil/TRMNL. Les providers métier
> (TCL, SIRI-SX, Vélo'v, météo), le `DashboardState`, le `DashboardView`,
> son `content_hash()` et le rendu Pillow restent **strictement inchangés**.

---

## 0. Ce que Home Assistant change par rapport à la v1 du plan

La v1 faisait de l'ESP32 un client HTTP autonome : il interrogeait le backend,
comparait le hash à une `global` persistée (`restore_value: yes`), gérait un
invariant « ne persister le hash qu'après affichage réussi », et pilotait son
propre deep sleep. Beaucoup de complexité vivait dans le YAML firmware.

Avec un Home Assistant déjà en place et le panneau **sur secteur**, on déplace
toute cette logique hors de l'ESP32 :

| Responsabilité | v1 (ESP autonome) | v2 (HA orchestrateur) |
|---|---|---|
| Savoir si l'écran doit changer | `global last_content_hash` sur l'ESP | comparaison de 2 sensors HA |
| Hash cible (contenu à jour) | GET HTTP depuis l'ESP | `rest` sensor HA sur `/api/v1/display/meta` |
| Hash réellement affiché | `global` persistée sur l'ESP | `text_sensor` publié par l'ESP après affichage |
| Décision de rafraîchir | machine à états en lambda C++ | 1 automation HA (2 sensors diffèrent) |
| Persistance après reboot | `restore_value` + invariant critique | aucune : au boot l'ESP retélécharge et republie |
| Cadence de réveil | deep sleep piloté par `refresh_seconds` | poll HA fixe (60 s) ; `refresh_seconds` redevient utile en mode batterie |
| Résistance panne backend | retry au réveil | `rest` sensor `unavailable` → automation inerte ; dernière image conservée |
| OTA malgré deep sleep | `deep_sleep.prevent` + `input_boolean` | pas de deep sleep → OTA trivial |

**Le firmware v2 ne contient aucune comparaison de hash, aucune `global`
persistée, aucune machine à états, aucun deep sleep.** Il expose un service
`refresh` et sait dessiner une image téléchargée. C'est tout.

**Le package HA v2 est minimal : 1 `rest` sensor + 1 automation + 1 script.**
Pas d'`input_text`, pas d'`input_boolean` : le hash affiché est porté par le
`text_sensor` de l'ESP lui-même, seule source de vérité de ce qui est à l'écran.

Tâches de la v1 **supprimées ou vidées** par ce choix : la machine à états
firmware (v1 Task 5), le durcissement de la persistance après deep sleep
(v1 Task 9), et la majeure partie de la section « ne pas dépendre du cache
ETag entre deux deep sleeps » (v1 §3).

---

## 1. Goal

Migrer le panneau XIAO du firmware TRMNL vers ESPHome, piloté par Home Assistant,
sans déplacer la logique métier ni le rendu graphique sur l'ESP32.

L'architecture cible doit :

- conserver FastAPI comme unique agrégateur de données ;
- conserver Pillow comme unique moteur de rendu 800×480 ;
- faire du XIAO un client d'affichage minimal, sans logique ;
- confier à Home Assistant la détection de changement et le déclenchement ;
- éviter tout refresh e-ink quand le contenu métier n'a pas changé ;
- résister à une panne backend sans effacer l'image affichée ;
- résister à une panne Home Assistant (dernière image conservée) ;
- conserver TRMNL intact tant que le test matériel n'est pas validé ;
- pouvoir abandonner la branche sans rien casser en cas d'échec matériel.

---

## 2. Architecture cible

```text
   TCL passages ───┐
   TCL SIRI-SX ────┤
   Vélo'v ─────────┼──► DashboardState ──► DashboardView ──► Pillow ──► BMP 1-bit 800×480
   Météo ──────────┘            │
                                └── content_hash()  (sha256[:16], déjà existant)

                    FastAPI expose (nouveau, additif) :
                      GET /api/v1/display/meta   -> { content_hash, refresh_seconds }
                      GET /image/dashboard.bmp   -> BMP 1-bit + ETag: "<hash>"

                                │
                                ▼
        ┌────────────────  HOME ASSISTANT  ────────────────┐
        │  sensor.…_target_hash  : rest, poll meta (60 s)   │
        │  sensor.…_content_hash : publié par l'ESP         │
        │  automation : target_hash renseigné ET            │
        │               target_hash != content_hash (ESP)   │
        │               -> esphome.eink_dashboard_refresh    │
        │  script     : force_refresh (debug)               │
        └────────────────────────┬─────────────────────────┘
                                 │ ESPHome Native API (chiffrée)
                                 ▼
                    ┌─────────────────────────┐
                    │ XIAO ESP32-C3 / ESPHome │
                    │  service: refresh(hash) │
                    │   -> online_image.update│
                    │   -> display.update     │
                    │   -> content_hash = hash│
                    │  diagnostics: RSSI, ... │
                    └───────────┬─────────────┘
                                ▼
                        ePaper 800×480
```

### 2.1 Ce qui reste côté Python (inchangé)

Providers, `DashboardState`, `Store`, `build_view`, `DashboardView.content_hash()`,
`render()`, `to_bmp_bytes()`, toute l'API TRMNL (`/api/setup`, `/api/display`,
`/api/log`, `/image/{name}`), `refresh_rate_for()`.

### 2.2 Ce qui est ajouté côté Python (additif, testable)

Un seul nouveau module de routes : `api/routes/display.py`.

- `GET /image/dashboard.bmp` — URL stable, `ETag: "<content_hash>"`,
  `Cache-Control: no-cache`, support `If-None-Match` → `304`.
- `GET /api/v1/display/meta` — `{ "content_hash": "...", "refresh_seconds": N }`.
  `refresh_seconds` = `refresh_rate_for(now)` existant, borné.

Aucune persistance serveur. Aucune base. Le hash et le BMP sont déjà produits
par le pipeline existant ; on les réexpose sous une URL découplée de TRMNL.

### 2.3 Ce qui passe côté ESPHome

Wi-Fi, Native API chiffrée, OTA, `online_image` (BMP BINARY), `display`
(`waveshare_epaper`, `7.50inv2`, `update_interval: never`), un service API
`refresh` (argument : `content_hash`), diagnostics. Rien d'autre.

### 2.4 Ce qui passe côté Home Assistant

Un package `homeassistant/eink_dashboard.yaml` : 1 `rest` sensor (hash cible),
1 automation (rafraîchir si le hash de l'ESP diffère du hash cible), 1 script de
refresh forcé (debug). Fourni prêt à copier ; HA n'est pas requis pour que
FastAPI fonctionne.

---

## 3. Contrat backend ↔ Home Assistant

### 3.1 `GET /api/v1/display/meta`

```json
{ "content_hash": "8c23ad0ff5e39142", "refresh_seconds": 300 }
```

**`content_hash`** — `DashboardView.content_hash()` tel quel (sha256 tronqué
16 hex). Change si une info visible change ; ne change pas si seule `as_of`
change ; ne change pas pour une donnée non affichée ; stable entre process.

**`refresh_seconds`** — `refresh_rate_for(now, has_event)`, borné côté serveur
(voir *Delta 2026-09-…* en fin de document) :

| Créneau | Valeur |
|---|---|
| 07:30–09:00 | 180 s |
| 09:00–21:00, rien à signaler | 1800 s |
| 09:00–21:00, perturbation active OU station Vélo'v < 3 | 300 s |
| 21:00–07:30 | secondes jusqu'à 07:30, plafonné 4 h |

En mode secteur (v2), HA poll à intervalle fixe et n'utilise ce champ que pour
information / debug ; il devient la cadence de réveil en mode batterie (§16).

### 3.2 `GET /image/dashboard.bmp`

```http
Content-Type: image/bmp
ETag: "8c23ad0ff5e39142"
Cache-Control: no-cache
```

Image : 800×480, BMP, 1 bit, monochrome — sortie directe de `to_bmp_bytes(render(view))`.
`If-None-Match: "<hash>"` identique → `304 Not Modified` (utilisé par le cache
HTTP interne d'`online_image`, non critique).

`/preview.png` reste pour le développement.

---

## 4. Flux de rafraîchissement (mode secteur)

```text
FastAPI met à jour DashboardView (providers en tâche de fond)
        │
        ▼
HA rest sensor poll /api/v1/display/meta  (toutes les 60 s)
        │
        ▼
sensor.eink_dashboard_target_hash change de valeur
        │
        ▼
automation « refresh » :
   condition : target_hash renseigné (ni unknown/unavailable/"")
               ET target_hash != sensor.eink_dashboard_content_hash  (celui de l'ESP)
        │
        ▼
   service esphome.eink_dashboard_refresh(content_hash = <target_hash>)
        │
        ▼
ESP : online_image.update
        ├── succès (on_download_finished)
        │      ├── display.update  (rafraîchit l'e-paper)
        │      └── text_sensor "Content hash" = <target_hash>
        │                 │
        │                 ▼
        │      les 2 sensors HA sont égaux → automation au repos
        │
        └── échec (on_error)
               ├── text_sensor "Content hash" = "error"
               └── écran inchangé
                   → target_hash ≠ "error" → l'automation re-déclenche au prochain poll
```

**Invariant conservé sans code dédié :** le seul état « ce qui est à l'écran »
est le `text_sensor` que l'ESP publie **après** un `on_download_finished` réussi.
Un échec le met à `"error"` (≠ hash cible) → nouvelle tentative au poll suivant.
Aucune persistance ni comparaison sur l'ESP ; aucun helper HA à tenir à jour.

### Scénarios de panne

| Panne | Comportement |
|---|---|
| Backend FastAPI down | `rest` sensor `unavailable` → automation ne déclenche pas → dernière image conservée. Reprise auto. |
| Home Assistant down | l'ESP ne reçoit aucun ordre → dernière image conservée. FastAPI continue de servir. Reprise auto au retour de HA. |
| Wi-Fi ESP coupé | `sensor.…_content_hash` (ESP) `unavailable` → l'automation ne peut pas confirmer l'égalité mais le service ne part pas tant que l'ESP est injoignable. Au retour, `wifi.on_connect` → `online_image.update` redessine, l'ESP republie, HA resynchronise. |
| Image corrompue / téléchargement KO | `on_error` → `text_sensor = "error"` → ≠ hash cible → retry au poll suivant. Écran inchangé. |
| Reboot ESP | pas de `global` à restaurer. `wifi.on_connect` → `online_image.update` → l'image courante est re-téléchargée et redessinée une fois, l'ESP republie son hash. |

---

## 5. Structure des fichiers cible

```text
repo/
├── config/dashboard.toml                     # inchangé
│
├── firmware/                                  # nouveau
│   ├── xiao-epaper.yaml
│   ├── secrets.example.yaml
│   └── README.md
│
├── homeassistant/                             # nouveau
│   ├── eink_dashboard.yaml
│   ├── secrets.example.yaml
│   └── README.md
│
├── src/eink_dashboard/
│   ├── api/routes/
│   │   ├── dashboard.py                       # inchangé
│   │   ├── device.py                          # inchangé (TRMNL, rollback)
│   │   └── display.py                         # nouveau : contrat HA
│   ├── main.py                                # +1 include_router
│   ├── render/…                               # inchangé
│   └── services/dashboard.py                  # inchangé
│
├── tests/unit/
│   └── test_display_api.py                    # nouveau
│
└── docs/
    ├── 2026-09-03-…-implementation-plan.md    # ce fichier
    └── 2026-09-03-test-materiel-checklist.md  # nouveau : à suivre pendant le test
```

---

## 6. Contraintes

**Backend**

- Python `>=3.12` ; aucune nouvelle dépendance ; aucune base ; aucune persistance serveur.
- FastAPI + Pillow restent la source de vérité du rendu.
- `mypy --strict` (via `pyproject`, `files = ["src"]`) + `ruff check .` + `ruff format --check .` propres.
- Tests réseau réels exclus par défaut (`-m 'not network'`).
- Aucun secret versionné. TRMNL non touché.

**Firmware**

- ESPHome officiel ; board `esp32-c3-devkitm-1` ; pinout officiel Seeed (voir §12).
- `display: waveshare_epaper`, `model: 7.50inv2`, `update_interval: never`.
- `online_image` en `format: BMP`, `type: BINARY`, `update_interval: never`.
- Aucune logique TCL/Vélo'v/météo en lambda. Aucun pin inventé.
- Deep sleep **absent** en v2 (mode secteur). Wi-Fi + clés via `secrets.yaml`, hors Git.
- Native API chiffrée, OTA protégé par mot de passe.

**Home Assistant**

- Package autonome, activé par `packages:` ou copié dans `configuration.yaml`.
- Aucune entité inutile. HA non requis pour le fonctionnement de FastAPI.
- L'URL du backend et les secrets vivent dans `homeassistant/secrets.yaml` (hors Git).

---

## 7. Task 0 — Baseline et rollback

**Objectif :** point de comparaison + garantie de retour arrière.

- [ ] `git status` propre avant de commencer ; branche `feat/ha-esphome-migration` créée.
- [ ] Suite backend verte sur `main` : `pytest -q`, `mypy`, `ruff check .`, `ruff format --check .`.
- [ ] Sauvegarder la config/firmware TRMNL actuellement flashée (copie dans `firmware/README.md` ou note perso).
- [ ] Vérifier `/preview.png` et le BMP servi par `/image/{name}` (via `/api/display`).
- [ ] Noter le comportement actuel : cadence, temps d'affichage, réaction aux pannes.
- [ ] **Ne supprimer aucun endpoint TRMNL.**

**Rollback global :** si le test matériel échoue,
`git checkout main && git branch -D feat/ha-esphome-migration`. Rien d'autre à défaire.

---

## 8. Task 1 — Backend : endpoint image stable + meta

**Files**

- Create: `src/eink_dashboard/api/routes/display.py`
- Modify: `src/eink_dashboard/main.py` (inclure `display.router` **avant** `device.router` pour que `/image/dashboard.bmp` gagne sur `/image/{name}`)
- Create: `tests/unit/test_display_api.py`

**`display.py`**

1. Helper interne : `view_for(...)` → `content_hash` + BMP (réutilise `ImageCache`, clé `dash-<hash>.bmp`, comme `device.py`).
2. `GET /api/v1/display/meta` → `{ "content_hash": view.content_hash(), "refresh_seconds": refresh_rate_for(now) }`.
3. `GET /image/dashboard.bmp` → `Response(bmp, media_type="image/bmp", headers={ETag, Cache-Control})` ;
   si `If-None-Match` == `"<hash>"` → `Response(status_code=304, headers=...)`.
4. `GET /image/dashboard.png` → même chose en PNG 1 bit (fallback `online_image`,
   voir §9). Même `ETag`, même cache partagé.

Pas de nouvelle logique métier : `refresh_rate_for` et `content_hash()` existent déjà.

**Tests (`test_display_api.py`)** — client montant `display.router` + `device.router` :

- [ ] `/api/v1/display/meta` : 200, corps == exactement `{content_hash, refresh_seconds}`.
- [ ] `content_hash` : 16 caractères hex.
- [ ] `refresh_seconds` ∈ `{PEAK_REFRESH, DAY_REFRESH, NIGHT_REFRESH}` et > 0.
- [ ] `meta.content_hash` == ETag de `/image/dashboard.bmp` (sans les guillemets).
- [ ] `/image/dashboard.bmp` : 200, `Content-Type: image/bmp`, corps commence par `BM`.
- [ ] BMP : mode 1 bit, taille 800×480 (relecture Pillow).
- [ ] `ETag` présent, `Cache-Control: no-cache`.
- [ ] ETag stable quand l'état ne change pas (2 requêtes successives).
- [ ] ETag stable quand seul le nombre de bornes Vélo'v change (donnée non affichée).
- [ ] ETag différent quand le nombre de vélos disponibles change (donnée visible).
- [ ] `If-None-Match` avec l'ETag courant → `304`, sans corps.
- [ ] `If-None-Match` obsolète → `200` + nouveau corps.
- [ ] Store vide (backend « dégradé ») → `/api/v1/display/meta` répond quand même `200`.

**Validation :** `pytest tests/unit/test_display_api.py -v`, puis suite complète + `mypy` + `ruff`.

**Commit :** `feat: expose stable dashboard bmp and display meta endpoints`

---

## 9. Task 2 — Firmware ESPHome minimal

**Files**

- Create: `firmware/xiao-epaper.yaml`
- Create: `firmware/secrets.example.yaml`
- Create: `firmware/README.md`

**`xiao-epaper.yaml`** (voir §12 pour le pinout ; adapter si le cookbook Seeed a bougé) :

- `esp32: board: esp32-c3-devkitm-1`
- `wifi:` avec `on_connect: - component.update: dashboard_image`
- `api:` chiffrée + `services: - service: refresh` / `variables: { content_hash: string }`
  → `lambda 'id(pending_hash) = content_hash;'` puis `component.update: dashboard_image`
- `ota: - platform: esphome` avec `password: !secret ota_password`
- `http_request:` (dépendance d'`online_image`), `timeout: 15s`
- `globals: - id: pending_hash` (`std::string`, `restore_value: no`) — RAM seulement, pas de persistance
- `spi: { clk_pin: GPIO8, mosi_pin: GPIO10 }`
- `online_image:` `id: dashboard_image`, `url: !secret dashboard_image_url`,
  `format: BMP`, `type: BINARY`, `update_interval: never`
  - `on_download_finished: [ component.update: main_display, text_sensor.template.publish shown_hash = pending_hash ]`
  - `on_error: [ text_sensor.template.publish shown_hash = "error" ]`
- `display: - platform: waveshare_epaper`, `id: main_display`, `model: 7.50inv2`,
  `update_interval: never`, `lambda: it.image(0, 0, id(dashboard_image));`
- diagnostics : `sensor.wifi_signal`, `sensor.uptime`, `text_sensor.template shown_hash`
  (`name: "Content hash"`), `text_sensor.version`, `binary_sensor.status`

**`secrets.example.yaml`** : `wifi_ssid`, `wifi_password`, `api_encryption_key`,
`ota_password`, `dashboard_image_url` (`http://<IP_BACKEND>:9001/image/dashboard.bmp`).

**Note fallback** (dans le README) : `/image/dashboard.png` est déjà exposé
(Task 1). Si le BMP 1 bit ne décode pas proprement sur l'ESP32-C3, il suffit de
pointer `dashboard_image_url` sur le `.png` et de passer `format: PNG` — aucune
modif backend.

**Validation locale (avant flash) :** `esphome config firmware/xiao-epaper.yaml`
(nécessite ESPHome installé ; à défaut, revue manuelle + validation le jour du test).

**Commit :** `chore: add ESPHome firmware for XIAO epaper (HA-orchestrated)`

---

## 10. Task 3 — Package Home Assistant

**Files**

- Create: `homeassistant/eink_dashboard.yaml`
- Create: `homeassistant/secrets.example.yaml`
- Create: `homeassistant/README.md`

**`eink_dashboard.yaml`** (contenu réel du fichier livré) :

```yaml
rest:
  - resource: !secret eink_dashboard_meta_url
    scan_interval: 60
    sensor:
      - name: "Eink dashboard target hash"
        unique_id: eink_dashboard_target_hash
        value_template: "{{ value_json.content_hash }}"
        json_attributes: [refresh_seconds]

automation:
  - alias: "Eink dashboard - refresh e-paper on content change"
    trigger:
      - trigger: state
        entity_id: sensor.eink_dashboard_target_hash
      - trigger: state
        entity_id: sensor.eink_dashboard_content_hash   # publié par l'ESP
      - trigger: homeassistant
        event: start
    condition:
      - condition: template
        value_template: >
          {{ states('sensor.eink_dashboard_target_hash')
             not in ['unknown', 'unavailable', 'None', ''] }}
      - condition: template
        value_template: >
          {{ states('sensor.eink_dashboard_target_hash')
             != states('sensor.eink_dashboard_content_hash') }}
    action:
      - service: esphome.eink_dashboard_refresh
        data:
          content_hash: "{{ states('sensor.eink_dashboard_target_hash') }}"
    mode: single

script:
  eink_dashboard_force_refresh:
    alias: "Eink dashboard - force refresh"
    sequence:
      - service: esphome.eink_dashboard_refresh
        data:
          content_hash: "{{ states('sensor.eink_dashboard_target_hash') }}"
```

> `sensor.eink_dashboard_content_hash` = le `text_sensor` « Content hash » de
> l'ESP (domaine `sensor` côté HA). Si le device n'est pas nommé `eink-dashboard`,
> ajuster ce nom et celui du service `esphome.<name>_refresh` — voir README.

**`secrets.example.yaml`** : `eink_dashboard_meta_url: http://<IP_BACKEND>:9001/api/v1/display/meta`.

**`README.md`** : activer `packages:` dans `configuration.yaml`, copier le fichier,
renseigner les secrets, adopter le device ESPHome, vérifier les noms d'entités /
de service, tester `script.eink_dashboard_force_refresh`.

**Commit :** `feat: add Home Assistant package to orchestrate eink refresh`

---

## 11. Task 4 — Documentation du test matériel

**Files**

- Create: `docs/2026-09-03-test-materiel-checklist.md`

Checklist ordonnée à suivre le jour du test (backend lancé, ESP à portée) :

1. **Backend** : `docker compose up -d --build` ; vérifier `/health`,
   `/api/v1/display/meta` (hash + refresh_seconds), `/image/dashboard.bmp`
   (BM, 800×480), `/preview.png`.
2. **Flash** : brancher le XIAO en USB, `esphome run firmware/xiao-epaper.yaml`,
   renseigner `firmware/secrets.yaml` d'abord.
3. **Appairage HA** : le device apparaît → adopter. Noter le nom réel du service
   `esphome.<name>_refresh` et de l'entité `sensor.<name>_content_hash` ; ajuster
   le package HA si `<name>` ≠ `eink_dashboard`.
4. **Premier affichage** : appeler le service `refresh` à la main
   (Outils de développement → Services) avec le hash courant → l'écran se dessine.
   Vérifier : orientation, noir/blanc non inversé, pas de crop, 800×480 plein cadre.
   Vérifier que `sensor.<name>_content_hash` passe à ce hash.
5. **Boucle nominale** : activer le package HA. Forcer un changement de donnée
   visible (ex. fixture) → l'écran se rafraîchit tout seul sous ~60 s, les 2
   sensors HA se rejoignent.
6. **Pas de refresh inutile** : laisser tourner 20 min sans changement de donnée
   visible → **aucun** rafraîchissement e-ink, hash de l'ESP stable, automation jamais déclenchée.
7. **Pannes** :
   - couper FastAPI → `sensor.<name>_target_hash` `unavailable`, écran conservé ; relancer → reprise.
   - couper HA → écran conservé ; relancer (trigger `homeassistant start`) → resync.
   - couper le Wi-Fi de l'ESP → au retour, une seule redraw (`wifi.on_connect`), puis resync.
   - `esphome logs` : surveiller RAM, absence de reboot / watchdog sur 20+ cycles.
8. **OTA** : modifier un `name:` trivial, `esphome run` par OTA (pas de deep sleep → doit marcher direct).
9. **Verdict** :
   - **OK** → garder la branche, laisser tourner 48 h, puis planifier la suppression TRMNL (§15) et la V2 métier (§17).
   - **KO** (instable, RAM, décodage BMP) → tester le fallback PNG (§9). Toujours KO →
     `git checkout main`, abandonner la branche, ré-flasher le firmware TRMNL sauvegardé.

**Commit :** `docs: add hardware test checklist for the ESPHome branch`

---

## 12. Pinout et config de référence Seeed (à revérifier le jour du test)

Source : `https://wiki.seeedstudio.com/xiao_075inch_epaper_panel_esphome/`

```yaml
esp32:
  board: esp32-c3-devkitm-1

spi:
  clk_pin: GPIO8
  mosi_pin: GPIO10

display:
  - platform: waveshare_epaper
    cs_pin: GPIO3
    dc_pin: GPIO5
    busy_pin:
      number: GPIO4
      inverted: true
    reset_pin: GPIO2
    model: 7.50inv2
    update_interval: never
```

Instruction agent (rappel) : lire la doc ESPHome/Seeed courante avant de figer le
YAML, ne pas inventer de pin, valider avec `esphome config` avant tout flash,
ne jamais toucher à TRMNL avant le verdict du test.

---

## 13. Definition of Done (v2)

1. Le panneau tourne sous ESPHome et est adopté par Home Assistant.
2. FastAPI reste la source de vérité du contenu ; Pillow celle du layout.
3. Le firmware ne contient **aucune** logique métier, `global` persistée, ni machine à états.
4. HA poll `/api/v1/display/meta` et déclenche `esphome.<name>_refresh` quand le hash cible diffère du hash publié par l'ESP.
5. Un hash identique n'entraîne **aucun** refresh e-paper.
6. Un hash différent télécharge le BMP puis rafraîchit l'écran.
7. Le `text_sensor` de l'ESP ne passe au nouveau hash qu'après affichage réussi (`"error"` sinon → retry).
8. Panne backend → ancienne image conservée, reprise auto.
9. Panne Home Assistant → affichage conservé, pas de blocage, resync au retour.
10. L'écran V2 peut évoluer sans recompiler ESPHome (critère architectural majeur).
11. TRMNL (`device.py`, `test_device_api.py`) reste intact et fonctionnel.
12. Toute la suite Python reste verte, `mypy --strict` et `ruff` propres.
13. La branche est abandonnable sans effet de bord si le test matériel échoue.

---

## 14. Ordre des commits

```text
feat: expose stable dashboard bmp and display meta endpoints
chore: add ESPHome firmware for XIAO epaper (HA-orchestrated)
feat: add Home Assistant package to orchestrate eink refresh
docs: add hardware test checklist for the ESPHome branch
```

Après validation terrain seulement :

```text
refactor: remove obsolete TRMNL device protocol
```

Ne jamais mélanger dans un même commit : suppression TRMNL, activation deep
sleep, refonte graphique V2.

---

## 15. Task 5 (post-validation) — Retirer TRMNL

Pré-requis : POC stable + boucle HA stable + **plusieurs jours d'usage réel** sans
écran blanc, sans blocage, sans reboot intempestif, reprise auto après panne.

- Delete: routes TRMNL dans `api/routes/device.py` + `DEVICE_API_ENABLED` dans `main.py`
- Delete/Modify: `tests/unit/test_device_api.py`
- Modify: `core/config.py` (retirer `device_mac`, `device_api_key`, leur validation), `.env.example`
- Modify: `README.md`
- Conserver la config TRMNL dans l'historique Git / la doc de migration.

---

## 16. Task 6 (optionnel, plus tard) — Mode batterie / deep sleep

**Brouillon livré, non validé sur matériel** (voir *Delta* en fin de document) :

- `firmware/xiao-epaper-battery.yaml` — l'ESP se réveille seul, fait un cycle
  complet (Wi-Fi → API → lecture des entités HA → redessin conditionnel → sommeil),
  puis `deep_sleep.enter` pour `refresh_seconds` borné [60 s, 6 h]. `run_duration`
  = failsafe. `input_boolean.eink_dashboard_maintenance` → `deep_sleep.prevent`
  (fenêtre OTA). `fast_connect` + IP statique pour raccourcir le pic de réveil.
- `homeassistant/eink_dashboard_battery.yaml` — remplace le package secteur. Plus
  d'appel de service : HA mémorise le hash affiché dans
  `input_text.eink_dashboard_shown_hash` (mis à jour depuis le `text_sensor` de
  l'ESP), que l'ESP relit au réveil pour décider s'il redessine.
- **La décision de cadence reste en Python** (`refresh_rate_for`), l'ESP ne fait
  qu'obéir à `refresh_seconds`.

Point de vigilance : l'ESP ne doit jamais attendre HA indéfiniment (`wait_until`
timeout 30 s, `delay 6s` puis on continue avec les valeurs disponibles).
Autonomie estimée avec ce profil et une LiPo 2000 mAh : ~3 mois (à mesurer).

---

## 17. Task 7 (post-validation) — Réintégrer la V2 métier

Une fois la couche ESPHome stable, poursuivre la V2 dashboard (compactage T2,
premier passage prioritaire, Vélo'v nom court + vélos seuls, perturbations T2/D,
météo courte). **Aucune de ces évolutions ne doit toucher le firmware ni le
package HA** — modification Python/Pillow uniquement.

---

## 18. Risques et mitigations

| Risque | Impact | Mitigation |
|---|---|---|
| `online_image` gourmand en RAM sur ESP32-C3 | reboot / watchdog | test 20+ cycles avant validation ; BMP BINARY ; fallback PNG documenté |
| BMP 1 bit Pillow mal décodé par ESPHome | image absente / corrompue | fallback `/image/dashboard.png` + `format: PNG` prêt |
| collision de route `/image/dashboard.bmp` vs `/image/{name}` | 404 sur le BMP | inclure `display.router` avant `device.router` ; test dédié |
| HA down au moment d'un changement | écran obsolète temporairement | resync automatique au retour (trigger `homeassistant start` + les 2 hashs diffèrent) |
| backend down | écran stale | `rest` sensor `unavailable` → pas de déclenchement ; dernière image conservée |
| nom réel du service/entité ESPHome ≠ supposé | automation muette | checklist §11 : relever et ajuster le package après appairage |
| suppression TRMNL trop tôt | rollback difficile | coexistence jusqu'au verdict terrain + 48 h |
| logique métier qui glisse dans le YAML | maintenance difficile | firmware limité à téléchargement + affichage ; revue de diff |

---

## 19. Références (à revérifier au moment de l'implémentation)

- Seeed — XIAO 7.5" ePaper Panel ESPHome : `https://wiki.seeedstudio.com/xiao_075inch_epaper_panel_esphome/`
- ESPHome — Online Image : `https://esphome.io/components/online_image.html`
- ESPHome — HTTP Request : `https://esphome.io/components/http_request.html`
- ESPHome — Native API / services : `https://esphome.io/components/api.html`
- ESPHome — Waveshare e-Paper : `https://esphome.io/components/display/waveshare_epaper.html`
- Home Assistant — RESTful sensor : `https://www.home-assistant.io/integrations/rest/`
- Home Assistant — Packages : `https://www.home-assistant.io/docs/configuration/packages/`
- ESPHome — Deep Sleep : `https://esphome.io/components/deep_sleep.html`
- ESPHome — Import d'entités HA : `https://esphome.io/components/sensor/homeassistant.html`

---

## 20. Delta 2026-09-03b — cadence adaptative + brouillon mode batterie

Motivation : préparer l'autonomie sur batterie. Coût dominant d'un réveil deep
sleep = la reconnexion Wi-Fi, pas le redessin. Deux leviers : (a) espacer les
réveils quand il ne se passe rien, (b) ne pas redessiner l'e-paper inutilement.

**Backend (livré, testé — `pytest`/`mypy`/`ruff` verts) :**

- `DashboardView.coarse` (renseigné par `build_view` via `in_coarse_window(now)`).
  De 09:00 à 21:00 locale, `content_hash()` bascule sur un payload « grossier » :
  ne réagit qu'aux **alertes** (perturbations / `traffic_note`) et au **passage
  d'une station Vélo'v sous 3 vélos** (ou `stale`). Comptes à rebours, météo et
  nombre exact de vélos n'altèrent plus le hash → plus de redraw e-ink pour ça.
  Hors de cette fenêtre : hash complet, comportement V2 inchangé.
- Layout : en mode `coarse`, l'heure d'en-tête devient « MAJ HH:MM » (l'écran est
  figé entre deux évènements, on l'annonce).
- `refresh_rate_for(now, *, has_event)` réécrit (cf. tableau §3.1). Nouvelles
  constantes `PEAK_REFRESH=180`, `DAY_EVENT_REFRESH=300`, `DAY_IDLE_REFRESH=1800`,
  `NIGHT_MAX_SLEEP=4h`. Suppression de `_EVENING_PEAK` (la logique évènement
  couvre la journée jusqu'à 21:00). `view_has_event(view)` expose le prédicat.
- `/api/v1/display/meta` passe `has_event=view_has_event(view)`.
- TRMNL (`device.py`) : `view_for(..., coarse_enabled=False)` → image pleine
  fidélité conservée, aucun impact sur le protocole legacy.

**Firmware / HA (brouillons, à valider — checklist §10bis) :**

- `firmware/xiao-epaper-battery.yaml`, `homeassistant/eink_dashboard_battery.yaml`
  (cf. §16). Non passés par `esphome config` (ESPHome non installé en local).

Non fait volontairement : mesure de batterie affichée sur le panneau (le panneau
Seeed n'expose pas de pont diviseur documenté ; sans intérêt tant qu'on est sur
secteur). Une icône « batterie faible » pourra être ajoutée côté Pillow quand le
mode batterie sera actif, hors hash.

---

## 21. Delta 2026-09-03c — nuit figée + une ligne T2 par sens

**Backend (livré, testé — `pytest`/`mypy`/`ruff` verts) :**

- `in_night_window(now)` (21:00–07:30 locale, bornes de `refresh_rate_for`).
  `DashboardView.night` → `content_hash()` renvoie un payload constant
  `{"night": true}` : la nuit le panneau ne se redessine plus **du tout**, pas
  même sur perturbation ou Vélo'v bas (contrairement au mode `coarse` de jour).
  `night` implique `coarse` (en-tête « MAJ HH:MM »). Gated par `coarse_enabled`,
  donc TRMNL (`device.py`) reste pleine fidélité.
  Motivation : en mode batterie l'ESP se réveille ~toutes les 4 h la nuit ;
  sans gel le hash bougeait à chaque réveil (comptes à rebours) → download BMP +
  redessin inutiles. Désormais : 1 redraw en entrant dans la nuit, 1 à 07:30.
- `_departures` regroupe par `(arrêt, ligne)` au lieu de `(ligne, direction)`.
  Un arrêt suivi = un sens → 2 lignes T2 garanties. Les terminus partiels (Hauts
  de Feuilly, Essarts-Iris, Montrochet vs Perrache) se fondent dans la ligne de
  leur arrêt au lieu d'empiler 3-4 lignes qui débordaient sur la zone VÉLO'V.
- `TclStop.label` (optionnel) : libellé de sens affiché. Sinon alias de
  direction, sinon destination du prochain passage. `config/dashboard.toml` fixe
  `label = "St-Priest"` / `label = "Montrochet"`. Effet de bord : contourne le
  mojibake `HÃ´tel RÃ©gion` de l'API grandlyon (le libellé ne vient plus du flux
  brut).

Non fait : `NIGHT_MAX_SLEEP` reste à 4 h (le gel du hash suffit ; passer à 6 h
n'économise qu'un réveil Wi-Fi/nuit contre une latence OTA doublée).

---

## 22. Delta 2026-09-03d — migration mode batterie + mesure batterie

Décision : passer le panneau en deep sleep pour de vrai (il tournait en fait le
firmware secteur *sur batterie* → ~1 j d'autonomie).

**Firmware `xiao-epaper-battery.yaml` (`esphome config` + `esphome compile` verts,
RAM 13.8 % / Flash 57.2 %) :**

- report des correctifs matériels validés sur le firmware secteur : `friendly_name`
  = « Eink Dashboard » (le tiret cassait le slug HA), `post_connect_roaming: false`
  (roaming Freebox qui redémarrait l'adaptateur ~50 s).
- mesure batterie : pont diviseur /2 de la carte pilote Seeed, `output` GPIO6
  (enable, HIGH le temps de la mesure), `adc` GPIO1 `×2`. Exposé en
  `sensor.*_tension_batterie` (V) + `sensor.*_batterie` (%, courbe LiPo approx.,
  `device_class: battery`) + `binary_sensor.*_batterie_faible`.
- lecture pendant la fenêtre de 6 s déjà présente dans le cycle de réveil → zéro
  temps de réveil en plus.
- pastille « batterie faible » dessinée par le `lambda` du `display` (batterie +
  « ! » dans la zone vide de l'en-tête) quand `battery_low` ; hystérésis 3.55 /
  3.65 V portée par un global `restore_value: yes`.
- `battery_low` ajoute le suffixe `-lowbat` au hash comparé → franchir le seuil
  force **un** redraw (apparition/disparition de la pastille), sinon écran figé.
  Rendu 100 % côté ESP, aucun changement backend.

**Package HA `eink_dashboard_battery.yaml` :** `input_text` max 32 → 40 (suffixe
`-lowbat`), automation `persistent_notification` sur `binary_sensor.*_batterie_faible`
maintenu 10 min.

**À valider sur matériel** (checklist §10bis, réécrite) : l'hypothèse broche
enable = GPIO6 vient du cookbook PlatformIO Seeed EE0x ; à confirmer, repli GPIO7.

Non fait : affichage du `%` exact sur l'e-paper (seule la pastille « faible »
apparaît) ; réglage fin de la courbe LiPo (à caler avec une vraie décharge).
