"""AgentProfile — the persona YAML loader (architecture.md §7.2).

The "Agent Designer" surface for the MVP: a persona/model/memory config that packages
into a runnable agent.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError


class AgentProfile(BaseModel):
    name: str
    model_type: str
    system_prompt: str
    temperature: float = 0.7
    memory_limit: int = 10

    @classmethod
    def load_from_yaml(cls, path: str | Path) -> AgentProfile:
        text = Path(path).read_text(encoding="utf-8")
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError(f"invalid YAML in profile {path!r}: {exc}") from exc

        try:
            return cls.model_validate(data)
        except ValidationError as exc:
            raise ValueError(f"invalid agent profile {path!r}: {exc}") from exc
