# Pla: tornar a fer funcionar Home Assistant amb la llista de dispositius

## Estat actual (2026-10-20)

- HA 2026.10.0 (MCP: `http://192.168.3.2:9583/...`), broker MQTT `192.168.3.2:1883` (usuari `mqtt`) amb discovery activat i **zero** temes retinguts.
- Integració `custom_components.sonoff` instal·lada **3.17.1**: no carrega cap dispositiu.
- Causa al log de HA: `TypeError: XRegistryCloud.login() got an unexpected keyword argument 'mqtt_enabled'` (`custom_components/sonoff/__init__.py:228`).
- Per què: el wizard desa els camps `mqtt_*` dins `entry.data` i `async_setup_entry` cridava `login(**data)`.
- Add-on **OpenSonoffMQTT no instal·lat** a HA, per tant el discovery des de l'app encara no pot aparèixer.
- Fix ja aplicat en local (sense commit): `login(..., **_extra)` + log debug, a les dues còpies (`custom_components/.../cloud.py` i `addon/app/ewelink/cloud.py`).

## Fases

1. **Fix + test** (jo; test: subagent)
   - `login()` tolera claus extra a les dues còpies.
   - Test de regressió `addon/tests/test_cloud_login.py`.
   - Bump: `custom_components/sonoff/manifest.json` 3.18.1, `addon/config.yaml` 0.3.1.
2. **PR + CI + release** (jo)
   - Branca `fix/login-extra-args` → commit → push → PR → label `automerge`.
   - Checks obligatoris: Add-on tests, Lint, Validate metadata, Build add-on image, PR title, HACS, Hassfest.
   - Squash merge, tag `v3.18.1`, workflow Release.
3. **Actualitzar HA real** (jo, via MCP)
   - `update.opensonoffmqtt_update` → install.
   - Recarregar l'entrada de configuració `01M5B6QSM7HNF7N1Y74K4GSE9G`.
4. **Verificació** (subagent + jo)
   - Logs sense `TypeError`; dispositius Sonoff > 0; bridge MQTT publica `<prefix>/<id>/state`.
   - Diagnostics de la integració: `version: 3.18.1`.
5. **Opcional (decisió de l'usuari)**
   - Instal·lar l'add-on OpenSonoffMQTT si vol la llista de l'app via MQTT discovery.

## Criteris d'acceptació

- HA mostra els dispositius Sonoff (entitats > 0) després de recarregar l'entrada.
- Cap `TypeError` al log de `custom_components.sonoff`.
- CI i release `v3.18.1` verds.
- Bridge MQTT de la integració connectat (o log clar si el broker no és accessible).

## Riscos

- L'entitat d'actualització de HACS pot trigar a veure 3.18.1 → forçar `update.check` i esperar.
- Si HA no pot arribar a `192.168.3.2:1883`, el bridge fallarà però les entitats no.
- `master` està protegit: res de push directe; tot per PR amb el label `automerge`.
