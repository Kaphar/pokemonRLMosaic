"""Skill registry."""

from __future__ import annotations

from typing import Any

from skill_lab.skills.base import Skill
from skill_lab.skills.navigate import NavigateToSkill


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def reset(self) -> None:
        for skill in self._skills.values():
            skill.reset()

    def __contains__(self, name: str) -> bool:
        return name in self._skills

    def __repr__(self) -> str:
        return f"SkillRegistry({list(self._skills.keys())})"


def default_registry() -> SkillRegistry:
    registry = SkillRegistry()
    registry.register(NavigateToSkill(target_map_id=0))
    return registry
