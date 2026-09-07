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

from skill_lab.curriculum import list_stages, get_stage


class Launcher:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Pokemon Red Skill Lab")
        self.root.geometry("520x520")
        self.root.resizable(False, False)

        self.checkpoint_dir = PROJECT_ROOT / "mosaic_sessions" / "checkpoints"
        self.checkpoints = self._find_checkpoints()

        self.mode_var = tk.StringVar(value="new" if not self.checkpoints else "train")
        self.model_var = tk.StringVar()
        self.stage_var = tk.StringVar(value="starter")
        self.training_mode_var = tk.StringVar(value="segment")  # NEW
        self.rows_var = tk.IntVar(value=6)
        self.cols_var = tk.IntVar(value=7)
        self.max_steps_var = tk.IntVar(value=500)  # NEW: segment length
        self.batch_iterations_var = tk.IntVar(value=10_000_000)
        self.hud_var = tk.BooleanVar(value=True)
        self.speed_var = tk.IntVar(value=2)  # NEW: emulator speed
        self.continuous_var = tk.BooleanVar(value=False)
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
        main_frame = ttk.Frame(self.root, padding=15)
        main_frame.grid(row=0, column=0, sticky="nsew")

        # Title
        ttk.Label(
            main_frame, text="Pokemon Red Skill Lab", font=("", 16, "bold")
        ).grid(row=0, column=0, columnspan=2, pady=(0, 10))

        # Row 1: Mode
        ttk.Label(main_frame, text="Mode:").grid(row=1, column=0, sticky="w", pady=2)
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

        # Row 2: Model
        ttk.Label(main_frame, text="Model:").grid(row=2, column=0, sticky="w", pady=2)
        self.model_combo = ttk.Combobox(
            main_frame, textvariable=self.model_var, width=35, state="readonly"
        )
        self.model_combo.grid(row=2, column=1, pady=2)
        if self.checkpoints:
            self.model_combo["values"] = [str(p.name) for p in self.checkpoints]
            self.model_var.set(self.checkpoints[0].name)

        # Row 3: Stage
        ttk.Label(main_frame, text="Stage:").grid(row=3, column=0, sticky="w", pady=2)
        self.stage_combo = ttk.Combobox(
            main_frame, textvariable=self.stage_var,
            values=list_stages(), state="readonly", width=15
        )
        self.stage_combo.grid(row=3, column=1, pady=2, sticky="w")
        self.stage_combo.bind("<<ComboboxSelected>>", self._on_stage_change)

        # Row 4: Training Mode (Segment vs Fullrun)
        ttk.Label(main_frame, text="Training:").grid(row=4, column=0, sticky="w", pady=2)
        train_frame = ttk.Frame(main_frame)
        train_frame.grid(row=4, column=1, sticky="w")
        ttk.Radiobutton(
            train_frame, text="Segment (reset after N steps)",
            variable=self.training_mode_var, value="segment",
            command=self._on_training_mode_change
        ).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(
            train_frame, text="Fullrun (no reset)",
            variable=self.training_mode_var, value="fullrun",
            command=self._on_training_mode_change
        ).pack(side=tk.LEFT, padx=5)

        # Row 5: Segment Steps
        ttk.Label(main_frame, text="Steps:").grid(row=5, column=0, sticky="w", pady=2)
        steps_frame = ttk.Frame(main_frame)
        steps_frame.grid(row=5, column=1, sticky="w")
        self.steps_spinbox = ttk.Spinbox(
            steps_frame, from_=100, to=20000,
            textvariable=self.max_steps_var, width=8
        )
        self.steps_spinbox.pack(side=tk.LEFT, padx=5)
        self.steps_label = ttk.Label(steps_frame, text="(steps per segment before reset)")
        self.steps_label.pack(side=tk.LEFT)

        # Row 6: Speed
        ttk.Label(main_frame, text="Speed:").grid(row=6, column=0, sticky="w", pady=2)
        speed_frame = ttk.Frame(main_frame)
        speed_frame.grid(row=6, column=1, sticky="w")
        ttk.Spinbox(speed_frame, from_=1, to=10, textvariable=self.speed_var, width=4).pack(side=tk.LEFT, padx=5)
        ttk.Label(speed_frame, text="(1=normal, 2=double, 0=turbo)").pack(side=tk.LEFT)

        # Row 7: Continuous
        ttk.Checkbutton(
            main_frame, text="Run continuously (repeat batches)",
            variable=self.continuous_var
        ).grid(row=8, column=0, columnspan=2, sticky="w", pady=5)

        # Row 8: Batch iterations
        ttk.Label(main_frame, text="Batch iterations:").grid(row=9, column=0, sticky="w", pady=2)
        batch_frame = ttk.Frame(main_frame)
        batch_frame.grid(row=9, column=1, sticky="w")
        ttk.Entry(
            batch_frame, textvariable=self.batch_iterations_var, width=12
        ).pack(side=tk.LEFT, padx=5)
        ttk.Label(batch_frame, text="(steps before each reset/report)").pack(side=tk.LEFT)

        # Row 9: Layout
        ttk.Label(main_frame, text="Layout:").grid(row=7, column=0, sticky="w", pady=2)
        layout_frame = ttk.Frame(main_frame)
        layout_frame.grid(row=7, column=1, sticky="w")
        ttk.Label(layout_frame, text="Rows:").pack(side=tk.LEFT)
        ttk.Spinbox(layout_frame, from_=1, to=10, textvariable=self.rows_var, width=4).pack(side=tk.LEFT, padx=(2, 10))
        ttk.Label(layout_frame, text="Cols:").pack(side=tk.LEFT)
        ttk.Spinbox(layout_frame, from_=1, to=12, textvariable=self.cols_var, width=4).pack(side=tk.LEFT, padx=2)
        self.total_envs_var = tk.StringVar(value="= 42 envs")
        ttk.Label(layout_frame, textvariable=self.total_envs_var).pack(side=tk.LEFT, padx=5)
        self.rows_var.trace_add("write", self._update_total)
        self.cols_var.trace_add("write", self._update_total)

        # Row 10: HUD
        ttk.Checkbutton(
            main_frame, text="Use HUD overlay", variable=self.hud_var
        ).grid(row=10, column=0, columnspan=2, sticky="w", pady=5)

        # Row 11: Stage description
        self.stage_desc_var = tk.StringVar(value="")
        ttk.Label(
            main_frame, textvariable=self.stage_desc_var,
            font=("", 8), foreground="gray"
        ).grid(row=11, column=0, columnspan=2, sticky="w")

        # Row 12: Launch
        ttk.Button(
            main_frame, text="Launch", command=self._launch
        ).grid(row=12, column=0, columnspan=2, pady=10)

        # Initialize
        self._on_mode_change()
        self._on_stage_change(None)
        self._on_training_mode_change()
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

    def _on_training_mode_change(self) -> None:
        if self.training_mode_var.get() == "fullrun":
            self.steps_spinbox.config(state="disabled")
            self.steps_label.config(text="(no reset in fullrun mode)")
        else:
            self.steps_spinbox.config(state="normal")
            self.steps_label.config(text="(steps per segment before reset)")

    def _launch(self) -> None:
        mode = self.mode_var.get()
        rows = self.rows_var.get()
        cols = self.cols_var.get()
        num_envs = rows * cols
        use_hud = self.hud_var.get()
        stage_name = self.stage_var.get()
        training_mode = self.training_mode_var.get()
        max_steps = self.max_steps_var.get() if training_mode == "segment" else 999999
        batch_iterations = self.batch_iterations_var.get()
        if batch_iterations < 1:
            raise ValueError("Batch iterations must be at least 1")

        args = argparse.Namespace(
            model=None,
            dry_run=False,
            rom=Path("PokemonRed.gb"),
            init_state=Path("init.state"),
            max_steps=max_steps,
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
            total_timesteps=batch_iterations,
            save_freq=100_000,
            checkpoint_dir=Path("mosaic_sessions/checkpoints"),
            resume=False,
            loop=False,
            no_hud=not use_hud,
            stage=stage_name,
            mosaic_rows=rows,
            mosaic_cols=cols,
            training_mode=training_mode,
            emulator_speed=self.speed_var.get(),
            milestones_path=Path("skill_lab/milestones.json"),
            continuous=self.continuous_var.get(), 
        )

        if mode == "train" and self.checkpoints:
            selected_name = self.model_var.get()
            selected = next(
                (p for p in self.checkpoints if p.name == selected_name), None
            )
            if selected is not None:
                args.model = str(selected)

        self.root.destroy()

        from skill_lab.run_mosaic import main
        main(args)

    def run(self) -> None:
        self.root.mainloop()


def launch_gui() -> None:
    Launcher().run()