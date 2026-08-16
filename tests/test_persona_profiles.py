"""profiles/aggressive.yml + profiles/cautious.yml -- contrasting personas
(ARENA-105, roadmap.md §v04.01, architecture.md §7.2).

No model call: this only validates the profiles load and genuinely contrast --
persona *quality* is judged by demo, per the roadmap's own Tests note.
"""

from __future__ import annotations

from agent.profile import AgentProfile


def test_both_profiles_load_and_validate() -> None:
    aggressive = AgentProfile.load_from_yaml("profiles/aggressive.yml")
    cautious = AgentProfile.load_from_yaml("profiles/cautious.yml")
    for profile in (aggressive, cautious):
        assert profile.name
        assert profile.model_type == "haiku"
        assert isinstance(profile.temperature, float)
        assert 0.0 <= profile.temperature <= 1.0
        assert profile.system_prompt
        assert profile.memory_limit > 0


def test_the_two_personas_genuinely_contrast() -> None:
    aggressive = AgentProfile.load_from_yaml("profiles/aggressive.yml")
    cautious = AgentProfile.load_from_yaml("profiles/cautious.yml")

    assert aggressive.name != cautious.name
    assert aggressive.system_prompt != cautious.system_prompt
    # The whole point of this phase: a real tonal/temperament gap, not two
    # profiles that happen to have different names.
    assert aggressive.temperature > cautious.temperature
