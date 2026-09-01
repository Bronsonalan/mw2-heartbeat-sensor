import inspect
import json
import os
import tempfile
import unittest

import sources
from sources import DemoSource, RadarSource, ReplaySource


class FakeClock:
    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def write_replay(lines):
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False)
    try:
        for line in lines:
            if isinstance(line, str):
                handle.write(line + "\n")
            else:
                handle.write(json.dumps(line) + "\n")
        return handle.name
    finally:
        handle.close()


class SourceTests(unittest.TestCase):
    def tearDown(self):
        source = getattr(self, "source", None)
        if source is not None:
            source.stop()

    def test_radar_source_missing_port_degrades_to_error_snapshot(self):
        self.source = RadarSource(port="/tmp/definitely-missing-ld2450-port")

        snapshot = self.source.snapshot()
        self.source.stop()
        self.source.stop()

        self.assertEqual(snapshot._fields, ("tracks", "error", "frames"))
        self.assertEqual(snapshot.tracks, [])
        self.assertIsNotNone(snapshot.error)
        self.assertEqual(snapshot.frames, 0)

    def test_demo_source_reuses_snapshot_within_sensor_window(self):
        clock = FakeClock()
        self.source = DemoSource(scenario="multi", seed=123, clock=clock)

        first = self.source.snapshot()
        clock.advance(0.05)
        repeated = self.source.snapshot()
        clock.advance(0.06)
        second = self.source.snapshot()

        self.assertIs(first, repeated)
        self.assertEqual(first.frames, 1)
        self.assertEqual(second.frames, 2)
        self.assertLessEqual(len(second.tracks), 3)
        self.assertIsNone(second.error)

    def test_demo_source_empty_is_healthy_no_contact(self):
        self.source = DemoSource(scenario="empty", clock=FakeClock())

        snapshot = self.source.snapshot()

        self.assertEqual(snapshot.tracks, [])
        self.assertIsNone(snapshot.error)
        self.assertEqual(snapshot.frames, 1)

    def test_replay_source_skips_malformed_lines_and_tracks_targets(self):
        path = write_replay(
            [
                "not json",
                {
                    "t": 0.0,
                    "seq": 1,
                    "targets": [{"x": 10, "y": 1000, "speed": -5, "resolution": 100}],
                },
            ]
        )
        self.addCleanup(os.unlink, path)
        self.source = ReplaySource(path, realtime=False, loop=False, clock=FakeClock())

        snapshot = self.source.snapshot()

        self.assertEqual(snapshot.frames, 1)
        self.assertEqual(len(snapshot.tracks), 1)
        self.assertEqual(snapshot.tracks[0].id, 1)
        self.assertEqual(snapshot.tracks[0].state, "acquiring")
        self.assertIn("malformed", snapshot.error)

    def test_replay_source_loops_track_fixtures_without_id_collisions(self):
        path = write_replay(
            [
                {
                    "t": 0.0,
                    "seq": 1,
                    "tracks": [
                        {
                            "id": 7,
                            "x": 1,
                            "y": 2,
                            "speed": 3,
                            "state": "live",
                            "age": 0.0,
                            "last_seen": 0.0,
                        }
                    ],
                }
            ]
        )
        self.addCleanup(os.unlink, path)
        self.source = ReplaySource(path, realtime=False, loop=True, clock=FakeClock())

        first = self.source.snapshot()
        second = self.source.snapshot()

        self.assertEqual(first.tracks[0].id, 7)
        self.assertEqual(second.tracks[0].id, 1_000_007)

    def test_replay_source_missing_file_returns_error_snapshot(self):
        self.source = ReplaySource("/tmp/missing-replay-file.ndjson", realtime=False, clock=FakeClock())

        snapshot = self.source.snapshot()

        self.assertEqual(snapshot.tracks, [])
        self.assertIsNotNone(snapshot.error)
        self.assertEqual(snapshot.frames, 0)

    def test_source_exports_and_constructor_signatures_match_contract(self):
        self.assertEqual(sources.__all__, ["RadarSource", "DemoSource", "ReplaySource"])
        self.assertEqual(list(inspect.signature(RadarSource).parameters), ["port", "baud", "orientation"])
        self.assertEqual(list(inspect.signature(DemoSource).parameters), ["scenario", "seed", "clock"])
        self.assertEqual(list(inspect.signature(ReplaySource).parameters), ["path", "loop", "realtime", "clock"])


if __name__ == "__main__":
    unittest.main()

