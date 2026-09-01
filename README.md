# MW2 Heartbeat Sensor

Raspberry Pi app for reading an HLK-LD2450 radar sensor, tracking moving contacts, and rendering a fullscreen MW2-inspired phosphor radar HUD.

## Contents

- `DATA_CONTRACT.md`: hardware, serial, parser, tracking, replay, and simulator contracts.
- `UI_SPEC.md`: the current phosphor HUD target.
- `fixtures/walk-01.ndjson`: replay fixture for development without hardware.
- `assets/phosphor/`: phosphor image assets and manifest.
- `deploy/`: Raspberry Pi setup notes.
- `test/`: expected test coverage.

## Ground Rules

- Use Python standard library plus apt packages only.
- Do not add package-manager lockfiles or dependency manifests.
- Keep real hardware optional for desktop replay and demo runs.

## Target Runtime

Raspberry Pi OS Bookworm 64-bit:

```bash
sudo apt update
sudo apt install -y python3-serial python3-pygame
```

Development should also run on a laptop in replay/demo mode when those packages are available.

## Expected Public Repo Shape

```text
.
|-- README.md
|-- DATA_CONTRACT.md
|-- UI_SPEC.md
|-- fixtures/
|-- assets/
|-- deploy/
|-- test/
|-- ld2450.py
|-- tracking.py
|-- sources.py
|-- simulator.py
|-- replay.py
|-- radar.py
`-- bench.py
```

This repository starts with the contracts, fixture, and assets. The source files above are the intended implementation surface for the project.

## Minimum Demo

The first public demo should support:

```bash
python3 radar.py --source replay --fixture fixtures/walk-01.ndjson --ui phosphor --selftest 90 --screenshot out.png
python3 radar.py --source demo --scenario multi --ui phosphor
python3 radar.py --source live --port /dev/serial0 --ui phosphor --fullscreen --invert-x
```

The first two commands must work without the sensor. The live command is the Raspberry Pi hardware path.

## License

License will be added after the copyright owner is confirmed.
