from __future__ import annotations

import unittest

from test.contract_support import (
    assert_field_order,
    optional_import,
)


class CrossLayerSnapshotContractTests(unittest.TestCase):
    def _source_layers(self):
        sources = optional_import(self, "sources")
        simulator = optional_import(self, "simulator")
        return sources, simulator

    def test_source_snapshot_shapes_do_not_diverge(self) -> None:
        sources, simulator = self._source_layers()
        if hasattr(sources, "SourceSnapshot") and hasattr(simulator, "SourceSnapshot"):
            assert_field_order(self, sources.SourceSnapshot, ("tracks", "error", "frames"))
            assert_field_order(self, simulator.SourceSnapshot, ("tracks", "error", "frames"))


if __name__ == "__main__":
    unittest.main()

