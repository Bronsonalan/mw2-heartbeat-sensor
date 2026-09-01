from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import unittest

from test.contract_support import ROOT


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON value {value}")


def _assert_finite_json(testcase: unittest.TestCase, value, label: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _assert_finite_json(testcase, child, f"{label}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_finite_json(testcase, child, f"{label}[{index}]")
    elif isinstance(value, float):
        testcase.assertTrue(math.isfinite(value), f"{label} must be finite")


def _png_size(path) -> tuple[int, int]:
    with open(path, "rb") as handle:
        header = handle.read(24)
    if len(header) < 24 or not header.startswith(b"\x89PNG\r\n\x1a\n"):
        raise AssertionError(f"{path} is not a PNG file")
    if header[12:16] != b"IHDR":
        raise AssertionError(f"{path} is missing a PNG IHDR chunk")
    return struct.unpack(">II", header[16:24])


class FixtureContractTests(unittest.TestCase):
    def test_walk_fixture_is_valid_ndjson_contract(self) -> None:
        fixture = ROOT / "fixtures" / "walk-01.ndjson"
        self.assertTrue(fixture.is_file(), "fixtures/walk-01.ndjson must exist")

        last_t: float | None = None
        last_seq: int | None = None
        nonblank = 0
        with fixture.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                nonblank += 1
                try:
                    record = json.loads(line, parse_constant=_reject_json_constant)
                except ValueError as exc:
                    self.fail(f"line {line_number} is not valid finite JSON: {exc}")

                self.assertIsInstance(record, dict, f"line {line_number} must be an object")
                self.assertIn("t", record, f"line {line_number} missing t")
                self.assertIn("seq", record, f"line {line_number} missing seq")
                has_targets = "targets" in record
                has_tracks = "tracks" in record
                self.assertNotEqual(
                    has_targets,
                    has_tracks,
                    f"line {line_number} must contain exactly one of targets or tracks",
                )

                t_value = record["t"]
                seq_value = record["seq"]
                self.assertIsInstance(t_value, (int, float), f"line {line_number} t must be numeric")
                self.assertFalse(isinstance(t_value, bool), f"line {line_number} t must not be bool")
                self.assertTrue(math.isfinite(float(t_value)), f"line {line_number} t must be finite")
                self.assertIsInstance(seq_value, int, f"line {line_number} seq must be int")
                self.assertFalse(isinstance(seq_value, bool), f"line {line_number} seq must not be bool")

                if last_t is not None:
                    self.assertGreaterEqual(
                        float(t_value),
                        last_t,
                        f"line {line_number} t must be non-decreasing",
                    )
                if last_seq is not None:
                    self.assertGreater(
                        seq_value,
                        last_seq,
                        f"line {line_number} seq must strictly increase",
                    )
                last_t = float(t_value)
                last_seq = seq_value

                items = record["targets"] if has_targets else record["tracks"]
                self.assertIsInstance(items, list, f"line {line_number} payload must be a list")
                _assert_finite_json(self, record, f"line {line_number}")

        self.assertGreater(nonblank, 0, "fixture must contain at least one data line")


class PhosphorAssetContractTests(unittest.TestCase):
    def test_phosphor_manifest_and_files_match_ui_spec(self) -> None:
        asset_dir = ROOT / "assets" / "phosphor"
        manifest_path = asset_dir / "manifest.json"
        self.assertTrue(manifest_path.is_file(), "assets/phosphor/manifest.json must exist")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        expected_values = {
            "profile": "phosphor",
            "size": [640, 480],
            "target_fps": 30,
            "travel_seconds": 0.85,
            "dwell_seconds": 0.35,
            "travel_frames": 26,
            "dwell_index": 26,
        }
        for key, expected in expected_values.items():
            self.assertEqual(manifest.get(key), expected, f"manifest {key} mismatch")

        expected_pngs = ["face.png"] + [f"sweep_{index:02d}.png" for index in range(27)]
        expected_files = set(expected_pngs + ["manifest.json"])
        actual_files = {path.name for path in asset_dir.iterdir() if path.is_file()}
        self.assertEqual(actual_files, expected_files)

        assets = manifest.get("assets")
        self.assertIsInstance(assets, list, "manifest assets must be a list")
        by_name = {asset.get("file"): asset for asset in assets if isinstance(asset, dict)}
        self.assertEqual(set(by_name), set(expected_pngs))

        for filename in expected_pngs:
            path = asset_dir / filename
            self.assertTrue(path.is_file(), f"{filename} must exist")
            self.assertEqual(_png_size(path), (640, 480), f"{filename} must be 640x480")

            asset = by_name[filename]
            data = path.read_bytes()
            self.assertEqual(asset.get("bytes"), len(data), f"{filename} byte count mismatch")
            self.assertEqual(
                asset.get("sha256"),
                hashlib.sha256(data).hexdigest(),
                f"{filename} sha256 mismatch",
            )


class RepositoryHygieneTests(unittest.TestCase):
    def test_no_dependency_manager_manifests(self) -> None:
        disallowed = {"requirements.txt", "pyproject.toml", "Pipfile", "poetry.lock", "package.json"}
        found: list[str] = []
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [
                dirname
                for dirname in dirnames
                if dirname not in {".git", "__pycache__", ".pytest_cache", ".mypy_cache"}
            ]
            for filename in filenames:
                if filename in disallowed:
                    found.append(str((ROOT / os.path.relpath(os.path.join(dirpath, filename), ROOT))))
        self.assertEqual(found, [], "do not add dependency-manager manifests")


if __name__ == "__main__":
    unittest.main()

