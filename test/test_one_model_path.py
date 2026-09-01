from __future__ import annotations

import ast
import inspect
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import ld2450
import radar
import replay
import simulator
import sources
import tracking


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_LOCAL_MODEL_CLASSES = {
    "Target",
    "Track",
    "SourceSnapshot",
    "SimpleTracker",
    "Orientation",
}


def _class_names_defined_in(module_name: str) -> set[str]:
    module_path = ROOT / f"{module_name}.py"
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}


class ModelPathImportTests(unittest.TestCase):
    def test_ui_layers_do_not_define_model_classes(self) -> None:
        for module_name in ("simulator", "replay", "radar"):
            with self.subTest(module=module_name):
                defined = _class_names_defined_in(module_name)
                self.assertFalse(
                    FORBIDDEN_LOCAL_MODEL_CLASSES & defined,
                    f"{module_name}.py must import shared model classes, not define them",
                )

    def test_simulator_reexports_canonical_model_types(self) -> None:
        self.assertIs(simulator.Target, ld2450.Target)
        self.assertIs(simulator.Track, tracking.Track)
        self.assertIs(simulator.SourceSnapshot, sources.SourceSnapshot)
        self.assertIs(simulator.Orientation, tracking.Orientation)

    def test_replay_uses_canonical_model_and_tracker_types(self) -> None:
        self.assertIs(replay.Target, ld2450.Target)
        self.assertIs(replay.Track, tracking.Track)
        self.assertIs(replay.SourceSnapshot, sources.SourceSnapshot)
        self.assertIs(replay.Orientation, tracking.Orientation)
        self.assertIs(replay.Tracker, tracking.Tracker)

        source = replay.ReplaySource(str(ROOT / "fixtures" / "walk-01.ndjson"), realtime=False)
        self.assertIsInstance(source._tracker, tracking.Tracker)

    def test_radar_uses_canonical_source_classes(self) -> None:
        self.assertIs(radar.RadarSource, sources.RadarSource)
        self.assertIs(radar.DemoSource, simulator.DemoSource)
        self.assertIs(radar.ReplaySource, replay.ReplaySource)

    def test_simple_tracker_is_not_exposed_as_a_class(self) -> None:
        for module in (simulator, replay):
            with self.subTest(module=module.__name__):
                self.assertFalse(
                    inspect.isclass(getattr(module, "SimpleTracker", None)),
                    f"{module.__name__}.SimpleTracker must not remain as a class",
                )


class RadarLiveSourceTests(unittest.TestCase):
    def test_live_cli_source_constructs_radar_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_port = str(Path(temp_dir) / "missing-serial")
            args = radar.build_parser().parse_args(
                [
                    "--source",
                    "live",
                    "--port",
                    missing_port,
                    "--baud",
                    "115200",
                    "--swap-xy",
                    "--invert-x",
                ]
            )
            source = radar.make_source(args)
            try:
                self.assertIsInstance(source, sources.RadarSource)
                self.assertEqual(source.port, missing_port)
                self.assertEqual(source.baud, 115200)
                self.assertEqual(source.tracker.orientation, tracking.Orientation(swap_xy=True, invert_x=True))
            finally:
                source.stop()

    def test_live_missing_port_snapshot_renders_sensor_offline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_port = str(Path(temp_dir) / "missing-serial")
            args = radar.build_parser().parse_args(["--source", "live", "--port", missing_port])
            source = radar.make_source(args)
            try:
                snapshot = source.snapshot()
                self.assertIsInstance(source, sources.RadarSource)
                self.assertTrue(snapshot.error)
                renderer = radar.PhosphorRenderer(scanlines=False)
                with mock.patch("radar.draw_text", wraps=radar.draw_text) as draw_text:
                    renderer.render(snapshot, now=0.0)
                self.assertIn("SENSOR OFFLINE", [call.args[1] for call in draw_text.call_args_list])
            finally:
                source.stop()


if __name__ == "__main__":
    unittest.main()
