"""Curriculum / Stage system for Skill Lab.

Each stage defines:
- Which actions are masked
- What rewards to emphasize
- Which starting state to use
- Per-environment directives (e.g., which starter to pick)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from skill_lab.rewards import REWARD_BASELINES, big_reward, medium_reward, small_reward


@dataclass
class Stage:
    """A single training stage in the curriculum."""
    name: str
    description: str

    # Action masking
    disable_start: bool = True
    disable_select: bool = True
    disable_B: bool = False

    # Reward configuration
    milestone_reward: float = medium_reward
    exploration_reward: float = small_reward
    combat_reward: float = 0.0

    # Starting state
    init_state: str = "v2/state/init.state"

    # Max steps per episode
    max_steps: int = 7200

    # Per-environment directives
    # Key = env index (or "default"), Value = directive config
    directives: dict[str, dict[str, Any]] = field(default_factory=dict)
    
    # Action masks dictionary (for JSON compatibility)
    action_masks: dict[str, bool] = field(default_factory=dict)


# ========================================
# STARTER POKEMON DIRECTIVES
# ========================================

STARTER_DIRECTIVES = {
    "charmander": {
        "target_starter": "Charmander",
        "description": "Navigate to pick Charmander (right ball)",
    },
    "squirtle": {
        "target_starter": "Squirtle",
        "description": "Navigate to pick Squirtle (middle ball)",
    },
    "bulbasaur": {
        "target_starter": "Bulbasaur",
        "description": "Navigate to pick Bulbasaur (left ball)",
    },
}


# ========================================
# STAGE DEFINITIONS
# ========================================

STAGES: dict[str, Stage] = {

    # "explore": Stage(
    #     name="explore",
    #     description="Learn basic movement and exploration.",
    #     disable_start=True,
    #     disable_select=True,
    #     milestone_reward=big_reward, 
    #     # milestone_multiplier=0.5,
    #     exploration_reward=small_reward,
    #     combat_reward=0.0,
    #     init_state="v2/state/init.state",
    #     max_steps=7200,
    # ),

    "progress": Stage(
        name="progress",
        description="Full game progression. All milestones active.",
        disable_start=True,
        disable_select=True,
        milestone_reward=big_reward,
        # where do we set up the milestone_multiplier. ?
        exploration_reward=small_reward,
        combat_reward=medium_reward,
        init_state="v2/state/init.state",
        max_steps=14400,
    ),

    "starter": Stage(
        name="starter",
        description="Get a starter Pokemon. Short episodes for fast learning.",
        disable_start=True,
        disable_select=True,
        milestone_reward=big_reward,
        exploration_reward=small_reward,
        combat_reward=0.0,
        init_state="v2/state/init.state",
        max_steps=1200,  # ← SHORT! Just enough to pick the starter
        directives={
            "0": STARTER_DIRECTIVES["charmander"],
            "1": STARTER_DIRECTIVES["squirtle"],
            "2": STARTER_DIRECTIVES["bulbasaur"],
            "default": STARTER_DIRECTIVES["charmander"],
        },
    ),

    "combat": Stage(
        name="combat",
        description="Learn to fight wild Pokemon.",
        disable_start=True,
        disable_select=True,
        milestone_reward=big_reward,
        # add a milestone_reward_multiplier
        exploration_reward=0.1,
        combat_reward=medium_reward,
        init_state="v2/state/combat_start.state",
        max_steps=3600,
    ),

    "menu": Stage(
        name="menu",
        description="Learn to navigate menus. Start/Select ENABLED.",
        disable_start=False,   # ← ENABLED for menu learning
        disable_select=False,  # ← ENABLED for menu learning
        milestone_reward=big_reward,
        exploration_reward=0.0, # should be renamed with _multiplier.
        combat_reward=0.0,      # should be renamed with _multiplier.
        init_state="v2/state/pokemon_center.state",
        max_steps=7200,
    ),

}


def get_stage(name: str) -> Stage:
    if name not in STAGES:
        available = ", ".join(STAGES.keys())
        raise KeyError(f"Unknown stage '{name}'. Available: {available}")
    return STAGES[name]


def list_stages() -> list[str]:
    return list(STAGES.keys())


def get_directive_for_env(stage: Stage, env_index: int) -> dict[str, Any]:
    """Get the directive for a specific environment index."""
    # Check if this specific env has a directive
    idx_str = str(env_index)
    if idx_str in stage.directives:
        return stage.directives[idx_str]
    # Fall back to default
    return stage.directives.get("default", {})


def stage_to_config(stage: Stage) -> dict[str, Any]:
    """Convert a Stage to a config dict for the environment wrapper."""
    return {
        "disable_start": stage.disable_start,
        "disable_select": stage.disable_select,
        "milestone_reward_multiplier": stage.milestone_reward,
        "event_reward_multiplier": 0.0,
        "exploration_reward_multiplier": stage.exploration_reward,
        "combat_reward_multiplier": stage.combat_reward,
        "capture_reward_multiplier": 0.0,
        "healing_reward_multiplier": 0.0,
        "training_reward_multiplier": 0.0,
        "breadcrumb_reward_multiplier": 0.0,
        "events_path": "v2/events.json",
        "max_steps": stage.max_steps,
    }