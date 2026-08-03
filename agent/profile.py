"""AgentProfile — the MVP Agent Designer surface (architecture.md §7.2, spec §5.2).

A profile packages a distinct agent identity into a runnable config, without touching core logic:
the persona (``system_prompt``), the vendor tier (``model_type`` — fed verbatim to
``create_llm_client``), the sampling temperature, and the short-term memory length. Profiles are
YAML files under ``profiles/``.
"""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


class AgentProfile(BaseModel):
    """A persona/model/memory config packaged into a runnable agent (spec §5.2)."""

    # extra="forbid": a typo'd key in a profile YAML fails loudly instead of being ignored.
    # protected_namespaces=(): allow the architecture-mandated field name `model_type`.
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    name: str
    system_prompt: str
    model_type: str = "haiku"  # -> create_llm_client dispatch (agent/llm.py); the only vendor impl
    temperature: float = Field(default=0.7, ge=0.0, le=1.0)
    memory_limit: int = Field(default=10, gt=0)

    @classmethod
    def load_from_yaml(cls, path: str | Path) -> "AgentProfile":
        """Load and validate a profile YAML; clear errors for missing/invalid/misshapen files."""
        profile_path = Path(path)
        if not profile_path.is_file():
            raise FileNotFoundError(f"profile not found: {profile_path}")
        raw: Any = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"profile {profile_path} must be a YAML mapping of profile fields")
        return cls.model_validate(raw)
