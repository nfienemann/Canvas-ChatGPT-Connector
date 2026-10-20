from pathlib import Path

import pytest
from pydantic import ValidationError

from canvas_bridge.config import Settings
from canvas_bridge.domain import DomainError


def test_T37_no_model_api_or_student_billing_dependency():
    text = Path("pyproject.toml").read_text()
    assert '"openai' not in text and '"anthropic' not in text and '"stripe' not in text
    assert "OPENAI_API_KEY" not in Path(".env.example").read_text()


def test_T38_unsupported_institutions_cannot_be_contacted(bridge):
    with pytest.raises(DomainError):
        bridge.registry.require("rowan-candidate")
    with pytest.raises(DomainError):
        bridge.registry.require("https://arbitrary.example")
    with pytest.raises(DomainError):
        bridge.registry.require("synthetic", synthetic=False)


def test_T37_T38_synthetic_cannot_bind_public_or_become_live_silently():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, profile="synthetic", host="0.0.0.0")  # noqa: S104
    with pytest.raises(ValidationError):
        Settings(_env_file=None, profile="hosted")
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            profile="hosted",
            live_access_enabled=True,
            database_url="sqlite:///:memory:",
        )
