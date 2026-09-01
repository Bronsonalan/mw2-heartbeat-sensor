"""Runtime data sources for radar tracks."""

from __future__ import annotations

import os
import threading
import time
from typing import NamedTuple

from ld2450 import _FrameParser
from tracking import Orientation, Track, Tracker


__all__ = ["RadarSource"]


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


