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
| Savoir si l'écran doit changer | `global last_content_hash` sur l'ESP | `input_text` côté HA |
| Décision de rafraîchir | machine à états en lambda C++ | 1 automation HA |
| Persistance du hash affiché | `restore_value` + invariant critique | `input_text` HA (durable par nature) |
| Cadence de réveil | deep sleep piloté par `refresh_seconds` | poll HA fixe (60 s) ; `refresh_seconds` redevient utile en mode batterie |
| Résistance panne backend | retry au réveil | l'ESP ne touche pas l'écran sans ordre HA ; dernière image conservée |
| OTA malgré deep sleep | `deep_sleep.prevent` + `input_boolean` | pas de deep sleep → OTA trivial |

**Le firmware v2 ne contient aucune comparaison de hash, aucune `global`
persistée, aucune machine à états, aucun deep sleep.** Il expose un service
`refresh` et sait dessiner une image téléchargée. C'est tout.

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
        ┌───────────────  HOME ASSISTANT  ───────────────┐
        │  rest sensor : poll /api/v1/display/meta (60 s) │
        │  input_text  : dernier hash réellement affiché  │
        │  automation  : si meta.hash != input_text       │
        │                et pas en maintenance            │
        │                -> esphome.eink_dashboard_refresh │
        │  automation  : shown_hash (ESP) -> input_text    │
        └───────────────────────┬────────────────────────┘
                                │ ESPHome Native API (chiffrée)
                                ▼
                    ┌─────────────────────────┐
                    │ XIAO ESP32-C3 / ESPHome │
                    │  service: refresh(hash) │
                    │   -> online_image.update│
                    │   -> display.update     │
                    │   -> shown_hash = hash  │
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

Un package `homeassistant/eink_dashboard.yaml` : 1 `rest` sensor, 1 `input_text`,
1 `input_boolean` (maintenance, optionnel), 2 automations, 1 script de refresh
forcé. Fourni prêt à copier ; HA n'est pas requis pour que FastAPI fonctionne.

---

## 3. Contrat backend ↔ Home Assistant

### 3.1 `GET /api/v1/display/meta`

```json
{ "content_hash": "8c23ad0ff5e39142", "refresh_seconds": 300 }
```

**`content_hash`** — `DashboardView.content_hash()` tel quel (sha256 tronqué
16 hex). Change si une info visible change ; ne change pas si seule `as_of`
change ; ne change pas pour une donnée non affichée ; stable entre process.

**`refresh_seconds`** — `refresh_rate_for(now)` : 120 s en pointe TCL, 300 s en
journée, 3600 s la nuit. Borné côté serveur. En mode secteur (v2), HA poll à
intervalle fixe et n'utilise ce champ que pour information / debug ; il
redeviendra la cadence de réveil quand le mode batterie sera activé (§16).

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
sensor.eink_dashboard_content_hash change de valeur
        │
        ▼
automation « refresh » :
   condition : hash != input_text.eink_dashboard_shown_hash
               ET input_boolean.eink_dashboard_maintenance == off
               ET device ESPHome disponible
        │
        ▼
   service esphome.eink_dashboard_refresh(content_hash = <hash>)
        │
        ▼
ESP : online_image.update
        ├── succès (on_download_finished)
        │      ├── display.update  (rafraîchit l'e-paper)
        │      └── text_sensor shown_hash = content_hash
        │                 │
        │                 ▼
        │      automation « mirror » : input_text = shown_hash
        │
        └── échec (on_error)
               ├── shown_hash = "error"
               └── écran inchangé ; input_text inchangé
                   → l'automation re-déclenchera au prochain poll (hash toujours != input_text)
```

**Invariant conservé, mais déplacé côté HA :** `input_text.eink_dashboard_shown_hash`
n'est mis à jour qu'après un `on_download_finished` réussi qui publie
`shown_hash`. Un échec de téléchargement laisse `input_text` sur l'ancienne
valeur → nouvelle tentative au poll suivant. Aucune logique de persistance sur
l'ESP.

### Scénarios de panne

| Panne | Comportement |
|---|---|
| Backend FastAPI down | `rest` sensor `unavailable` → automation ne déclenche pas → dernière image conservée. Reprise auto. |
| Home Assistant down | l'ESP ne reçoit aucun ordre → dernière image conservée. FastAPI continue de servir. Reprise auto au retour de HA. |
| Wi-Fi ESP coupé | device ESPHome `unavailable` → condition d'automation fausse → pas d'appel. Au retour, `wifi.on_connect` déclenche un `online_image.update`, puis HA resynchronise. |
| Image corrompue / téléchargement KO | `on_error` → `shown_hash = "error"` → `input_text` inchangé → retry au poll suivant. Écran inchangé. |
| Reboot ESP | pas de `global` à restaurer. `wifi.on_connect` → `online_image.update` → l'image courante est re-téléchargée et redessinée une fois. HA resynchronise `input_text`. |

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
    └── 2026-09-03-test-matériel-checklist.md  # nouveau : à suivre pendant le test
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
`ota_password`, `dashboard_image_url` (`http://<IP_BACKEND>:8000/image/dashboard.bmp`).

**Note fallback** (dans le README) : si le BMP 1 bit ne décode pas proprement sur
l'ESP32-C3, exposer aussi `/image/dashboard.png` côté backend et passer
`format: PNG` — `online_image` supporte les deux, PNG est le chemin le plus éprouvé.

**Validation locale (avant flash) :** `esphome config firmware/xiao-epaper.yaml`
(nécessite ESPHome installé ; à défaut, revue manuelle + validation le jour du test).

**Commit :** `chore: add ESPHome firmware for XIAO epaper (HA-orchestrated)`

---

## 10. Task 3 — Package Home Assistant

**Files**

- Create: `homeassistant/eink_dashboard.yaml`
- Create: `homeassistant/secrets.example.yaml`
- Create: `homeassistant/README.md`

**`eink_dashboard.yaml`**

```yaml
rest:
  - resource: !secret eink_dashboard_meta_url
    scan_interval: 60
    sensor:
      - name: "Eink dashboard content hash"
        unique_id: eink_dashboard_content_hash
        value_template: "{{ value_json.content_hash }}"
        json_attributes:
          - refresh_seconds

input_text:
  eink_dashboard_shown_hash:
    name: Eink dashboard shown hash
    max: 32

input_boolean:
  eink_dashboard_maintenance:
    name: Eink dashboard maintenance

automation:
  - alias: "Eink dashboard - refresh on content change"
    trigger:
      - trigger: state
        entity_id: sensor.eink_dashboard_content_hash
      - trigger: homeassistant
        event: start
    condition:
      - condition: template
        value_template: >
          {{ states('sensor.eink_dashboard_content_hash') not in
             ['unknown', 'unavailable', ''] }}
      - condition: template
        value_template: >
          {{ states('sensor.eink_dashboard_content_hash')
             != states('input_text.eink_dashboard_shown_hash') }}
      - condition: state
        entity_id: input_boolean.eink_dashboard_maintenance
        state: "off"
    action:
      - service: esphome.eink_dashboard_refresh
        data:
          content_hash: "{{ states('sensor.eink_dashboard_content_hash') }}"

  - alias: "Eink dashboard - record displayed hash"
    trigger:
      - trigger: state
        entity_id: text_sensor.eink_dashboard_content_hash   # shown_hash exposé par l'ESP
    condition:
      - condition: template
        value_template: "{{ trigger.to_state.state not in ['error', 'unknown', 'unavailable', ''] }}"
    action:
      - service: input_text.set_value
        target:
          entity_id: input_text.eink_dashboard_shown_hash
        data:
          value: "{{ trigger.to_state.state }}"

script:
  eink_dashboard_force_refresh:
    alias: Eink dashboard - force refresh
    sequence:
      - service: input_text.set_value
        target:
          entity_id: input_text.eink_dashboard_shown_hash
        data:
          value: "forced"
```

> Le nom exact de l'entité `text_sensor` publiée par l'ESP dépend du
> `friendly_name` / `name`. À ajuster dans le README au moment de l'appairage.

**`secrets.example.yaml`** : `eink_dashboard_meta_url: http://<IP_BACKEND>:8000/api/v1/display/meta`.

**`README.md`** : activer `packages:` dans `configuration.yaml`, copier le fichier,
renseigner les secrets, adopter le device ESPHome, retrouver le nom du service
`esphome.<name>_refresh` et de l'entité `text_sensor`, tester le script de refresh forcé.

**Commit :** `feat: add Home Assistant package to orchestrate eink refresh`

---

## 11. Task 4 — Documentation du test matériel

**Files**

- Create: `docs/2026-09-03-test-matériel-checklist.md`

Checklist ordonnée à suivre le jour du test (backend lancé, ESP à portée) :

1. **Backend** : `docker compose up -d --build` ; vérifier `/health`,
   `/api/v1/display/meta` (hash + refresh_seconds), `/image/dashboard.bmp`
   (BM, 800×480), `/preview.png`.
2. **Flash** : brancher le XIAO en USB, `esphome run firmware/xiao-epaper.yaml`,
   renseigner `firmware/secrets.yaml` d'abord.
3. **Appairage HA** : le device apparaît → adopter. Noter le nom réel du service
   `esphome.<name>_refresh` et de l'entité `text_sensor` ; ajuster le package HA.
4. **Premier affichage** : appeler le service `refresh` à la main
   (Outils de développement → Services) avec le hash courant → l'écran se dessine.
   Vérifier : orientation, noir/blanc non inversé, pas de crop, 800×480 plein cadre.
5. **Boucle nominale** : activer le package HA. Forcer un changement de donnée
   visible (ex. fixture) → l'écran se rafraîchit tout seul sous ~60 s.
6. **Pas de refresh inutile** : laisser tourner 20 min sans changement de donnée
   visible → **aucun** rafraîchissement e-ink (`shown_hash` stable, compteur HA à 0).
7. **Pannes** :
   - couper FastAPI → `sensor` `unavailable`, écran conservé ; relancer → reprise.
   - couper HA → écran conservé ; relancer → resync.
   - couper le Wi-Fi de l'ESP → au retour, une seule redraw, puis resync.
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
4. HA poll `/api/v1/display/meta` et déclenche `esphome.<name>_refresh` au changement de hash.
5. Un hash identique n'entraîne **aucun** refresh e-paper.
6. Un hash différent télécharge le BMP puis rafraîchit l'écran.
7. `input_text.eink_dashboard_shown_hash` n'est mis à jour qu'après affichage réussi.
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

Uniquement si l'autonomie sur secteur n'est plus souhaitée. Réintroduit alors,
côté firmware seulement :

- `deep_sleep:` avec `run_duration` failsafe + sortie explicite `deep_sleep.enter`
  `sleep_duration: !lambda "return id(next_sleep_ms);"` ;
- au réveil : laisser quelques secondes à la Native API ; si
  `input_boolean.eink_dashboard_maintenance == on` → `deep_sleep.prevent` ;
- `next_sleep_ms` alimenté par HA (entité `number`/`text` importée) à partir de
  `refresh_seconds` du meta endpoint — **la décision de cadence reste en Python**.

Le champ `refresh_seconds` de `/api/v1/display/meta` est déjà prêt pour ça.
Point de vigilance : l'ESP ne doit jamais attendre HA indéfiniment (timeout court,
sinon workflow normal).

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
| HA down au moment d'un changement | écran obsolète temporairement | resync automatique au retour (hash != input_text) |
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
