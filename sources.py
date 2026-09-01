"""Runtime data sources for radar tracks."""

from __future__ import annotations

import json
import math
import os
import random
import threading
import time
from dataclasses import dataclass
from typing import NamedTuple

from ld2450 import Target
from ld2450 import _FrameParser
from tracking import Orientation, Track, Tracker


__all__ = ["RadarSource", "DemoSource", "ReplaySource"]


class SourceSnapshot(NamedTuple):
    tracks: list[Track]
    error: str | None
    frames: int


class RadarSource:
    IDLE_TICK = 0.5
    SILENCE_ERROR = 2.0
    RETRY_MIN = 0.5
    RETRY_MAX = 5.0
    READ_TIMEOUT = 0.3
    READ_SIZE = 256

    def __init__(
        self,
        port: str = "/dev/serial0",
        baud: int = 256000,
        orientation: Orientation = Orientation(),
    ):
        self.port = port
        self.baud = baud
        self.tracker = Tracker(orientation=orientation)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._snapshot = SourceSnapshot([], None, 0)
        if not os.path.exists(port):
            self._publish(error=f"serial port not found: {port}")
        self._thread = threading.Thread(target=self._run, name="radar-source", daemon=True)
        self._thread.start()

    def snapshot(self) -> SourceSnapshot:
        with self._lock:
            return SourceSnapshot(list(self._snapshot.tracks), self._snapshot.error, self._snapshot.frames)

    def stop(self) -> None:
        self._stop_event.set()
        thread = getattr(self, "_thread", None)
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)

    def _publish(
        self,
        tracks: list[Track] | None = None,
        error: str | None | object = Ellipsis,
        frames: int | None = None,
    ) -> None:
        with self._lock:
            current = self._snapshot
            self._snapshot = SourceSnapshot(
                list(current.tracks if tracks is None else tracks),
                current.error if error is Ellipsis else error,
                current.frames if frames is None else frames,
            )

    def _wait(self, seconds: float) -> bool:
        return self._stop_event.wait(seconds)

    def _run(self) -> None:
        try:
            import serial  # type: ignore
        except Exception as exc:  # pragma: no cover - depends on host packages
            self._publish(error=f"serial package unavailable: {exc}")
            while not self._wait(self.RETRY_MAX):
                pass
            return

        backoff = self.RETRY_MIN
        while not self._stop_event.is_set():
            if not os.path.exists(self.port):
                self._publish(error=f"serial port not found: {self.port}")
                if self._wait(backoff):
                    break
                backoff = min(self.RETRY_MAX, backoff * 2)
                continue

            try:
                stream = serial.Serial(self.port, baudrate=self.baud, timeout=self.READ_TIMEOUT)
            except Exception as exc:
                self._publish(error=f"serial open failed: {exc}")
                if self._wait(backoff):
                    break
                backoff = min(self.RETRY_MAX, backoff * 2)
                continue

            backoff = self.RETRY_MIN
            parser = _FrameParser()
            last_data = time.monotonic()
            self._publish(error=None)
            try:
                while not self._stop_event.is_set():
                    try:
                        data = stream.read(self.READ_SIZE)
                    except Exception as exc:
                        self._publish(error=f"serial read failed: {exc}")
                        break

                    now = time.monotonic()
                    if data:
                        last_data = now
                        for targets in parser.feed(data):
                            tracks = self.tracker.update(targets, now=now)
                            self._publish(tracks=tracks, error=None, frames=self.snapshot().frames + 1)
                    elif now - last_data >= self.SILENCE_ERROR:
                        self._publish(error=f"sensor silence after {self.SILENCE_ERROR:.1f}s")
            finally:
                close = getattr(stream, "close", None)
                if close is not None:
                    close()


class DemoSource:
    INTERVAL = 0.1
    LONG_PAUSE_WINDOWS = 50

    def __init__(self, scenario: str = "walk", seed: int | None = None, clock=time.monotonic):
        self.scenario = scenario
        self.clock = clock
        self._rng = random.Random(seed)
        self._start = clock()
        self._last_window: int | None = None
        self._frames = 0
        self._phases = [self._rng.random() * math.tau for _ in range(3)]
        self._snapshot = SourceSnapshot([], None, 0)
        if scenario not in {"walk", "cross", "still", "empty", "multi"}:
            self._snapshot = SourceSnapshot([], f"unknown demo scenario: {scenario}", 0)

    def snapshot(self) -> SourceSnapshot:
        if self._snapshot.error is not None:
            return self._snapshot

        now = self.clock()
        window = int((now - self._start) / self.INTERVAL)
        if self._last_window == window:
            return self._snapshot
        if self._last_window is not None and window - self._last_window > self.LONG_PAUSE_WINDOWS:
            window = self._last_window + 1
            self._start = now - (window * self.INTERVAL)

        self._last_window = window
        self._frames += 1
        tracks = self._tracks_for(window, now)
        self._snapshot = SourceSnapshot(tracks, None, self._frames)
        return self._snapshot

    def stop(self) -> None:
        return None

    def _make_track(self, track_id: int, x: float, y: float, speed: float, now: float, age: float) -> Track:
        return Track(track_id, round(x), round(y), round(speed), "live", age, now)

    def _tracks_for(self, window: int, now: float) -> list[Track]:
        t = window * self.INTERVAL
        if self.scenario == "empty":
            return []
        if self.scenario == "still":
            return [self._make_track(1, 0, 1800, 0, now, t)]
        if self.scenario == "walk":
            x = -700 + (window % 80) * (1400 / 79)
            return [self._make_track(1, x, 1800, 18, now, t)]
        if self.scenario == "cross":
            x = -900 + (window % 100) * (1800 / 99)
            return [
                self._make_track(1, x, 1700, 22, now, t),
                self._make_track(2, -x, 2300, -18, now, t),
            ]

        tracks = []
        for index in range(3):
            phase = self._phases[index]
            x = math.sin(t * (0.7 + index * 0.2) + phase) * (450 + index * 130)
            y = 1500 + index * 450 + math.cos(t * 0.5 + phase) * 180
            speed = math.cos(t + phase) * 35
            tracks.append(self._make_track(index + 1, x, y, speed, now, t))
        return tracks


@dataclass
class _ReplayFrame:
    t: float
    seq: int
    kind: str
    items: list[Target] | list[Track]


class ReplaySource:
    MAX_FRAMES_PER_SNAPSHOT = 500
    LOOP_ID_STRIDE = 1_000_000

    def __init__(
        self,
        path: str,
        loop: bool = True,
        realtime: bool = True,
        clock=time.monotonic,
    ):
        self.path = path
        self.loop = loop
        self.realtime = realtime
        self.clock = clock
        self.tracker = Tracker()
        self._frames_data: list[_ReplayFrame] = []
        self._index = 0
        self._loop_index = 0
        self._emitted_frames = 0
        self._clock_start = clock()
        self._snapshot = SourceSnapshot([], None, 0)
        self._load_error: str | None = None
        self._load()
        if self._frames_data:
            first = self._frames_data[0].t
            last = self._frames_data[-1].t
            self._first_t = first
            self._loop_span = max(0.1, last - first) + 0.1
            if self._load_error:
                self._snapshot = SourceSnapshot([], self._load_error, 0)
        else:
            self._first_t = 0.0
            self._loop_span = 0.1
            self._snapshot = SourceSnapshot([], self._load_error or "replay contains no valid frames", 0)

    def snapshot(self) -> SourceSnapshot:
        if not self._frames_data:
            return self._snapshot
        if self.realtime:
            return self._snapshot_realtime()
        return self._snapshot_step()

    def stop(self) -> None:
        return None

    def _load(self) -> None:
        malformed = 0
        nonblank = 0
        last_t: float | None = None
        last_seq: int | None = None

        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                lines = list(handle)
        except OSError as exc:
            self._load_error = f"replay unreadable: {exc}"
            return

        for line_no, line in enumerate(lines, 1):
            text = line.strip()
            if not text:
                continue
            nonblank += 1
            try:
                frame = self._parse_line(text, line_no)
                if last_t is not None and frame.t < last_t:
                    raise ValueError("fixture timestamps must be non-decreasing")
                if last_seq is not None and frame.seq <= last_seq:
                    raise ValueError("fixture seq values must strictly increase")
                last_t = frame.t
                last_seq = frame.seq
                self._frames_data.append(frame)
            except Exception:
                malformed += 1

        if nonblank == 0:
            self._load_error = "replay file is empty"
        elif malformed:
            self._load_error = f"{malformed} malformed replay line(s) skipped"
        if malformed and not self._frames_data:
            self._load_error = f"replay contains no valid frames; {malformed} malformed line(s) skipped"

    def _parse_line(self, text: str, line_no: int) -> _ReplayFrame:
        obj = json.loads(text)
        if not isinstance(obj, dict):
            raise ValueError(f"line {line_no} is not an object")

        t = float(obj["t"])
        seq = int(obj["seq"])
        if not math.isfinite(t):
            raise ValueError(f"line {line_no} has non-finite timestamp")

        has_targets = "targets" in obj
        has_tracks = "tracks" in obj
        if has_targets == has_tracks:
            raise ValueError(f"line {line_no} must contain exactly one of targets or tracks")

        if has_targets:
            items = [self._target_from_obj(item) for item in obj["targets"]]
            return _ReplayFrame(t, seq, "targets", items)

        items = [self._track_from_obj(item, t) for item in obj["tracks"]]
        return _ReplayFrame(t, seq, "tracks", items)

    def _target_from_obj(self, obj: object) -> Target:
        if not isinstance(obj, dict):
            raise ValueError("target entry is not an object")
        return Target(int(obj["x"]), int(obj["y"]), int(obj["speed"]), int(obj["resolution"]))

    def _track_from_obj(self, obj: object, t: float) -> Track:
        if not isinstance(obj, dict):
            raise ValueError("track entry is not an object")
        return Track(
            int(obj["id"]),
            int(obj["x"]),
            int(obj["y"]),
            int(obj["speed"]),
            str(obj.get("state", "live")),
            float(obj.get("age", 0.0)),
            float(obj.get("last_seen", t)),
        )

    def _snapshot_step(self) -> SourceSnapshot:
        frame = self._next_frame()
        if frame is None:
            return self._snapshot
        return self._emit(frame)

    def _snapshot_realtime(self) -> SourceSnapshot:
        elapsed = self.clock() - self._clock_start
        emitted = False
        for _ in range(self.MAX_FRAMES_PER_SNAPSHOT):
            frame = self._peek_frame()
            if frame is None:
                break
            due_loop = self._loop_index + (1 if self._index >= len(self._frames_data) else 0)
            due_at = (frame.t + due_loop * self._loop_span) - self._first_t
            if due_at > elapsed:
                break
            self._next_frame()
            self._emit(frame)
            emitted = True
        if emitted:
            return self._snapshot
        return self._snapshot

    def _peek_frame(self) -> _ReplayFrame | None:
        if self._index < len(self._frames_data):
            return self._frames_data[self._index]
        if not self.loop:
            return None
        return self._frames_data[0]

    def _next_frame(self) -> _ReplayFrame | None:
        if self._index >= len(self._frames_data):
            if not self.loop:
                return None
            self._index = 0
            self._loop_index += 1
        frame = self._frames_data[self._index]
        self._index += 1
        return frame

    def _emit(self, frame: _ReplayFrame) -> SourceSnapshot:
        now = frame.t + self._loop_index * self._loop_span
        if frame.kind == "targets":
            tracks = self.tracker.update(frame.items, now=now)  # type: ignore[arg-type]
        else:
            offset = self._loop_index * self.LOOP_ID_STRIDE
            tracks = [
                Track(
                    track.id + offset,
                    track.x,
                    track.y,
                    track.speed,
                    track.state,
                    track.age + self._loop_index * self._loop_span,
                    track.last_seen + self._loop_index * self._loop_span,
                )
                for track in frame.items  # type: ignore[union-attr]
            ]
        self._emitted_frames += 1
        self._snapshot = SourceSnapshot(tracks, self._load_error, self._emitted_frames)
        return self._snapshot

