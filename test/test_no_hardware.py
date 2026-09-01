import inspect
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from radar import argv_from_environment, build_parser, distance_label
from replay import ReplaySource
from simulator import DemoSource, SourceSnapshot, Track


ROOT = Path(__file__).resolve().parents[1]


class FakeClock:
    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class ReplaySourceTests(unittest.TestCase):
    def test_fixture_targets_feed_tracker_and_snapshot_contract(self):
        clock = FakeClock()
        source = ReplaySource(str(ROOT / "fixtures" / "walk-01.ndjson"), loop=False, realtime=False, clock=clock)

        snapshots = [source.snapshot(), source.snapshot(), source.snapshot()]

        self.assertIsInstance(snapshots[-1], SourceSnapshot)
        self.assertEqual(snapshots[-1].error, None)
        self.assertEqual(snapshots[-1].frames, 3)
        self.assertEqual(len(snapshots[-1].tracks), 1)
        self.assertEqual(snapshots[-1].tracks[0].state, "live")
        self.assertGreater(snapshots[-1].tracks[0].distance, 1000)
        source.stop()
        source.stop()

    def test_malformed_lines_are_skipped_and_reported(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "bad.ndjson"
            path.write_text(
                "not json\n"
                '{"t": 0.0, "seq": 1, "targets": [{"x": 0, "y": 1000, "speed": 0, "resolution": 12}]}\n',
                encoding="utf-8",
            )

            source = ReplaySource(str(path), loop=False, realtime=False, clock=FakeClock())
            snapshot = source.snapshot()

        self.assertEqual(snapshot.frames, 1)
        self.assertEqual(len(snapshot.tracks), 1)
        self.assertIn("malformed", snapshot.error)

    def test_missing_and_fully_malformed_files_do_not_raise(self):
        missing = ReplaySource(str(ROOT / "fixtures" / "missing.ndjson"), realtime=False)
        self.assertIn("unable to read", missing.snapshot().error)

        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "bad.ndjson"
            path.write_text("{bad}\nNaN\n", encoding="utf-8")
            source = ReplaySource(str(path), realtime=False)
            snapshot = source.snapshot()
        self.assertEqual(snapshot.frames, 0)
        self.assertIn("no valid frames", snapshot.error)

    def test_track_fixture_loop_offsets_ids(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "tracks.ndjson"
            path.write_text(
                '{"t": 0.0, "seq": 1, "tracks": [{"id": 7, "x": 0, "y": 1000, "speed": 0, "state": "live", "age": 0, "last_seen": 0}]}\n',
                encoding="utf-8",
            )
            source = ReplaySource(str(path), loop=True, realtime=False, clock=FakeClock())
            first = source.snapshot()
            second = source.snapshot()
        self.assertEqual(first.tracks[0].id, 7)
        self.assertGreater(second.tracks[0].id, first.tracks[0].id)


class DemoSourceTests(unittest.TestCase):
    def test_all_required_scenarios_emit_contract_snapshots(self):
        for scenario in ("walk", "cross", "still", "empty", "multi"):
            with self.subTest(scenario=scenario):
                clock = FakeClock(10.0)
                source = DemoSource(scenario=scenario, seed=123, clock=clock)
                first = source.snapshot()
                clock.advance(0.05)
                same_window = source.snapshot()
                clock.advance(0.1)
                next_window = source.snapshot()

                self.assertIsNone(first.error)
                self.assertLessEqual(len(first.tracks), 3)
                self.assertEqual(first.frames, same_window.frames)
                self.assertEqual(next_window.frames, first.frames + 1)

    def test_constructor_signatures_match_contract(self):
        demo_sig = inspect.signature(DemoSource)
        replay_sig = inspect.signature(ReplaySource)
        self.assertIn("scenario", demo_sig.parameters)
        self.assertIn("seed", demo_sig.parameters)
        self.assertIn("clock", demo_sig.parameters)
        self.assertIn("path", replay_sig.parameters)
        self.assertIn("loop", replay_sig.parameters)
        self.assertIn("realtime", replay_sig.parameters)
        self.assertIn("clock", replay_sig.parameters)


class CliAndRendererTests(unittest.TestCase):
    def test_required_cli_flags_parse(self):
        parser = build_parser()
        args = parser.parse_args(
            [
                "--source",
                "replay",
                "--fixture",
                "fixtures/walk-01.ndjson",
                "--ui",
                "phosphor",
                "--selftest",
                "90",
                "--screenshot",
                "out.png",
                "--fps",
                "--no-scanlines",
                "--no-sweep-reveal",
            ]
        )
        self.assertEqual(args.source, "replay")
        self.assertEqual(args.selftest, 90)
        self.assertFalse(args.scanlines)
        self.assertFalse(args.sweep_reveal)

        args = parser.parse_args(["--demo", "--scenario", "multi", "--selftest"])
        self.assertTrue(args.demo)
        self.assertEqual(args.selftest, 120)

    def test_environment_to_argv_mapping(self):
        argv = argv_from_environment(
            {
                "MW2_RADAR_MODE": "replay",
                "MW2_RADAR_FIXTURE": "fixtures/walk-01.ndjson",
                "MW2_RADAR_UI": "phosphor",
                "MW2_RADAR_SWAP_XY": "0",
                "MW2_RADAR_INVERT_X": "1",
            }
        )
        self.assertEqual(argv, ["--source", "replay", "--ui", "phosphor", "--invert-x", "--fixture", "fixtures/walk-01.ndjson"])

    def test_distance_pill_labels(self):
        self.assertEqual(distance_label([]), "--.-m")
        self.assertEqual(distance_label([Track(1, 0, 1300, 0, "live", 1, 1)]), "1.3m")
        self.assertEqual(distance_label([Track(1, 0, 7000, 0, "live", 1, 1)]), ">6 M")
        self.assertEqual(distance_label([Track(1, 0, 1300, 0, "fading", 1, 1)]), "--.-m")

    def test_screenshot_selftest_creates_png_without_hardware(self):
        with tempfile.TemporaryDirectory() as tempdir:
            out = Path(tempdir) / "phosphor.png"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "radar.py"),
                    "--source",
                    "demo",
                    "--scenario",
                    "multi",
                    "--ui",
                    "phosphor",
                    "--selftest",
                    "3",
                    "--screenshot",
                    str(out),
                    "--no-scanlines",
                    "--no-sweep-reveal",
                ],
                cwd=str(ROOT),
                text=True,
                capture_output=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(out.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")


class FixtureConformanceTests(unittest.TestCase):
    def test_walk_fixture_is_line_delimited_contract_json(self):
        fixture = ROOT / "fixtures" / "walk-01.ndjson"
        previous_t = -math.inf
        previous_seq = -1
        count = 0
        for line in fixture.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            self.assertFalse(line.lstrip().startswith("["))
            obj = json.loads(line, parse_constant=lambda value: self.fail(f"invalid constant {value}"))
            self.assertIsInstance(obj, dict)
            self.assertEqual(("targets" in obj) + ("tracks" in obj), 1)
            self.assertGreaterEqual(obj["t"], previous_t)
            self.assertGreater(obj["seq"], previous_seq)
            self.assertTrue(math.isfinite(float(obj["t"])))
            previous_t = obj["t"]
            previous_seq = obj["seq"]
            count += 1
        self.assertGreater(count, 0)


if __name__ == "__main__":
    unittest.main()
