"""Blueprint schema and placeholder checks."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from homeassistant.components.blueprint.models import Blueprint
from homeassistant.components.blueprint.schemas import BLUEPRINT_SCHEMA

BLUEPRINT_DIR = Path(__file__).parents[1] / "blueprints" / "automation" / "tonewatch"


@pytest.mark.parametrize("name", ["play_dispatch_audio.yaml", "notify_with_audio.yaml"])
def test_blueprints_have_valid_inputs_and_no_undefined_placeholders(name: str) -> None:
    text = re.sub(r"!input ([A-Za-z0-9_]+)", r'"!input \1"', (BLUEPRINT_DIR / name).read_text())
    payload: dict[str, Any] = yaml.safe_load(text)
    Blueprint(payload, schema=BLUEPRINT_SCHEMA)
    assert payload["blueprint"]["domain"] == "automation"
    inputs = payload["blueprint"]["input"]
    assert len(inputs) == len(set(inputs))
    body = yaml.safe_dump(payload)
    placeholders = set(re.findall(r"!input ([A-Za-z0-9_]+)", body))
    assert placeholders <= set(inputs)
    assert payload["trigger"][0]["platform"] == "state"
