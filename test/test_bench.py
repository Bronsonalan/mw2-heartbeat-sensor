import io
import json
import unittest

import bench


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


class FakeSerial:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.closed = False

    def read(self, size):
        if self.chunks:
            return self.chunks.pop(0)
        return b""

    def close(self):
        self.closed = True


class BenchTests(unittest.TestCase):
    def test_ndjson_mode_prints_parsed_frames_with_fake_serial(self):
        fake = FakeSerial([frame(slot(-30, 1000, -4, 99))])
        stdout = io.StringIO()
        stderr = io.StringIO()

        code = bench.main(
            ["--port", "fake", "--ndjson", "--count", "1"],
            serial_factory=lambda **kwargs: fake,
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(code, 0)
        self.assertEqual(stderr.getvalue(), "")
        event = json.loads(stdout.getvalue())
        self.assertEqual(event["frame"], 1)
        self.assertEqual(event["targets"][0]["x"], -30)
        self.assertEqual(event["targets"][0]["speed"], -4)
        self.assertTrue(fake.closed)

    def test_default_mode_prints_hex_chunks(self):
        fake = FakeSerial([b"\xAA\xFF"])
        stdout = io.StringIO()

        code = bench.main(
            ["--port", "fake", "--count", "1"],
            serial_factory=lambda **kwargs: fake,
            stdout=stdout,
            stderr=io.StringIO(),
        )

        self.assertEqual(code, 0)
        self.assertEqual(stdout.getvalue(), "aa ff\n")

    def test_open_error_returns_nonzero_instead_of_raising(self):
        stderr = io.StringIO()

        code = bench.main(
            ["--port", "fake", "--count", "1"],
            serial_factory=lambda **kwargs: (_ for _ in ()).throw(OSError("no serial")),
            stdout=io.StringIO(),
            stderr=stderr,
        )

        self.assertEqual(code, 1)
        self.assertIn("no serial", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()

