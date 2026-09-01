import inspect
import unittest

import sources
from sources import RadarSource


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

    def test_source_exports_and_constructor_signatures_match_contract(self):
        self.assertEqual(sources.__all__, ["RadarSource"])
        self.assertEqual(list(inspect.signature(RadarSource).parameters), ["port", "baud", "orientation"])


if __name__ == "__main__":
    unittest.main()

