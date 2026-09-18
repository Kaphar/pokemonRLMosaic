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

from skill_lab.config import EVENT_JSON_PATH, REWARD_MODIFIER_PRAISE, REWARD_MODIFIER_SLASH, SPECIALIZATION_PRESETS, SAVE_ON_CATCH_ENABLED, SAVE_ON_CATCH_MIN_DV
from skill_lab.emulator import (
    ACTION_FREQ,
    make_vec_env,
    tile_group,
)
from skill_lab.inspector import ObservationInspector
from skill_lab.map_window import MapWindow
from skill_lab.mosaic import Mosaic
from skill_lab.stats_window import StatsWindow


from skill_lab.env_setup import setup_envs, ensure_env_exists, get_env_config, load_profile_config, load_stage_config

from skill_lab.curriculum import get_stage #, stage_to_config
from skill_lab.recorder import InputRecorder
from skill_lab.stats_tracker import StatsTracker
from skill_lab.rewards import check_baseline_rewards, medium_reward
from skill_lab.throughput import ThroughputLogger

class Profile:
    def __init__(self, name: str, count: int, model_path: str | None, explore_weight: float) -> None:
        self.name = name
        self.count = count
        self.model_path = model_path
        self.explore_weight = explore_weight


def make_config(profile: Profile, session_path: Path, args: argparse.Namespace) -> dict[str, Any]:
    from skill_lab.env_setup import load_stage_config

    stage_config = load_stage_config(args.stage)

    reward_scale = args.reward_scale
    explore_weight = args.explore_weight
    if args.specialization and args.specialization in SPECIALIZATION_PRESETS:
        preset = SPECIALIZATION_PRESETS[args.specialization]
        reward_scale = preset["reward_scale"]
        explore_weight = preset["explore_weight"]

    # Determine max_steps based on training mode
    training_mode = getattr(args, "training_mode", "segment")
    if training_mode == "fullrun":
        max_steps = 999999  # Effectively no limit
    else:
        max_steps = args.max_steps or stage_config.get("max_steps", 7200)

    init_state = Path(stage_config.get("init_state", "v2/state/init.state"))
    if args.init_state and args.init_state.exists():
        init_state = args.init_state

    # Get button masks from unified button_masks dict
    button_masks = stage_config.get("button_masks", {})
    disable_start = button_masks.get("Start", True)
    disable_select = button_masks.get("Select", True)
    disable_B = button_masks.get("B", False)
    disable_A = button_masks.get("A", False)

    return {
        "headless": True,
        "save_final_state": False,
        "early_stop": False,
        "action_freq": ACTION_FREQ,
        "init_state": str(init_state),
        "max_steps": max_steps,
        "print_rewards": False,
        "save_video": False,
        "fast_video": True,
        "session_path": session_path,
        "gb_path": str(args.rom),
        "debug": False,
        "reward_scale": reward_scale,
        "explore_weight": explore_weight,
        "noop_button": True,
        "speed": getattr(args, "emulator_speed", 2),
        "training_mode": training_mode,
        # Button masks from unified config
        "disable_start": disable_start,
        "disable_select": disable_select,
        "disable_B": disable_B,
        "disable_A": disable_A,
        "reward_scale": reward_scale,
        "milestone_reward": stage_config.get("milestone_reward", medium_reward),
        "healing_reward_multiplier": stage_config.get("healing_reward_multiplier", stage_config.get("healing_reward", 1.0)),
        "milestones_path": str(PROJECT_ROOT / "skill_lab" / "milestones.json"),
        "names_path": str(PROJECT_ROOT / "skill_lab" / "names.json"),
        # Save on catch settings
        "save_on_catch_enabled": SAVE_ON_CATCH_ENABLED,
        "save_on_catch_min_dv": SAVE_ON_CATCH_MIN_DV,
        # Stage-level reset_on_catch (read from stage config)
        "reset_on_catch": stage_config.get("reset_on_catch", False),
        # Plugin-based frame-exact input recording
        "record_input_with_plugin": getattr(args, "record_input_with_plugin", False),
        "record_input_path": str(Path(session_path) / "plugin_input_events.json"),
    }

def load_policy(path: str | None, env: DummyVecEnv, dry_run: bool) -> PPO | None:
    if dry_run: return None
    if not path: return None
    return PPO.load(path, env=env)


def create_model(env: DummyVecEnv, args: argparse.Namespace) -> PPO:
    model = PPO(
        "MultiInputPolicy", env, verbose=1, n_steps=args.n_steps, 
        batch_size=args.batch_size, n_epochs=args.n_epochs, gamma=args.gamma,
        ent_coef=args.ent_coef, tensorboard_log=str(PROJECT_ROOT / "mosaic_sessions" / "tensorboard"),
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
    if not checkpoint_dir.exists(): return None
    checkpoints = sorted(checkpoint_dir.glob("mosaic_*_steps.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    return checkpoints[0] if checkpoints else None


def parse_args() -> argparse.Namespace:
    from skill_lab.config import ACTION_FREQ, DEFAULT_INIT_STATE, DEFAULT_ROM, DEFAULT_MAX_STEPS, TOTAL_TILES
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="PPO checkpoint to load (skips training)")
    parser.add_argument("--dry-run", action="store_true", help="Run random actions, no training")
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--init-state", type=Path, default=DEFAULT_INIT_STATE)
    parser.add_argument("--stage", type=str, default="starter")
    parser.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--foreground", action="store_true", help="Keep the mosaic window above other windows")
    parser.add_argument("--teacher-bonus", type=float, default=medium_reward, help="Logged reward bonus for each human-guided action")
    parser.add_argument("--teacher-log", type=Path, default=Path("mosaic_sessions/teacher_actions.jsonl"))
    parser.add_argument("--num-envs", type=int, default=TOTAL_TILES, help="Number of environments to run")
    parser.add_argument("--reward-scale", type=float, default=1.0)
    parser.add_argument("--explore-weight", type=float, default=1.0)
    parser.add_argument("--specialization", type=str, default=None, choices=list(SPECIALIZATION_PRESETS.keys()))
    parser.add_argument("--no-hud", action="store_true", help="Disable HUD overlay on emulator tiles")

    parser.add_argument("--continuous", action="store_true", help="Run indefinitely without batch limits")
    parser.add_argument("--override-trainer-stage", action="store_true",
                        help="Force trainers to use the launcher-selected stage instead of their own saved stage")

    parser.add_argument("--record-input-with-plugin", action="store_true",
                        help="Record frame-exact inputs via plugin-style hook for deterministic replay")
    parser.add_argument("--use-legacy-recorder", action="store_true",
                        help="Use legacy recorder instead of plugin (only if plugin recording is disabled)")
    
    parser.add_argument("--disable-start-select", action="store_true", help="Mask Start/Select buttons in early game")
    
    parser.add_argument("--n-steps", type=int, default=256)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--n-epochs", type=int, default=1)
    parser.add_argument("--gamma", type=float, default=0.997)
    parser.add_argument("--ent-coef", type=float, default=0.01)
    parser.add_argument("--total-timesteps", type=int, default=1_000_000)
    parser.add_argument("--save-freq", type=int, default=100_000)
    parser.add_argument("--checkpoint-dir", type=Path, default=Path("mosaic_sessions/checkpoints"))
    parser.add_argument("--resume", action="store_true", help="Auto-resume from latest checkpoint")
    parser.add_argument("--loop", action="store_true", help="After each batch, show report and continue")
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
        if y > height - 30: break
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


def log_reward_configuration_summary(profile_name: str, profile_config: dict[str, Any], stage_name: str, stage_config: dict[str, Any]) -> None:
    """Print a clear reward summary derived from the JSON configuration."""
    summary = check_baseline_rewards(profile_config, stage_config)
    stage_multipliers = summary["stage_reward_multipliers"]
    effective = summary["effective_rewards"]

    cyan = "\033[36m"
    green = "\033[32m"
    yellow = "\033[33m"
    magenta = "\033[35m"
    reset = "\033[0m"

    print("\n" + "=" * 90)
    print(f"{cyan}=== REWARD CONFIGURATION SUMMARY ==={reset}")
    print(f"{yellow}Profile:{reset} {profile_name}")
    print(f"  - reward_scale: {green}{summary['reward_scale']:.2f}{reset}")
    print(f"  - explore_weight: {green}{profile_config.get('explore_weight', 1.0):.2f}{reset}")
    print(f"{yellow}Stage:{reset} {stage_name}")
    for label, key in (
        ("milestone_reward_multiplier", "milestone"),
        ("exploration_reward_multiplier", "exploration"),
        ("combat_reward_multiplier", "combat"),
        ("capture_reward_multiplier", "capture"),
        ("healing_reward_multiplier", "healing"),
    ):
        value = stage_multipliers.get(key, 0.0)
        color = green if value > 0 else "\033[90m"
        print(f"  - {label}: {color}{value:.2f}{reset}")
    print(f"\n{magenta}Final Effective Rewards:{reset}")
    for label, key in (
        ("Milestone", "milestone"),
        ("Exploration", "exploration"),
        ("Combat", "combat"),
        ("Capture", "capture"),
        ("Healing", "healing"),
    ):
        multiplier = stage_multipliers.get(key, 0.0)
        reward_value = effective.get(key, 0.0)
        calc = f"{multiplier:.2f} x {summary['reward_scale']:.2f}"
        print(f"  - {label}: {green}{reward_value:.2f}{reset} ({yellow}{calc}{reset})")
    print(f"{cyan}=" * 90 + f"{reset}\n")


def main(args: argparse.Namespace | None = None) -> None:
    if args is None: args = parse_args()

    # Get stage configuration from JSON
    stage_config = load_stage_config(args.stage)
    profile_name = args.specialization or "trainer"
    profile_config = load_profile_config(profile_name)
    if args.specialization and args.specialization in SPECIALIZATION_PRESETS:
        preset = SPECIALIZATION_PRESETS[args.specialization]
        profile_config = {**profile_config, **preset}
    else:
        args.reward_scale = float(profile_config.get("reward_scale", args.reward_scale))
        args.explore_weight = float(profile_config.get("explore_weight", args.explore_weight))

    print(f"Stage: {stage_config.get('name', args.stage)} - {stage_config.get('description', '')}")
    
    # Extract button masks from unified config
    button_masks = stage_config.get("button_masks", {})
    print(f"  Start masked: {button_masks.get('Start', True)}")
    print(f"  Select masked: {button_masks.get('Select', True)}")
    print(f"  B button masked: {button_masks.get('B', False)}")
    print(f"  A button masked: {button_masks.get('A', False)}")

    log_reward_configuration_summary(profile_name, profile_config, stage_config.get('name', args.stage), stage_config)

    if not args.rom.exists(): raise FileNotFoundError(f"ROM not found: {args.rom}")
    if not args.init_state.exists(): raise FileNotFoundError(f"Initial state not found: {args.init_state}")

    session_path = Path("mosaic_sessions")
    session_path.mkdir(exist_ok=True)

    profile = Profile("V2", args.num_envs, args.model, args.explore_weight)
    config = make_config(profile, session_path / profile.name.lower(), args)
    config["session_path"].mkdir(exist_ok=True)

    # Set up environment directives with ROM and init_state paths
    # setup_envs creates the initial folder structure if needed
    env_configs = setup_envs(
        num_envs=profile.count,
        stage=args.stage,
        rom_path=args.rom,
        init_state=args.init_state,
        mosaic_rows=getattr(args, "mosaic_rows", 6),
        mosaic_cols=getattr(args, "mosaic_cols", 7),
        override_trainer_stage=getattr(args, "override_trainer_stage", False),
    )

    # Ensure each environment exists (lazy creation on launch)
    # This allows envs to be created on-demand if we increase num_envs later
    for i in range(profile.count):
        ensure_env_exists(
            env_index=i,
            rom_source_path=args.rom,
            default_state_path=str(args.init_state),
            launcher_stage=args.stage,
            mosaic_rows=getattr(args, "mosaic_rows", 6),
            mosaic_cols=getattr(args, "mosaic_cols", 7),
        )

    # Print directive assignments (confirmation in logs)
    for cfg in env_configs:
        print(f"  Env {cfg['env_index']:02d} [{cfg['env_name']}]: "
              f"{cfg['description']} | target={cfg['target_starter']} | profile={cfg['profile']} | "
              f"rom={cfg.get('rom_file', 'N/A')} | state={cfg.get('init_state_file', 'N/A')}")

    # ========================================================================
    # DETAILED ENVIRONMENT SETTINGS LOG
    # ========================================================================
    print("\n" + "="*120)
    print("ENVIRONMENT CONFIGURATION SUMMARY")
    print("="*120)
    print(f"Total Environments: {profile.count}")
    print(f"Stage: {args.stage}")
    print(f"ROM: {args.rom.name}")
    print(f"Init State: {args.init_state.name}")
    print(f"Reward Scale: {config['reward_scale']:.2f}")
    print(f"Explore Weight: {config['explore_weight']:.2f}")
    print(f"Max Steps: {config['max_steps']}")
    print(f"Training Mode: {config['training_mode']}")
    print(f"Noop Button: {config['noop_button']}")
    print(f"Emulator Speed: {config['speed']}")
    print(f"Disable Start: {config['disable_start']}")
    print(f"Disable Select: {config['disable_select']}")
    print(f"Disable B: {config['disable_B']}")
    print(f"Disable A: {config.get('disable_A', False)}")
    print("-"*120)
    
    # Compact per-env settings table with all key details including ROM and state
    header = (
        f"{'Env':<5} {'Name':<18} {'Profile':<9} {'Catch Directives':<35} {'Train Directives':<30} "
        f"{'Save?':<6} {'Reset?':<7} {'Target':<12} {'ROM':<18} {'State':<18}"
    )
    print(header)
    print("-"*120)
    
    for cfg in env_configs:
        catch_list = ", ".join(cfg.get('catch_directive', [])[:3])
        if len(cfg.get('catch_directive', [])) > 3:
            catch_list += f" (+{len(cfg['catch_directive'])-3})"
        train_list = ", ".join(cfg.get('train_directive', [])[:2])
        if len(cfg.get('train_directive', [])) > 2:
            train_list += f" (+{len(cfg['train_directive'])-2})"
        
        save_flag = "Y" if cfg.get('save_on_catch', False) else "N"
        reset_flag = "Y" if cfg.get('reset_on_catch', False) else "N"
        target = cfg.get('target_starter', '-') or "-"
        rom_file = cfg.get('rom_file', 'N/A')
        state_file = cfg.get('init_state_file', 'N/A')
        
        print(
            f"{cfg['env_index']:>4}  {cfg['env_name']:<18} {cfg['profile']:<9} "
            f"{catch_list:<35} {train_list:<30} {save_flag:<6} {reset_flag:<7} {target:<12} "
            f"{rom_file:<18} {state_file:<18}"
        )
    
    print("-"*120)
    
    # Profile distribution summary
    trainer_count = sum(1 for cfg in env_configs if cfg['profile'] == 'trainer')
    explorer_count = sum(1 for cfg in env_configs if cfg['profile'] == 'explorer')
    print(f"\nProfile Distribution: {trainer_count} Trainer, {explorer_count} Explorer")
    
    # Count ROM distribution
    red_count = sum(1 for cfg in env_configs if cfg.get('rom_file', '').endswith('.gb') and 'Blue' not in cfg.get('rom_file', ''))
    blue_count = sum(1 for cfg in env_configs if cfg.get('rom_file', '').endswith('.gb') and 'Blue' in cfg.get('rom_file', ''))
    print(f"ROM Distribution: {red_count} Red, {blue_count} Blue")
    
    # Stage config details
    print(f"\nStage Configuration ({args.stage}):")
    button_masks = stage_config.get("button_masks", {})
    print(f"  - Start Button Masked: {button_masks.get('Start', True)}")
    print(f"  - Select Button Masked: {button_masks.get('Select', True)}")
    print(f"  - B Button Masked: {button_masks.get('B', False)}")
    print(f"  - A Button Masked: {button_masks.get('A', False)}")
    milestone_multiplier = stage_config.get("milestone_reward_multiplier", stage_config.get("milestone_reward", "medium_reward"))
    exploration_multiplier = stage_config.get("exploration_reward_multiplier", stage_config.get("exploration_reward", 0.0))
    combat_multiplier = stage_config.get("combat_reward_multiplier", stage_config.get("combat_reward", 0.0))
    capture_multiplier = stage_config.get("capture_reward_multiplier", stage_config.get("capture_reward", 0.0))
    healing_multiplier = stage_config.get("healing_reward_multiplier", stage_config.get("healing_reward", 0.0))
    print(f"  - Milestone Reward Multiplier: {milestone_multiplier}")
    print(f"  - Exploration Reward Multiplier: {exploration_multiplier}")
    print(f"  - Combat Reward Multiplier: {combat_multiplier}")
    print(f"  - Capture Reward Multiplier: {capture_multiplier}")
    print(f"  - Healing Reward Multiplier: {healing_multiplier}")
    print(f"  - Max Steps (stage default): {stage_config.get('max_steps', 7200)}")
    print("="*120 + "\n")

    # Create vectorized environment with per-env configs
    env = make_vec_env(profile.count, config, env_configs=env_configs)


    model_path = args.model
    if model_path is None and args.resume:
        latest = find_latest_checkpoint(args.checkpoint_dir)
        if latest is not None: model_path = str(latest)

    model = load_policy(model_path, env, args.dry_run)
    training = not args.dry_run
    if training and model is None: model = create_model(env, args)
    if training and model is not None and not hasattr(model, "_logger"):
        from stable_baselines3.common.logger import configure
        model._logger = configure(None, ["stdout"])

    args.checkpoint_dir.mkdir(parents=True, exist_ok=True)
    args.teacher_log = PROJECT_ROOT / args.teacher_log
    args.teacher_log.parent.mkdir(parents=True, exist_ok=True)

    # Create input recorder
    recorder = InputRecorder(
        session_path=config["session_path"],
        init_state=str(args.init_state),
        noop_action=env.envs[0].noop_button_index,
        rom_path=str(args.rom),
        action_freq=ACTION_FREQ,
    )

    # Create stats tracker
    stats_tracker = StatsTracker(
        history_path=PROJECT_ROOT / "mosaic_sessions" / "stats_history.json"
    )

    # HRL/Objectives removed! The environment handles rules now.
    mosaic = Mosaic(
        num_tiles=env.num_envs,
        foreground=args.foreground,
        rows=getattr(args, "mosaic_rows", 6),
        cols=getattr(args, "mosaic_cols", 7),
    )
    inspector = ObservationInspector()
    map_window = MapWindow()
    stats_window = StatsWindow()
    
    observation = env.reset()
    reward_modifiers = [0.0 for _ in range(env.num_envs)]
    reward_history: list[list[float]] = [[] for _ in range(env.num_envs)]
    batch_stats = BatchStats(env.num_envs)
    throughput = ThroughputLogger("mosaic")
    step_count = 0
    batch_number = 0
    ppo_update_count = 0

    # Dummy objective info to keep the UI from crashing if it expects it
    objective_info = [("Curriculum", "Playing", 0.0) for _ in range(env.num_envs)]

    print("Mosaic running. Press Q or Escape in the mosaic window to stop.")
    try:
        print("Entering main loop...")
        continue_batches = getattr(args, "loop", False) or getattr(args, "continuous", False)
        while True:
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
                                    "timestamp": time.time(), "instance": local_index + 1,
                                    "action": int(human_action), "teacher_bonus": args.teacher_bonus,
                                }, log_file)
                                log_file.write("\n")
                    # Input replay override: replay recorded actions while a
                    # replay sequence is loaded and not yet exhausted. Once the
                    # sequence is consumed the model/human automatically take over.
                    _replay_action = env.envs[local_index].consume_replay_action()
                    if _replay_action is not None:
                        actions[local_index] = _replay_action
                    # REMOVED: boundary.apply() - Environment handles masking now


                # Environment step handles everything: masking, memory reading, milestones
                next_observation, raw_rewards, dones, infos = env.step(actions)
                raw_rewards = np.array(raw_rewards, dtype=np.float32)
                batch_stats.update(raw_rewards, env.num_envs)

                # Track objective completions (debounced: only updates when event happens)
                for local_index in range(env.num_envs):
                    info = infos[local_index] if local_index < len(infos) else {}
                    if "objective_steps" in info:
                        stats_tracker.record_completion(
                            env_index=local_index,
                            env_name=info.get("objective_env_name", f"Env{local_index}"),
                            directive=info.get("objective_directive", "unknown"),
                            steps=info["objective_steps"],
                            success=info.get("objective_success", False),
                        )

                # Render stats window (debounced: only renders when needs_render=True)
                if not stats_tracker.render():
                    print("[Stats] Stats window closed by user")
                # # Render stats window periodically
                # if step_count % (env.num_envs * 5) == 0:
                #     stats_tracker.render()

                # Record inputs
                for local_index in range(env.num_envs):
                    info = infos[local_index] if local_index < len(infos) else {}
                    masked = info.get("masked_action", False)
                    recorder.record(
                        env_index=local_index,
                        step=int(env.envs[local_index].step_count),
                        action=int(actions[local_index]),
                        masked=masked,
                    )

                if training:
                    dones = np.zeros(env.num_envs, dtype=np.bool_)
                    modified_rewards = raw_rewards + np.array(reward_modifiers, dtype=np.float32)
                    model.rollout_buffer.add(
                        _transpose_for_model(observation), actions, modified_rewards,
                        dones, values, log_probs,
                    )

                observation = next_observation
                step_count += env.num_envs
                throughput.update(step_count)

                for idx in range(env.num_envs):
                    reward_history[idx].append(float(raw_rewards[idx]))
                    if len(reward_history[idx]) > 200: reward_history[idx] = reward_history[idx][-200:]

                if mosaic.last_action == "Slash" and mosaic.last_action_target is not None:
                    reward_modifiers[mosaic.last_action_target] = REWARD_MODIFIER_SLASH
                elif mosaic.last_action == "Praise" and mosaic.last_action_target is not None:
                    reward_modifiers[mosaic.last_action_target] = REWARD_MODIFIER_PRAISE
                elif mosaic.last_action == "RESET" and mosaic.last_action_target is not None:
                    # Reset the selected environment
                    target_idx = mosaic.last_action_target
                    print(f"[Mosaic] Resetting environment {target_idx}")
                    env.env_method("reset", indices=[target_idx])
                elif mosaic.last_action == "KILL" and mosaic.last_action_target is not None:
                    # Kill the selected environment - apply penalty then reset
                    target_idx = mosaic.last_action_target
                    penalty = -100.0  # Significant penalty for glitched games
                    reward_modifiers[target_idx] = penalty
                    print(f"[Mosaic] KILL: Applying penalty {penalty} and resetting environment {target_idx}")
                    env.env_method("reset", indices=[target_idx])
                mosaic.last_action = None
                mosaic.last_action_target = None

                visible_indices = mosaic.visible_indices(batch_stats.env_rewards)
                if not mosaic.display_paused:
                    for local_index in visible_indices:
                        all_tiles.append(tile_group(
                            observation, env, profile.name, local_index, mosaic.selected_index,
                            model is not None, show_hud=not args.no_hud,
                        ))

                # UI Rendering Logic (Preserved exactly as you had it)
                if not mosaic.display_paused and mosaic.selected_index is not None:
                    inspector.show()
                    if not inspector.render(env, mosaic.selected_index, reward_history[mosaic.selected_index]):
                        mosaic.selected_index = None
                else: inspector.hide()

                if not mosaic.display_paused and mosaic.stats_visible:
                    stats_window.show()
                    if not stats_window.render(env, env.num_envs, action_freq=ACTION_FREQ, scores=batch_stats.env_rewards):
                        mosaic.stats_visible = False
                else: stats_window.hide()

                if not mosaic.display_paused and mosaic.map_visible and mosaic.selected_index is not None:
                    map_window.show()
                    map_window.set_tracked_env(mosaic.selected_index)
                    if not map_window.render(env, mosaic.selected_index): map_window.map_visible = False
                else: map_window.hide()

                mosaic.pending_human_action = None
                if not mosaic.display_paused:
                    mosaic.render(
                        all_tiles, reward_modifiers=reward_modifiers, ppo_updates=ppo_update_count,
                        objective_info=objective_info, step_count=step_count, batch_number=batch_number,
                        model_name=model_path, tile_indices=visible_indices,
                    )

                if step_count % max(1, args.num_envs * 10) == 0: print(f"Progress: {step_count} steps")
                # Save recordings periodically
                # if step_count % 10000 < env.num_envs: # see how we handle this, we could just save when we decide to save a state.
                #     save_path = recorder.save() # run this action from the button
                #     print(f"[Recorder] Saved inputs to: {save_path}")

                key = mosaic.poll_key()
                if key in (ord("q"), 27): raise KeyboardInterrupt

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
            if not getattr(args, "continuous", False):
                show_report(batch_stats, profile.name)
            if not continue_batches: break
            batch_stats.reset()
            print(f"Batch {batch_number} complete. Continuing to next batch...")
    except KeyboardInterrupt: pass
    finally:
        stats_tracker.save_history()  # Save stats for next run
        # Save plugin-based frame-exact input recording
        if getattr(args, "record_input_with_plugin", False):
            from skill_lab.emulator_with_debug import (
                _plugin_recording_registry,
                finalize_input_recording,
            )
            save_paths = []
            for env_obj in env.envs:
                pyboy = env_obj.pyboy
                pid = id(pyboy)
                entry = _plugin_recording_registry.get(pid)
                if entry and entry["events"]:
                    output_path = Path(config["record_input_path"]).parent / f"plugin_inputs_env{env_obj.env_index}.json"
                    effective_actions = [
                        int(action["action"])
                        for action in getattr(env_obj, "_episode_actions", [])
                    ]
                    finalize_input_recording(
                        pyboy,
                        output_path,
                        actions=effective_actions,
                        action_freq=int(entry["action_freq"]),
                        noop_action=int(entry["noop_action"]),
                        rom_path=Path(args.rom),
                        init_state_path=Path(env_obj.init_state),
                    )
                    save_paths.append(output_path)
            if save_paths:
                print(f"[Plugin Recorder] Saved input recordings to: {save_paths}")
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