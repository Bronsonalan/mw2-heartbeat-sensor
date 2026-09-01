# Test Plan

The test layer catches contract drift between the radar data implementation and
the replay/UI implementation. It is intentionally written with Python
`unittest` and the standard library only.

## How to Run

Run the repository gate from the repo root:

```bash
python3 -m unittest discover -s test -t .
```

GitHub Actions runs the same command on pull requests and pushes to `main`.

## What Runs on Main Today

These tests run even when implementation modules such as `ld2450.py`,
`tracking.py`, `sources.py`, `replay.py`, `simulator.py`, and `radar.py` are not
present:

- `fixtures/walk-01.ndjson` is newline-delimited JSON.
- Blank fixture lines are allowed.
- Each fixture object has `t`, `seq`, and exactly one of `targets` or `tracks`.
- Fixture `t` values are non-decreasing and `seq` values strictly increase.
- Fixture JSON does not contain `NaN`, `Infinity`, or `-Infinity`.
- `assets/phosphor/manifest.json` matches `UI_SPEC.md` for profile, size,
  target FPS, travel/dwell timing, travel frames, and dwell index.
- The phosphor asset pack contains exactly `face.png`, `sweep_00.png` through
  `sweep_26.png`, and `manifest.json`, with manifest byte counts and SHA-256
  values matching the files.
- Dependency-manager manifests (`requirements.txt`, `pyproject.toml`,
  `Pipfile`, `poetry.lock`, `package.json`) are absent.

## What Activates After Modules Land

The implementation-facing tests use skip-if-missing imports. Once a module file
exists, import or contract failures are real test failures.

Data-side coverage includes:

- `Target(x, y, speed, resolution)` field order.
- LD2450 sign-flag decoding golden cases, including byte pairs that signed
  int16 parsing would decode incorrectly.
- Dropping all-zero target slots and treating an empty target list as healthy.
- `Track(id, x, y, speed, state, age, last_seen)` field order and the
  `acquiring`, `live`, and `fading` states.
- Tracker constants: 600 mm gate, 0.4 position alpha, 0.25 speed alpha,
  3-frame confirmation, 0.8 s grace, sticky confirmation, fading/drop on empty
  input, and monotonic never-reused IDs.
- `RadarSource(port, baud, orientation)`, `DemoSource(scenario, seed, clock)`,
  and `ReplaySource(path, loop, realtime, clock)` constructor shapes.
- Source `snapshot()`/`stop()` behavior and snapshot shape:
  `tracks`, `error`, and `frames`.

UI/replay-side coverage includes:

- Simulator `Target` and `Track` field order.
- Demo scenarios `walk`, `cross`, `still`, `empty`, and `multi`, with no more
  than three simultaneous tracks.
- Replay source snapshot behavior for empty target frames.
- Radar CLI flags from `UI_SPEC.md`, including `--source`, `--fixture`,
  `--scenario`, `--ui`, `--selftest`, `--screenshot`, `--invert-x`,
  `--swap-xy`, sweep reveal flags, FPS, and scanline controls.
- Distance pill labels: `--.-m`, one-decimal meters, and `>6 M`.

When both data-side `sources.py` and UI-side `replay.py`/`simulator.py` exist,
cross-layer tests assert that both implementations expose the same source
snapshot contract instead of choosing one side as canonical.

## Required Test Areas

- LD2450 frame header/tail recognition.
- Sign-flag coordinate decoding.
- Empty target slot removal.
- Three-slot frame parsing.
- Tracker confirmation after three frames.
- Tracker fading and drop after empty input.
- Monotonic track IDs.
- Replay fixture parsing.
- Malformed replay line handling.
- Demo source scenarios.
- Source snapshot contract.
- Source constructor signatures.
- CLI launch flags.
- Launcher environment-to-argv mapping.
- Screenshot self-test creation.
- Fixture conformance: line-delimited JSON, non-decreasing `t`, strictly
  increasing `seq`, no NaN/Infinity.

## Desktop Gate

The desktop gate should pass without the radar sensor attached:
Replay and demo mode must pass without the radar sensor attached.

```bash
python3 -m unittest discover -s test -t .
python3 radar.py --source replay --fixture fixtures/walk-01.ndjson --ui phosphor --selftest 90 --screenshot out/phosphor-replay.png
python3 radar.py --source demo --scenario multi --ui phosphor --selftest 120 --screenshot out/phosphor-demo.png
```

## Pi Gate

The Pi gate requires hardware:

```bash
python3 bench.py --port /dev/serial0 --baud 256000 --hex
python3 bench.py --port /dev/serial0 --baud 256000 --ndjson
python3 radar.py --source live --port /dev/serial0 --baud 256000 --ui phosphor --fullscreen --invert-x
```

## Review Checklist

For RAY/data PRs:

- Parser uses LD2450 sign-flag encoding, not two's complement.
- All-zero slots are dropped and empty target lists are healthy.
- Tracker constants and state transitions match `DATA_CONTRACT.md`.
- Source snapshots keep empty tracks distinct from sensor errors.
- Live-source failures publish error strings instead of crashing UI loops.

For IRIS/UI PRs:

- Replay, simulator, and radar CLI stay aligned with `DATA_CONTRACT.md` and
  `UI_SPEC.md`.
- Demo/replay sources expose the same snapshot shape as data sources.
- Demo scenarios remain deterministic with an injectable clock and stay capped
  at three simultaneous tracks.
- Distance pill labels match the UI spec.
- Phosphor rendering uses validated assets or clearly reports asset mismatch.

## Visual Smoke Test

Generated screenshots should show the phosphor HUD, sweep state, contact pips,
and distance pill clearly. Pixel-perfect output is not required unless the
implementation deliberately reuses the supplied asset pack and matching
geometry.

## Hygiene Gate

- No package-manager dependency manifests.
- No secrets.
- No local machine paths.
