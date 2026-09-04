"""Run V2-compatible PyBoy environments in a live mosaic with optional training."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv
from pyboy.utils import WindowEvent

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from skill_lab.config import REWARD_MODIFIER_PRAISE, REWARD_MODIFIER_SLASH, SPECIALIZATION_PRESETS
from skill_lab.emulator import (
    ACTION_FREQ,
    #ActionBoundary,
    make_vec_env,
    tile_group,
)
from skill_lab.inspector import ObservationInspector
from skill_lab.map_window import MapWindow
from skill_lab.mosaic import Mosaic
from skill_lab.stats_window import StatsWindow
from skill_lab.objectives.concrete import LevelPikachuObjective, ReachPewterObjective, TrainSquirtleObjective
from skill_lab.objectives.manager import ObjectiveManager


class Profile:
    def __init__(
        self,
        name: str,
        count: int,
        model_path: str | None,
        explore_weight: float,
    ) -> None:
        self.name = name
        self.count = count
        self.model_path = model_path
        self.explore_weight = explore_weight


def make_config(profile: Profile, session_path: Path, args: argparse.Namespace) -> dict[str, Any]:
    reward_scale = args.reward_scale
    explore_weight = args.explore_weight
    if args.specialization and args.specialization in SPECIALIZATION_PRESETS:
        preset = SPECIALIZATION_PRESETS[args.specialization]
        reward_scale = preset["reward_scale"]
        explore_weight = preset["explore_weight"]
    return {
        "headless": True,
        "save_final_state": False,
        "early_stop": False,
        "action_freq": ACTION_FREQ,
        "init_state": str(args.init_state),
        "max_steps": args.max_steps,
        "print_rewards": False,
        "save_video": False,
        "fast_video": True,
        "session_path": session_path,
        "gb_path": str(args.rom),
        "debug": False,
        "reward_scale": reward_scale,
        "explore_weight": explore_weight,
        "noop_button": True,
    }


def load_policy(path: str | None, env: DummyVecEnv, dry_run: bool) -> PPO | None:
    if dry_run:
        return None
    if not path:
        return None
    return PPO.load(path, env=env)


def create_model(env: DummyVecEnv, args: argparse.Namespace) -> PPO:
    n_steps = args.n_steps
    model = PPO(
        "MultiInputPolicy",
        env,
        verbose=1,
        n_steps=n_steps,
        batch_size=args.batch_size,
        n_epochs=args.n_epochs,
        gamma=args.gamma,
        ent_coef=args.ent_coef,
        tensorboard_log=str(PROJECT_ROOT / "mosaic_sessions" / "tensorboard"),
    )
    from stable_baselines3.common.logger import configure
    model._logger = configure(None, ["stdout"])
    return model


def _transpose_for_model(observation: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    transposed = dict(observation)
    for key in ("screens", "map"):
        if key in transposed:
            transposed[key] = np.transpose(transposed[key], (0, 3, 1, 2))
    return transposed


def find_latest_checkpoint(checkpoint_dir: Path) -> Path | None:
    if not checkpoint_dir.exists():
        return None
    checkpoints = sorted(checkpoint_dir.glob("mosaic_*_steps.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    return checkpoints[0] if checkpoints else None


def parse_args() -> argparse.Namespace:
    from skill_lab.config import (
        ACTION_FREQ,
        DEFAULT_INIT_STATE,
        DEFAULT_ROM,
        DEFAULT_MAX_STEPS,
        TOTAL_TILES,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="PPO checkpoint to load (skips training)")
    parser.add_argument("--dry-run", action="store_true", help="Run random actions, no training")
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--init-state", type=Path, default=DEFAULT_INIT_STATE)
    parser.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--low-hp-threshold", type=float, default=0.35,
                        help="Authorize menu entry at or below this party HP fraction")
    parser.add_argument("--foreground", action="store_true",
                        help="Keep the mosaic window above other windows")
    parser.add_argument("--teacher-bonus", type=float, default=5.0,
                        help="Logged reward bonus for each human-guided action")
    parser.add_argument("--teacher-log", type=Path, default=Path("mosaic_sessions/teacher_actions.jsonl"),
                        help="JSONL file for human-guided actions")
    parser.add_argument("--num-envs", type=int, default=TOTAL_TILES,
                        help="Number of environments to run")
    parser.add_argument("--reward-scale", type=float, default=1.0,
                        help="Reward scale passed to the environment")
    parser.add_argument("--explore-weight", type=float, default=1.0,
                        help="Explore weight for the environment")
    parser.add_argument("--specialization", type=str, default=None,
                        choices=list(SPECIALIZATION_PRESETS.keys()),
                        help="Override reward/explore weights with a preset")
    parser.add_argument("--objective", type=str, default="explore",
                        choices=["explore", "reach_pewter", "level_pikachu", "train_squirtle"],
                        help="Objective for all environments")
    parser.add_argument("--no-hud", action="store_true",
                        help="Disable HUD overlay on emulator tiles for performance")
    parser.add_argument("--n-steps", type=int, default=256,
                        help="PPO rollout length per environment")
    parser.add_argument("--batch-size", type=int, default=512,
                        help="PPO mini-batch size")
    parser.add_argument("--n-epochs", type=int, default=1,
                        help="PPO epochs per update")
    parser.add_argument("--gamma", type=float, default=0.997,
                        help="PPO discount factor")
    parser.add_argument("--ent-coef", type=float, default=0.01,
                        help="PPO entropy coefficient")
    parser.add_argument("--total-timesteps", type=int, default=1_000_000,
                        help="Total training timesteps per batch")
    parser.add_argument("--save-freq", type=int, default=100_000,
                        help="Save checkpoint every N timesteps")
    parser.add_argument("--checkpoint-dir", type=Path, default=Path("mosaic_sessions/checkpoints"),
                        help="Directory for saving checkpoints")
    parser.add_argument("--resume", action="store_true",
                        help="Auto-resume from latest checkpoint if no --model is given")
    parser.add_argument("--loop", action="store_true",
                        help="After each batch, show report and continue indefinitely")
    return parser.parse_args()


class BatchStats:
    def __init__(self, num_envs: int) -> None:
        self.num_envs = num_envs
        self.reset()

    def reset(self) -> None:
        self.total_steps = 0
        self.env_steps = np.zeros(self.num_envs, dtype=np.int64)
        self.env_rewards = np.zeros(self.num_envs, dtype=np.float64)
        self.env_min_rewards = np.full(self.num_envs, np.inf, dtype=np.float64)
        self.env_max_rewards = np.full(self.num_envs, -np.inf, dtype=np.float64)
        self.batch_count = 0

    def update(self, raw_rewards: np.ndarray, num_envs: int) -> None:
        self.total_steps += num_envs
        self.env_steps += 1
        self.env_rewards += raw_rewards
        self.env_min_rewards = np.minimum(self.env_min_rewards, raw_rewards)
        self.env_max_rewards = np.maximum(self.env_max_rewards, raw_rewards)
        self.batch_count += 1


def build_report_image(stats: BatchStats, profile_name: str) -> np.ndarray:
    width, height = 640, 480
    image = np.full((height, width, 3), 30, dtype=np.uint8)

    y = 30
    cv2.putText(image, "Batch Report", (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
    y += 40
    cv2.putText(image, f"Profile: {profile_name}", (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
    y += 30
    cv2.putText(image, f"Total steps: {stats.total_steps}", (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 1)
    y += 25
    avg_reward = float(np.mean(stats.env_rewards))
    cv2.putText(image, f"Avg total reward/env: {avg_reward:+.2f}", (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 1)
    y += 35

    cv2.putText(image, "Environment breakdown:", (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 1)
    y += 25
    cv2.line(image, (20, y), (width - 20, y), (80, 80, 80), thickness=1)
    y += 15

    for idx in range(stats.num_envs):
        if y > height - 30:
            break
        total = stats.env_rewards[idx]
        avg = total / max(int(stats.env_steps[idx]), 1)
        text = f"Env {idx + 1:02d} | steps {stats.env_steps[idx]:6d} | reward {total:+10.2f} | avg {avg:+.4f}"
        cv2.putText(image, text, (25, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 220, 220), 1)
        y += 18

    cv2.putText(image, "Press any key to continue", (20, height - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 150), 1)
    return image


def show_report(stats: BatchStats, profile_name: str) -> None:
    report = build_report_image(stats, profile_name)
    cv2.namedWindow("Batch Report")
    cv2.imshow("Batch Report", report)
    cv2.waitKey(0)
    cv2.destroyWindow("Batch Report")


def main(args: argparse.Namespace | None = None) -> None:
    if args is None:
        args = parse_args()

    rom_path = args.rom
    init_state_path = args.init_state
    if not rom_path.exists():
        raise FileNotFoundError(f"ROM not found: {rom_path}")
    if not init_state_path.exists():
        raise FileNotFoundError(f"Initial state not found: {init_state_path}")

    session_path = Path("mosaic_sessions")
    session_path.mkdir(exist_ok=True)

    profile = Profile("V2", args.num_envs, args.model, args.explore_weight)
    config = make_config(profile, session_path / profile.name.lower(), args)
    config["session_path"].mkdir(exist_ok=True)

    env = make_vec_env(profile.count, config)
    model_path = args.model
    if model_path is None and args.resume:
        latest = find_latest_checkpoint(args.checkpoint_dir)
        if latest is not None:
            model_path = str(latest)
            print(f"Auto-resuming from latest checkpoint: {model_path}")

    model = load_policy(model_path, env, args.dry_run)
    training = not args.dry_run
    if training and model is None:
        model = create_model(env, args)
    if training and model is not None and not hasattr(model, "_logger"):
        from stable_baselines3.common.logger import configure
        model._logger = configure(None, ["stdout"])

    args.checkpoint_dir.mkdir(parents=True, exist_ok=True)
    args.teacher_log = PROJECT_ROOT / args.teacher_log
    args.teacher_log.parent.mkdir(parents=True, exist_ok=True)

    # boundary = ActionBoundary(args.low_hp_threshold)
    mosaic = Mosaic(num_tiles=env.num_envs, foreground=args.foreground)
    inspector = ObservationInspector()
    map_window = MapWindow()
    stats_window = StatsWindow()
    objective_factories = {
        "explore": lambda: __import__("skill_lab.objectives.explore", fromlist=["ExploreObjective"]).ExploreObjective(),
        "reach_pewter": lambda: ReachPewterObjective(),
        "level_pikachu": lambda: LevelPikachuObjective(),
        "train_squirtle": lambda: TrainSquirtleObjective(),
    }
    objective_factory = objective_factories.get(args.objective, objective_factories["explore"])
    objective_manager = ObjectiveManager(env.num_envs, objective_factory=objective_factory)
    observation = env.reset()

    reward_modifiers = [0.0 for _ in range(env.num_envs)]
    reward_history: list[list[float]] = [[] for _ in range(env.num_envs)]
    batch_stats = BatchStats(env.num_envs)
    step_count = 0
    batch_number = 0
    ppo_update_count = 0

    print("Mosaic running. Press Q or Escape in the mosaic window to stop.")
    print("Click an emulator to select it, then use Control/Slash/Praise in the right panel.")
    if args.specialization:
        print(f"Specialization preset: {args.specialization}")
    if args.dry_run:
        print("Dry-run mode: random actions only.")
    elif model is None:
        print("Training PPO from scratch.")
    else:
        print(f"Loaded model from: {model_path}")
        if training:
            print("Training PPO from loaded model.")
        else:
            print("Playing model (inference mode).")
    print("To view TensorBoard: tensorboard --logdir mosaic_sessions/tensorboard")
    if args.loop:
        print("Loop mode: after each batch, a report is shown and training continues.")

    try:
        print("Entering main loop...")
        while True:
            print(f"Starting batch loop, step_count={step_count}, target={(batch_number + 1) * args.total_timesteps}")
            while step_count < (batch_number + 1) * args.total_timesteps:
                all_tiles = []

                if model is None:
                    actions = np.random.randint(0, env.action_space.n, size=env.num_envs)
                else:
                    if training:
                        with torch.no_grad():
                            obs_tensor, _ = model.policy.obs_to_tensor(_transpose_for_model(observation))
                            actions, values, log_probs = model.policy(obs_tensor)
                        actions = actions.detach().cpu().numpy()
                        values = values.detach()
                        log_probs = log_probs.detach()
                    else:
                        with torch.no_grad():
                            obs_tensor, _ = model.policy.obs_to_tensor(_transpose_for_model(observation))
                            actions, _, _ = model.policy(obs_tensor)
                        actions = actions.detach().cpu().numpy()

                for local_index in range(env.num_envs):
                    if local_index == mosaic.selected_index and mosaic.control_active:
                        human_action = mosaic.pending_human_action
                        if human_action is None:
                            actions[local_index] = env.envs[local_index].noop_button_index
                        else:
                            actions[local_index] = human_action
                            with args.teacher_log.open("a", encoding="utf-8") as log_file:
                                json.dump({
                                    "timestamp": time.time(),
                                    "instance": local_index + 1,
                                    "action": int(human_action),
                                    "teacher_bonus": args.teacher_bonus,
                                    "map_id": int(env.envs[local_index].current_map_id),
                                    "step": int(env.envs[local_index].step_count),
                                }, log_file)
                                log_file.write("\n")
                    else:
                        actions[local_index] = boundary.apply(
                            env.envs[local_index], int(actions[local_index])
                        )

                next_observation, raw_rewards, _, _ = env.step(actions)
                raw_rewards = np.array(raw_rewards, dtype=np.float32)
                batch_stats.update(raw_rewards, env.num_envs)

                if training:
                    dones = np.zeros(env.num_envs, dtype=np.bool_)
                    modified_rewards = raw_rewards + np.array(reward_modifiers, dtype=np.float32)
                    model.rollout_buffer.add(
                        _transpose_for_model(observation),
                        actions,
                        modified_rewards,
                        dones,
                        values,
                        log_probs,
                    )

                observation = next_observation
                step_count += env.num_envs

                objective_manager.update(observation, env)
                objective_info = []
                for idx in range(env.num_envs):
                    objective_info.append((
                        objective_manager.objectives[idx].name if objective_manager.objectives[idx] is not None else "None",
                        objective_manager.current_subgoal(idx),
                        objective_manager.progress(idx),
                    ))

                for idx in range(env.num_envs):
                    reward_history[idx].append(float(raw_rewards[idx]))
                    if len(reward_history[idx]) > 200:
                        reward_history[idx] = reward_history[idx][-200:]

                if mosaic.last_action == "Slash" and mosaic.last_action_target is not None:
                    reward_modifiers[mosaic.last_action_target] = REWARD_MODIFIER_SLASH
                elif mosaic.last_action == "Praise" and mosaic.last_action_target is not None:
                    reward_modifiers[mosaic.last_action_target] = REWARD_MODIFIER_PRAISE
                mosaic.last_action = None
                mosaic.last_action_target = None

                for local_index in range(env.num_envs):
                    all_tiles.append(tile_group(
                        observation,
                        env,
                        profile.name,
                        local_index,
                        mosaic.selected_index,
                        model is not None,
                        show_hud=not args.no_hud,
                    ))

                if mosaic.selected_index is not None:
                    inspector.show()
                    if not inspector.render(env, mosaic.selected_index, reward_history[mosaic.selected_index]):
                        mosaic.selected_index = None
                else:
                    inspector.hide()

                if mosaic.stats_visible:
                    stats_window.show()
                    if not stats_window.render(env, env.num_envs, action_freq=ACTION_FREQ, scores=batch_stats.env_rewards):
                        mosaic.stats_visible = False
                else:
                    stats_window.hide()

                if mosaic.map_visible and mosaic.selected_index is not None:
                    map_window.show()
                    map_window.set_tracked_env(mosaic.selected_index)
                    if not map_window.render(env, mosaic.selected_index):
                        mosaic.map_visible = False
                else:
                    map_window.hide()

                mosaic.pending_human_action = None
                mosaic.render(
                    all_tiles,
                    reward_modifiers=reward_modifiers,
                    ppo_updates=ppo_update_count,
                    objective_info=objective_info,
                    step_count=step_count,
                    batch_number=batch_number,
                    model_name=model_path,
                )

                if step_count % max(1, args.num_envs * 10) == 0:
                    print(f"Progress: {step_count} steps")

                key = mosaic.poll_key()
                if key in (ord("q"), 27):
                    raise KeyboardInterrupt

                if training and model.rollout_buffer.full:
                    with torch.no_grad():
                        obs_tensor, _ = model.policy.obs_to_tensor(_transpose_for_model(observation))
                        _, last_value, _ = model.policy(obs_tensor)
                        last_value = last_value.detach()
                    model.rollout_buffer.compute_returns_and_advantage(last_value, np.zeros(env.num_envs, dtype=np.bool_))
                    model.train()
                    model.rollout_buffer.reset()
                    ppo_update_count += 1

                if training and step_count % args.save_freq < env.num_envs:
                    checkpoint_path = args.checkpoint_dir / f"mosaic_{step_count:08d}_steps"
                    model.save(str(checkpoint_path))
                    print(f"Saved checkpoint: {checkpoint_path}")

            batch_number += 1
            show_report(batch_stats, profile.name)

            if not args.loop:
                break

            batch_stats.reset()
            print(f"Batch {batch_number} complete. Continuing to next batch...")
    except KeyboardInterrupt:
        pass
    finally:
        env.close()
        inspector.close()
        map_window.close()
        stats_window.close()
        mosaic.close()


if __name__ == "__main__":
    if len(sys.argv) == 1:
        from skill_lab.launcher import launch_gui
        launch_gui()
    else:
        main()
