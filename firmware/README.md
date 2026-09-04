# Firmware ESPHome — XIAO 7.5" ePaper Panel

Firmware minimal, orchestré par Home Assistant. Voir le plan :
`docs/2026-09-03-eink-dashboard-lyon-esphome-implementation-plan.md`.

## Ce que fait ce firmware

- se connecte au Wi-Fi et à la Native API (chiffrée) ;
- expose un service `esphome.eink_dashboard_refresh(content_hash)` ;
- sur appel : télécharge `dashboard_image_url` (BMP 1 bit 800x480), le dessine,
  publie le hash en `text_sensor` **Content hash** ;
- sur échec de téléchargement : publie `error`, laisse l'écran intact ;
- au (re)boot / reconnexion Wi-Fi : retélécharge et redessine une fois.

Pas de deep sleep, pas de comparaison de hash, pas de persistance : Home Assistant
décide quand rafraîchir (voir `homeassistant/`).

## Préparer

```bash
cp firmware/secrets.example.yaml firmware/secrets.yaml
# renseigner wifi, api_encryption_key, ota_password, dashboard_image_url
esphome config firmware/xiao-epaper.yaml     # valide la syntaxe
```

## Flasher (premier flash : USB)

```bash
esphome run firmware/xiao-epaper.yaml
```

Si l'ESP ne prend pas le firmware par USB : maintenir **BOOT**, presser **RESET**,
relâcher **BOOT** pour forcer le mode téléchargement, puis relancer.

Les flashs suivants passent par OTA (pas de deep sleep → toujours joignable).

## Après le flash

1. Le device apparaît dans Home Assistant → **Adopter**.
2. Relever le nom réel du service (`esphome.<name>_refresh`) et de l'entité
   `text_sensor` (`Content hash`). Les reporter dans `homeassistant/README.md`
   si `<name>` ≠ `eink_dashboard`.
3. Outils de développement → Services → appeler `esphome.eink_dashboard_refresh`
   avec le `content_hash` courant (lu sur `http://<backend>:9001/api/v1/display/meta`).
   L'écran doit se dessiner.

## Vérifications matérielles (checklist complète : `docs/2026-09-03-test-materiel-checklist.md`)

- orientation, noir/blanc non inversé, pas de crop, plein cadre 800x480 ;
- `esphome logs` : pas de reboot / watchdog sur 20+ téléchargements ;
- RAM libre stable.

## Fallback BMP → PNG

`online_image` décode BMP 1/8/24 bits **et** PNG. Si le BMP produit par Pillow
ne s'affiche pas correctement :

1. ajouter côté backend une route `GET /image/dashboard.png` (le pipeline a déjà
   `to_png_bytes`), même `ETag` ;
2. dans `secrets.yaml` : `dashboard_image_url: http://<backend>:9001/image/dashboard.png` ;
3. dans `xiao-epaper.yaml` : `format: PNG`.

## Rendu noir/blanc

Le BMP 1 bit de Pillow a le bit à 1 sur les pixels **blancs** ; `online_image`
`type: BINARY` dessine un bit à 1 en avant-plan. Le lambda du `display` échange
donc `COLOR_OFF, COLOR_ON` pour garder fond blanc / texte noir. En cas de
bascule vers `format: PNG`, revérifier ce point (le retirer si le PNG s'affiche
déjà à l'endroit).

## Pinout de référence (Seeed)

| Fonction | GPIO |
|---|---|
| SPI CLK | GPIO8 |
| SPI MOSI | GPIO10 |
| CS | GPIO3 |
| DC | GPIO5 |
| BUSY | GPIO4 (inverted) |
| RESET | GPIO2 |

`board: esp32-c3-devkitm-1`, `display model: 7.50inv2`.

## Mode batterie / deep sleep (`xiao-epaper-battery.yaml`)

Variante **non encore validée sur matériel**. `xiao-epaper.yaml` (secteur, pas de
deep sleep) reste la référence tant que le test §10bis de la checklist n'est pas
passé.

Différences :

- l'ESP se réveille seul, fait un cycle complet, se rendort — HA n'appelle plus
  de service `refresh` ;
- au réveil il importe de HA : `sensor.eink_dashboard_target_hash` (+ attribut
  `refresh_seconds`), `input_text.eink_dashboard_shown_hash`,
  `input_boolean.eink_dashboard_maintenance` ;
- il ne redessine l'e-paper **que si** le hash cible diffère du hash mémorisé par
  HA ; sinon il se rendort sans toucher l'écran ;
- `sleep_duration` = `refresh_seconds` fourni par le backend, borné [60 s, 6 h].
  Le backend renvoie 180 s de 07:30 à 09:00, 1800 s en journée calme, 300 s si une
  perturbation est active ou une station Vélo'v sous 3 vélos, et « dors jusqu'à
  07:30 » (plafonné 4 h) la nuit.
- gel du contenu : de 09:00 à 21:00 le hash ne réagit qu'aux évènements
  (perturbation, Vélo'v bas) ; de **21:00 à 07:30 le hash est totalement figé**
  → aucun redessin la nuit, l'en-tête affiche « MAJ HH:MM ».

**Pas de mesure de batterie** : le XIAO ESP32-C3 du panneau n'expose aucune broche
ADC libre reliée à la batterie (sonde du 2026-09-04 : GPIO0/GPIO1 flottants). Il
faudrait souder un pont diviseur ou ajouter une puce I²C (cf. plan §22).

Utiliser le package HA **`homeassistant/eink_dashboard_battery.yaml`** (à la place
de `eink_dashboard.yaml`) et renseigner `static_ip` / `gateway` / `subnet` dans
`secrets.yaml`. Migration détaillée : `docs/2026-09-03-test-materiel-checklist.md`
§10bis. Pour un OTA : activer `input_boolean.eink_dashboard_maintenance`, attendre
un réveil, flasher, désactiver.

## Rollback vers TRMNL

Ce firmware ne touche pas le backend. Pour revenir en arrière : reflasher le
firmware TRMNL précédent. Les endpoints TRMNL (`/api/setup`, `/api/display`, …)
sont restés en place côté FastAPI.

<!-- Config TRMNL précédente (à compléter avant migration si non documentée ailleurs) :
     modèle firmware, version, refresh_rate, URL serveur.
-->
