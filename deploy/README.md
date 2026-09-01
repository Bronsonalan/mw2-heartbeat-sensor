# Deploy Notes

These notes define the Raspberry Pi deployment target for the project.

## Pi Packages

```bash
sudo apt update
sudo apt install -y python3-serial python3-pygame
```

Do not require Python or JavaScript package-manager installs for the video build.

## Pi Serial Setup

The HLK-LD2450 should be connected to the primary UART exposed as `/dev/serial0`.

Required Pi setup:

```bash
sudo raspi-config
```

In the serial interface settings:

- Login shell over serial: disabled.
- Serial hardware: enabled.

Also ensure:

```bash
sudo systemctl disable --now serial-getty@ttyAMA0.service
sudo usermod -aG dialout "$USER"
```

Reboot after changing serial or group membership.

## Runtime Environment

The deploy profile should default to the phosphor UI and live hardware:

```text
MW2_RADAR_MODE=live
MW2_RADAR_PORT=/dev/serial0
MW2_RADAR_BAUD=256000
MW2_RADAR_UI=phosphor
MW2_RADAR_SWAP_XY=0
MW2_RADAR_INVERT_X=1
```

`MW2_RADAR_INVERT_X=1` matches the measured video build orientation.

The launcher should understand exactly three modes:

```text
live
demo
replay
```

In replay mode, require `MW2_RADAR_FIXTURE` to point at an NDJSON fixture file.

`MW2_RADAR_PORT` is passed only in live mode. `MW2_RADAR_UI` accepts `phosphor` or `template`, with `phosphor` as the deploy default and `template` as a rollback profile.

## Smoke Commands

Run replay first:

```bash
python3 radar.py --source replay --fixture fixtures/walk-01.ndjson --ui phosphor --selftest 90 --screenshot out.png
```

Then run demo mode:

```bash
python3 radar.py --source demo --scenario multi --ui phosphor
```

Then run live hardware:

```bash
python3 radar.py --source live --port /dev/serial0 --baud 256000 --ui phosphor --fullscreen --invert-x
```

## Bench Commands

The project should provide a simple serial bench tool:

```bash
python3 bench.py --port /dev/serial0 --baud 256000 --hex
python3 bench.py --port /dev/serial0 --baud 256000 --ndjson
```

Use the bench output to confirm the Pi sees valid LD2450 frames before debugging the HUD.
