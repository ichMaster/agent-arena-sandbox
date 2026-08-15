"""AgentProfile -- the Agent Designer surface for the MVP (architecture.md §7.2)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel


class AgentProfile(BaseModel):
    name: str
    model_type: str  # -> create_llm_client
    temperature: float
    system_prompt: str  # the persona
    memory_limit: int

    @classmethod
    def load_from_yaml(cls, path: str | Path) -> AgentProfile:
        text = Path(path).read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        return cls.model_validate(data)
