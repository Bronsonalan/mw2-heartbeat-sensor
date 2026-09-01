import math
import unittest

import ld2450
from ld2450 import Target, parse_frame


def encode_sign_flag(value):
    magnitude = abs(value)
    lo = magnitude & 0xFF
    hi = (magnitude >> 8) & 0x7F
    if value >= 0:
        hi |= 0x80
    return bytes([lo, hi])


def slot(x, y, speed, resolution):
    return (
        encode_sign_flag(x)
        + encode_sign_flag(y)
        + encode_sign_flag(speed)
        + bytes([resolution & 0xFF, (resolution >> 8) & 0xFF])
    )


def frame(*slots):
    payload = b"".join(slots)
    payload += b"\x00" * (24 - len(payload))
    return bytes.fromhex("AA FF 03 00") + payload + bytes.fromhex("55 CC")


class LD2450Tests(unittest.TestCase):
    def test_parse_three_slots_and_drop_empty_slot(self):
        data = frame(slot(-300, 1200, -45, 360), b"\x00" * 8, slot(42, -99, 12, 7))

        targets = parse_frame(data)

        self.assertEqual(
            targets,
            [Target(-300, 1200, -45, 360), Target(42, -99, 12, 7)],
        )
        self.assertTrue(targets[0].approaching)
        self.assertAlmostEqual(targets[0].distance, math.hypot(-300, 1200))
        self.assertLess(targets[0].angle, 0)

    def test_sign_flag_encoding_is_not_twos_complement(self):
        target = parse_frame(frame(slot(-300, 300, -2, 3)))[0]

        self.assertEqual(target.x, -300)
        self.assertEqual(target.y, 300)
        self.assertEqual(target.speed, -2)

    def test_invalid_frame_header_tail_or_length_raises_value_error(self):
        valid = frame(slot(1, 2, 3, 4))
        self.assertEqual(len(valid), 30)

        with self.assertRaises(ValueError):
            parse_frame(b"\x00" + valid[1:])
        with self.assertRaises(ValueError):
            parse_frame(valid[:-2] + b"\x00\x00")
        with self.assertRaises(ValueError):
            parse_frame(valid[:-1])

    def test_module_exports_match_contract_surface(self):
        self.assertEqual(ld2450.__all__, ["Target", "parse_frame"])


if __name__ == "__main__":
    unittest.main()

