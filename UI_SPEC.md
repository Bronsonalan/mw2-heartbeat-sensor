# UI Spec

Phosphor is the canonical on-camera UI for the project.

## Launch Target

Required launch profile:

```bash
python3 radar.py --source replay --fixture fixtures/walk-01.ndjson --ui phosphor --selftest 90 --screenshot out.png
python3 radar.py --source demo --scenario multi --ui phosphor
python3 radar.py --source live --port /dev/serial0 --ui phosphor --fullscreen --invert-x
```

Required CLI options:

- `--source live|demo|replay`
- `--demo`
- `--port`
- `--baud`
- `--fixture`
- `--scenario`
- `--fullscreen`
- `--ui template|phosphor`
- `--swap-xy`
- `--invert-x`
- `--size`
- `--selftest`
- `--screenshot`
- `--sweep-reveal` and `--no-sweep-reveal`
- `--fps`
- `--no-scanlines`

The deploy profile should default to phosphor. Template may exist as a rollback view, but it is not the public target.

## Canvas

- Base size: `640 x 480`.
- UI loop target: `60 fps`.
- Phosphor asset pack target: `30 fps`.
- Use integer-safe geometry where possible.
- The UI must remain readable fullscreen on the Pi display path and in generated screenshots.

## Phosphor Geometry

```text
maximum range: 6000 mm
drawn arc: 180 degrees
real sensor cone: 120 degrees
origin y: height * 0.90
maximum radius: height * 0.80
range rings: 1, 2, 3, 4, 5, 6 m
minimum surface: 160 x 160
```

Do not stretch 120 degrees of sensor data across the full 180 degree face. Clamp contact bearings to the real cone.

## Phosphor Palette

```text
base:       #04100A
wash:       #14482C
grid:       #3FE07A
chevron:    #9BFFC6
sweep:      #78FFAA
edge:       #CFFFE0
void:       #04100A
halo:       #FF2B2B
mid:        #FF5A4D
core:       #FFF4F2
pill fill:  #04140C
pill text:  #B6FFD2
```

## Radar Face

The face should read as a practical MW2-inspired heartbeat sensor screen, not a generic radar chart.

Required elements:

- Dark green phosphor field.
- Semicircle radar grid rising from the bottom-center origin.
- Range rings and radial tick marks.
- Subtle phosphor wash.
- Visible sweep band.
- Bottom-center distance pill.
- Optional bottom-right FPS readout.
- SENSOR OFFLINE state when the source reports a non-empty error.

The empty healthy state shows the face with no contacts and no offline band.

## Phosphor Asset Pack

Use `assets/phosphor/manifest.json` to validate assets before rendering them.

Expected manifest values:

```text
profile: phosphor
size: 640 x 480
target fps: 30
travel seconds: 0.85
dwell seconds: 0.35
travel frames: 26
dwell index: 26
```

Expected files:

- `face.png`
- `sweep_00.png` through `sweep_26.png`
- `manifest.json`

If the assets are missing or mismatched, the app may render a procedural preview, but the on-camera target should use the supplied asset pack.

## Sweep Behavior

- Sweep should advance by elapsed time, not by number of UI loop iterations.
- The sweep travels across the face, then dwells briefly.
- Travel time is `0.85 s`.
- Dwell time is `0.35 s`.
- Full cycle time is `1.20 s`.
- The final dwell frame is `sweep_26.png`.
- Sweep reveal defaults on.
- `--no-sweep-reveal` draws contacts continuously for tests or alternate shots.
- When sweep reveal is on, a contact brightens only when the sweep crosses its true distance.
- Contact reveal decays in five steps across one sweep cycle: `1.00`, `0.75`, `0.50`, `0.28`, `0.12`.

## Contact Behavior

- Hide contacts beyond display range.
- Keep the true measured distance for HUD text even when a contact is beyond range.
- Render contacts as red/white phosphor pips with glow.
- Use a stronger center and softer outer rings.
- Acquiring contacts render at `0.63` brightness.
- Fading contacts decay over `1.3 s` with a floor of `0.18` while the tracker still reports them.
- Multiple contacts must be visible without UI collapse.
- Unknown track states should render as `live`.
- Broken track objects should be skipped instead of crashing the display.

## Distance Pill

The bottom-center pill reports nearest solid contact distance.

Required outputs:

- No solid contact and no error: `--.-m`
- Normal nearest contact: one decimal meter value, for example `1.3m`.
- Beyond maximum range: `>6 M`.

The pill must remain stable in size and position across updates.

## Visual Target

The implementation should match the layout, palette, legibility, phosphor sweep feel, and contact treatment described in this spec closely enough for filming and practical use.
