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
4. A code owner (`@Assidefok`) reviews the PR. Keep the PR small and linked to
   its issue; the review is what keeps `master` trustworthy.
5. PRs are merged with **Squash and merge**; the branch is deleted afterwards,
   and history stays linear.
6. Do not force-push `master` and do not merge your own PR without review.
7. Dependabot PRs are handled by automation (see below): patch and minor
   updates merge by themselves once every required check passes; major updates
   wait for a human.

## Automation

The repository runs itself as much as possible:

- **Branch protection** (`protect-master` ruleset): `master` only accepts pull
  requests. Required checks: `Add-on tests`, `Lint`, `Validate metadata`,
  `Build add-on image`, `PR title`, `HACS`, `Hassfest`. Force pushes and branch
  deletions are blocked.
- **Dependabot** ([`.github/dependabot.yml`](.github/dependabot.yml)) opens
  weekly PRs for pip (`/addon`, `/scripts`), Docker (`/addon`) and GitHub
  Actions. Commit messages use `chore(deps): ...`, so they pass the PR title
  check.
- **Dependabot auto-merge**
  ([`.github/workflows/dependabot-auto-merge.yml`](.github/workflows/dependabot-auto-merge.yml))
  enables auto-merge (squash) for **patch and minor** updates as soon as every
  required check is green; major updates get a comment and stay open.
- **`automerge` label**: add it to any PR and
  [`automerge.yml`](.github/workflows/automerge.yml) enables auto-merge once the
  required checks pass.
- **CodeRabbit** ([`.coderabbit.yaml`](.coderabbit.yaml)) reviews PRs
  automatically once the
  [CodeRabbit GitHub App](https://github.com/apps/coderabbitai) is installed on
  the repository.
- **Dependabot alerts and security updates** are enabled in the repository
  settings, so vulnerable dependencies get a PR as soon as one is published.

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
