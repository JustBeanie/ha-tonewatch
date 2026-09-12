uv := env_var_or_default("TONEWATCH_UV", "uv")

lint:
    {{uv}} run ruff check custom_components tests
    {{uv}} run ruff format --check custom_components tests

typecheck:
    {{uv}} run mypy custom_components/tonewatch

test:
    {{uv}} run pytest

check: lint typecheck test
