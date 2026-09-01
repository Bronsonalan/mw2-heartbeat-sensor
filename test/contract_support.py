"""Shared helpers for contract tests that must run before app modules exist."""

from __future__ import annotations

import dataclasses
import importlib
import importlib.util
import inspect
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TRACK_STATES = ("acquiring", "live", "fading")


class ManualClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


def optional_import(testcase, module_name: str):
    """Import an implementation module, skipping only when its file is absent."""

    try:
        spec = importlib.util.find_spec(module_name)
    except (ImportError, AttributeError):
        spec = None
    if spec is None:
        testcase.skipTest(f"{module_name}.py is not present yet")
    return importlib.import_module(module_name)


def field_names(cls: type) -> tuple[str, ...]:
    if hasattr(cls, "_fields"):
        return tuple(cls._fields)
    if dataclasses.is_dataclass(cls):
        return tuple(field.name for field in dataclasses.fields(cls))
    annotations = getattr(cls, "__annotations__", None)
    if annotations:
        return tuple(annotations)
    signature = inspect.signature(cls)
    names = []
    for name, param in signature.parameters.items():
        if name == "self":
            continue
        if param.kind in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD, param.KEYWORD_ONLY):
            names.append(name)
    return tuple(names)


def assert_field_order(testcase, cls: type, expected: tuple[str, ...]) -> None:
    testcase.assertEqual(
        field_names(cls),
        expected,
        f"{cls.__module__}.{cls.__name__} fields must stay in contract order",
    )


def assert_constructor_prefix(testcase, constructor: Any, expected: tuple[str, ...]) -> None:
    signature = inspect.signature(constructor)
    names = [
        name
        for name, param in signature.parameters.items()
        if name != "self"
        and param.kind
        in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD, param.KEYWORD_ONLY)
    ]
    testcase.assertEqual(
        names[: len(expected)],
        list(expected),
        f"{constructor} constructor should begin with {expected}",
    )


def assert_snapshot_method_takes_no_args(testcase, source: Any) -> None:
    signature = inspect.signature(source.snapshot)
    testcase.assertEqual(
        tuple(signature.parameters),
        (),
        "snapshot() must be callable with no arguments",
    )


def assert_snapshot_shape(testcase, snapshot: Any) -> None:
    for attr in ("tracks", "error", "frames"):
        testcase.assertTrue(hasattr(snapshot, attr), f"snapshot missing {attr!r}")
    testcase.assertIsInstance(snapshot.tracks, list)
    testcase.assertTrue(
        snapshot.error is None or isinstance(snapshot.error, str),
        "snapshot.error must be None or a user-visible string",
    )
    testcase.assertIsInstance(snapshot.frames, int)
    testcase.assertFalse(isinstance(snapshot.frames, bool))
    testcase.assertGreaterEqual(snapshot.frames, 0)
    for track in snapshot.tracks:
        assert_track_shape(testcase, track)


def assert_track_shape(testcase, track: Any) -> None:
    for attr in ("id", "x", "y", "speed", "state", "age", "last_seen"):
        testcase.assertTrue(hasattr(track, attr), f"track missing {attr!r}")
    testcase.assertIn(track.state, TRACK_STATES)


def assert_stop_idempotent(testcase, source: Any) -> None:
    testcase.assertTrue(hasattr(source, "stop"), "source missing stop()")
    source.stop()
    source.stop()


def make_target(target_cls: type, x: int = 0, y: int = 1000, speed: int = 0, resolution: int = 360):
    return target_cls(x, y, speed, resolution)


def update_tracker(tracker: Any, targets: list[Any], clock: ManualClock, now: float) -> list[Any]:
    clock.now = now
    signature = inspect.signature(tracker.update)
    if "now" in signature.parameters:
        return list(tracker.update(targets, now=now))
    if "timestamp" in signature.parameters:
        return list(tracker.update(targets, timestamp=now))
    return list(tracker.update(targets))

