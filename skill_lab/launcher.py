"""Launcher GUI for the skill lab mosaic."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import tkinter as tk
from tkinter import ttk

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from skill_lab.config import TOTAL_TILES
from skill_lab.run_mosaic import main


class Launcher:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Pokemon Red Skill Lab")
        self.root.geometry("420x320")
        self.root.resizable(False, False)

        self.checkpoint_dir = PROJECT_ROOT / "mosaic_sessions" / "checkpoints"
        self.checkpoints = self._find_checkpoints()

        self.mode_var = tk.StringVar(value="new" if not self.checkpoints else "train")
        self.model_var = tk.StringVar()
        self.num_envs_var = tk.IntVar(value=12)
        self.hud_var = tk.BooleanVar(value=True)

        self._build_ui()

    def _find_checkpoints(self) -> list[Path]:
        if not self.checkpoint_dir.exists():
            return []
        return sorted(self.checkpoint_dir.glob("mosaic_*_steps.zip"), key=lambda p: p.stat().st_mtime, reverse=True)

    def _build_ui(self) -> None:
        main_frame = ttk.Frame(self.root, padding=20)
        main_frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(main_frame, text="Pokemon Red Skill Lab", font=("", 16, "bold")).grid(row=0, column=0, columnspan=2, pady=(0, 20))

        ttk.Label(main_frame, text="Mode:").grid(row=1, column=0, sticky="w", pady=5)
        mode_frame = ttk.Frame(main_frame)
        mode_frame.grid(row=1, column=1, sticky="w")
        ttk.Radiobutton(mode_frame, text="New Model", variable=self.mode_var, value="new", command=self._on_mode_change).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(mode_frame, text="Train Model", variable=self.mode_var, value="train", command=self._on_mode_change).pack(side=tk.LEFT, padx=5)

        ttk.Label(main_frame, text="Model:").grid(row=2, column=0, sticky="w", pady=5)
        self.model_combo = ttk.Combobox(main_frame, textvariable=self.model_var, width=40, state="readonly")
        self.model_combo.grid(row=2, column=1, pady=5)
        if self.checkpoints:
            self.model_combo["values"] = [str(p.name) for p in self.checkpoints]
            self.model_var.set(self.checkpoints[0].name)

        ttk.Label(main_frame, text="Environments:").grid(row=3, column=0, sticky="w", pady=5)
        env_frame = ttk.Frame(main_frame)
        env_frame.grid(row=3, column=1, sticky="w")
        env_spin = ttk.Spinbox(env_frame, from_=1, to=TOTAL_TILES, textvariable=self.num_envs_var, width=5)
        env_spin.pack(side=tk.LEFT, padx=5)
        ttk.Label(env_frame, text=f"(max {TOTAL_TILES})").pack(side=tk.LEFT)

        ttk.Checkbutton(main_frame, text="Use HUD overlay (cv2 information inside image)", variable=self.hud_var).grid(row=4, column=0, columnspan=2, sticky="w", pady=15)

        self.mask_start_select_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            main_frame,
            text="Disable Start/Select buttons (action masking)",
            variable=self.mask_start_select_var,
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=5)

        ttk.Button(main_frame, text="Launch", command=self._launch).grid(row=5, column=0, columnspan=2, pady=10)

        self._on_mode_change()

    def _on_mode_change(self) -> None:
        if self.mode_var.get() == "train":
            self.model_combo.config(state="readonly")
        else:
            self.model_combo.config(state="disabled")

    def _launch(self) -> None:
        mode = self.mode_var.get()
        num_envs = max(1, min(TOTAL_TILES, int(self.num_envs_var.get())))
        use_hud = self.hud_var.get()
        disable_start_select=self.mask_start_select_var.get(),

        args = argparse.Namespace(
            model=None,
            dry_run=False,
            rom=Path("PokemonRed.gb"),
            init_state=Path("init.state"),
            max_steps=2048 * 80,
            seed=0,
            foreground=False,
            teacher_bonus=5.0,
            teacher_log=Path("mosaic_sessions/teacher_actions.jsonl"),
            num_envs=num_envs,
            reward_scale=1.0,
            explore_weight=1.0,
            specialization=None,
            n_steps=256,
            batch_size=512,
            n_epochs=1,
            gamma=0.997,
            ent_coef=0.01,
            total_timesteps=1_000_000,
            save_freq=100_000,
            checkpoint_dir=Path("mosaic_sessions/checkpoints"),
            resume=False,
            loop=False,
            no_hud=not use_hud,
            # NEW: Action masking and milestones
            disable_start_select=True,
            milestones_path=Path("skill_lab/milestones.json"),
        )

        if mode == "train" and self.checkpoints:
            selected_name = self.model_var.get()
            selected = next((p for p in self.checkpoints if p.name == selected_name), None)
            if selected is not None:
                args.model = str(selected)

        self.root.destroy()
        main(args)

    def run(self) -> None:
        self.root.mainloop()


def launch_gui() -> None:
    Launcher().run()
