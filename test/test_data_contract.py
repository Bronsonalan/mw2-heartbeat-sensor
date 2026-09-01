from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from test.contract_support import (
    ManualClock,
    TRACK_STATES,
    assert_constructor_prefix,
    assert_field_order,
    assert_snapshot_method_takes_no_args,
    assert_snapshot_shape,
    assert_stop_idempotent,
    make_target,
    optional_import,
    update_tracker,
)


HEADER = bytes.fromhex("AA FF 03 00")
TAIL = bytes.fromhex("55 CC")
EMPTY_SLOT = b"\x00" * 8


def _encode_sign_flag(value: int) -> bytes:
    magnitude = abs(value)
    if magnitude > 0x7FFF:
        raise ValueError("LD2450 sign-flag magnitude is 15 bits")
    lo = magnitude & 0xFF
    hi = (magnitude >> 8) & 0x7F
    if value >= 0:
        hi |= 0x80
    return bytes((lo, hi))


def _slot(x: int, y: int, speed: int, resolution: int) -> bytes:
    return (
        _encode_sign_flag(x)
        + _encode_sign_flag(y)
        + _encode_sign_flag(speed)
        + int(resolution).to_bytes(2, "little", signed=False)
    )


def _frame(*slots: bytes) -> bytes:
    if len(slots) != 3:
        raise ValueError("LD2450 frames have exactly three slots")
    return HEADER + b"".join(slots) + TAIL


class DataShapeContractTests(unittest.TestCase):
    def test_ld2450_target_field_order(self) -> None:
        ld2450 = optional_import(self, "ld2450")
        self.assertTrue(hasattr(ld2450, "Target"), "ld2450 must export Target")
        assert_field_order(self, ld2450.Target, ("x", "y", "speed", "resolution"))

    def test_tracking_track_field_order_and_states(self) -> None:
        tracking = optional_import(self, "tracking")
        self.assertTrue(hasattr(tracking, "Track"), "tracking must export Track")
        assert_field_order(self, tracking.Track, ("id", "x", "y", "speed", "state", "age", "last_seen"))
        for state in TRACK_STATES:
            track = tracking.Track(1, 0, 1000, 0, state, 0.0, 0.0)
            self.assertEqual(track.state, state)


class LD2450ParserContractTests(unittest.TestCase):
    def test_sign_flag_decoding_golden_frame(self) -> None:
        ld2450 = optional_import(self, "ld2450")
        self.assertTrue(hasattr(ld2450, "parse_frame"), "ld2450 must export parse_frame")

        # 0x8102 little-endian would be -32510 as int16, but the LD2450 rule is +258.
        self.assertNotEqual(int.from_bytes(bytes((0x02, 0x81)), "little", signed=True), 258)
        frame = _frame(_slot(258, -258, -1, 360), EMPTY_SLOT, EMPTY_SLOT)
        targets = ld2450.parse_frame(frame)

        self.assertEqual(len(targets), 1)
        target = targets[0]
        self.assertEqual((target.x, target.y, target.speed, target.resolution), (258, -258, -1, 360))

    def test_empty_slots_are_dropped_and_empty_frame_is_healthy(self) -> None:
        ld2450 = optional_import(self, "ld2450")
        self.assertEqual(ld2450.parse_frame(_frame(EMPTY_SLOT, EMPTY_SLOT, EMPTY_SLOT)), [])

        targets = ld2450.parse_frame(_frame(EMPTY_SLOT, _slot(-17, 1772, 0, 360), EMPTY_SLOT))
        self.assertEqual(len(targets), 1)
        self.assertEqual((targets[0].x, targets[0].y), (-17, 1772))


class TrackerContractTests(unittest.TestCase):
    def _constant(self, tracking, tracker, names: tuple[str, ...]):
        for container in (tracking, type(tracker), tracker):
            for name in names:
                if hasattr(container, name):
                    return getattr(container, name)
        self.fail(f"missing tracker constant aliases {names}")

    def test_tracker_constants_match_data_contract(self) -> None:
        tracking = optional_import(self, "tracking")
        clock = ManualClock()
        tracker = tracking.Tracker(clock=clock)

        self.assertEqual(
            self._constant(tracking, tracker, ("ASSOCIATION_GATE_MM", "association_gate", "gate_mm")),
            600,
        )
        self.assertAlmostEqual(
            self._constant(tracking, tracker, ("POSITION_ALPHA", "position_alpha")),
            0.4,
        )
        self.assertAlmostEqual(
            self._constant(tracking, tracker, ("SPEED_ALPHA", "speed_alpha")),
            0.25,
        )
        self.assertEqual(
            self._constant(tracking, tracker, ("CONFIRMATION_FRAMES", "confirmation_frames", "confirm_frames")),
            3,
        )
        self.assertAlmostEqual(
            self._constant(tracking, tracker, ("GRACE_SECONDS", "grace_seconds")),
            0.8,
        )

    def test_tracker_state_flow_sticky_confirmation_and_never_reused_ids(self) -> None:
        ld2450 = optional_import(self, "ld2450")
        tracking = optional_import(self, "tracking")
        clock = ManualClock()
        tracker = tracking.Tracker(clock=clock)
        target = make_target(ld2450.Target, 0, 1000, 0, 360)

        first = update_tracker(tracker, [target], clock, 0.0)
        self.assertEqual(first[0].state, "acquiring")
        first_id = first[0].id
        self.assertEqual(update_tracker(tracker, [target], clock, 0.1)[0].state, "acquiring")
        confirmed = update_tracker(tracker, [target], clock, 0.2)
        self.assertEqual(confirmed[0].id, first_id)
        self.assertEqual(confirmed[0].state, "live")

        fading = update_tracker(tracker, [], clock, 0.3)
        self.assertEqual(fading[0].id, first_id)
        self.assertEqual(fading[0].state, "fading")

        returned = update_tracker(tracker, [target], clock, 0.4)
        self.assertEqual(returned[0].id, first_id)
        self.assertEqual(returned[0].state, "live")

        self.assertEqual(update_tracker(tracker, [], clock, 1.3), [])
        replacement = update_tracker(tracker, [make_target(ld2450.Target, 2000, 1000, 0, 360)], clock, 1.4)
        self.assertEqual(len(replacement), 1)
        self.assertGreater(replacement[0].id, first_id)


class SourceContractTests(unittest.TestCase):
    def test_source_constructor_signatures(self) -> None:
        sources = optional_import(self, "sources")
        assert_constructor_prefix(self, sources.RadarSource, ("port", "baud", "orientation"))
        assert_constructor_prefix(self, sources.DemoSource, ("scenario", "seed", "clock"))
        assert_constructor_prefix(self, sources.ReplaySource, ("path", "loop", "realtime", "clock"))

    def test_replay_empty_targets_are_healthy_snapshot_not_error(self) -> None:
        sources = optional_import(self, "sources")
        clock = ManualClock()
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir) / "empty.ndjson"
            fixture.write_text('{"t": 0.0, "seq": 1, "targets": []}\n', encoding="utf-8")
            source = sources.ReplaySource(str(fixture), loop=False, realtime=False, clock=clock)
            assert_snapshot_method_takes_no_args(self, source)
            snapshot = source.snapshot()
            assert_snapshot_shape(self, snapshot)
            self.assertEqual(snapshot.tracks, [])
            self.assertIsNone(snapshot.error, "empty tracks must not be reported as a sensor error")
            assert_stop_idempotent(self, source)

    def test_demo_scenarios_are_healthy_and_cap_tracks(self) -> None:
        sources = optional_import(self, "sources")
        for scenario in ("walk", "cross", "still", "empty", "multi"):
            with self.subTest(scenario=scenario):
                clock = ManualClock()
                source = sources.DemoSource(scenario=scenario, seed=123, clock=clock)
                assert_snapshot_method_takes_no_args(self, source)
                for _ in range(5):
                    snapshot = source.snapshot()
                    assert_snapshot_shape(self, snapshot)
                    self.assertIsNone(snapshot.error)
                    self.assertLessEqual(len(snapshot.tracks), 3)
                    clock.advance(0.11)
                assert_stop_idempotent(self, source)


if __name__ == "__main__":
    unittest.main()

