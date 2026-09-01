from __future__ import annotations

import tempfile
import types
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
    optional_import,
)


class SimulatorContractTests(unittest.TestCase):
    def test_target_and_track_field_order(self) -> None:
        simulator = optional_import(self, "simulator")
        assert_field_order(self, simulator.Target, ("x", "y", "speed", "resolution"))
        assert_field_order(self, simulator.Track, ("id", "x", "y", "speed", "state", "age", "last_seen"))
        for state in TRACK_STATES:
            self.assertEqual(simulator.Track(1, 0, 1000, 0, state, 0.0, 0.0).state, state)

    def test_demo_constructor_scenarios_and_track_cap(self) -> None:
        simulator = optional_import(self, "simulator")
        assert_constructor_prefix(self, simulator.DemoSource, ("scenario", "seed", "clock"))
        for scenario in ("walk", "cross", "still", "empty", "multi"):
            with self.subTest(scenario=scenario):
                clock = ManualClock()
                source = simulator.DemoSource(scenario=scenario, seed=123, clock=clock)
                assert_snapshot_method_takes_no_args(self, source)
                for _ in range(5):
                    snapshot = source.snapshot()
                    assert_snapshot_shape(self, snapshot)
                    self.assertIsNone(snapshot.error)
                    self.assertLessEqual(len(snapshot.tracks), 3)
                    clock.advance(0.11)
                assert_stop_idempotent(self, source)


class ReplayContractTests(unittest.TestCase):
    def test_replay_constructor_and_empty_snapshot_contract(self) -> None:
        replay = optional_import(self, "replay")
        assert_constructor_prefix(self, replay.ReplaySource, ("path", "loop", "realtime", "clock"))

        clock = ManualClock()
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir) / "empty.ndjson"
            fixture.write_text('{"t": 0.0, "seq": 1, "targets": []}\n', encoding="utf-8")
            source = replay.ReplaySource(str(fixture), loop=False, realtime=False, clock=clock)
            assert_snapshot_method_takes_no_args(self, source)
            snapshot = source.snapshot()
            assert_snapshot_shape(self, snapshot)
            self.assertEqual(snapshot.tracks, [])
            self.assertIsNone(snapshot.error, "empty tracks must not be reported as a sensor error")
            assert_stop_idempotent(self, source)


class RadarCliContractTests(unittest.TestCase):
    def test_cli_flags_from_ui_spec(self) -> None:
        radar = optional_import(self, "radar")
        self.assertTrue(hasattr(radar, "build_parser"), "radar must expose build_parser()")
        parser = radar.build_parser()

        for source in ("live", "demo", "replay"):
            with self.subTest(source=source):
                self.assertEqual(parser.parse_args(["--source", source]).source, source)
        with self.assertRaises(SystemExit):
            parser.parse_args(["--source", "invalid"])

        for ui in ("template", "phosphor"):
            with self.subTest(ui=ui):
                self.assertEqual(parser.parse_args(["--ui", ui]).ui, ui)

        args = parser.parse_args(
            [
                "--source",
                "replay",
                "--demo",
                "--port",
                "/dev/null",
                "--baud",
                "256000",
                "--fixture",
                "fixtures/walk-01.ndjson",
                "--scenario",
                "multi",
                "--fullscreen",
                "--ui",
                "phosphor",
                "--swap-xy",
                "--invert-x",
                "--size",
                "640x480",
                "--selftest",
                "90",
                "--screenshot",
                "out.png",
                "--sweep-reveal",
                "--no-sweep-reveal",
                "--fps",
                "--no-scanlines",
            ]
        )
        for attr in (
            "source",
            "demo",
            "port",
            "baud",
            "fixture",
            "scenario",
            "fullscreen",
            "ui",
            "swap_xy",
            "invert_x",
            "size",
            "selftest",
            "screenshot",
            "sweep_reveal",
            "fps",
            "scanlines",
        ):
            self.assertTrue(hasattr(args, attr), f"missing CLI destination {attr}")

    def test_distance_pill_labels(self) -> None:
        radar = optional_import(self, "radar")
        self.assertTrue(hasattr(radar, "distance_label"), "radar must expose distance_label()")

        def track(y: int, state: str = "live"):
            return types.SimpleNamespace(id=1, x=0, y=y, speed=0, state=state, age=0.0, last_seen=0.0)

        self.assertEqual(radar.distance_label([]), "--.-m")
        self.assertEqual(radar.distance_label([track(1300)]), "1.3m")
        self.assertEqual(radar.distance_label([track(6100)]), ">6 M")
        self.assertEqual(radar.distance_label([track(1300, "fading")]), "--.-m")


if __name__ == "__main__":
    unittest.main()

