from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from test.contract_support import (
    ManualClock,
    assert_constructor_prefix,
    assert_field_order,
    assert_snapshot_method_takes_no_args,
    assert_snapshot_shape,
    assert_stop_idempotent,
    optional_import,
)


class CrossLayerSnapshotContractTests(unittest.TestCase):
    def _both_layers(self):
        sources = optional_import(self, "sources")
        replay = optional_import(self, "replay")
        simulator = optional_import(self, "simulator")
        return sources, replay, simulator

    def test_source_snapshot_shapes_do_not_diverge(self) -> None:
        sources, replay, simulator = self._both_layers()
        if hasattr(sources, "SourceSnapshot") and hasattr(simulator, "SourceSnapshot"):
            assert_field_order(self, sources.SourceSnapshot, ("tracks", "error", "frames"))
            assert_field_order(self, simulator.SourceSnapshot, ("tracks", "error", "frames"))

        assert_constructor_prefix(self, sources.DemoSource, ("scenario", "seed", "clock"))
        assert_constructor_prefix(self, simulator.DemoSource, ("scenario", "seed", "clock"))
        assert_constructor_prefix(self, sources.ReplaySource, ("path", "loop", "realtime", "clock"))
        assert_constructor_prefix(self, replay.ReplaySource, ("path", "loop", "realtime", "clock"))

    def test_demo_sources_share_snapshot_contract_for_all_scenarios(self) -> None:
        sources, _replay, simulator = self._both_layers()
        for module in (sources, simulator):
            for scenario in ("walk", "cross", "still", "empty", "multi"):
                with self.subTest(module=module.__name__, scenario=scenario):
                    clock = ManualClock()
                    source = module.DemoSource(scenario=scenario, seed=123, clock=clock)
                    assert_snapshot_method_takes_no_args(self, source)
                    snapshot = source.snapshot()
                    assert_snapshot_shape(self, snapshot)
                    self.assertIsNone(snapshot.error)
                    self.assertLessEqual(len(snapshot.tracks), 3)
                    assert_stop_idempotent(self, source)

    def test_replay_sources_share_empty_snapshot_contract(self) -> None:
        sources, replay, _simulator = self._both_layers()
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir) / "empty.ndjson"
            fixture.write_text('{"t": 0.0, "seq": 1, "targets": []}\n', encoding="utf-8")
            for module in (sources, replay):
                with self.subTest(module=module.__name__):
                    clock = ManualClock()
                    source = module.ReplaySource(str(fixture), loop=False, realtime=False, clock=clock)
                    assert_snapshot_method_takes_no_args(self, source)
                    snapshot = source.snapshot()
                    assert_snapshot_shape(self, snapshot)
                    self.assertEqual(snapshot.tracks, [])
                    self.assertIsNone(snapshot.error, "empty tracks must not be treated as source failure")
                    assert_stop_idempotent(self, source)


if __name__ == "__main__":
    unittest.main()

