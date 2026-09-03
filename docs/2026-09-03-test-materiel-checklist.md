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
#     ota_password, dashboard_image_url = http://<IP_BACKEND>:8000/image/dashboard.bmp
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
# secrets.yaml HA : eink_dashboard_meta_url: http://<IP_BACKEND>:8000/api/v1/display/meta
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
