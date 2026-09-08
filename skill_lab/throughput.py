"""Periodic training throughput reporting."""

from __future__ import annotations

import time
from typing import Any

from stable_baselines3.common.callbacks import BaseCallback


class ThroughputLogger:
    def __init__(self, label: str, interval_seconds: float = 60.0) -> None:
        self.label = label
        self.interval_seconds = interval_seconds
        self.started_at = time.perf_counter()
        self.last_at = self.started_at
        self.last_steps = 0

    def update(self, total_steps: int) -> None:
        now = time.perf_counter()
        elapsed = now - self.last_at
        if elapsed < self.interval_seconds:
            return
        delta_steps = total_steps - self.last_steps
        overall_elapsed = max(now - self.started_at, 1e-9)
        print(
            f"[{self.label}] throughput: {delta_steps / elapsed * 60:.0f} env steps/min "
            f"(overall {total_steps / overall_elapsed * 60:.0f}/min)",
            flush=True,
        )
        self.last_at = now
        self.last_steps = total_steps


class ThroughputCallback(BaseCallback):
    def __init__(self, label: str, interval_seconds: float = 60.0, verbose: int = 0) -> None:
        super().__init__(verbose)
        self.throughput = ThroughputLogger(label, interval_seconds)

    def _on_step(self) -> bool:
        self.throughput.update(self.num_timesteps)
        return True
