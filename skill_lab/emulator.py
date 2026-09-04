"""Environment factory for the Skill Lab.

This file creates PyBoy environments wrapped with SkillLabWrapper.
It also provides the tile_group() function for rendering the mosaic UI.

Key concept:
    make_vec_env() creates N environments, each wrapped in SkillLabWrapper.
    The wrapper handles action masking and milestone rewards automatically.
    The main script (run_mosaic.py) doesn't need to worry about any of it.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from pyboy.utils import WindowEvent

PROJECT_ROOT = Path(__file__).resolve().parents[1]
V2_DIR = PROJECT_ROOT / "v2"
if str(V2_DIR) not in sys.path:
    sys.path.insert(0, str(V2_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from v2.red_gym_env_v2 import RedGymEnv
from skill_lab.config import ACTION_FREQ, TILE_HEIGHT, TILE_WIDTH, EVENT_JSON_PATH
from skill_lab.env_wrapper import SkillLabWrapper


def make_env(rank: int, env_conf: dict[str, Any]):
    """Create a single environment factory for DummyVecEnv."""
    def _init() -> SkillLabWrapper:
        cfg = dict(env_conf)
        cfg["instance_id"] = f"mosaic-{rank:03d}"

        # Create the base environment
        base_env = RedGymEnv(cfg)

        # Wrap it with our custom logic
        wrapped_env = SkillLabWrapper(base_env, config={
            "disable_start_select": cfg.get("disable_start_select", True),
            "milestone_reward": cfg.get("milestone_reward", 5.0),
            "milestones_path": cfg.get("milestones_path", None),
        })

        return wrapped_env

    return _init


def make_vec_env(num_envs: int, env_conf: dict[str, Any]):
    """Create a vectorized environment with N parallel instances."""
    from stable_baselines3.common.vec_env import DummyVecEnv
    return DummyVecEnv([make_env(i, env_conf) for i in range(num_envs)])


def observation_frame(observation: dict[str, np.ndarray], index: int) -> np.ndarray:
    """Extract a single frame from the batched observation."""
    image = observation["screens"][index, :, :, 0]
    image = np.repeat(image[:, :, None], 3, axis=2)
    return image


def tile_group(
    observation: dict[str, np.ndarray],
    env,
    profile_name: str,
    env_index: int,
    selected_index: int | None,
    model_loaded: bool,
    show_hud: bool = True,
) -> np.ndarray:
    """Render a single emulator tile with HUD overlay."""
    tile = observation_frame(observation, env_index)
    tile = cv2.resize(tile, (TILE_WIDTH, TILE_HEIGHT), interpolation=cv2.INTER_NEAREST)

    if not show_hud:
        if selected_index == env_index:
            cv2.rectangle(tile, (0, 0), (TILE_WIDTH - 1, TILE_HEIGHT - 1), (0, 220, 255), thickness=3)
        return tile

    steps = env.get_attr("step_count")[env_index]
    map_id = int(env.get_attr("current_map_id")[env_index])
    level_sum = int(env.get_attr("current_level_sum")[env_index])
    hp = float(env.get_attr("read_hp_fraction")[env_index]())

    emulator_frames = steps * ACTION_FREQ
    game_seconds = emulator_frames / 60.0
    label = (
        f"{profile_name} {env_index + 1} | step {steps} | "
        f"game {game_seconds / 60:.1f}m | map {map_id:02X} | lvl {level_sum}"
    )
    if not model_loaded:
        label += " | dry-run"
    if selected_index == env_index:
        label += " | SELECTED"
        border_color = (0, 220, 255)
    else:
        border_color = (20, 20, 20)

    overlay = tile.copy()
    cv2.rectangle(overlay, (0, 0), (TILE_WIDTH - 1, 22), (0, 0, 0), thickness=-1)
    cv2.putText(overlay, label, (5, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
    alpha = 0.6
    tile[:] = cv2.addWeighted(overlay, alpha, tile, 1 - alpha, 0)

    cv2.rectangle(tile, (0, 0), (TILE_WIDTH - 1, TILE_HEIGHT - 1), border_color, thickness=3)
    hp_text = f"HP {hp:.0%}"
    cv2.putText(tile, hp_text, (5, TILE_HEIGHT - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
    return tile