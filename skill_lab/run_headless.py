"""Fast headless Skill Lab training with optional launcher UI.

Run with arguments for unattended training, or without arguments to open the
parameter launcher. Continuous mode trains until interrupted with Ctrl+C.
"""

from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path

from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import CallbackList, CheckpointCallback
from stable_baselines3.common.vec_env import SubprocVecEnv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from skill_lab.config import ACTION_FREQ, DEFAULT_INIT_STATE, DEFAULT_ROM
from skill_lab.curriculum import get_stage, list_stages
from skill_lab.emulator import make_env
from skill_lab.env_setup import setup_envs
from skill_lab.throughput import ThroughputCallback

DEFAULT_CHECKPOINT_DIR = PROJECT_ROOT / "mosaic_sessions" / "headless_checkpoints"
DEFAULT_SESSION_DIR = PROJECT_ROOT / "mosaic_sessions" / "headless"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=list_stages(), default="starter")
    parser.add_argument("--num-envs", type=int, default=16)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--init-state", type=Path, default=None)
    parser.add_argument("--total-timesteps", type=int, default=1_000_000)
    parser.add_argument("--n-steps", type=int, default=256)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--n-epochs", type=int, default=1)
    parser.add_argument("--gamma", type=float, default=0.997)
    parser.add_argument("--ent-coef", type=float, default=0.01)
    parser.add_argument("--reward-scale", type=float, default=1.0)
    parser.add_argument("--explore-weight", type=float, default=1.0)
    parser.add_argument("--emulator-speed", type=int, default=0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--checkpoint-dir", type=Path, default=DEFAULT_CHECKPOINT_DIR)
    parser.add_argument("--checkpoint-freq", type=int, default=100_000)
    parser.add_argument("--session-dir", type=Path, default=DEFAULT_SESSION_DIR)
    parser.add_argument("--resume", type=Path, default=None, help="PPO checkpoint path without or with .zip")
    parser.add_argument("--new-model", action="store_true", help="Ignore existing checkpoints and start a new model")
    parser.add_argument("--continuous", action="store_true", help="Train until interrupted with Ctrl+C")
    parser.add_argument("--no-save-objective-states", action="store_true")
    return parser.parse_args(argv)


def resolve_init_state(args: argparse.Namespace) -> Path:
    stage = get_stage(args.stage)
    if args.init_state is not None:
        return args.init_state.expanduser().resolve()
    stage_path = PROJECT_ROOT / stage.init_state
    if stage_path.is_file():
        return stage_path
    return DEFAULT_INIT_STATE


def build_config(args: argparse.Namespace, init_state: Path) -> dict:
    stage = get_stage(args.stage)
    max_steps = stage.max_steps
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
        "session_path": args.session_dir,
        "gb_path": str(args.rom),
        "debug": False,
        "reward_scale": args.reward_scale,
        "explore_weight": args.explore_weight,
        "noop_button": True,
        "speed": args.emulator_speed,
        "training_mode": "segment",
        "disable_start": stage.disable_start,
        "disable_select": stage.disable_select,
        "milestone_reward": stage.milestone_reward,
        "milestones_path": str(PROJECT_ROOT / "skill_lab" / "milestones.json"),
        "names_path": str(PROJECT_ROOT / "skill_lab" / "names.json"),
        "save_objective_states": not args.no_save_objective_states,
    }


def checkpoint_base(path: Path) -> Path:
    return Path(str(path)[:-4]) if path.suffix == ".zip" else path


def find_latest_checkpoint(checkpoint_dir: Path, stage_name: str) -> Path | None:
    """Return the newest checkpoint for a stage, if one exists."""
    candidates = list(checkpoint_dir.glob(f"{stage_name}_ppo_*.zip"))
    candidates.extend(checkpoint_dir.glob(f"{stage_name}_ppo_last.zip"))
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def resolve_resume(args: argparse.Namespace) -> Path | None:
    """Use an explicit checkpoint, otherwise resume the latest by default."""
    if args.new_model:
        return None
    if args.resume is not None:
        return args.resume.expanduser().resolve()
    return find_latest_checkpoint(args.checkpoint_dir.expanduser(), args.stage)


def command_line(args: argparse.Namespace) -> str:
    parts = ["python", "skill_lab/run_headless.py"]
    for key, value in vars(args).items():
        flag = "--" + key.replace("_", "-")
        if isinstance(value, bool):
            if value:
                parts.append(flag)
        elif value is not None:
            parts.extend([flag, str(value)])
    return shlex.join(parts)


def validate_args(args: argparse.Namespace, init_state: Path) -> None:
    if args.num_envs < 1:
        raise ValueError("--num-envs must be at least 1")
    if args.n_steps < 1:
        raise ValueError("--n-steps must be at least 1")
    if args.batch_size < 1 or args.batch_size > args.n_steps * args.num_envs:
        raise ValueError("--batch-size must be between 1 and n_steps * num_envs")
    if args.total_timesteps < 1 and not args.continuous:
        raise ValueError("--total-timesteps must be at least 1 unless --continuous is used")
    if not args.rom.is_file():
        raise FileNotFoundError(f"ROM not found: {args.rom}")
    if not init_state.is_file():
        raise FileNotFoundError(f"Initial state not found: {init_state}")
    if args.resume is not None and not Path(str(args.resume) + ("" if str(args.resume).endswith(".zip") else ".zip")).is_file():
        raise FileNotFoundError(f"Checkpoint not found: {args.resume}")


def train(args: argparse.Namespace) -> None:
    args.resume = resolve_resume(args)
    init_state = resolve_init_state(args)
    validate_args(args, init_state)
    args.session_dir = args.session_dir.expanduser().resolve()
    args.checkpoint_dir = args.checkpoint_dir.expanduser().resolve()
    args.session_dir.mkdir(parents=True, exist_ok=True)
    args.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    stage = get_stage(args.stage)
    config = build_config(args, init_state)
    env_configs = setup_envs(args.num_envs, stage=args.stage)
    env = SubprocVecEnv([
        make_env(index, config, env_configs[index])
        for index in range(args.num_envs)
    ], start_method="spawn")

    checkpoint_callback = CheckpointCallback(
        save_freq=max(1, args.checkpoint_freq // args.num_envs),
        save_path=str(args.checkpoint_dir),
        name_prefix=f"{args.stage}_ppo",
    )
    callbacks = CallbackList([
        checkpoint_callback,
        ThroughputCallback("headless"),
    ])
    model = None
    try:
        print(f"Stage: {stage.name} - {stage.description}")
        print(f"Workers: {args.num_envs} | rollout: {args.n_steps * args.num_envs} steps")
        print(f"Continuous: {args.continuous}")
        print(f"Resume: {args.resume if args.resume else 'new model'}")
        print(f"Command: {command_line(args)}")
        if args.resume is not None:
            model = PPO.load(str(checkpoint_base(args.resume)), env=env)
            model.n_steps = args.n_steps
            model.n_envs = args.num_envs
            model.rollout_buffer.buffer_size = args.n_steps
            model.rollout_buffer.n_envs = args.num_envs
            model.rollout_buffer.reset()
        else:
            model = PPO(
                "MultiInputPolicy",
                env,
                verbose=1,
                n_steps=args.n_steps,
                batch_size=args.batch_size,
                n_epochs=args.n_epochs,
                gamma=args.gamma,
                ent_coef=args.ent_coef,
                seed=args.seed,
                tensorboard_log=str(args.session_dir / "tensorboard"),
            )

        learn_kwargs = {
            "total_timesteps": max(args.total_timesteps, 1),
            "callback": callbacks,
            "reset_num_timesteps": args.resume is None,
            "tb_log_name": f"{args.stage}_ppo",
        }
        if args.continuous:
            print("Training continuously. Press Ctrl+C to stop; checkpoints remain available.")
            while True:
                model.learn(**learn_kwargs)
                learn_kwargs["reset_num_timesteps"] = False
        else:
            model.learn(**learn_kwargs)
    except KeyboardInterrupt:
        print("\nTraining interrupted. Checkpoints already written remain available.")
    finally:
        env.close()
        if model is not None:
            model.save(str(args.checkpoint_dir / f"{args.stage}_ppo_last"))
            print(f"Saved final checkpoint: {args.checkpoint_dir / (args.stage + '_ppo_last.zip')}")


def launch_gui() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("Pokemon Red Headless Training")
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=14)
    frame.grid()

    variables = {
        "stage": tk.StringVar(value="starter"),
        "num_envs": tk.IntVar(value=16),
        "total_timesteps": tk.IntVar(value=1_000_000),
        "n_steps": tk.IntVar(value=256),
        "batch_size": tk.IntVar(value=512),
        "checkpoint_freq": tk.IntVar(value=100_000),
        "continuous": tk.BooleanVar(value=False),
        "resume": tk.StringVar(),
        "new_model": tk.BooleanVar(value=False),
    }
    row = 0
    ttk.Label(frame, text="Headless Skill Lab Training", font=("", 14, "bold")).grid(row=row, column=0, columnspan=3, pady=(0, 10))
    row += 1
    for label, key, values in (
        ("Stage", "stage", list_stages()),
    ):
        ttk.Label(frame, text=f"{label}:").grid(row=row, column=0, sticky="w", pady=3)
        ttk.Combobox(frame, textvariable=variables[key], values=values, state="readonly", width=22).grid(row=row, column=1, columnspan=2, sticky="w")
        row += 1
    for label, key in (("Workers", "num_envs"), ("Total timesteps", "total_timesteps"), ("PPO n_steps", "n_steps"), ("Batch size", "batch_size"), ("Checkpoint frequency", "checkpoint_freq")):
        ttk.Label(frame, text=f"{label}:").grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(frame, textvariable=variables[key], width=24).grid(row=row, column=1, columnspan=2, sticky="w")
        row += 1
    ttk.Checkbutton(frame, text="Run continuously until Ctrl+C", variable=variables["continuous"]).grid(row=row, column=0, columnspan=3, sticky="w", pady=5)
    row += 1
    ttk.Label(frame, text="Resume checkpoint:").grid(row=row, column=0, sticky="w", pady=3)
    ttk.Entry(frame, textvariable=variables["resume"], width=42).grid(row=row, column=1, sticky="w")

    def choose_checkpoint() -> None:
        path = filedialog.askopenfilename(filetypes=[("PPO checkpoints", "*.zip"), ("All files", "*.*")])
        if path:
            variables["resume"].set(path)

    ttk.Button(frame, text="Choose...", command=choose_checkpoint).grid(row=row, column=2, padx=(5, 0))
    row += 1
    ttk.Checkbutton(
        frame, text="Start a new model instead of resuming latest checkpoint",
        variable=variables["new_model"],
    ).grid(row=row, column=0, columnspan=3, sticky="w", pady=5)
    row += 1

    def start() -> None:
        try:
            values = {key: variable.get() for key, variable in variables.items()}
            values["rom"] = DEFAULT_ROM
            values["init_state"] = None
            values["reward_scale"] = 1.0
            values["explore_weight"] = 1.0
            values["n_epochs"] = 1
            values["gamma"] = 0.997
            values["ent_coef"] = 0.01
            values["emulator_speed"] = 0
            values["seed"] = 0
            values["checkpoint_dir"] = DEFAULT_CHECKPOINT_DIR
            values["session_dir"] = DEFAULT_SESSION_DIR
            values["no_save_objective_states"] = False
            values["resume"] = Path(values["resume"]) if values["resume"] else None
            args = argparse.Namespace(**values)
            root.destroy()
            train(args)
        except (OSError, ValueError) as error:
            messagebox.showerror("Cannot start training", str(error), parent=root)

    ttk.Button(frame, text="Start training", command=start).grid(row=row, column=0, columnspan=3, pady=(10, 0))
    root.mainloop()


if __name__ == "__main__":
    if len(sys.argv) == 1:
        launch_gui()
    else:
        train(parse_args())
