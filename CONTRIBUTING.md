# Contributing to ha-tonewatch

Thanks for helping improve the ToneWatch integration. Please search existing issues before opening a new one. For a bug, include your Home Assistant and ToneWatch versions, a short reproduction, relevant redacted logs, and whether ToneWatch runs as a Home Assistant App or elsewhere. Never attach a token, signed live URL, recording, or unredacted CAD data.

## Local development

The locked development environment uses Python 3.14 and Home Assistant 2026.10.4. The shipped integration continues to support Home Assistant 2026.2 and Python 3.13.

```sh
uv sync --locked --python 3.14
uv run ruff check custom_components tests
uv run ruff format --check custom_components tests
uv run mypy custom_components/tonewatch
uv run pytest
```

On Linux, run the full test suite before a pull request. Home Assistant's test harness imports Unix modules and does not run natively on Windows; WSL is suitable. CI also runs Hassfest and HACS validation.

Keep entity unique IDs and blueprint input keys stable. Add tests for changed behavior, update `strings.json` and `translations/en.json` together, and document changes a user will notice. Run both blueprint tests when changing automation examples. Use the upstream [ToneWatch API](https://github.com/JustBeanie/tonewatch) as the source for server payloads.

Security reports belong in [private vulnerability reporting](https://github.com/JustBeanie/ha-tonewatch/security/advisories/new), not public issues.
