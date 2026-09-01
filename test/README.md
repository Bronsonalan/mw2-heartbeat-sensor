# Test Plan

The project should include tests before the live hardware path is treated as complete.

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
- Fixture conformance: line-delimited JSON, non-decreasing `t`, strictly increasing `seq`, no NaN/Infinity.

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

## Visual Smoke Test

Generated screenshots should show the phosphor HUD, sweep state, contact pips, and distance pill clearly. Pixel-perfect output is not required unless the implementation deliberately reuses the supplied asset pack and matching geometry.

## Hygiene Gate

- No package-manager dependency manifests.
- No secrets.
- No local machine paths.
