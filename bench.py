"""Small serial bench tool for HLK-LD2450 data on /dev/serial0."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Callable, TextIO

from ld2450 import Target
from ld2450 import _FrameParser


__all__ = ["main"]


def _target_dict(target: Target) -> dict[str, int]:
    return {
        "x": target.x,
        "y": target.y,
        "speed": target.speed,
        "resolution": target.resolution,
    }


def _default_serial_factory():
    try:
        import serial  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"serial package unavailable: {exc}") from exc
    return serial.Serial


def _open_serial(serial_factory: Callable[..., object], port: str, baud: int, timeout: float) -> object:
    try:
        return serial_factory(port=port, baudrate=baud, timeout=timeout)
    except TypeError:
        return serial_factory(port, baud, timeout=timeout)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect raw HLK-LD2450 serial data")
    parser.add_argument("--port", default="/dev/serial0")
    parser.add_argument("--baud", type=int, default=256000)
    parser.add_argument("--hex", action="store_true", help="print raw serial chunks as hex")
    parser.add_argument("--ndjson", action="store_true", help="print parsed frames as newline-delimited JSON")
    parser.add_argument("--count", type=int, default=None, help="stop after this many serial reads")
    parser.add_argument("--read-size", type=int, default=256)
    parser.add_argument("--timeout", type=float, default=0.3)
    return parser


def main(
    argv: list[str] | None = None,
    *,
    serial_factory: Callable[..., object] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    args = _build_arg_parser().parse_args(argv)
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    if not args.hex and not args.ndjson:
        args.hex = True

    try:
        factory = _default_serial_factory() if serial_factory is None else serial_factory
        stream = _open_serial(factory, args.port, args.baud, args.timeout)
    except Exception as exc:
        stderr.write(f"bench: {exc}\n")
        return 1

    parser = _FrameParser()
    reads = 0
    frames = 0
    try:
        while args.count is None or reads < args.count:
            try:
                data = stream.read(args.read_size)  # type: ignore[attr-defined]
            except Exception as exc:
                stderr.write(f"bench: serial read failed: {exc}\n")
                return 1
            reads += 1
            if not data:
                continue
            if args.hex:
                stdout.write(bytes(data).hex(" ") + "\n")
            if args.ndjson:
                for targets in parser.feed(data):
                    frames += 1
                    stdout.write(
                        json.dumps(
                            {
                                "frame": frames,
                                "targets": [_target_dict(target) for target in targets],
                            },
                            separators=(",", ":"),
                        )
                        + "\n"
                    )
    finally:
        close = getattr(stream, "close", None)
        if close is not None:
            close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

