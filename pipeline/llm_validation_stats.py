"""Per-model LLM validation failure counters (compare extraction quality)."""

from __future__ import annotations

import csv
import threading
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class _ModelBucket:
    ok: int = 0
    fail: int = 0

    @property
    def total(self) -> int:
        return self.ok + self.fail

    @property
    def failure_rate(self) -> float:
        return (self.fail / self.total) if self.total else 0.0


@dataclass
class ValidationStatsRegistry:
    """Thread-safe counters keyed by model id."""

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _by_model: dict[str, _ModelBucket] = field(default_factory=dict)

    def record(self, model: str, *, success: bool) -> None:
        key = (model or "unknown").strip() or "unknown"
        with self._lock:
            bucket = self._by_model.setdefault(key, _ModelBucket())
            if success:
                bucket.ok += 1
            else:
                bucket.fail += 1

    def snapshot(self) -> dict[str, dict[str, float | int]]:
        with self._lock:
            return {
                model: {
                    "ok": bucket.ok,
                    "fail": bucket.fail,
                    "total": bucket.total,
                    "failure_rate": round(bucket.failure_rate, 4),
                }
                for model, bucket in sorted(self._by_model.items())
            }

    def reset(self) -> None:
        with self._lock:
            self._by_model.clear()

    def write_csv(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = self.snapshot()
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["model", "ok", "fail", "total", "failure_rate"],
            )
            writer.writeheader()
            for model, stats in rows.items():
                writer.writerow({"model": model, **stats})
        return path

    def write_markdown(self, path: Path, *, title: str = "LLM validation stats") -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = self.snapshot()
        lines = [
            f"# {title}",
            "",
            "| model | ok | fail | total | failure_rate |",
            "|---|---:|---:|---:|---:|",
        ]
        if not rows:
            lines.append("| _(none)_ | 0 | 0 | 0 | 0 |")
        else:
            for model, stats in rows.items():
                lines.append(
                    f"| {model} | {stats['ok']} | {stats['fail']} | "
                    f"{stats['total']} | {stats['failure_rate']:.2%} |"
                )
        lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")
        return path


# Process-wide registry used by analyse / comparative tests.
VALIDATION_STATS = ValidationStatsRegistry()
