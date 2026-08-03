"""The Agent Designer's output for the MVP (architecture.md §7.2).

A profile is the whole of an agent's identity: who it is, which model it thinks with,
how hot, and how much it remembers. Everything is validated **at load**, because the
alternative is discovering a typo at the first model call -- mid-match, after a seat has
been taken.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent.llm import SUPPORTED_MODEL_TYPES

#: Anthropic accepts 0.0-1.0; a profile outside that range is a mistake, not a style.
MIN_TEMPERATURE = 0.0
MAX_TEMPERATURE = 1.0

#: Enough context to taunt with, bounded so a prompt cannot grow without limit.
DEFAULT_MEMORY_LIMIT = 10
MAX_MEMORY_LIMIT = 100


class ProfileError(ValueError):
    """A profile could not be loaded. Always names the file."""


class AgentProfile(BaseModel):
    """A persona, a model, and a memory budget."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=64)
    system_prompt: str = Field(min_length=1, max_length=4000)
    model_type: str = "haiku"
    temperature: float = 1.0
    memory_limit: int = DEFAULT_MEMORY_LIMIT

    @field_validator("model_type")
    @classmethod
    def _known_model_type(cls, value: str) -> str:
        """Reject at load, not at the first model call.

        ``create_llm_client`` would raise on an unknown type anyway -- but only once the
        agent is already seated in a match. Failing here turns a mid-game crash into a
        startup error.
        """
        if value not in SUPPORTED_MODEL_TYPES:
            raise ValueError(
                f"unknown model_type {value!r}; supported: {', '.join(SUPPORTED_MODEL_TYPES)}"
            )
        return value

    @field_validator("temperature")
    @classmethod
    def _sane_temperature(cls, value: float) -> float:
        if not MIN_TEMPERATURE <= value <= MAX_TEMPERATURE:
            raise ValueError(
                f"temperature {value} is outside {MIN_TEMPERATURE}-{MAX_TEMPERATURE}"
            )
        return value

    @field_validator("memory_limit")
    @classmethod
    def _sane_memory_limit(cls, value: int) -> int:
        if not 1 <= value <= MAX_MEMORY_LIMIT:
            raise ValueError(f"memory_limit {value} is outside 1-{MAX_MEMORY_LIMIT}")
        return value

    @classmethod
    def load_from_yaml(cls, path: str | Path) -> AgentProfile:
        """Read and validate a profile. Every failure names the file."""
        location = Path(path)
        try:
            raw: Any = yaml.safe_load(location.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ProfileError(f"no profile at {location}") from exc
        except yaml.YAMLError as exc:
            raise ProfileError(f"{location} is not valid YAML: {exc}") from exc

        if not isinstance(raw, dict):
            raise ProfileError(f"{location} must contain a YAML mapping, got {type(raw).__name__}")
        try:
            return cls(**raw)
        except Exception as exc:
            raise ProfileError(f"{location}: {exc}") from exc
