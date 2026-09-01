"""HLK-LD2450 frame parsing utilities."""

from __future__ import annotations

import math
from typing import NamedTuple


__all__ = ["Target", "parse_frame"]


_HEADER = bytes.fromhex("AA FF 03 00")
_TAIL = bytes.fromhex("55 CC")
_FRAME_LENGTH = 30
_SLOT_COUNT = 3
_SLOT_LENGTH = 8
_PAYLOAD_LENGTH = _SLOT_COUNT * _SLOT_LENGTH


class Target(NamedTuple):
    x: int
    y: int
    speed: int
    resolution: int

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


def _decode_sign_flag(lo: int, hi: int) -> int:
    """Decode the LD2450 sign-flag integer format."""

    if not 0 <= lo <= 0xFF or not 0 <= hi <= 0xFF:
        raise ValueError("sign-flag bytes must be in range 0..255")
    value = ((hi & 0x7F) << 8) | lo
    if hi & 0x80:
        return value
    return -value


def _decode_slot(slot: bytes) -> Target | None:
    if len(slot) != _SLOT_LENGTH:
        raise ValueError("LD2450 target slot must be 8 bytes")
    if slot == b"\x00" * _SLOT_LENGTH:
        return None

    x = _decode_sign_flag(slot[0], slot[1])
    y = _decode_sign_flag(slot[2], slot[3])
    speed = _decode_sign_flag(slot[4], slot[5])
    resolution = slot[6] | (slot[7] << 8)
    return Target(x, y, speed, resolution)


def parse_frame(frame: bytes | bytearray | memoryview) -> list[Target]:
    """Parse one complete 30-byte LD2450 frame.

    Invalid framing raises ValueError. Healthy empty frames return an empty list.
    """

    data = bytes(frame)
    if len(data) != _FRAME_LENGTH:
        raise ValueError(f"LD2450 frame must be {_FRAME_LENGTH} bytes")
    if not data.startswith(_HEADER):
        raise ValueError("LD2450 frame header mismatch")
    if not data.endswith(_TAIL):
        raise ValueError("LD2450 frame tail mismatch")

    payload = data[len(_HEADER) : -len(_TAIL)]
    if len(payload) != _PAYLOAD_LENGTH:
        raise ValueError("LD2450 payload length mismatch")

    targets: list[Target] = []
    for index in range(_SLOT_COUNT):
        start = index * _SLOT_LENGTH
        target = _decode_slot(payload[start : start + _SLOT_LENGTH])
        if target is not None:
            targets.append(target)
    return targets


class _FrameParser:
    """Incrementally extract valid LD2450 frames from arbitrary serial chunks."""

    def __init__(self, max_buffer: int = 4096):
        self._buffer = bytearray()
        self._max_buffer = max_buffer

    def feed(self, data: bytes | bytearray | memoryview) -> list[list[Target]]:
        if data:
            self._buffer.extend(data)
        frames: list[list[Target]] = []

        while True:
            header_at = self._buffer.find(_HEADER)
            if header_at < 0:
                keep = max(0, len(_HEADER) - 1)
                if len(self._buffer) > keep:
                    del self._buffer[:-keep]
                break
            if header_at:
                del self._buffer[:header_at]
            if len(self._buffer) < _FRAME_LENGTH:
                break

            candidate = bytes(self._buffer[:_FRAME_LENGTH])
            if candidate.endswith(_TAIL):
                frames.append(parse_frame(candidate))
                del self._buffer[:_FRAME_LENGTH]
                continue

            # Bad tail after a plausible header: advance one byte and resync.
            del self._buffer[0]

        if len(self._buffer) > self._max_buffer:
            del self._buffer[: -self._max_buffer]
        return frames

