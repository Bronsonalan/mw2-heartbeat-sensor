import unittest

from ld2450 import Target
from tracking import Orientation, Tracker


class TrackingTests(unittest.TestCase):
    def test_confirmation_stable_id_orientation_and_empty_drop(self):
        tracker = Tracker(orientation=Orientation(invert_x=True))
        target = Target(100, 1000, -20, 360)

        first = tracker.update([target], now=0.0)
        second = tracker.update([target], now=0.1)
        third = tracker.update([target], now=0.2)

        self.assertEqual(first[0].id, second[0].id)
        self.assertEqual(second[0].id, third[0].id)
        self.assertEqual(third[0].state, "live")
        self.assertEqual(third[0].x, -100)
        self.assertTrue(third[0].approaching)

        fading = tracker.update([], now=0.6)
        self.assertEqual(fading[0].state, "fading")
        self.assertEqual(fading[0].id, third[0].id)

        self.assertEqual(tracker.update([], now=1.1), [])

    def test_confirmed_track_returns_live_during_grace_period(self):
        tracker = Tracker()
        target = Target(0, 1200, 0, 100)
        tracker.update([target], now=0.0)
        tracker.update([target], now=0.1)
        live = tracker.update([target], now=0.2)[0]

        fading = tracker.update([], now=0.5)[0]
        returned = tracker.update([Target(20, 1210, 4, 100)], now=0.6)[0]

        self.assertEqual(live.state, "live")
        self.assertEqual(fading.state, "fading")
        self.assertEqual(returned.id, live.id)
        self.assertEqual(returned.state, "live")

    def test_track_ids_are_monotonic_and_not_reused(self):
        tracker = Tracker()
        first = tracker.update([Target(0, 1000, 0, 1)], now=0.0)[0]
        tracker.update([], now=1.0)

        second = tracker.update([Target(2000, 1000, 0, 1)], now=1.1)[0]

        self.assertGreater(second.id, first.id)

    def test_nearest_neighbor_uses_shortest_global_pairs_first(self):
        tracker = Tracker(confirmation_frames=1)
        tracker.update([Target(0, 1000, 0, 1), Target(500, 1000, 0, 1)], now=0.0)

        tracks = tracker.update([Target(480, 1000, 0, 1), Target(20, 1000, 0, 1)], now=0.1)

        self.assertEqual([track.id for track in tracks], [1, 2])
        self.assertLess(tracks[0].x, 100)
        self.assertGreater(tracks[1].x, 400)


if __name__ == "__main__":
    unittest.main()

