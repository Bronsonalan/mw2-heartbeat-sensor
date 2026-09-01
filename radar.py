"""MW2-style heartbeat sensor HUD launcher.

The replay and demo sources deliberately avoid live hardware imports so this
module can run on a laptop with no radar attached.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import struct
import sys
import time
import zlib
from typing import Any, Iterable, NamedTuple

from replay import ReplaySource
from simulator import DemoSource, StaticErrorSource
from sources import RadarSource, SourceSnapshot
from tracking import Orientation, Track


BASE_SIZE = (640, 480)
MAX_RANGE_MM = 6000
SENSOR_HALF_CONE_DEG = 60.0
SWEEP_TRAVEL_SECONDS = 0.85
SWEEP_DWELL_SECONDS = 0.35
SWEEP_CYCLE_SECONDS = SWEEP_TRAVEL_SECONDS + SWEEP_DWELL_SECONDS
PHOSPHOR_TRAVEL_FRAMES = 26
PHOSPHOR_DWELL_INDEX = 26
REVEAL_STEPS = (1.0, 0.75, 0.50, 0.28, 0.12)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

PALETTE = {
    "base": (0x04, 0x10, 0x0A),
    "wash": (0x14, 0x48, 0x2C),
    "grid": (0x3F, 0xE0, 0x7A),
    "chevron": (0x9B, 0xFF, 0xC6),
    "sweep": (0x78, 0xFF, 0xAA),
    "edge": (0xCF, 0xFF, 0xE0),
    "void": (0x04, 0x10, 0x0A),
    "halo": (0xFF, 0x2B, 0x2B),
    "mid": (0xFF, 0x5A, 0x4D),
    "core": (0xFF, 0xF4, 0xF2),
    "pill_fill": (0x04, 0x14, 0x0C),
    "pill_text": (0xB6, 0xFF, 0xD2),
}
BACKGROUND = tuple(
    int(PALETTE["base"][index] + (PALETTE["wash"][index] - PALETTE["base"][index]) * 0.15)
    for index in range(3)
)
PHOSPHOR_HALO = PALETTE["halo"]
PHOSPHOR_MID = PALETTE["mid"]
PHOSPHOR_CORE = PALETTE["core"]
PHOSPHOR_VOID = PALETTE["void"]


FONT = {
    " ": ("00000", "00000", "00000", "00000", "00000", "00000", "00000"),
    "-": ("00000", "00000", "00000", "11110", "00000", "00000", "00000"),
    ".": ("00000", "00000", "00000", "00000", "00000", "01100", "01100"),
    ">": ("10000", "01000", "00100", "00010", "00100", "01000", "10000"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("10010", "10010", "10010", "11111", "00010", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00010", "11100"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01111", "10000", "10000", "10000", "10000", "10000", "01111"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01111", "10000", "10000", "10011", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("01110", "00100", "00100", "00100", "00100", "00100", "01110"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "m": ("00000", "00000", "11010", "10101", "10101", "10101", "10101"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
}
SCANLINE_DARKEN_TABLE = bytes(int(value * 0.68) for value in range(256))


class PhosphorGeometry(NamedTuple):
    width: int
    height: int
    origin: tuple[int, int]
    radius: int


class Canvas:
    def __init__(
        self,
        width: int,
        height: int,
        color: tuple[int, int, int],
        pixels: bytes | bytearray | None = None,
    ) -> None:
        self.width = width
        self.height = height
        if pixels is None:
            self.pixels = bytearray(color * (width * height))
        else:
            expected = width * height * 3
            if len(pixels) != expected:
                raise ValueError(f"canvas pixel buffer must be {expected} bytes")
            self.pixels = bytearray(pixels)

    @classmethod
    def from_pixels(cls, width: int, height: int, pixels: bytes | bytearray) -> "Canvas":
        return cls(width, height, BACKGROUND, pixels=pixels)

    def blend_pixel(self, x: int, y: int, color: tuple[int, int, int], alpha: float = 1.0) -> None:
        if x < 0 or y < 0 or x >= self.width or y >= self.height or alpha <= 0.0:
            return
        alpha = min(1.0, alpha)
        offset = (y * self.width + x) * 3
        for channel, value in enumerate(color):
            base = self.pixels[offset + channel]
            self.pixels[offset + channel] = int(base + (value - base) * alpha)

    def fill_rect(self, x: int, y: int, w: int, h: int, color: tuple[int, int, int], alpha: float = 1.0) -> None:
        for yy in range(max(0, y), min(self.height, y + h)):
            for xx in range(max(0, x), min(self.width, x + w)):
                self.blend_pixel(xx, yy, color, alpha)

    def draw_line(
        self,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        color: tuple[int, int, int],
        alpha: float = 1.0,
        thickness: int = 1,
    ) -> None:
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        x, y = x0, y0
        while True:
            self._stamp(x, y, max(1, thickness), color, alpha)
            if x == x1 and y == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x += sx
            if e2 <= dx:
                err += dx
                y += sy

    def draw_circle(
        self,
        cx: int,
        cy: int,
        radius: int,
        color: tuple[int, int, int],
        alpha: float = 1.0,
        fill: bool = False,
    ) -> None:
        if radius <= 0:
            self.blend_pixel(cx, cy, color, alpha)
            return
        for y in range(cy - radius, cy + radius + 1):
            for x in range(cx - radius, cx + radius + 1):
                d2 = (x - cx) * (x - cx) + (y - cy) * (y - cy)
                if fill:
                    if d2 <= radius * radius:
                        self.blend_pixel(x, y, color, alpha)
                elif abs(math.sqrt(d2) - radius) <= 0.75:
                    self.blend_pixel(x, y, color, alpha)

    def _stamp(self, cx: int, cy: int, thickness: int, color: tuple[int, int, int], alpha: float) -> None:
        radius = max(0, thickness // 2)
        for y in range(cy - radius, cy + radius + 1):
            for x in range(cx - radius, cx + radius + 1):
                self.blend_pixel(x, y, color, alpha)

    def darken_scanlines(self) -> None:
        stride = self.width * 3
        for y in range(1, self.height, 3):
            start = y * stride
            end = start + stride
            self.pixels[start:end] = self.pixels[start:end].translate(SCANLINE_DARKEN_TABLE)

    def write_png(self, path: str) -> None:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        rows = []
        stride = self.width * 3
        for y in range(self.height):
            start = y * stride
            rows.append(b"\x00" + bytes(self.pixels[start : start + stride]))
        raw = b"".join(rows)
        with output.open("wb") as handle:
            handle.write(b"\x89PNG\r\n\x1a\n")
            _write_chunk(handle, b"IHDR", struct.pack("!IIBBBBB", self.width, self.height, 8, 2, 0, 0, 0))
            _write_chunk(handle, b"IDAT", zlib.compress(raw, 9))
            _write_chunk(handle, b"IEND", b"")


class PhosphorRenderer:
    def __init__(
        self,
        size: tuple[int, int] = BASE_SIZE,
        sweep_reveal: bool = True,
        scanlines: bool = True,
        assets_dir: str = "assets/phosphor",
    ) -> None:
        self.size = size
        self.sweep_reveal = sweep_reveal
        self.scanlines = scanlines
        self.assets_ok, self.asset_errors = validate_phosphor_assets(assets_dir)
        self._asset_frames: list[bytes] | None = None
        if self.assets_ok and self.size == BASE_SIZE:
            try:
                self._asset_frames = _load_phosphor_asset_frames(assets_dir)
            except (OSError, ValueError, zlib.error) as exc:
                self.assets_ok = False
                self.asset_errors.append(f"unable to load phosphor assets: {exc}")
        self._last_sweep_distance: float | None = None
        self._revealed_at: dict[int, float] = {}

    def render(
        self,
        snapshot: SourceSnapshot,
        now: float,
        show_fps: bool = False,
        fps_value: float | None = None,
    ) -> Canvas:
        width, height = self.size
        geom = _phosphor_geometry(self.size)
        origin = geom.origin
        radius = geom.radius
        previous_sweep = self._last_sweep_distance
        asset_frame, sweep_distance = self._asset_frame(now)
        if asset_frame is not None:
            canvas = Canvas.from_pixels(width, height, asset_frame)
            self._last_sweep_distance = sweep_distance
        else:
            canvas = Canvas(width, height, BACKGROUND)
            sweep_distance = self._draw_face(canvas, origin, radius, now)
        tracks = list(_valid_tracks(snapshot.tracks))
        self._draw_contacts(canvas, tracks, origin, radius, previous_sweep, sweep_distance, now)
        self._draw_pill(canvas, tracks)
        if snapshot.error:
            self._draw_offline(canvas, snapshot.error)
        if show_fps:
            label = "FPS --" if fps_value is None else f"FPS {int(round(fps_value)):02d}"
            draw_text(canvas, label, width - text_width(label, 2) - 10, height - 24, 2, PALETTE["pill_text"], 0.82)
        if self.scanlines:
            canvas.darken_scanlines()
        return canvas

    def _asset_frame(self, now: float) -> tuple[bytes | None, float]:
        if self._asset_frames is None:
            return None, 0.0
        _, sweep_distance, frame_index = _sweep_state(now)
        return self._asset_frames[frame_index], sweep_distance

    def _draw_face(self, canvas: Canvas, origin: tuple[int, int], radius: int, now: float) -> float:
        ox, oy = origin
        for meters in range(1, 7):
            r = int(radius * meters / 6)
            self._draw_arc(canvas, origin, r, -90, 90, PALETTE["grid"], 0.28 if meters < 6 else 0.48, 1)
        for deg in range(-90, 91, 15):
            end = _polar(origin, radius, deg)
            alpha = 0.38 if deg % 30 == 0 else 0.20
            canvas.draw_line(ox, oy, end[0], end[1], PALETTE["grid"], alpha, 1)
        for deg in (-60, 60):
            end = _polar(origin, radius, deg)
            canvas.draw_line(ox, oy, end[0], end[1], PALETTE["chevron"], 0.40, 1)

        sweep_fraction, sweep_distance, _ = _sweep_state(now)
        sweep_r = int(radius * sweep_fraction)
        for offset, alpha in ((0, 0.42), (-5, 0.22), (-10, 0.13), (-16, 0.08)):
            r = max(0, sweep_r + offset)
            self._draw_arc(canvas, origin, r, -90, 90, PALETTE["sweep"], alpha, 2 if offset == 0 else 1)
        self._last_sweep_distance = sweep_distance
        canvas.draw_line(ox - radius, oy, ox + radius, oy, PALETTE["edge"], 0.32, 1)
        return sweep_distance

    def _draw_arc(
        self,
        canvas: Canvas,
        origin: tuple[int, int],
        radius: int,
        start_deg: int,
        end_deg: int,
        color: tuple[int, int, int],
        alpha: float,
        thickness: int,
    ) -> None:
        previous: tuple[int, int] | None = None
        for deg in range(start_deg, end_deg + 1, 2):
            point = _polar(origin, radius, deg)
            if previous is not None:
                canvas.draw_line(previous[0], previous[1], point[0], point[1], color, alpha, thickness)
            previous = point

    def _draw_contacts(
        self,
        canvas: Canvas,
        tracks: list[Track],
        origin: tuple[int, int],
        radius: int,
        previous_sweep_distance: float | None,
        sweep_distance: float,
        now: float,
    ) -> None:
        previous_sweep = 0.0 if previous_sweep_distance is None else previous_sweep_distance
        if sweep_distance < previous_sweep:
            previous_sweep = 0.0
        for track in tracks:
            distance = track.distance
            if distance > MAX_RANGE_MM:
                continue
            brightness = self._contact_brightness(track, previous_sweep, sweep_distance, now)
            if brightness <= 0.0:
                continue
            bearing = max(-SENSOR_HALF_CONE_DEG, min(SENSOR_HALF_CONE_DEG, track.angle))
            r = radius * distance / MAX_RANGE_MM
            x, y = _polar_float(origin, r, bearing)
            self._draw_pip(canvas, x, y, brightness)

    def _contact_brightness(
        self,
        track: Track,
        previous_sweep: float,
        sweep_distance: float,
        now: float,
    ) -> float:
        state = track.state if track.state in {"acquiring", "live", "fading"} else "live"
        if self.sweep_reveal:
            crossed = previous_sweep <= track.distance <= sweep_distance
            if crossed:
                self._revealed_at[track.id] = now
            revealed_at = self._revealed_at.get(track.id)
            if revealed_at is None:
                return 0.0
            age = max(0.0, now - revealed_at)
            step = min(len(REVEAL_STEPS) - 1, int((age / SWEEP_CYCLE_SECONDS) * len(REVEAL_STEPS)))
            brightness = REVEAL_STEPS[step]
        else:
            brightness = 1.0
        if state == "acquiring":
            brightness *= 0.63
        elif state == "fading":
            faded_for = max(0.0, now - track.last_seen)
            brightness *= max(0.18, 1.0 - faded_for / 1.3)
        return brightness

    def _draw_pip(self, canvas: Canvas, x: float, y: float, brightness: float) -> None:
        cx = int(round(x))
        cy = int(round(y))
        h = canvas.height
        canvas.draw_circle(cx, cy, max(3, round(h * 0.047)), PHOSPHOR_HALO, 0.12 * brightness, fill=True)
        canvas.draw_circle(cx, cy, max(2, round(h * 0.037)), PHOSPHOR_VOID, 0.82 * brightness, fill=True)
        canvas.draw_circle(cx, cy, max(2, round(h * 0.030)), PHOSPHOR_HALO, 0.35 * brightness, fill=True)
        canvas.draw_circle(cx, cy, max(1, round(h * 0.019)), PHOSPHOR_MID, 0.82 * brightness, fill=True)
        canvas.draw_circle(cx, cy, max(1, round(h * 0.0086)), PHOSPHOR_CORE, min(1.0, brightness), fill=True)

    def _draw_pill(self, canvas: Canvas, tracks: list[Track]) -> None:
        width = canvas.width
        height = canvas.height
        label = distance_label(tracks)
        pill_w = max(118, text_width(label, 3) + 34)
        pill_h = 34
        x = (width - pill_w) // 2
        y = height - pill_h - 12
        canvas.fill_rect(x, y, pill_w, pill_h, PALETTE["pill_fill"], 0.92)
        canvas.draw_line(x, y, x + pill_w, y, PALETTE["edge"], 0.62, 1)
        canvas.draw_line(x, y + pill_h, x + pill_w, y + pill_h, PALETTE["edge"], 0.62, 1)
        canvas.draw_line(x, y, x, y + pill_h, PALETTE["edge"], 0.62, 1)
        canvas.draw_line(x + pill_w, y, x + pill_w, y + pill_h, PALETTE["edge"], 0.62, 1)
        draw_text(
            canvas,
            label,
            x + (pill_w - text_width(label, 3)) // 2,
            y + 7,
            3,
            PALETTE["pill_text"],
            0.95,
        )

    def _draw_offline(self, canvas: Canvas, message: str) -> None:
        label = "SENSOR OFFLINE"
        x = (canvas.width - text_width(label, 2)) // 2
        y = 20
        canvas.fill_rect(x - 14, y - 7, text_width(label, 2) + 28, 27, PALETTE["pill_fill"], 0.95)
        draw_text(canvas, label, x, y, 2, PALETTE["halo"], 0.9)


class PygamePhosphorRenderer:
    def __init__(
        self,
        pygame: Any,
        size: tuple[int, int] = BASE_SIZE,
        sweep_reveal: bool = True,
        scanlines: bool = True,
        assets_dir: str = "assets/phosphor",
    ) -> None:
        self.pygame = pygame
        self.size = size
        self.sweep_reveal = sweep_reveal
        self.scanlines = scanlines
        self.assets_ok = False
        self.asset_errors: list[str] = []
        self._face: Any | None = None
        self._sweeps: list[Any] = []
        self._fallback = PhosphorRenderer(size=size, sweep_reveal=sweep_reveal, scanlines=scanlines, assets_dir=assets_dir)
        self._last_sweep_distance: float | None = None
        self._revealed_at: dict[int, float] = {}
        self._pill_font = None
        self._small_font = None
        try:
            pygame.font.init()
            self._pill_font = pygame.font.Font(None, max(24, round(size[1] * 0.068)))
            self._small_font = pygame.font.Font(None, max(18, round(size[1] * 0.045)))
        except Exception as exc:
            self.asset_errors.append(f"unable to initialize pygame fonts: {exc}")
        if size != BASE_SIZE:
            self.asset_errors.append("phosphor asset pack is only available at 640x480")
            return
        try:
            self._face, self._sweeps = load_phosphor_sweep_assets(pygame, assets_dir, size)
            self.assets_ok = True
        except (OSError, ValueError) as exc:
            self.asset_errors.append(f"unable to load phosphor assets: {exc}")

    def render(
        self,
        snapshot: SourceSnapshot,
        now: float,
        show_fps: bool = False,
        fps_value: float | None = None,
    ) -> Any:
        if not self.assets_ok or self._face is None:
            canvas = self._fallback.render(snapshot, now, show_fps=show_fps, fps_value=fps_value)
            return self.pygame.image.frombuffer(bytes(canvas.pixels), self.size, "RGB").copy()

        geom = _phosphor_geometry(self.size)
        _, sweep_distance, frame_index = _sweep_state(now)
        previous_sweep = self._last_sweep_distance
        frame = self._face.copy()
        frame.blit(self._sweeps[frame_index], (0, 0), special_flags=self.pygame.BLEND_ADD)
        self._last_sweep_distance = sweep_distance
        draw_phosphor_hud(
            self.pygame,
            frame,
            geom,
            list(_valid_tracks(snapshot.tracks)),
            snapshot.error,
            previous_sweep,
            sweep_distance,
            now,
            self._revealed_at,
            self.sweep_reveal,
            self._pill_font,
            self._small_font,
            show_fps,
            fps_value,
        )
        if self.scanlines:
            _draw_pygame_scanlines(self.pygame, frame)
        return frame


def load_phosphor_sweep_assets(
    pygame: Any,
    assets_dir: str = "assets/phosphor",
    size: tuple[int, int] = BASE_SIZE,
) -> tuple[Any, list[Any]]:
    assets_ok, errors = validate_phosphor_assets(assets_dir)
    if not assets_ok:
        raise ValueError("; ".join(errors))

    root = Path(assets_dir)
    face = _load_pygame_surface(pygame, root / "face.png", size)
    sweeps = [_load_pygame_surface(pygame, root / f"sweep_{index:02d}.png", size) for index in range(PHOSPHOR_DWELL_INDEX + 1)]
    return face, sweeps


def draw_phosphor_contact(
    pygame: Any,
    frame: Any,
    geom: PhosphorGeometry,
    contact: Track,
    now: float,
    brightness: float,
) -> None:
    distance = contact.distance
    if distance > MAX_RANGE_MM:
        return
    fade = brightness
    if contact.state == "acquiring":
        fade *= 0.63
    elif contact.state == "fading":
        fade *= min(1.0, max(0.18, 1.0 - (now - contact.last_seen) / 1.3))
    if fade <= 0:
        return

    h = geom.height
    bearing = max(-SENSOR_HALF_CONE_DEG, min(SENSOR_HALF_CONE_DEG, contact.angle))
    contact_radius = geom.radius * distance / MAX_RANGE_MM
    px, py = _polar_float(geom.origin, contact_radius, bearing)
    local_scale = 2
    outer_radius = max(3, round(h * 0.047))
    padding = max(3, round(outer_radius * 0.75))
    native_side = outer_radius * 2 + padding * 2
    high_side = native_side * local_scale
    local = pygame.Surface((high_side, high_side), pygame.SRCALPHA)
    bloom = pygame.Surface((high_side, high_side), pygame.SRCALPHA)
    origin_x = round(px)
    origin_y = round(py)
    centre = (
        high_side // 2 + round((px - origin_x) * local_scale),
        high_side // 2 + round((py - origin_y) * local_scale),
    )

    def ring(colour: tuple[int, int, int], alpha: float, radius: float) -> None:
        clamped = max(0.0, min(1.0, alpha))
        pygame.draw.circle(local, (*colour, round(255 * clamped)), centre, max(1, round(radius * local_scale)))

    pygame.draw.circle(bloom, (*PHOSPHOR_HALO, round(255 * 0.18 * fade)), centre, max(1, round(outer_radius * local_scale)))
    ring(PHOSPHOR_VOID, 0.85 * fade, h * 0.037)
    ring(PHOSPHOR_HALO, 0.35 * fade, h * 0.030)
    ring(PHOSPHOR_MID, fade, h * 0.019)
    ring(PHOSPHOR_CORE, fade, h * 0.0086)
    tiny = pygame.transform.smoothscale(bloom, (max(1, high_side // 3), max(1, high_side // 3)))
    glow = pygame.transform.smoothscale(tiny, (native_side, native_side))
    crisp = pygame.transform.smoothscale(local, (native_side, native_side))
    destination = (round(origin_x - native_side / 2), round(origin_y - native_side / 2))
    frame.blit(glow, destination)
    frame.blit(crisp, destination)


def draw_phosphor_hud(
    pygame: Any,
    frame: Any,
    geom: PhosphorGeometry,
    tracks: list[Track],
    error: str | None,
    previous_sweep_distance: float | None,
    sweep_distance: float,
    now: float,
    revealed_at: dict[int, float],
    sweep_reveal: bool,
    pill_font: Any,
    small_font: Any,
    show_fps: bool = False,
    fps_value: float | None = None,
) -> None:
    previous_sweep = 0.0 if previous_sweep_distance is None else previous_sweep_distance
    if sweep_distance < previous_sweep:
        previous_sweep = 0.0
    for track in tracks:
        brightness = _contact_reveal_brightness(track, previous_sweep, sweep_distance, now, revealed_at, sweep_reveal)
        if brightness > 0.0:
            draw_phosphor_contact(pygame, frame, geom, track, now, brightness)
    _draw_pygame_pill(pygame, frame, geom, distance_label(tracks), pill_font)
    if error:
        _draw_pygame_offline(pygame, frame, geom, small_font)
    if show_fps:
        label = "FPS --" if fps_value is None else f"FPS {int(round(fps_value)):02d}"
        _draw_pygame_label(pygame, frame, label, geom.width - 10, geom.height - 24, small_font, align_right=True)


def distance_label(tracks: Iterable[Track]) -> str:
    solid = [track for track in _valid_tracks(tracks) if track.state != "fading"]
    if not solid:
        return "--.-m"
    nearest = min(solid, key=lambda track: track.distance)
    if nearest.distance > MAX_RANGE_MM:
        return ">6 M"
    return f"{nearest.distance / 1000:.1f}m"


def _valid_tracks(tracks: Iterable[object]) -> Iterable[Track]:
    for track in tracks:
        try:
            if not all(hasattr(track, attr) for attr in ("id", "x", "y", "speed", "state", "age", "last_seen")):
                continue
            x = int(getattr(track, "x"))
            y = int(getattr(track, "y"))
            speed = int(getattr(track, "speed"))
            ident = int(getattr(track, "id"))
            state = str(getattr(track, "state"))
            age = float(getattr(track, "age"))
            last_seen = float(getattr(track, "last_seen"))
        except (TypeError, ValueError):
            continue
        yield Track(ident, x, y, speed, state, age, last_seen)


def _contact_reveal_brightness(
    track: Track,
    previous_sweep: float,
    sweep_distance: float,
    now: float,
    revealed_at: dict[int, float],
    sweep_reveal: bool,
) -> float:
    if track.distance > MAX_RANGE_MM:
        return 0.0
    if not sweep_reveal:
        return 1.0
    crossed = previous_sweep <= track.distance <= sweep_distance
    if crossed:
        revealed_at[track.id] = now
    seen_at = revealed_at.get(track.id)
    if seen_at is None:
        return 0.0
    age = max(0.0, now - seen_at)
    step = min(len(REVEAL_STEPS) - 1, int((age / SWEEP_CYCLE_SECONDS) * len(REVEAL_STEPS)))
    return REVEAL_STEPS[step]


def _load_pygame_surface(pygame: Any, path: Path, size: tuple[int, int]) -> Any:
    surface = pygame.image.load(str(path))
    if surface.get_size() != size:
        raise ValueError(f"{path.name} size {surface.get_width()}x{surface.get_height()} does not match {size[0]}x{size[1]}")
    try:
        if pygame.display.get_init() and pygame.display.get_surface() is not None:
            return surface.convert_alpha()
    except Exception:
        pass
    return surface.copy()


def _draw_pygame_pill(pygame: Any, frame: Any, geom: PhosphorGeometry, label: str, font: Any) -> None:
    rendered = _render_pygame_text(font, label, PALETTE["pill_text"])
    text_w = rendered.get_width() if rendered is not None else text_width(label, 3)
    text_h = rendered.get_height() if rendered is not None else 21
    pill_w = max(118, text_w + 34)
    pill_h = max(34, text_h + 14)
    x = (geom.width - pill_w) // 2
    y = geom.height - pill_h - 12
    pill = pygame.Surface((pill_w, pill_h), pygame.SRCALPHA)
    rect = pygame.Rect(0, 0, pill_w, pill_h)
    pygame.draw.rect(pill, (*PALETTE["pill_fill"], 235), rect)
    pygame.draw.rect(pill, (*PALETTE["edge"], 158), rect, width=1)
    if rendered is not None:
        pill.blit(rendered, ((pill_w - rendered.get_width()) // 2, (pill_h - rendered.get_height()) // 2))
    frame.blit(pill, (x, y))


def _draw_pygame_offline(pygame: Any, frame: Any, geom: PhosphorGeometry, font: Any) -> None:
    label = "SENSOR OFFLINE"
    rendered = _render_pygame_text(font, label, PHOSPHOR_HALO)
    text_w = rendered.get_width() if rendered is not None else text_width(label, 2)
    text_h = rendered.get_height() if rendered is not None else 14
    panel_w = text_w + 28
    panel_h = text_h + 14
    x = (geom.width - panel_w) // 2
    y = 13
    panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
    pygame.draw.rect(panel, (*PALETTE["pill_fill"], 242), pygame.Rect(0, 0, panel_w, panel_h))
    if rendered is not None:
        panel.blit(rendered, ((panel_w - rendered.get_width()) // 2, (panel_h - rendered.get_height()) // 2))
    frame.blit(panel, (x, y))


def _draw_pygame_label(
    pygame: Any,
    frame: Any,
    label: str,
    x: int,
    y: int,
    font: Any,
    align_right: bool = False,
) -> None:
    rendered = _render_pygame_text(font, label, PALETTE["pill_text"])
    if rendered is None:
        return
    if align_right:
        x -= rendered.get_width()
    frame.blit(rendered, (x, y))


def _render_pygame_text(font: Any, label: str, colour: tuple[int, int, int]) -> Any | None:
    if font is None:
        return None
    return font.render(label, True, colour)


def _draw_pygame_scanlines(pygame: Any, frame: Any) -> None:
    width, height = frame.get_size()
    overlay = pygame.Surface((width, height), pygame.SRCALPHA)
    for y in range(1, height, 3):
        pygame.draw.line(overlay, (0, 0, 0, 82), (0, y), (width, y))
    frame.blit(overlay, (0, 0))


def _phosphor_geometry(size: tuple[int, int]) -> PhosphorGeometry:
    width, height = size
    origin = (width // 2, int(height * 0.90))
    radius = int(height * 0.80)
    radius = max(64, min(radius, height - 16, width // 2 - 12))
    return PhosphorGeometry(width, height, origin, radius)


def _polar(origin: tuple[int, int], radius: int, bearing_deg: float) -> tuple[int, int]:
    radians = math.radians(bearing_deg)
    return (
        int(round(origin[0] + math.sin(radians) * radius)),
        int(round(origin[1] - math.cos(radians) * radius)),
    )


def _polar_float(origin: tuple[int, int], radius: float, bearing_deg: float) -> tuple[float, float]:
    radians = math.radians(bearing_deg)
    return (
        origin[0] + math.sin(radians) * radius,
        origin[1] - math.cos(radians) * radius,
    )


def draw_text(
    canvas: Canvas,
    text: str,
    x: int,
    y: int,
    scale: int,
    color: tuple[int, int, int],
    alpha: float = 1.0,
) -> None:
    cursor = x
    for char in text:
        glyph = FONT.get(char) or FONT.get(char.upper(), FONT[" "])
        for yy, row in enumerate(glyph):
            for xx, bit in enumerate(row):
                if bit == "1":
                    canvas.fill_rect(cursor + xx * scale, y + yy * scale, scale, scale, color, alpha)
        cursor += 6 * scale


def text_width(text: str, scale: int) -> int:
    return max(0, len(text) * 6 * scale - scale)


def _write_chunk(handle, kind: bytes, payload: bytes) -> None:
    handle.write(struct.pack("!I", len(payload)))
    handle.write(kind)
    handle.write(payload)
    checksum = zlib.crc32(kind)
    checksum = zlib.crc32(payload, checksum)
    handle.write(struct.pack("!I", checksum & 0xFFFFFFFF))


def _sweep_state(now: float) -> tuple[float, float, int]:
    phase = now % SWEEP_CYCLE_SECONDS
    if phase < SWEEP_TRAVEL_SECONDS:
        sweep_fraction = phase / SWEEP_TRAVEL_SECONDS
        frame_index = min(PHOSPHOR_TRAVEL_FRAMES - 1, int(sweep_fraction * PHOSPHOR_TRAVEL_FRAMES))
        return sweep_fraction, sweep_fraction * MAX_RANGE_MM, frame_index
    return 1.0, float(MAX_RANGE_MM), PHOSPHOR_DWELL_INDEX


def _load_phosphor_asset_frames(assets_dir: str) -> list[bytes]:
    root = Path(assets_dir)
    face_size, face = _load_png_rgb(root / "face.png")
    if face_size != BASE_SIZE:
        raise ValueError(f"face.png size {face_size[0]}x{face_size[1]} does not match {BASE_SIZE[0]}x{BASE_SIZE[1]}")
    frames: list[bytes] = []
    for index in range(PHOSPHOR_DWELL_INDEX + 1):
        sweep_size, sweep = _load_png_rgb(root / f"sweep_{index:02d}.png")
        if sweep_size != face_size:
            raise ValueError(f"sweep_{index:02d}.png size does not match face.png")
        frames.append(_composite_sweep_frame(face, sweep))
    return frames


def _composite_sweep_frame(face: bytes, sweep: bytes) -> bytes:
    if len(face) != len(sweep):
        raise ValueError("sweep frame size does not match face")
    frame = bytearray(face)
    for offset in range(0, len(sweep), 3):
        sr = sweep[offset]
        sg = sweep[offset + 1]
        sb = sweep[offset + 2]
        if sr or sg or sb:
            frame[offset] = _screen_channel(frame[offset], sr)
            frame[offset + 1] = _screen_channel(frame[offset + 1], sg)
            frame[offset + 2] = _screen_channel(frame[offset + 2], sb)
    return bytes(frame)


def _screen_channel(base: int, overlay: int) -> int:
    return 255 - ((255 - base) * (255 - overlay) // 255)


def _load_png_rgb(path: Path) -> tuple[tuple[int, int], bytes]:
    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError(f"{path.name} is not a PNG file")

    offset = len(PNG_SIGNATURE)
    width: int | None = None
    height: int | None = None
    bit_depth: int | None = None
    color_type: int | None = None
    interlace: int | None = None
    idat_parts: list[bytes] = []
    while offset < len(data):
        if offset + 8 > len(data):
            raise ValueError(f"{path.name} has a truncated PNG chunk")
        length = int.from_bytes(data[offset : offset + 4], "big")
        kind = data[offset + 4 : offset + 8]
        payload_start = offset + 8
        payload_end = payload_start + length
        if payload_end + 4 > len(data):
            raise ValueError(f"{path.name} has a truncated PNG payload")
        payload = data[payload_start:payload_end]
        offset = payload_end + 4
        if kind == b"IHDR":
            width = int.from_bytes(payload[0:4], "big")
            height = int.from_bytes(payload[4:8], "big")
            bit_depth = payload[8]
            color_type = payload[9]
            compression = payload[10]
            filter_method = payload[11]
            interlace = payload[12]
            if compression != 0 or filter_method != 0:
                raise ValueError(f"{path.name} uses unsupported PNG compression/filter settings")
        elif kind == b"IDAT":
            idat_parts.append(payload)
        elif kind == b"IEND":
            break

    if width is None or height is None or bit_depth is None or color_type is None or interlace is None:
        raise ValueError(f"{path.name} is missing IHDR")
    if bit_depth != 8 or color_type not in (2, 6) or interlace != 0:
        raise ValueError(f"{path.name} must be non-interlaced 8-bit RGB/RGBA")
    if not idat_parts:
        raise ValueError(f"{path.name} is missing image data")

    channels = 4 if color_type == 6 else 3
    stride = width * channels
    rgb_stride = width * 3
    raw = zlib.decompress(b"".join(idat_parts))
    expected = (stride + 1) * height
    if len(raw) != expected:
        raise ValueError(f"{path.name} has unexpected decompressed length")

    pixels = bytearray(width * height * 3)
    previous = bytearray(stride)
    raw_offset = 0
    output_offset = 0
    for _ in range(height):
        filter_type = raw[raw_offset]
        raw_offset += 1
        row = bytearray(raw[raw_offset : raw_offset + stride])
        raw_offset += stride
        _unfilter_png_row(row, previous, channels, filter_type, path.name)
        if color_type == 2:
            pixels[output_offset : output_offset + rgb_stride] = row
        else:
            _copy_rgba_as_rgb(row, pixels, output_offset)
        previous = row
        output_offset += rgb_stride
    return (width, height), bytes(pixels)


def _copy_rgba_as_rgb(row: bytearray, pixels: bytearray, output_offset: int) -> None:
    target = output_offset
    for source in range(0, len(row), 4):
        alpha = row[source + 3]
        pixels[target] = row[source] * alpha // 255
        pixels[target + 1] = row[source + 1] * alpha // 255
        pixels[target + 2] = row[source + 2] * alpha // 255
        target += 3


def _unfilter_png_row(row: bytearray, previous: bytearray, bpp: int, filter_type: int, filename: str) -> None:
    if filter_type == 0:
        return
    if filter_type == 1:
        for index in range(len(row)):
            left = row[index - bpp] if index >= bpp else 0
            row[index] = (row[index] + left) & 0xFF
        return
    if filter_type == 2:
        for index in range(len(row)):
            row[index] = (row[index] + previous[index]) & 0xFF
        return
    if filter_type == 3:
        for index in range(len(row)):
            left = row[index - bpp] if index >= bpp else 0
            row[index] = (row[index] + ((left + previous[index]) // 2)) & 0xFF
        return
    if filter_type == 4:
        for index in range(len(row)):
            left = row[index - bpp] if index >= bpp else 0
            up = previous[index]
            upper_left = previous[index - bpp] if index >= bpp else 0
            row[index] = (row[index] + _paeth_predictor(left, up, upper_left)) & 0xFF
        return
    raise ValueError(f"{filename} uses unsupported PNG filter {filter_type}")


def _paeth_predictor(left: int, up: int, upper_left: int) -> int:
    estimate = left + up - upper_left
    left_distance = abs(estimate - left)
    up_distance = abs(estimate - up)
    upper_left_distance = abs(estimate - upper_left)
    if left_distance <= up_distance and left_distance <= upper_left_distance:
        return left
    if up_distance <= upper_left_distance:
        return up
    return upper_left


def validate_phosphor_assets(assets_dir: str = "assets/phosphor") -> tuple[bool, list[str]]:
    root = Path(assets_dir)
    manifest_path = root / "manifest.json"
    errors: list[str] = []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except OSError as exc:
        return False, [f"missing phosphor manifest: {exc}"]
    except json.JSONDecodeError as exc:
        return False, [f"invalid phosphor manifest: {exc}"]

    expected = {
        "profile": "phosphor",
        "size": [640, 480],
        "target_fps": 30,
        "travel_seconds": 0.85,
        "dwell_seconds": 0.35,
        "travel_frames": 26,
        "dwell_index": 26,
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            errors.append(f"manifest {key} mismatch")
    expected_files = ["face.png"] + [f"sweep_{index:02d}.png" for index in range(27)]
    listed = {asset.get("file") for asset in manifest.get("assets", []) if isinstance(asset, dict)}
    for filename in expected_files:
        if filename not in listed:
            errors.append(f"manifest missing {filename}")
        elif not (root / filename).is_file():
            errors.append(f"asset missing {filename}")
    return not errors, errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MW2 heartbeat sensor HUD")
    parser.add_argument("--source", choices=("live", "demo", "replay"), default="live")
    parser.add_argument("--demo", action="store_true", help="shortcut for --source demo")
    parser.add_argument("--port", default="/dev/serial0")
    parser.add_argument("--baud", type=int, default=256000)
    parser.add_argument("--fixture")
    parser.add_argument("--scenario", choices=tuple(sorted(DemoSource.scenarios)), default="walk")
    parser.add_argument("--fullscreen", action="store_true")
    parser.add_argument("--ui", choices=("template", "phosphor"), default="phosphor")
    parser.add_argument("--swap-xy", action="store_true")
    parser.add_argument("--invert-x", action="store_true")
    parser.add_argument("--size", type=parse_size, default=BASE_SIZE)
    parser.add_argument("--selftest", nargs="?", const=120, type=int)
    parser.add_argument("--screenshot")
    parser.add_argument("--sweep-reveal", dest="sweep_reveal", action="store_true", default=True)
    parser.add_argument("--no-sweep-reveal", dest="sweep_reveal", action="store_false")
    parser.add_argument("--fps", action="store_true")
    parser.add_argument("--no-scanlines", dest="scanlines", action="store_false", default=True)
    return parser


def parse_size(value: str) -> tuple[int, int]:
    normalized = value.lower().replace(",", "x")
    try:
        width_text, height_text = normalized.split("x", 1)
        width = int(width_text)
        height = int(height_text)
    except (ValueError, AttributeError):
        raise argparse.ArgumentTypeError("size must be WIDTHxHEIGHT") from None
    if width < 160 or height < 160:
        raise argparse.ArgumentTypeError("size must be at least 160x160")
    return width, height


def argv_from_environment(env: dict[str, str] | None = None) -> list[str]:
    env = os.environ if env is None else env
    mode = env.get("MW2_RADAR_MODE", "live")
    if mode not in {"live", "demo", "replay"}:
        raise ValueError("MW2_RADAR_MODE must be live, demo, or replay")
    argv = ["--source", mode]
    ui = env.get("MW2_RADAR_UI", "phosphor")
    if ui:
        argv.extend(["--ui", ui])
    if _truthy(env.get("MW2_RADAR_SWAP_XY", "0")):
        argv.append("--swap-xy")
    if _truthy(env.get("MW2_RADAR_INVERT_X", "0")):
        argv.append("--invert-x")
    if mode == "live":
        argv.extend(["--port", env.get("MW2_RADAR_PORT", "/dev/serial0")])
        argv.extend(["--baud", env.get("MW2_RADAR_BAUD", "256000")])
    elif mode == "replay" and env.get("MW2_RADAR_FIXTURE"):
        argv.extend(["--fixture", env["MW2_RADAR_FIXTURE"]])
    elif mode == "demo" and env.get("MW2_RADAR_SCENARIO"):
        argv.extend(["--scenario", env["MW2_RADAR_SCENARIO"]])
    return argv


def _truthy(value: str | None) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def make_source(args: argparse.Namespace):
    orientation = Orientation(swap_xy=args.swap_xy, invert_x=args.invert_x)
    if args.demo:
        args.source = "demo"
    if args.source == "demo":
        return DemoSource(scenario=args.scenario)
    if args.source == "replay":
        if not args.fixture:
            return StaticErrorSource("replay fixture is required")
        return ReplaySource(args.fixture, loop=True, realtime=True, orientation=orientation)
    return RadarSource(port=args.port, baud=args.baud, orientation=orientation)


def run(args: argparse.Namespace) -> int:
    source = make_source(args)
    return run_phosphor(args, source)


def run_phosphor(args: argparse.Namespace, source: Any) -> int:
    renderer = PhosphorRenderer(size=args.size, sweep_reveal=args.sweep_reveal, scanlines=args.scanlines)
    frames = max(1, args.selftest) if args.selftest is not None else None
    finite = frames is not None or args.screenshot is not None
    pygame = _load_pygame()
    screen = None
    clock = None
    if pygame is not None:
        try:
            pygame.init()
            renderer = PygamePhosphorRenderer(pygame, size=args.size, sweep_reveal=args.sweep_reveal, scanlines=args.scanlines)
            if not finite:
                flags = pygame.FULLSCREEN if args.fullscreen else 0
                screen = pygame.display.set_mode(args.size, flags)
                pygame.display.set_caption("MW2 Heartbeat Sensor")
                clock = pygame.time.Clock()
        except Exception as exc:
            print(f"pygame display unavailable, using headless renderer: {exc}", file=sys.stderr)
            pygame = None
            renderer = PhosphorRenderer(size=args.size, sweep_reveal=args.sweep_reveal, scanlines=args.scanlines)
    elif not finite:
        print("pygame is not available; running headless. Use --selftest to exit automatically.", file=sys.stderr)

    target_fps = 60
    frame_count = 0
    last_frame: Canvas | Any | None = None
    last_tick = time.monotonic()
    fps_value: float | None = None
    try:
        try:
            while frames is None or frame_count < frames:
                now = time.monotonic()
                elapsed = max(1e-6, now - last_tick)
                last_tick = now
                fps_value = 1.0 / elapsed
                if screen is not None and pygame is not None:
                    for event in pygame.event.get():
                        if event.type == pygame.QUIT:
                            frames = frame_count
                        elif event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_q):
                            frames = frame_count
                snapshot = source.snapshot()
                last_frame = renderer.render(snapshot, now=now, show_fps=args.fps, fps_value=fps_value)
                if screen is not None and pygame is not None:
                    screen.blit(last_frame, (0, 0))
                    pygame.display.flip()
                    assert clock is not None
                    clock.tick(target_fps)
                else:
                    time.sleep(1.0 / target_fps)
                frame_count += 1
                if args.screenshot is not None and args.selftest is None:
                    break
        except KeyboardInterrupt:
            pass
        finally:
            source.stop()

        if args.screenshot:
            if last_frame is None:
                last_frame = renderer.render(source.snapshot(), now=time.monotonic(), show_fps=args.fps, fps_value=fps_value)
            _write_rendered_frame(last_frame, args.screenshot, pygame)
        return 0
    finally:
        if pygame is not None:
            pygame.quit()


def _load_pygame():
    try:
        import pygame  # type: ignore
    except Exception:
        return None
    return pygame


def _write_rendered_frame(frame: Any, path: str, pygame: Any | None) -> None:
    if isinstance(frame, Canvas):
        frame.write_png(path)
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if pygame is None:
        raise RuntimeError("pygame frame cannot be written without pygame")
    pygame.image.save(frame, str(output))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    if argv is None:
        argv = sys.argv[1:]
    if not argv and os.environ.get("MW2_RADAR_MODE"):
        argv = argv_from_environment()
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
