# Contributing to OpenSonoffMQTT

Thanks for helping! This repository ships two things:

| Folder | What it is |
| --- | --- |
| `custom_components/sonoff/` | Home Assistant integration (fork of [AlexxIT/SonoffLAN](https://github.com/AlexxIT/SonoffLAN)) with the MQTT bridge and its setup wizard. |
| `addon/` | Stand-alone app (Home Assistant add-on / Docker): same MQTT topics, its own web page, own eWeLink client. |

`addon/app/ewelink/{base,cloud,local}.py` are copies of
`custom_components/sonoff/core/ewelink/`. **If you change one, change the other**
so the app and the integration speak the same protocol.

## Development setup

You need Python 3.12+ and (optional, for the app) Docker.

```sh
git clone https://github.com/Assidefok/OpenSonoffMQTT.git
cd OpenSonoffMQTT
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate

pip install -r addon/requirements.txt -r scripts/requirements.txt
pip install pytest ruff
```

## Checks to run before opening a PR

```sh
pytest addon/tests -q                  # unit tests (no Home Assistant needed)
ruff check addon/app addon/tests       # lint (E, F, W; line length 88)
python scripts/validate_metadata.py    # manifest, translations, add-on YAML, compose
docker build -t opensonoffmqtt:dev addon   # optional: verifies the add-on image
```

The Home Assistant integration tests in `tests/` need the upstream
`homeassistant` test dependencies; they are not required for changes that only
touch `addon/`.

Try the app locally with `docker compose up -d` and open
<http://localhost:8099>, or run it directly:

```sh
cd addon
CONFIG_PATH=./data/config.json python -m uvicorn app.main:app --port 8099
```

## Branches and commits

- Work on a fork, in a branch named after the type: `feat/lan-control`,
  `fix/mqtt-reconnect`, `docs/add-on-screenshot`.
- Commits and **PR titles** follow [Conventional Commits](https://www.conventionalcommits.org/):
  `feat: ...`, `fix: ...`, `docs: ...`, `refactor: ...`, `test: ...`, `ci: ...`,
  `build: ...`, `chore: ...`.
- Keep one topic per PR. Do not mix refactors with fixes.
- Do not bump `custom_components/sonoff/manifest.json` or `addon/config.yaml`
  versions in a feature PR; releases are cut by the maintainers.

## Pull request protocol

1. **Open an issue first** for anything bigger than a typo, so the approach can
   be agreed before you write code.
2. Fill in the PR template: what it does, type, checklist, how you tested it.
   UI changes need a screenshot.
3. Make sure CI is green. The `CI` workflow runs the add-on tests, ruff, the
   metadata validation, the Docker build and the PR title check; the `HACS
   validation` workflow runs hassfest/HACS checks.
4. A code owner (`@Assidefok`) reviews the PR. At least one approving review is
   required, plus green checks.
5. PRs are merged with **Squash and merge**; the branch is deleted afterwards.
6. Do not force-push `master` and do not merge your own PR without review.
7. Dependabot PRs follow the same rules: wait for green CI, then merge. Groups
   are configured in `.github/dependabot.yml` (weekly, Monday).

## Releases (maintainers)

1. Bump `custom_components/sonoff/manifest.json` `version` (semver).
   If the add-on changed, bump `addon/config.yaml` `version` too (its own semver).
2. Commit as `chore(release): vX.Y.Z`.
3. Tag and push: `git tag vX.Y.Z && git push origin vX.Y.Z`.
4. The `Release` workflow checks that the tag matches the manifest version,
   creates the GitHub release with generated notes, and publishes the add-on
   image to `ghcr.io/assidefok/opensonoffmqtt`.
5. Users get the integration update via HACS and the add-on update via the
   Home Assistant add-on store.

## Security

Please do not open a public issue for a vulnerability (credentials leaking,
authentication bypass, command injection...). Contact the maintainer privately
through GitHub instead.

## Code style

- Line length 88, ruff rules `E`, `F`, `W` (see `pyproject.toml`).
- Type hints are welcome in new code.
- Keep vendored eWeLink modules close to upstream so future syncs stay easy.
