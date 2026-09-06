"""Statistics tracker for monitoring training progress.

Tracks:
- Time to complete objective (steps)
- Success/failure rates per directive
- Rolling averages over time
- History across multiple runs

Displays in a separate OpenCV window.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import cv2
import numpy as np


class StatsTracker:
    """Tracks and displays training statistics."""

    def __init__(self, history_path: Path | None = None) -> None:
        self.history_path = history_path
        self.start_time = time.time()

        # Per-environment tracking
        self.env_stats: dict[int, dict[str, Any]] = {}

        # Aggregate tracking
        self.completion_times: list[float] = []  # Steps to complete
        self.success_count = 0
        self.failure_count = 0
        self.total_resets = 0

        # Rolling average (last N completions)
        self.rolling_window = 50
        self.avg_history: list[float] = []  # Average over time

        # Per-directive tracking
        self.directive_stats: dict[str, dict[str, int]] = defaultdict(
            lambda: {"success": 0, "failure": 0, "total_steps": 0, "count": 0}
        )

        # Load previous history
        self.previous_runs: list[dict] = []
        if history_path and history_path.exists():
            self._load_history()

    def _load_history(self) -> None:
        """Load statistics from previous runs."""
        try:
            with open(self.history_path, "r") as f:
                data = json.load(f)
            self.previous_runs = data.get("runs", [])
        except (json.JSONDecodeError, FileNotFoundError):
            pass

    def save_history(self) -> None:
        """Save current run statistics to history file."""
        if not self.history_path:
            return

        run_data = {
            "timestamp": time.time(),
            "duration_seconds": time.time() - self.start_time,
            "total_completions": len(self.completion_times),
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "avg_completion_steps": self.get_average_completion_time(),
            "directive_stats": dict(self.directive_stats),
        }

        self.previous_runs.append(run_data)

        # Keep only last 100 runs
        self.previous_runs = self.previous_runs[-100:]

        data = {"runs": self.previous_runs}
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.history_path, "w") as f:
            json.dump(data, f, indent=2)

    def record_completion(
        self,
        env_index: int,
        env_name: str,
        directive: str,
        steps: int,
        success: bool,
    ) -> None:
        """Record when an environment completes its objective."""
        self.total_resets += 1

        if success:
            self.success_count += 1
            self.completion_times.append(float(steps))
            self.directive_stats[directive]["success"] += 1
            self.directive_stats[directive]["total_steps"] += steps
            self.directive_stats[directive]["count"] += 1
        else:
            self.failure_count += 1
            self.directive_stats[directive]["failure"] += 1

        # Update rolling average
        if len(self.completion_times) > 0:
            recent = self.completion_times[-self.rolling_window:]
            avg = sum(recent) / len(recent)
            self.avg_history.append(avg)

        # Store per-env stat
        self.env_stats[env_index] = {
            "env_name": env_name,
            "directive": directive,
            "steps": steps,
            "success": success,
            "timestamp": time.time(),
        }

    def get_average_completion_time(self) -> float:
        if not self.completion_times:
            return 0.0
        return sum(self.completion_times) / len(self.completion_times)

    def get_rolling_average(self) -> float:
        if not self.completion_times:
            return 0.0
        recent = self.completion_times[-self.rolling_window:]
        return sum(recent) / len(recent)

    def get_success_rate(self) -> float:
        total = self.success_count + self.failure_count
        if total == 0:
            return 0.0
        return self.success_count / total

    def render(self, window_name: str = "Training Statistics") -> None:
        """Render the statistics window."""
        width, height = 700, 600
        canvas = np.full((height, width, 3), 25, dtype=np.uint8)

        y = 30

        # Title
        cv2.putText(canvas, "Training Statistics", (20, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
        y += 40

        # Elapsed time
        elapsed = time.time() - self.start_time
        minutes = int(elapsed // 60)
        seconds = int(elapsed % 60)
        cv2.putText(canvas, f"Session time: {minutes}m {seconds}s", (20, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1)
        y += 30

        # Overall stats
        cv2.putText(canvas, f"Total resets: {self.total_resets}", (20, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 1)
        y += 25

        cv2.putText(canvas, f"Success: {self.success_count}  |  "
                    f"Failure: {self.failure_count}  |  "
                    f"Rate: {self.get_success_rate():.1%}", (20, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 1)
        y += 25

        avg_time = self.get_average_completion_time()
        rolling_avg = self.get_rolling_average()
        cv2.putText(canvas, f"Avg steps to complete: {avg_time:.0f}  |  "
                    f"Recent avg: {rolling_avg:.0f}", (20, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 1)
        y += 40

        # Per-directive breakdown
        cv2.putText(canvas, "Directive Breakdown:", (20, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        y += 25
        cv2.line(canvas, (20, y), (width - 20, y), (80, 80, 80), 1)
        y += 20

        for directive, stats in self.directive_stats.items():
            total = stats["success"] + stats["failure"]
            if total == 0:
                continue
            rate = stats["success"] / total
            avg_steps = stats["total_steps"] / max(stats["count"], 1)

            color = (0, 255, 0) if rate > 0.7 else (0, 255, 255) if rate > 0.4 else (0, 0, 255)
            text = (f"{directive:20s} | success: {stats['success']:4d} | "
                    f"fail: {stats['failure']:4d} | rate: {rate:.0%} | "
                    f"avg steps: {avg_steps:.0f}")
            cv2.putText(canvas, text, (25, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
            y += 22

        y += 20

        # Progress graph (rolling average over time)
        if len(self.avg_history) > 1:
            cv2.putText(canvas, "Rolling avg completion steps:", (20, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            y += 10

            graph_x, graph_y = 30, y + 10
            graph_w, graph_h = width - 60, 100

            # Draw graph border
            cv2.rectangle(canvas, (graph_x, graph_y),
                          (graph_x + graph_w, graph_y + graph_h), (60, 60, 60), 1)

            # Plot rolling average
            data = self.avg_history[-200:]  # Last 200 points
            if len(data) > 1:
                max_val = max(data) if max(data) > 0 else 1
                points = []
                for i, val in enumerate(data):
                    px = graph_x + int(i * graph_w / max(len(data) - 1, 1))
                    py = graph_y + graph_h - int(val / max_val * graph_h)
                    points.append((px, py))

                for i in range(len(points) - 1):
                    cv2.line(canvas, points[i], points[i + 1], (0, 200, 255), 1)

                # Label max/min
                cv2.putText(canvas, f"{max_val:.0f}", (graph_x + graph_w + 5, graph_y + 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.35, (150, 150, 150), 1)
                cv2.putText(canvas, "0", (graph_x + graph_w + 5, graph_y + graph_h),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.35, (150, 150, 150), 1)

            y += graph_h + 30

        # Previous runs history
        if self.previous_runs:
            cv2.putText(canvas, f"Previous runs: {len(self.previous_runs)}", (20, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 150), 1)
            y += 20
            for run in self.previous_runs[-5:]:
                avg = run.get("avg_completion_steps", 0)
                succ = run.get("success_count", 0)
                cv2.putText(canvas, f"  Run: {succ} completions, avg {avg:.0f} steps",
                            (30, y), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (120, 120, 120), 1)
                y += 18

        # Display
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
        cv2.imshow(window_name, canvas)