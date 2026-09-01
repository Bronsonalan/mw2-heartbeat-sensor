"""Nearest-neighbor contact tracking for parsed radar targets."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Iterable, NamedTuple

from ld2450 import Target


ASSOCIATION_GATE_MM = 600
POSITION_ALPHA = 0.4
SPEED_ALPHA = 0.25
CONFIRMATION_FRAMES = 3
GRACE_SECONDS = 0.8


class Orientation(NamedTuple):
    swap_xy: bool = False
    invert_x: bool = False


class Track(NamedTuple):
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
        if self.x == 0 and self.y == 0:
            return 0.0
        return math.degrees(math.atan2(self.x, self.y))

    @property
    def approaching(self) -> bool:
        return self.speed < 0


@dataclass
class _TrackState:
    id: int
    x: float
    y: float
    speed: float
    created: float
    last_seen: float
    hits: int = 1
    confirmed: bool = False
    matched_this_frame: bool = True

    def as_track(self, now: float) -> Track:
        if self.matched_this_frame:
            state = "live" if self.confirmed else "acquiring"
        else:
            state = "fading"
        return Track(
            self.id,
            round(self.x),
            round(self.y),
            round(self.speed),
            state,
            now - self.created,
            self.last_seen,
        )


def apply_orientation(target: Target, orientation: Orientation) -> Target:
    x = target.x
    y = target.y
    if orientation.swap_xy:
        x, y = y, x
    if orientation.invert_x:
        x = -x
    return Target(x, y, target.speed, target.resolution)


class Tracker:
    def __init__(
        self,
        orientation: Orientation = Orientation(),
        clock=time.monotonic,
        association_gate: int = ASSOCIATION_GATE_MM,
        position_alpha: float = POSITION_ALPHA,
        speed_alpha: float = SPEED_ALPHA,
        confirmation_frames: int = CONFIRMATION_FRAMES,
        grace_seconds: float = GRACE_SECONDS,
    ):
        self.orientation = orientation
        self.clock = clock
        self.association_gate = association_gate
        self.position_alpha = position_alpha
        self.speed_alpha = speed_alpha
        self.confirmation_frames = confirmation_frames
        self.grace_seconds = grace_seconds
        self._next_id = 1
        self._tracks: list[_TrackState] = []

    def update(self, targets: Iterable[Target], now: float | None = None) -> list[Track]:
        now = self.clock() if now is None else now
        oriented = [apply_orientation(target, self.orientation) for target in targets]

        for track in self._tracks:
            track.matched_this_frame = False

        pairs: list[tuple[float, int, int]] = []
        for track_index, track in enumerate(self._tracks):
            for target_index, target in enumerate(oriented):
                distance = math.hypot(track.x - target.x, track.y - target.y)
                if distance <= self.association_gate:
                    pairs.append((distance, track_index, target_index))

        pairs.sort(key=lambda item: item[0])
        matched_tracks: set[int] = set()
        matched_targets: set[int] = set()

        for _, track_index, target_index in pairs:
            if track_index in matched_tracks or target_index in matched_targets:
                continue
            track = self._tracks[track_index]
            target = oriented[target_index]
            track.x = track.x + self.position_alpha * (target.x - track.x)
            track.y = track.y + self.position_alpha * (target.y - track.y)
            track.speed = track.speed + self.speed_alpha * (target.speed - track.speed)
            track.last_seen = now
            track.hits += 1
            if track.hits >= self.confirmation_frames:
                track.confirmed = True
            track.matched_this_frame = True
            matched_tracks.add(track_index)
            matched_targets.add(target_index)

        for target_index, target in enumerate(oriented):
            if target_index in matched_targets:
                continue
            self._tracks.append(
                _TrackState(
                    id=self._next_id,
                    x=float(target.x),
                    y=float(target.y),
                    speed=float(target.speed),
                    created=now,
                    last_seen=now,
                    confirmed=self.confirmation_frames <= 1,
                )
            )
            self._next_id += 1

        self._tracks = [
            track
            for track in self._tracks
            if track.matched_this_frame or now - track.last_seen <= self.grace_seconds
        ]

        return [track.as_track(now) for track in sorted(self._tracks, key=lambda item: item.id)]

