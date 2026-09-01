"""Demo data and minimal display-track models for the no-hardware HUD path."""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
import time
from typing import Callable, Iterable


@dataclass(frozen=True)
class Target:
    x: int
    y: int
    speed: int
    resolution: int

    @property
    def distance(self) -> float:
        return math.hypot(self.x, self.y)

    @property
    def angle(self) -> float:
        return math.degrees(math.atan2(self.x, self.y))

    @property
    def approaching(self) -> bool:
        return self.speed < 0


@dataclass(frozen=True)
class Track:
    id: int
    x: int
    y: int
    speed: int
    state: str
    age: float
    last_seen: float

    @property
    def distance(self) -> float:
        return math.hypot(self.x, self.y)

    @property
    def angle(self) -> float:
        return math.degrees(math.atan2(self.x, self.y))

    @property
    def approaching(self) -> bool:
        return self.speed < 0


@dataclass(frozen=True)
class SourceSnapshot:
    tracks: list[Track]
    error: str | None
    frames: int


class Orientation:
    def __init__(self, swap_xy: bool = False, invert_x: bool = False) -> None:
        self.swap_xy = bool(swap_xy)
        self.invert_x = bool(invert_x)

    def apply(self, target: Target) -> Target:
        x, y = target.x, target.y
        if self.swap_xy:
            x, y = y, x
        if self.invert_x:
            x = -x
        return Target(int(x), int(y), int(target.speed), int(target.resolution))


@dataclass
class _Tracked:
    id: int
    x: float
    y: float
    speed: float
    created_at: float
    last_seen: float
    hits: int = 1
    confirmed: bool = False
    missed: bool = False


class SimpleTracker:
    """Small contract-compatible tracker used until the hardware tracker lands."""

    gate_mm = 600.0
    position_alpha = 0.4
    speed_alpha = 0.25
    confirm_frames = 3
    grace_seconds = 0.8

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._tracks: list[_Tracked] = []
        self._next_id = 1

    def update(
        self, targets: Iterable[Target], timestamp: float | None = None
    ) -> list[Track]:
        now = self.clock() if timestamp is None else float(timestamp)
        raw_targets = list(targets)

        pairs: list[tuple[float, int, int]] = []
        for track_index, track in enumerate(self._tracks):
            for target_index, target in enumerate(raw_targets):
                distance = math.hypot(track.x - target.x, track.y - target.y)
                if distance <= self.gate_mm:
                    pairs.append((distance, track_index, target_index))
        pairs.sort(key=lambda item: item[0])

        matched_tracks: set[int] = set()
        matched_targets: set[int] = set()
        for _, track_index, target_index in pairs:
            if track_index in matched_tracks or target_index in matched_targets:
                continue
            track = self._tracks[track_index]
            target = raw_targets[target_index]
            track.x = (1.0 - self.position_alpha) * track.x + self.position_alpha * target.x
            track.y = (1.0 - self.position_alpha) * track.y + self.position_alpha * target.y
            track.speed = (1.0 - self.speed_alpha) * track.speed + self.speed_alpha * target.speed
            track.last_seen = now
            track.hits += 1
            if track.hits >= self.confirm_frames:
                track.confirmed = True
            track.missed = False
            matched_tracks.add(track_index)
            matched_targets.add(target_index)

        for target_index, target in enumerate(raw_targets):
            if target_index in matched_targets:
                continue
            self._tracks.append(
                _Tracked(
                    id=self._next_id,
                    x=float(target.x),
                    y=float(target.y),
                    speed=float(target.speed),
                    created_at=now,
                    last_seen=now,
                )
            )
            self._next_id += 1

        survivors: list[_Tracked] = []
        for track_index, track in enumerate(self._tracks):
            if track_index not in matched_tracks and track.last_seen < now:
                track.missed = True
            if now - track.last_seen <= self.grace_seconds:
                survivors.append(track)
        self._tracks = survivors
        return [self._display_track(track, now) for track in self._tracks]

    def _display_track(self, track: _Tracked, now: float) -> Track:
        if track.missed:
            state = "fading"
        elif track.confirmed:
            state = "live"
        else:
            state = "acquiring"
        return Track(
            id=track.id,
            x=int(round(track.x)),
            y=int(round(track.y)),
            speed=int(round(track.speed)),
            state=state,
            age=max(0.0, now - track.created_at),
            last_seen=track.last_seen,
        )


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
        tracks = self._tracks_for(elapsed, now)
        self._snapshot = SourceSnapshot(tracks=tracks, error=None, frames=self._snapshot.frames + 1)
        return self._snapshot

    def stop(self) -> None:
        self._stopped = True

    def _tracks_for(self, elapsed: float, now: float) -> list[Track]:
        builders = {
            "walk": self._walk,
            "cross": self._cross,
            "still": self._still,
            "empty": self._empty,
            "multi": self._multi,
        }
        return builders[self.scenario](elapsed, now)[:3]

    def _track(self, ident: int, x: float, y: float, speed: float, now: float) -> Track:
        return Track(ident, int(round(x)), int(round(y)), int(round(speed)), "live", now - self._started_at, now)

    def _walk(self, elapsed: float, now: float) -> list[Track]:
        y = 2900 - 1300 * ((math.sin(elapsed * 0.75) + 1.0) / 2.0)
        x = 420 * math.sin(elapsed * 1.1)
        speed = -28 if math.cos(elapsed * 0.75) > 0 else 18
        return [self._track(1, x, y, speed, now)]

    def _cross(self, elapsed: float, now: float) -> list[Track]:
        phase = (elapsed * 0.22) % 2.0
        x = -2600 + 5200 * (phase if phase <= 1.0 else 2.0 - phase)
        return [self._track(1, x, 2300 + 140 * math.sin(elapsed), 12, now)]

    def _still(self, elapsed: float, now: float) -> list[Track]:
        wobble = 18 * math.sin(elapsed * 0.6)
        return [self._track(1, wobble, 1900, 0, now)]

    def _empty(self, elapsed: float, now: float) -> list[Track]:
        return []

    def _multi(self, elapsed: float, now: float) -> list[Track]:
        return [
            self._track(1, -900 + 260 * math.sin(elapsed * 1.1), 1750 + 160 * math.cos(elapsed), -18, now),
            self._track(2, 1150 * math.sin(elapsed * 0.58), 3150 + 240 * math.sin(elapsed * 0.9), 9, now),
            self._track(3, 1750 * math.sin(elapsed * 0.32 + 1.2), 4550 + 260 * math.cos(elapsed * 0.7), -6, now),
        ]


class StaticErrorSource:
    def __init__(self, message: str) -> None:
        self._snapshot = SourceSnapshot([], message, 0)

    def snapshot(self) -> SourceSnapshot:
        return self._snapshot

    def stop(self) -> None:
        return None
