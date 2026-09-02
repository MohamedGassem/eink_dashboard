# API TCL — `tcl_sytral.tclpassagearret`

Capture réelle faite le 2026-09-02 vers 23:00 (Europe/Paris) via :

```bash
curl -s -u "$GRANDLYON_USERNAME:$GRANDLYON_PASSWORD" \
  'https://download.data.grandlyon.com/ws/rdata/tcl_sytral.tclpassagearret/all.json?maxfeatures=20&start=1'
```

Authentification **HTTP Basic** obligatoire (compte data.grandlyon.com). Sans
identifiants la réponse est `{"detail": "Informations d'authentification non fournies."}`.

## Enveloppe

```json
{
  "fields": ["id", "ligne", "direction", "delaipassage", "type", "heurepassage",
             "idtarretdestination", "coursetheorique", "gid", "last_update_fme"],
  "layer_name": "tcl_sytral.tclpassagearret",
  "nb_results": 20,
  "next": "https://.../all.json?...&start=21&maxfeatures=20",
  "values": [ { ...un passage... } ]
}
```

## Champs d'un enregistrement de `values`

| Clé API | Exemple | Rôle | Nom interne |
|---|---|---|---|
| `id` | `30101` (entier) | Identifiant du **point d'arrêt** (arrêt × ligne × sens). Correspond à `id` du référentiel `tcl_sytral.tclarret`. | `stop_id` |
| `ligne` | `"A"`, `"C24"` | Numéro / lettre de ligne | `line` |
| `direction` | `"Vaulx-en-Velin La Soie"` | Libellé de destination | `direction` |
| `heurepassage` | `"2026-09-02 23:25:30"` | Heure de passage attendue. **Datetime naïf**, en heure locale `Europe/Paris`. Format `%Y-%m-%d %H:%M:%S`. | `expected_at` |
| `type` | `"T"` | `"T"` = théorique (horaire), `"E"` = estimé (temps réel). Voir note ci-dessous. | `kind` |
| `delaipassage` | `"34 min"`, `"Proche"`, `"23h52"` | Délai pré-formaté par l'API. Non utilisé : on recalcule depuis `heurepassage`. | — |
| `idtarretdestination` | `36394` | Point d'arrêt terminus | — |
| `coursetheorique` | `"301_301A-080CM_00401137"` | Identifiant de course | — |
| `gid` | `1` | Clé technique datapusher | — |
| `last_update_fme` | `"2026-09-02 22:51:00"` | Horodatage de la dernière mise à jour du flux côté SYTRAL | — |

## Notes

- **`type`** : la capture de 23:00 ne contient que `"T"` (la nuit, tous les
  passages sont théoriques). La valeur temps réel `"E"` est documentée par le
  webservice SYTRAL `tclpassagearret`. `mapper.REALTIME_KIND = "E"` ; une capture
  de jour la confirmera via `tests/integration/test_tcl_live.py`.
- **`id` entier** : le référentiel et la config utilisent des chaînes. Le schéma
  Pydantic active `coerce_numbers_to_str=True`.
- **Filtrage serveur** : `?field=id&value=30103` renvoie uniquement les passages
  de ce point d'arrêt. Le client interroge un point d'arrêt à la fois.
- **Fuseau** : `heurepassage` est naïf. Le schéma lui attache `Europe/Paris`
  (`PassageRecord._assume_paris`). Aucun `datetime` naïf ne sort du module.

## Points d'arrêt de référence (vérifiés le 2026-09-02)

Depuis `tcl_sytral.tclarret` (`?field=nom&value=Bellecour`) :

| `id` | Nom | Desserte |
|---|---|---|
| `30103` | Bellecour | `A:A` (métro A, sens aller) |
| `46051` | Bellecour | `A:R` (métro A, sens retour) |
| `30201` | Bellecour | `D:A` (métro D, sens aller) |
| `30202` | Bellecour | `D:R` (métro D, sens retour) |

Le choix définitif des arrêts suivis dans `config/dashboard.toml` revient à
l'utilisateur.
