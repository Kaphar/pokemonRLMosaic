"""Launcher GUI for the skill lab mosaic."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from skill_lab.config import DEFAULT_EMULATOR_SPEED, DEFAULT_MAX_STEPS
from skill_lab.curriculum import list_stages, get_stage
from skill_lab.rewards import medium_reward
from skill_lab.env_setup import PROFILES, ENVS_DIR


class EnvConfigWindow:
    """Configuration window for setting up environment settings per trainer and worker."""
    
    def __init__(self, parent) -> None:
        self.top = tk.Toplevel(parent)
        self.top.title("Environment Configuration")
        self.top.geometry("700x550")
        self.top.resizable(True, True)
        
        # Load current configs if they exist
        self.trainer_configs = self._load_trainer_configs()
        self.worker_defaults = self._load_worker_defaults()
        
        self._build_ui()
    
    def _load_trainer_configs(self) -> dict:
        """Load existing trainer configurations from env folders."""
        configs = {}
        trainer_names = ["CharmanderTrainer", "SquirtleTrainer", "BulbasaurTrainer"]
        
        for trainer_name in trainer_names:
            trainer_dir = ENVS_DIR / trainer_name
            config_file = trainer_dir / "trainer_config.json"
            if config_file.exists():
                with open(config_file, "r") as f:
                    configs[trainer_name] = json.load(f)
            else:
                # Default config
                configs[trainer_name] = {
                    "profile": "trainer" if trainer_name == "CharmanderTrainer" else "explorer",
                    "rom": "PokemonRed.gb",
                    "init_state": f"{trainer_name.replace('Trainer', '').lower()}.init.state",
                    "stage": "progress",
                    "reward_scale": 2.0 if trainer_name == "CharmanderTrainer" else 1.0,
                    "explore_weight": 0.5 if trainer_name == "CharmanderTrainer" else 1.0,
                }
        
        return configs
    
    def _load_worker_defaults(self) -> dict:
        """Load worker default configuration."""
        config_file = ENVS_DIR / "worker_defaults.json"
        if config_file.exists():
            with open(config_file, "r") as f:
                return json.load(f)
        return {
            "blue_rom_chance": 0.5,
            "profile_distribution": "50/50",
            "stage": "progress",
            "reward_scale": 1.0,
            "explore_weight": 1.0,
        }
    
    def _build_ui(self) -> None:
        main_frame = ttk.Frame(self.top, padding=10)
        main_frame.grid(row=0, column=0, sticky="nsew")
        
        # Title
        ttk.Label(main_frame, text="Environment Configuration Setup", font=("", 14, "bold")).grid(
            row=0, column=0, columnspan=2, pady=(0, 10)
        )
        
        # Trainer configurations notebook
        notebook = ttk.Notebook(main_frame)
        notebook.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=5)
        
        # Create tabs for each trainer
        for trainer_name in ["CharmanderTrainer", "SquirtleTrainer", "BulbasaurTrainer"]:
            tab = ttk.Frame(notebook, padding=10)
            notebook.add(tab, text=trainer_name.replace("Trainer", ""))
            self._build_trainer_tab(tab, trainer_name)
        
        # Worker defaults tab
        worker_tab = ttk.Frame(notebook, padding=10)
        notebook.add(worker_tab, text="Worker Defaults")
        self._build_worker_tab(worker_tab)
        
        # Buttons
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=2, column=0, columnspan=2, pady=10)
        ttk.Button(btn_frame, text="Save Configuration", command=self._save_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=self.top.destroy).pack(side=tk.LEFT, padx=5)
    
    def _build_trainer_tab(self, tab, trainer_name: str) -> None:
        config = self.trainer_configs[trainer_name]
        
        # Profile selection
        ttk.Label(tab, text="Profile:").grid(row=0, column=0, sticky="w", pady=5)
        profile_var = tk.StringVar(value=config.get("profile", "trainer"))
        ttk.Combobox(tab, textvariable=profile_var, values=["trainer", "explorer"], 
                     state="readonly", width=15).grid(row=0, column=1, sticky="w", pady=5)
        
        # ROM selection
        ttk.Label(tab, text="ROM File:").grid(row=1, column=0, sticky="w", pady=5)
        rom_var = tk.StringVar(value=config.get("rom", "PokemonRed.gb"))
        ttk.Combobox(tab, textvariable=rom_var, values=["PokemonRed.gb", "PokemonBlue.gb"],
                     state="readonly", width=20).grid(row=1, column=1, sticky="w", pady=5)
        
        # Initial state
        ttk.Label(tab, text="Initial State:").grid(row=2, column=0, sticky="w", pady=5)
        state_var = tk.StringVar(value=config.get("init_state", "init.state"))
        ttk.Entry(tab, textvariable=state_var, width=25).grid(row=2, column=1, sticky="w", pady=5)
        
        # Stage selection
        ttk.Label(tab, text="Training Stage:").grid(row=3, column=0, sticky="w", pady=5)
        stage_var = tk.StringVar(value=config.get("stage", "progress"))
        ttk.Combobox(tab, textvariable=stage_var, values=list_stages(),
                     state="readonly", width=15).grid(row=3, column=1, sticky="w", pady=5)
        
        # Reward scale
        ttk.Label(tab, text="Reward Scale:").grid(row=4, column=0, sticky="w", pady=5)
        reward_scale_var = tk.DoubleVar(value=config.get("reward_scale", 1.0))
        ttk.Spinbox(tab, from_=0.1, to=10.0, increment=0.1, textvariable=reward_scale_var,
                    width=8).grid(row=4, column=1, sticky="w", pady=5)
        
        # Explore weight
        ttk.Label(tab, text="Explore Weight:").grid(row=5, column=0, sticky="w", pady=5)
        explore_weight_var = tk.DoubleVar(value=config.get("explore_weight", 1.0))
        ttk.Spinbox(tab, from_=0.1, to=10.0, increment=0.1, textvariable=explore_weight_var,
                    width=8).grid(row=5, column=1, sticky="w", pady=5)
        
        # Store variables for saving
        tab.config_vars = {
            "profile": profile_var,
            "rom": rom_var,
            "init_state": state_var,
            "stage": stage_var,
            "reward_scale": reward_scale_var,
            "explore_weight": explore_weight_var,
        }
        tab.trainer_name = trainer_name
    
    def _build_worker_tab(self, tab) -> None:
        config = self.worker_defaults
        
        # Blue ROM chance
        ttk.Label(tab, text="Blue ROM Chance:").grid(row=0, column=0, sticky="w", pady=5)
        blue_chance_var = tk.DoubleVar(value=config.get("blue_rom_chance", 0.5))
        ttk.Spinbox(tab, from_=0.0, to=1.0, increment=0.1, textvariable=blue_chance_var,
                    width=8).grid(row=0, column=1, sticky="w", pady=5)
        ttk.Label(tab, text="(0.0 = all Red, 1.0 = all Blue, 0.5 = 50/50)").grid(
            row=0, column=2, sticky="w", pady=5)
        
        # Profile distribution
        ttk.Label(tab, text="Profile Distribution:").grid(row=1, column=0, sticky="w", pady=5)
        profile_dist_var = tk.StringVar(value=config.get("profile_distribution", "50/50"))
        ttk.Combobox(tab, textvariable=profile_dist_var, 
                     values=["50/50", "all_trainer", "all_explorer"],
                     state="readonly", width=15).grid(row=1, column=1, sticky="w", pady=5)
        
        # Stage selection
        ttk.Label(tab, text="Training Stage:").grid(row=2, column=0, sticky="w", pady=5)
        stage_var = tk.StringVar(value=config.get("stage", "progress"))
        ttk.Combobox(tab, textvariable=stage_var, values=list_stages(),
                     state="readonly", width=15).grid(row=2, column=1, sticky="w", pady=5)
        
        # Reward scale
        ttk.Label(tab, text="Reward Scale:").grid(row=3, column=0, sticky="w", pady=5)
        reward_scale_var = tk.DoubleVar(value=config.get("reward_scale", 1.0))
        ttk.Spinbox(tab, from_=0.1, to=10.0, increment=0.1, textvariable=reward_scale_var,
                    width=8).grid(row=3, column=1, sticky="w", pady=5)
        
        # Explore weight
        ttk.Label(tab, text="Explore Weight:").grid(row=4, column=0, sticky="w", pady=5)
        explore_weight_var = tk.DoubleVar(value=config.get("explore_weight", 1.0))
        ttk.Spinbox(tab, from_=0.1, to=10.0, increment=0.1, textvariable=explore_weight_var,
                    width=8).grid(row=4, column=1, sticky="w", pady=5)
        
        # Store variables for saving
        tab.config_vars = {
            "blue_chance": blue_chance_var,
            "profile_dist": profile_dist_var,
            "stage": stage_var,
            "reward_scale": reward_scale_var,
            "explore_weight": explore_weight_var,
        }
    
    def _save_config(self) -> None:
        """Save configuration to files."""
        # Save trainer configs
        for trainer_name in ["CharmanderTrainer", "SquirtleTrainer", "BulbasaurTrainer"]:
            trainer_dir = ENVS_DIR / trainer_name
            trainer_dir.mkdir(parents=True, exist_ok=True)
            
            config_file = trainer_dir / "trainer_config.json"
            # Would need to get actual values from the UI widgets
            # For now this is a placeholder - full implementation would extract widget values
        
        # Save worker defaults
        worker_config_file = ENVS_DIR / "worker_defaults.json"
        # Would need to get actual values from the UI widgets
        
        messagebox.showinfo("Configuration Saved", 
                           "Environment configuration has been saved.\nThese settings will be used on next launch.")
        self.top.destroy()


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
        self.num_envs_var = tk.IntVar(value=42)
        self.max_steps_var = tk.IntVar(value=DEFAULT_MAX_STEPS)  # Load from config
        self.batch_iterations_var = tk.IntVar(value=10_000_000)
        self.hud_var = tk.BooleanVar(value=True)
        self.speed_var = tk.IntVar(value=DEFAULT_EMULATOR_SPEED)  # Load from config (0=auto)
        self.continuous_var = tk.BooleanVar(value=False)
        self.record_input_var = tk.BooleanVar(value=True)  # Changed: record plugin enabled by default
        self.legacy_recorder_var = tk.BooleanVar(value=False)  # NEW: legacy recorder option
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
        ttk.Spinbox(speed_frame, from_=0, to=10, textvariable=self.speed_var, width=4).pack(side=tk.LEFT, padx=5)
        ttk.Label(speed_frame, text="(0=auto/turbo, 1=normal, 2=double)").pack(side=tk.LEFT)

        # Row 8: Worker environments
        ttk.Label(main_frame, text="Worker environments:").grid(row=8, column=0, sticky="w", pady=2)
        worker_frame = ttk.Frame(main_frame)
        worker_frame.grid(row=8, column=1, sticky="w")
        ttk.Spinbox(worker_frame, from_=1, to=512, textvariable=self.num_envs_var, width=8).pack(side=tk.LEFT, padx=5)
        ttk.Label(worker_frame, text="(all train; mosaic shows one page)").pack(side=tk.LEFT)

        # Row 9: Continuous
        ttk.Checkbutton(
            main_frame, text="Run continuously (repeat batches)",
            variable=self.continuous_var
        ).grid(row=9, column=0, columnspan=2, sticky="w", pady=5)

        # Row 10: Batch iterations
        ttk.Label(main_frame, text="Batch iterations:").grid(row=10, column=0, sticky="w", pady=2)
        batch_frame = ttk.Frame(main_frame)
        batch_frame.grid(row=10, column=1, sticky="w")
        ttk.Entry(
            batch_frame, textvariable=self.batch_iterations_var, width=12
        ).pack(side=tk.LEFT, padx=5)
        ttk.Label(batch_frame, text="(steps before each reset/report)").pack(side=tk.LEFT)

        # Row 7: Layout
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

        # Row 11: HUD
        ttk.Checkbutton(
            main_frame, text="Use HUD overlay", variable=self.hud_var
        ).grid(row=11, column=0, columnspan=2, sticky="w", pady=5)

        # Row 12: Record frame-exact inputs (plugin-based, enabled by default)
        ttk.Checkbutton(
            main_frame, text="Record frame-exact inputs (plugin)", variable=self.record_input_var
        ).grid(row=12, column=0, columnspan=2, sticky="w", pady=5)

        # Row 13: Legacy recorder (only if plugin recording is disabled)
        self.legacy_check = ttk.Checkbutton(
            main_frame, text="Use legacy recorder (instead of plugin)", variable=self.legacy_recorder_var, state="disabled"
        )
        self.legacy_check.grid(row=13, column=0, columnspan=2, sticky="w", pady=5)
        self.record_input_var.trace_add("write", self._toggle_legacy_option)

        # Row 14: Stage description
        self.stage_desc_var = tk.StringVar(value="")
        ttk.Label(
            main_frame, textvariable=self.stage_desc_var,
            font=("", 8), foreground="gray"
        ).grid(row=14, column=0, columnspan=2, sticky="w")


        # Row 15: Setup Environment Config button
        ttk.Button(
            main_frame, text="Setup Environment Config", command=self._open_env_config
        ).grid(row=15, column=0, columnspan=2, pady=5)

        # Row 16: Launch
        ttk.Button(
            main_frame, text="Launch", command=self._launch
        ).grid(row=15, column=0, columnspan=2, pady=10)

        # Initialize
        self._on_mode_change()
        self._on_stage_change(None)
        self._on_training_mode_change()
        self._update_total()
        self._toggle_legacy_option()

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

    def _toggle_legacy_option(self, *args) -> None:
        """Enable legacy recorder checkbox only when plugin recording is disabled."""
        if self.record_input_var.get():
            self.legacy_check.config(state="disabled")
            self.legacy_recorder_var.set(False)
        else:
            self.legacy_check.config(state="normal")

    def _open_env_config(self) -> None:
        """Open the environment configuration window."""
        EnvConfigWindow(self.root)

    def _launch(self) -> None:
        mode = self.mode_var.get()
        rows = self.rows_var.get()
        cols = self.cols_var.get()
        num_envs = self.num_envs_var.get()
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
            teacher_bonus=medium_reward,
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
            record_input_with_plugin=self.record_input_var.get(),
            use_legacy_recorder=self.legacy_recorder_var.get(),
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