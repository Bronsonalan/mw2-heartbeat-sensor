# Data Contract

This file defines the behavior the project must match before the video build is considered usable.

## Hardware Target

- Host: Raspberry Pi 4 Model B, 8 GB.
- OS: Raspberry Pi OS Bookworm 64-bit.
- Display runtime: pygame fullscreen on the Pi.
- Sensor: HLK-LD2450 24 GHz radar module.
- Serial path on Pi: `/dev/serial0`.
- Serial mapping: `/dev/serial0` should point to `ttyAMA0`.
- Bluetooth serial must be disabled on the Pi build.
- `serial-getty` on the sensor UART must be disabled.
- Runtime user must be in the `dialout` group.

## Wiring

- LD2450 VCC -> Pi 5V pin 2 or pin 4.
- LD2450 GND -> Pi GND pin 6.
- LD2450 RX -> Pi TXD pin 8.
- LD2450 TX -> Pi RXD pin 10.
- Do not swap TX/RX beyond the mapping above.

## Serial Stream

- Baud: `256000`.
- Format: 8N1.
- Expected update cadence: about 10 Hz.
- Frame length: 30 bytes.
- Header: `AA FF 03 00`.
- Tail: `55 CC`.
- Payload: three target slots, eight bytes per slot.

## Target Slots

Each frame contains exactly three target slots. Each slot reports:

- `x_mm`
- `y_mm`
- `speed_cm_s`
- `resolution`

An all-zero slot is empty and must be dropped.

An empty target list is a healthy no-contact state. It is not an error.

## Target Shape

The parsed target shape should have these fields in this order:

```text
Target(x: int, y: int, speed: int, resolution: int)
```

Derived values:

- `distance`: straight-line distance in millimeters.
- `angle`: bearing in degrees, where 0 is straight ahead and negative is the minus-x side.
- `approaching`: true when `speed < 0`.

## Signed Values

LD2450 coordinate and speed values are sign-flag encoded, not two's complement.

Use this rule:

```text
value = ((hi & 0x7f) << 8) | lo
if hi has bit 7 set, value is positive
if hi has bit 7 clear, value is negative
```

Do not parse these fields as ordinary signed 16-bit integers.

## Coordinate Orientation

The implementation should support runtime orientation flags:

- `swap_xy`
- `invert_x`

The measured video build uses:

```text
swap_xy = false
invert_x = true
```

The physical sensor board was mounted tall, with the long axis vertical. A wide mount collapsed usable azimuth in the working build.

Orientation is applied once, at the raw-target-to-track boundary:

```text
Orientation(swap_xy: bool = false, invert_x: bool = false)
```

Apply `swap_xy` first, then `invert_x`.

## Tracking Contract

The tracker consumes parsed raw targets and emits stable display tracks.

The display track shape should have these fields in this order:

```text
Track(id: int, x: int, y: int, speed: int, state: str, age: float, last_seen: float)
```

Derived values match `Target`:

- `distance`: straight-line distance in millimeters.
- `angle`: bearing in degrees.
- `approaching`: true when `speed < 0`.

Required behavior:

- Association gate: `600 mm`.
- Position smoothing alpha: `0.4`.
- Speed smoothing alpha: `0.25`.
- Confirmation threshold: `3 frames`.
- Grace period before drop: `0.8 seconds`.
- Track IDs are monotonic and never reused.
- Track states: `acquiring`, `live`, `fading`.
- Confirmation is sticky. A confirmed track that disappears briefly and returns should come back as `live`, not restart as `acquiring`.
- Association should be nearest-neighbor by shortest global pair first, with no pair beyond the 600 mm gate.
- Empty input must age, fade, and drop tracks. It must not create placeholder tracks.
- Distances stay in millimeters internally.
- Display may divide by 1000 for meters.
- Speed stays in centimeters per second internally.

The LD2450 tracks motion, not bodies. A stationary person may disappear.

## Source Contract

All runtime data sources should expose the same snapshot shape:

```text
tracks: list of display tracks
error: None when healthy, otherwise a user-visible error string
frames: count of parsed or emitted frames
```

The source snapshot call must:

- Take no arguments.
- Return quickly.
- Not raise for ordinary sensor absence, malformed fixture lines, or disconnected serial.
- Keep empty tracks distinct from sensor error.

The source stop call must be safe to call more than once.

Recommended constructor shapes:

```text
RadarSource(port: str = "/dev/serial0", baud: int = 256000, orientation: Orientation = Orientation())
DemoSource(scenario: str = "walk", seed: int | None = None, clock = time.monotonic)
ReplaySource(path: str, loop: bool = true, realtime: bool = true, clock = time.monotonic)
```

## Live Source

The live source should read serial in the background and publish snapshots.

Recommended behavior:

- Missing serial package: publish an error string.
- Missing port: publish an error string.
- Sensor silence after about 2 seconds: publish an error string.
- Retry serial open with bounded backoff.
- Keep the UI loop alive even when live hardware is absent.

Reference timing constants from the working build:

```text
idle tick: 0.5 s
silence error: 2.0 s
retry min: 0.5 s
retry max: 5.0 s
read timeout: 0.3 s
read size: 256 bytes
```

## Demo Source

The demo source exists for filming and desktop work without hardware.

Required scenarios:

- `walk`
- `cross`
- `still`
- `empty`
- `multi`

Recommended behavior:

- Emit at 0.1 second intervals.
- Cap catch-up work per snapshot.
- Resync after long pauses.
- Produce display tracks directly.
- Return the same snapshot when called repeatedly within one 0.1 second sensor window.
- Keep frame counts monotonic.
- Use the random seed and injectable clock to make tests deterministic.
- Never emit more than three simultaneous tracks.
- Avoid requiring serial hardware.

## Replay Source

Replay fixtures use newline-delimited JSON.

Each line is one object with:

- `t`: fixture timestamp.
- `seq`: increasing sequence number.
- exactly one of `targets` or `tracks`.

Rules:

- Repeated `t` values are allowed.
- In fixtures, `t` should be non-decreasing and `seq` should strictly increase.
- Sequence gaps are legal.
- Do not wrap the file in a JSON array.
- Do not emit NaN or Infinity.
- Unknown keys should be ignored.
- Blank lines should be ignored.
- Malformed lines should be counted, skipped, and surfaced as an error string.
- Missing, unreadable, empty, or fully malformed files should surface an error string instead of raising.
- Target fixtures must pass through the tracker.
- Track fixtures may construct display tracks directly.
- Looping replay should offset timestamps and avoid ID collisions.
- `realtime=false` should advance one frame per snapshot call.
- `realtime=true` should consume all frames whose `t` is due and display the last due frame.
- One snapshot call should consume at most 500 replay frames.
