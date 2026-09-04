"""Base classes for skills."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import numpy as np


class Skill(ABC):
    def __init__(self, name: str, description: str = "") -> None:
        self.name = name
        self.description = description

    @abstractmethod
    def reset(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def update(self, observation: dict[str, np.ndarray], env) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_action(self, observation: dict[str, np.ndarray], env, base_policy_action: int) -> int:
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"Skill({self.name})"
