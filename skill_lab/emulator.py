import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from gymnasium import spaces
from pyboy.utils import WindowEvent

PROJECT_ROOT = Path(__file__).resolve().parents[1]
V2_DIR = PROJECT_ROOT / "v2"
if str(V2_DIR) not in sys.path:
    sys.path.insert(0, str(V2_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from v2.red_gym_env_v2 import RedGymEnv
from skill_lab.config import ACTION_FREQ, TILE_HEIGHT, TILE_WIDTH


def project_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def make_env(rank: int, env_conf: dict[str, Any]):
    def _init() -> RedGymEnv:
        cfg = dict(env_conf)
        cfg["instance_id"] = f"mosaic-{rank:03d}"
        return RedGymEnv(cfg)

    return _init


def make_vec_env(num_envs: int, env_conf: dict[str, Any]):
    from stable_baselines3.common.vec_env import DummyVecEnv

    return DummyVecEnv([make_env(i, env_conf) for i in range(num_envs)])


def load_policy(path: str | None, env, dry_run: bool):
    if dry_run:
        return None
    if not path:
        raise ValueError("A model path is required, or use --dry-run.")

    from stable_baselines3 import PPO

    return PPO.load(path, env=env)


def observation_frame(observation: dict[str, np.ndarray], index: int) -> np.ndarray:
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
) -> np.ndarray:
    tile = observation_frame(observation, env_index)
    tile = cv2.resize(tile, (TILE_WIDTH, TILE_HEIGHT), interpolation=cv2.INTER_NEAREST)

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
    cv2.putText(
        overlay, label, (5, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1
    )
    alpha = 0.6
    tile[:] = cv2.addWeighted(overlay, alpha, tile, 1 - alpha, 0)

    cv2.rectangle(tile, (0, 0), (TILE_WIDTH - 1, TILE_HEIGHT - 1), border_color, thickness=3)
    hp_text = f"HP {hp:.0%}"
    cv2.putText(
        tile, hp_text, (5, TILE_HEIGHT - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1
    )
    return tile


class ActionBoundary:
    def __init__(self, low_hp_threshold: float) -> None:
        self.low_hp_threshold = low_hp_threshold
        self.last_reason = "menu locked"

    def menu_permission(self, env: RedGymEnv) -> tuple[bool, str]:
        hp = float(env.read_hp_fraction())
        if hp <= self.low_hp_threshold:
            return True, f"low HP {hp:.0%}"
        return False, f"HP {hp:.0%}"

    def apply(self, env: RedGymEnv, action: int) -> int:
        if action >= len(env.valid_actions):
            return env.noop_button_index
        if env.valid_actions[action] == WindowEvent.PRESS_BUTTON_START:
            allowed, reason = self.menu_permission(env)
            self.last_reason = reason if allowed else f"menu denied ({reason})"
            if not allowed:
                return env.noop_button_index
            self.last_reason = f"menu allowed ({reason})"
        return action
