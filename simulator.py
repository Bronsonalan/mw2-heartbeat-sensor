"""Demo data sources for the no-hardware HUD path."""

from __future__ import annotations

import math
import random
import time
from typing import Callable

from ld2450 import Target
from sources import SourceSnapshot
from tracking import Orientation, Track, Tracker


__all__ = ["DemoSource", "StaticErrorSource", "Orientation", "SourceSnapshot", "Target", "Track", "Tracker"]

DEMO_RESOLUTION = 360


class DemoSource:
    """Deterministic display-track source for filming and desktop development."""

    scenarios = {"walk", "cross", "still", "empty", "multi"}
    interval = 0.1

    def __init__(
        self,
        scenario: str = "walk",
        seed: int | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.scenario = scenario if scenario in self.scenarios else "walk"
        self.clock = clock
        self.random = random.Random(seed)
        self._started_at = self.clock()
        self._last_window: int | None = None
        self._tracker = Tracker(clock=clock, confirmation_frames=1)
        self._snapshot = SourceSnapshot([], None, 0)
        self._stopped = False

    def snapshot(self) -> SourceSnapshot:
        if self._stopped:
            return self._snapshot
        now = self.clock()
        window = int(max(0.0, now - self._started_at) / self.interval)
        if window == self._last_window:
            return self._snapshot
        self._last_window = window
        elapsed = window * self.interval
        tracks = self._tracker.update(self._targets_for(elapsed), now=now)[:3]
        self._snapshot = SourceSnapshot(tracks=tracks, error=None, frames=self._snapshot.frames + 1)
        return self._snapshot

    def stop(self) -> None:
        self._stopped = True

    def _targets_for(self, elapsed: float) -> list[Target]:
        builders = {
            "walk": self._walk,
            "cross": self._cross,
            "still": self._still,
            "empty": self._empty,
            "multi": self._multi,
        }
        return builders[self.scenario](elapsed)[:3]

    def _target(self, x: float, y: float, speed: float) -> Target:
        return Target(int(round(x)), int(round(y)), int(round(speed)), DEMO_RESOLUTION)

    def _walk(self, elapsed: float) -> list[Target]:
        y = 2900 - 1300 * ((math.sin(elapsed * 0.75) + 1.0) / 2.0)
        x = 420 * math.sin(elapsed * 1.1)
        speed = -28 if math.cos(elapsed * 0.75) > 0 else 18
        return [self._target(x, y, speed)]

    def _cross(self, elapsed: float) -> list[Target]:
        phase = (elapsed * 0.22) % 2.0
        x = -2600 + 5200 * (phase if phase <= 1.0 else 2.0 - phase)
        return [self._target(x, 2300 + 140 * math.sin(elapsed), 12)]

    def _still(self, elapsed: float) -> list[Target]:
        wobble = 18 * math.sin(elapsed * 0.6)
        return [self._target(wobble, 1900, 0)]

    def _empty(self, elapsed: float) -> list[Target]:
        return []

    def _multi(self, elapsed: float) -> list[Target]:
        return [
            self._target(-900 + 260 * math.sin(elapsed * 1.1), 1750 + 160 * math.cos(elapsed), -18),
            self._target(1150 * math.sin(elapsed * 0.58), 3150 + 240 * math.sin(elapsed * 0.9), 9),
            self._target(1750 * math.sin(elapsed * 0.32 + 1.2), 4550 + 260 * math.cos(elapsed * 0.7), -6),
        ]


class StaticErrorSource:
    def __init__(self, message: str) -> None:
        self._snapshot = SourceSnapshot([], message, 0)

    def snapshot(self) -> SourceSnapshot:
        return self._snapshot

    def stop(self) -> None:
        return None
