"""Replay source for newline-delimited JSON radar fixtures."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import time
from typing import Callable, Iterable

from ld2450 import Target
from sources import SourceSnapshot
from tracking import Orientation, Track, Tracker


MAX_FRAMES_PER_SNAPSHOT = 500


@dataclass(frozen=True)
class _Record:
    t: float
    seq: int
    kind: str
    items: list[Target] | list[Track]


class ReplaySource:
    def __init__(
        self,
        path: str,
        loop: bool = True,
        realtime: bool = True,
        clock: Callable[[], float] = time.monotonic,
        orientation: Orientation = Orientation(),
    ) -> None:
        self.path = path
        self.loop = loop
        self.realtime = realtime
        self.clock = clock
        self.orientation = orientation
        self._records: list[_Record] = []
        self._malformed = 0
        self._load_error: str | None = None
        self._index = 0
        self._loop_count = 0
        self._tracker = Tracker(orientation=orientation, clock=clock)
        self._snapshot = SourceSnapshot([], None, 0)
        self._real_started_at: float | None = None
        self._stopped = False
        self._load()
        if self._records:
            first_t = self._records[0].t
            last_t = self._records[-1].t
            self._loop_duration = max(0.1, last_t - first_t + 0.1)
        else:
            self._loop_duration = 0.1
            self._snapshot = SourceSnapshot([], self._load_error, 0)

    def snapshot(self) -> SourceSnapshot:
        if self._stopped or not self._records:
            return self._snapshot

        if self.realtime:
            self._snapshot_realtime()
        else:
            self._snapshot_step()
        return self._snapshot

    def stop(self) -> None:
        self._stopped = True

    def _snapshot_realtime(self) -> None:
        now = self.clock()
        if self._real_started_at is None:
            self._real_started_at = now
        due_t = self._records[0].t + max(0.0, now - self._real_started_at)
        consumed = 0
        while consumed < MAX_FRAMES_PER_SNAPSHOT and self._records:
            record = self._records[self._index]
            record_t = record.t + self._loop_count * self._loop_duration
            if record_t > due_t:
                break
            self._consume(record, record_t)
            consumed += 1
            if not self._advance_index():
                break

    def _snapshot_step(self) -> None:
        if not self._records:
            return
        record = self._records[self._index]
        record_t = record.t + self._loop_count * self._loop_duration
        self._consume(record, record_t)
        self._advance_index()

    def _advance_index(self) -> bool:
        self._index += 1
        if self._index < len(self._records):
            return True
        if not self.loop:
            self._index = len(self._records) - 1
            return False
        self._index = 0
        self._loop_count += 1
        return True

    def _consume(self, record: _Record, playback_t: float) -> None:
        if record.kind == "targets":
            tracks = self._tracker.update(record.items, now=playback_t)  # type: ignore[arg-type]
        else:
            tracks = self._offset_tracks(record.items)  # type: ignore[arg-type]
        self._snapshot = SourceSnapshot(
            tracks=list(tracks),
            error=self._status_error(),
            frames=self._snapshot.frames + 1,
        )

    def _offset_tracks(self, tracks: Iterable[Track]) -> list[Track]:
        if self._loop_count == 0:
            return list(tracks)
        offset = self._loop_count * (self._max_track_id() + 1)
        return [
            Track(
                id=track.id + offset,
                x=track.x,
                y=track.y,
                speed=track.speed,
                state=track.state,
                age=track.age,
                last_seen=track.last_seen,
            )
            for track in tracks
        ]

    def _max_track_id(self) -> int:
        max_id = 0
        for record in self._records:
            if record.kind != "tracks":
                continue
            for track in record.items:  # type: ignore[union-attr]
                max_id = max(max_id, track.id)
        return max_id

    def _status_error(self) -> str | None:
        if self._malformed:
            return f"replay skipped {self._malformed} malformed line(s)"
        return self._load_error

    def _load(self) -> None:
        fixture = Path(self.path)
        try:
            text = fixture.read_text(encoding="utf-8")
        except OSError as exc:
            self._load_error = f"unable to read replay fixture: {exc}"
            return

        saw_line = False
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            saw_line = True
            try:
                record = self._parse_line(line)
            except ValueError:
                self._malformed += 1
                continue
            if record is None:
                self._malformed += 1
                continue
            self._records.append(record)

        if not saw_line:
            self._load_error = "replay fixture is empty"
        elif not self._records:
            self._load_error = "replay fixture has no valid frames"

    def _parse_line(self, line: str) -> _Record | None:
        obj = json.loads(line, parse_constant=_reject_json_constant)
        if not isinstance(obj, dict):
            return None
        if ("targets" in obj) == ("tracks" in obj):
            return None
        t = _finite_float(obj.get("t"))
        seq = _integer(obj.get("seq"))
        if t is None or seq is None:
            return None
        if "targets" in obj:
            targets = self._parse_targets(obj.get("targets"))
            if targets is None:
                return None
            return _Record(t=t, seq=seq, kind="targets", items=targets)
        tracks = self._parse_tracks(obj.get("tracks"))
        if tracks is None:
            return None
        return _Record(t=t, seq=seq, kind="tracks", items=tracks)

    def _parse_targets(self, value: object) -> list[Target] | None:
        if not isinstance(value, list):
            return None
        targets: list[Target] = []
        for item in value:
            if not isinstance(item, dict):
                return None
            x = _integer(item.get("x"))
            y = _integer(item.get("y"))
            speed = _integer(item.get("speed"))
            resolution = _integer(item.get("resolution"))
            if None in (x, y, speed, resolution):
                return None
            targets.append(Target(x, y, speed, resolution))  # type: ignore[arg-type]
        return targets

    def _parse_tracks(self, value: object) -> list[Track] | None:
        if not isinstance(value, list):
            return None
        tracks: list[Track] = []
        for item in value:
            if not isinstance(item, dict):
                return None
            ident = _integer(item.get("id"))
            x = _integer(item.get("x"))
            y = _integer(item.get("y"))
            speed = _integer(item.get("speed"))
            state = item.get("state")
            age = _finite_float(item.get("age", 0.0))
            last_seen = _finite_float(item.get("last_seen", 0.0))
            if None in (ident, x, y, speed, age, last_seen) or not isinstance(state, str):
                return None
            tracks.append(
                Track(
                    id=ident,  # type: ignore[arg-type]
                    x=x,  # type: ignore[arg-type]
                    y=y,  # type: ignore[arg-type]
                    speed=speed,  # type: ignore[arg-type]
                    state=state,
                    age=age,  # type: ignore[arg-type]
                    last_seen=last_seen,  # type: ignore[arg-type]
                )
            )
        return tracks


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant {value}")


def _finite_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    if not math.isfinite(numeric):
        return None
    return numeric


def _integer(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return int(value)
