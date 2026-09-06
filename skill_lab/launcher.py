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
from skill_lab.curriculum import list_stages, get_stage


class Launcher:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Pokemon Red Skill Lab")
        self.root.geometry("480x420")
        self.root.resizable(False, False)

        self.checkpoint_dir = PROJECT_ROOT / "mosaic_sessions" / "checkpoints"
        self.checkpoints = self._find_checkpoints()

        self.mode_var = tk.StringVar(value="new" if not self.checkpoints else "train")
        self.model_var = tk.StringVar()
        self.stage_var = tk.StringVar(value="explore")
        self.rows_var = tk.IntVar(value=6)
        self.cols_var = tk.IntVar(value=7)
        self.hud_var = tk.BooleanVar(value=True)

        self._build_ui()

    def _find_checkpoints(self) -> list[Path]:
        if not self.checkpoint_dir.exists():
            return []
        return sorted(
            self.checkpoint_dir.glob("mosaic_*_steps.zip"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

    def _build_ui(self) -> None:
        main_frame = ttk.Frame(self.root, padding=20)
        main_frame.grid(row=0, column=0, sticky="nsew")

        # Title
        ttk.Label(
            main_frame, text="Pokemon Red Skill Lab", font=("", 16, "bold")
        ).grid(row=0, column=0, columnspan=2, pady=(0, 15))

        # Mode selection
        ttk.Label(main_frame, text="Mode:").grid(row=1, column=0, sticky="w", pady=3)
        mode_frame = ttk.Frame(main_frame)
        mode_frame.grid(row=1, column=1, sticky="w")
        ttk.Radiobutton(
            mode_frame, text="New Model", variable=self.mode_var,
            value="new", command=self._on_mode_change
        ).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(
            mode_frame, text="Train Model", variable=self.mode_var,
            value="train", command=self._on_mode_change
        ).pack(side=tk.LEFT, padx=5)

        # Model selection
        ttk.Label(main_frame, text="Model:").grid(row=2, column=0, sticky="w", pady=3)
        self.model_combo = ttk.Combobox(
            main_frame, textvariable=self.model_var, width=35, state="readonly"
        )
        self.model_combo.grid(row=2, column=1, pady=3)
        if self.checkpoints:
            self.model_combo["values"] = [str(p.name) for p in self.checkpoints]
            self.model_var.set(self.checkpoints[0].name)

        # Stage selection
        ttk.Label(main_frame, text="Stage:").grid(row=3, column=0, sticky="w", pady=3)
        self.stage_combo = ttk.Combobox(
            main_frame, textvariable=self.stage_var,
            values=list_stages(), state="readonly", width=15
        )
        self.stage_combo.grid(row=3, column=1, pady=3, sticky="w")
        self.stage_combo.bind("<<ComboboxSelected>>", self._on_stage_change)

        # Stage description
        self.stage_desc_var = tk.StringVar(value="")
        ttk.Label(
            main_frame, textvariable=self.stage_desc_var,
            font=("", 8), foreground="gray"
        ).grid(row=4, column=0, columnspan=2, sticky="w")

        # Layout: Rows and Columns
        ttk.Label(main_frame, text="Layout:").grid(row=5, column=0, sticky="w", pady=3)
        layout_frame = ttk.Frame(main_frame)
        layout_frame.grid(row=5, column=1, sticky="w")

        ttk.Label(layout_frame, text="Rows:").pack(side=tk.LEFT)
        ttk.Spinbox(
            layout_frame, from_=1, to=10, textvariable=self.rows_var, width=4
        ).pack(side=tk.LEFT, padx=(2, 10))

        ttk.Label(layout_frame, text="Cols:").pack(side=tk.LEFT)
        ttk.Spinbox(
            layout_frame, from_=1, to=12, textvariable=self.cols_var, width=4
        ).pack(side=tk.LEFT, padx=2)

        self.total_envs_var = tk.StringVar(value="= 42 envs")
        ttk.Label(layout_frame, textvariable=self.total_envs_var).pack(side=tk.LEFT, padx=5)

        # Update total when rows/cols change
        self.rows_var.trace_add("write", self._update_total)
        self.cols_var.trace_add("write", self._update_total)

        # HUD toggle
        ttk.Checkbutton(
            main_frame, text="Use HUD overlay", variable=self.hud_var
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=10)

        # Launch button
        ttk.Button(
            main_frame, text="Launch", command=self._launch
        ).grid(row=7, column=0, columnspan=2, pady=10)

        # Initialize
        self._on_mode_change()
        self._on_stage_change(None)
        self._update_total()

    def _update_total(self, *args) -> None:
        total = self.rows_var.get() * self.cols_var.get()
        self.total_envs_var.set(f"= {total} envs")

    def _on_mode_change(self) -> None:
        if self.mode_var.get() == "train":
            self.model_combo.config(state="readonly")
        else:
            self.model_combo.config(state="disabled")

    def _on_stage_change(self, event) -> None:
        stage_name = self.stage_var.get()
        try:
            stage = get_stage(stage_name)
            self.stage_desc_var.set(stage.description)
        except KeyError:
            self.stage_desc_var.set("")

    def _launch(self) -> None:
        mode = self.mode_var.get()
        rows = self.rows_var.get()
        cols = self.cols_var.get()
        num_envs = rows * cols
        use_hud = self.hud_var.get()
        stage_name = self.stage_var.get()

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
            # NEW: Stage and layout
            stage=stage_name,
            mosaic_rows=rows,
            mosaic_cols=cols,
            disable_start_select=None,  # Let the stage handle this
            milestones_path=Path("skill_lab/milestones.json"),
        )

        if mode == "train" and self.checkpoints:
            selected_name = self.model_var.get()
            selected = next(
                (p for p in self.checkpoints if p.name == selected_name), None
            )
            if selected is not None:
                args.model = str(selected)

        self.root.destroy()
        main(args)

    def run(self) -> None:
        self.root.mainloop()


def launch_gui() -> None:
    Launcher().run()