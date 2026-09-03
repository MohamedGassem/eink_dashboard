# Test matériel — branche `feat/ha-esphome-migration`

**But :** valider la chaîne FastAPI → Home Assistant → ESPHome → e-paper sur le
XIAO 7.5". À faire d'une traite, ESP à portée Wi-Fi, backend joignable.

**Prérequis :** ESPHome installé (`pip install esphome` ou add-on HA), le XIAO en
USB pour le premier flash, l'IP LAN de la machine qui fait tourner FastAPI.

À la fin : **verdict OK** → on garde la branche ; **verdict KO** → `git checkout main`,
`git branch -D feat/ha-esphome-migration`, reflasher le firmware TRMNL.

---

## 1. Backend

```bash
git checkout feat/ha-esphome-migration
docker compose up -d --build
```

- [ ] `GET /health` → 200
- [ ] `GET /api/v1/display/meta` → `{"content_hash":"<16 hex>","refresh_seconds":N}`
- [ ] `GET /image/dashboard.bmp` → `Content-Type: image/bmp`, commence par `BM`,
      `ETag` == le `content_hash` ci-dessus
- [ ] ouvrir le BMP : 800×480, noir & blanc, lisible
- [ ] `GET /image/dashboard.png` → même `ETag`, image identique
- [ ] `GET /preview.png` → inchangé par rapport à avant

Noter le `content_hash` courant : `________________`

---

## 2. Firmware

```bash
cp firmware/secrets.example.yaml firmware/secrets.yaml
#  -> wifi_ssid, wifi_password, api_encryption_key (openssl rand -base64 32),
#     ota_password, dashboard_image_url = http://<IP_BACKEND>:9001/image/dashboard.bmp
esphome config firmware/xiao-epaper.yaml        # doit sortir "Configuration is valid!"
esphome run firmware/xiao-epaper.yaml           # USB ; si refus : BOOT+RESET puis relancer
```

- [ ] `esphome config` valide (corriger toute erreur de pin / d'option avant de flasher)
- [ ] flash OK, l'ESP boote, se connecte au Wi-Fi (voir `esphome logs`)
- [ ] pas de reboot en boucle, pas de `Guru Meditation` / watchdog

---

## 3. Appairage Home Assistant

- [ ] le device `eink-dashboard` est découvert → **Adopter**
- [ ] entités visibles : `sensor.*_wifi_signal`, `*_uptime`, `sensor.*_content_hash`
      (text_sensor « Content hash »), `*_esphome_version`, `*_ip_address`, `binary_sensor.*_status`
- [ ] noter le nom réel du device : `________________`
      → si ≠ `eink-dashboard`, adapter `homeassistant/eink_dashboard.yaml`
      (`sensor.<nom>_content_hash`, `esphome.<nom>_refresh`)
- [ ] service `esphome.<nom>_refresh` présent dans Outils de développement → Services

---

## 4. Premier affichage (manuel, sans le package)

Outils de développement → Services :

```yaml
service: esphome.eink_dashboard_refresh
data:
  content_hash: "<le content_hash noté en §1>"
```

- [ ] l'e-paper se dessine dans les ~5 s
- [ ] orientation correcte (paysage, texte à l'endroit)
- [ ] noir sur blanc (pas inversé)
- [ ] pas de rognage, image plein cadre 800×480
- [ ] `sensor.<nom>_content_hash` passe à la valeur envoyée
- [ ] `esphome logs` : « image dashboard affichée », RAM libre stable

> Si l'image est absente / bruitée : passer au **fallback PNG** —
> `dashboard_image_url` → `.../image/dashboard.png`, `format: PNG` dans le YAML,
> `esphome run`, recommencer §4.

---

## 5. Package Home Assistant

```bash
cp homeassistant/eink_dashboard.yaml <config_ha>/packages/eink_dashboard.yaml
# secrets.yaml HA : eink_dashboard_meta_url: http://<IP_BACKEND>:9001/api/v1/display/meta
```

- [ ] packages activés (`homeassistant: packages: !include_dir_named packages`)
- [ ] recharger « RESTful » + « Automations » (ou redémarrer HA)
- [ ] `sensor.eink_dashboard_target_hash` a une valeur = `content_hash` courant
- [ ] `script.eink_dashboard_force_refresh` → l'écran se redessine

---

## 6. Boucle nominale

- [ ] provoquer un changement de donnée **visible** (attendre un passage T2 qui
      change de minute, ou injecter une fixture) → sous ~60 s l'automation
      `Eink dashboard - refresh e-paper on content change` se déclenche **une fois**
- [ ] `sensor.eink_dashboard_target_hash` et `sensor.*_content_hash` se rejoignent
- [ ] l'e-paper montre la nouvelle donnée

## 7. Pas de refresh inutile

- [ ] laisser tourner **20 min** sans changement visible
- [ ] l'automation ne se déclenche **jamais** (trace à vide dans ses infos)
- [ ] aucun rafraîchissement e-ink (l'écran ne clignote pas)

## 8. Pannes

- [ ] `docker compose stop` → `sensor.eink_dashboard_target_hash` = `unavailable`,
      écran conservé → `docker compose start` → resync sous ~60 s
- [ ] redémarrer HA → écran conservé → au retour, resync si le contenu a changé entre-temps
- [ ] couper le Wi-Fi de l'ESP 2 min puis rétablir → une seule redraw au retour,
      pas de boucle
- [ ] laisser 20+ cycles de refresh s'enchaîner (baisser `scan_interval` à 15 s
      temporairement + fixture qui bouge) → aucun reboot, RAM stable

## 9. OTA

- [ ] changer `friendly_name` (cosmétique), `esphome run` → passe **par OTA**
      (pas de deep sleep, l'ESP est toujours joignable)

---

## 10bis. Migration mode batterie / deep sleep

`esphome config` **et** `esphome compile` passent sur `xiao-epaper-battery.yaml`
(RAM 13.8 %, Flash 57.2 %). Matériel en plus : la LiPo 1S sur le connecteur du
panneau, un wattmètre USB en série pour la conso (optionnel).

**Ordre important : le package HA d'abord, le firmware ensuite** (sinon au premier
réveil l'ESP ne trouve ni `input_text.eink_dashboard_shown_hash` ni
`input_boolean.eink_dashboard_maintenance` → redraw à chaque réveil, OTA impossible).

### a. Backend

- [ ] déployer le commit « nuit figée » : `git pull` puis `docker compose up -d --build`
- [ ] `GET /api/v1/display/meta` après 21:00 → `refresh_seconds` ≥ plusieurs heures,
      `content_hash` stable d'un appel à l'autre

### b. Package Home Assistant : `eink_dashboard.yaml` → `eink_dashboard_battery.yaml`

Le *comment* dépend de l'install (les deux fichiers définissent le même `rest`,
donc **remplacement**, jamais cohabitation) :

- install par dossier `packages/` : `cp homeassistant/eink_dashboard_battery.yaml
  <config_ha>/packages/eink_dashboard.yaml`
- `!include` explicite : faire pointer l'include sur le nouveau fichier, ou
  remplacer le contenu
- collé dans `configuration.yaml` : remplacer les blocs `rest:` / `automation:` /
  `script:` de l'ancien par ceux du nouveau, **ajouter** `input_text:` +
  `input_boolean:` (attention aux collisions de clés avec tes autres helpers)

Puis :

- [ ] recharger (Outils de dév → YAML → RESTful, Automations, `input_text`,
      `input_boolean`) ou redémarrer HA
- [ ] `input_text.eink_dashboard_shown_hash` et
      `input_boolean.eink_dashboard_maintenance` existent
- [ ] l'automation `Eink dashboard - refresh e-paper on content change` a disparu
      (le service `esphome.eink_dashboard_refresh` n'existe plus en deep sleep)

### c. Firmware

- [ ] `secrets.yaml` : `static_ip` / `gateway` / `subnet` renseignés (IP fixe hors DHCP)
- [ ] **activer `input_boolean.eink_dashboard_maintenance`** avant le flash
- [ ] `esphome run firmware/xiao-epaper-battery.yaml` → **OTA** (le panneau tourne
      encore le firmware secteur, joignable ; pas besoin d'USB). Après ce flash,
      tout OTA suivant exige la fenêtre `maintenance`.
- [ ] logs : boot → Wi-Fi/API → `output.turn_on adc_enable` → lecture ADC →
      compare `ha_target_hash` (+ `-lowbat` si besoin) / `ha_shown_hash` →
      dessine si différent → reste éveillé (maintenance ON)

### d. Capteur batterie

- [ ] `sensor.eink_dashboard_tension_batterie` : valeur crédible **3,3–4,2 V**
      (le panneau est en charge USB → attendu ~4,1–4,2 V)
- [ ] `sensor.eink_dashboard_batterie` : `%` cohérent
- [ ] **si valeur nulle / aberrante / ~1,6 V incohérent** : la broche enable
      n'est pas GPIO6 → essayer `pin: GPIO7` sur `output: adc_enable`, ou vérifier
      le ratio du pont (`filters: multiply`). Le remonter.
- [ ] débrancher l'USB → la tension baisse (batterie seule sous charge Wi-Fi) ;
      rebrancher → elle remonte vers 4,2 V au réveil suivant
- [ ] (optionnel) baisser temporairement le seuil `3.55f` près de la tension
      courante → au réveil suivant la pastille batterie apparaît dans l'en-tête,
      `input_text` prend le suffixe `-lowbat` ; remettre le seuil

### e. Deep sleep

- [ ] désactiver `maintenance` → l'ESP entre en deep sleep (log + durée =
      `refresh_seconds`)
- [ ] réveil suivant : se reconnecte, relit la batterie, **ne redessine pas**
      si le contenu est inchangé (log « contenu inchangé »)
- [ ] changer une donnée visible en journée → au réveil suivant (≤ `refresh_seconds`)
      l'écran se met à jour, `input_text.eink_dashboard_shown_hash` suit
- [ ] nuit : aucun réveil ne redessine (hash gelé 21:00–07:30)
- [ ] (optionnel) wattmètre : sommeil ~50 µA, pic de réveil (durée × courant) →
      autonomie estimée vs ~3 mois / 2000 mAh

Rollback batterie → secteur : `maintenance` ON → attendre un réveil →
`esphome run firmware/xiao-epaper.yaml` (OTA) ou USB (BOOT+RESET) ; remettre le
package `homeassistant/eink_dashboard.yaml`.

---

## 10. Verdict

- [ ] **OK** — tout passe, RAM stable, pas de reboot.
      → garder la branche, laisser tourner 48 h (§22 du plan), puis planifier
      suppression TRMNL + V2 métier.
- [ ] **KO** — instabilité RAM / reboot / décodage image même en PNG.
      → `git checkout main && git branch -D feat/ha-esphome-migration`,
      reflasher le firmware TRMNL, documenter le blocage ici :

```
Blocage observé :



```
