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
   avec le `content_hash` courant (lu sur `http://<backend>:8000/api/v1/display/meta`).
   L'écran doit se dessiner.

## Vérifications matérielles (checklist complète : `docs/2026-09-03-test-matériel-checklist.md`)

- orientation, noir/blanc non inversé, pas de crop, plein cadre 800x480 ;
- `esphome logs` : pas de reboot / watchdog sur 20+ téléchargements ;
- RAM libre stable.

## Fallback BMP → PNG

`online_image` décode BMP 1/8/24 bits **et** PNG. Si le BMP produit par Pillow
ne s'affiche pas correctement :

1. ajouter côté backend une route `GET /image/dashboard.png` (le pipeline a déjà
   `to_png_bytes`), même `ETag` ;
2. dans `secrets.yaml` : `dashboard_image_url: http://<backend>:8000/image/dashboard.png` ;
3. dans `xiao-epaper.yaml` : `format: PNG`.

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

## Rollback vers TRMNL

Ce firmware ne touche pas le backend. Pour revenir en arrière : reflasher le
firmware TRMNL précédent. Les endpoints TRMNL (`/api/setup`, `/api/display`, …)
sont restés en place côté FastAPI.

<!-- Config TRMNL précédente (à compléter avant migration si non documentée ailleurs) :
     modèle firmware, version, refresh_rate, URL serveur.
-->
