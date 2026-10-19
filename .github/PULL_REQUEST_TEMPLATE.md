## What does this PR do?

<!-- One or two sentences. Link the issue it fixes: "Closes #123". -->

## Type of change

- [ ] `feat` - new feature
- [ ] `fix` - bug fix
- [ ] `docs` - documentation only
- [ ] `refactor` - no behaviour change
- [ ] `test` - tests only
- [ ] `ci` / `build` - workflows, packaging, dependencies
- [ ] `chore` - anything else

## Checklist

- [ ] I have read [CONTRIBUTING.md](../CONTRIBUTING.md).
- [ ] The PR title follows Conventional Commits, e.g. `feat: add LAN control to the add-on`.
- [ ] Tests pass locally: `pytest addon/tests -q`.
- [ ] Lint passes locally: `ruff check addon/app addon/tests`.
- [ ] Metadata validates: `python scripts/validate_metadata.py`.
- [ ] Documentation updated when user-facing behaviour changed (README / addon/README).
- [ ] The integration version in `custom_components/sonoff/manifest.json` was **not** bumped here (maintainers bump it at release time).
- [ ] UI changes include a screenshot in the description.
- [ ] No secrets, tokens, passwords or personal data are committed.

## How was this tested?

<!-- Commands you ran, device models, Home Assistant version... -->

## Related issues

<!-- Closes #... -->
