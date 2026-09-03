# Package Home Assistant — dashboard e-ink Lyon

Orchestration du rafraîchissement de l'e-paper. HA n'est **pas** requis pour que
FastAPI fonctionne ; il ne fait que décider *quand* l'écran doit changer.

Plan : `docs/2026-09-03-eink-dashboard-lyon-esphome-implementation-plan.md`.

## Principe

| Entité | Origine | Rôle |
|---|---|---|
| `sensor.eink_dashboard_target_hash` | ce package (`rest`, poll 60 s) | hash du contenu à jour, servi par `/api/v1/display/meta` |
| `sensor.eink_dashboard_content_hash` | device ESPHome (`text_sensor` « Content hash ») | hash réellement affiché à l'écran |
| `esphome.eink_dashboard_refresh` | firmware ESPHome | télécharge + dessine l'image du hash passé |

Automation : si les deux hash diffèrent (et que le hash cible est valide),
appeler le service `refresh`. L'ESP dessine puis republie son hash → les deux
sensors se rejoignent → repos.

## Installation

1. **Activer les packages** dans `configuration.yaml` (si pas déjà fait) :

   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```

2. **Copier le package** :

   ```bash
   cp homeassistant/eink_dashboard.yaml <config_ha>/packages/eink_dashboard.yaml
   ```

3. **Renseigner le secret** — ajouter à `<config_ha>/secrets.yaml` :

   ```yaml
   eink_dashboard_meta_url: "http://<IP_BACKEND>:9001/api/v1/display/meta"
   ```

4. **Adopter le device ESPHome** (intégration ESPHome → Découvert → Configurer).

5. **Vérifier les noms.** Le package suppose un device nommé `eink-dashboard`.
   Si votre device porte un autre nom, remplacer dans `eink_dashboard.yaml` :
   - `sensor.eink_dashboard_content_hash` → `sensor.<votre_nom>_content_hash`
   - `esphome.eink_dashboard_refresh` → `esphome.<votre_nom>_refresh`
   (Outils de développement → États / Services pour retrouver les noms exacts.)

6. **Recharger** : Outils de développement → YAML → « RESTful » + « Automations »
   (ou redémarrer HA).

## Vérifier

- Outils de développement → États : `sensor.eink_dashboard_target_hash` a une
  valeur de 16 caractères hex, attribut `refresh_seconds`.
- Appeler `script.eink_dashboard_force_refresh` → l'écran se redessine,
  `sensor.eink_dashboard_content_hash` prend la valeur cible.
- Forcer un changement de donnée visible côté backend → sous ~60 s l'automation
  `Eink dashboard - refresh e-paper on content change` se déclenche une fois.
- Laisser tourner sans changement → l'automation ne se déclenche jamais.

## Pannes (comportement attendu)

- **Backend down** : `target_hash` → `unavailable`, automation inerte, écran conservé.
- **HA down** : écran conservé ; au redémarrage, trigger `homeassistant start`
  resynchronise si besoin.
- **ESP hors ligne** : `content_hash` → `unavailable` ; au retour, l'ESP
  redessine (`wifi.on_connect`) et republie.

## Variante mode batterie

`eink_dashboard_battery.yaml` remplace ce package quand l'ESP tourne sous
`firmware/xiao-epaper-battery.yaml` (deep sleep). Installer **l'un ou l'autre**,
jamais les deux (même `rest` sensor). En mode batterie HA n'appelle plus de
service : il mémorise le hash affiché dans `input_text.eink_dashboard_shown_hash`
et expose `input_boolean.eink_dashboard_maintenance` (garde l'ESP éveillé pour un
OTA). Voir `docs/2026-09-03-test-materiel-checklist.md` §10bis.

## Désinstaller (rollback)

Supprimer `packages/eink_dashboard.yaml`, la ligne de `secrets.yaml`, recharger.
Aucun impact sur FastAPI ni sur les autres intégrations.
