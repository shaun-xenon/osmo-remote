# Osmo Remote

A Kubuntu desktop remote for the **DJI Osmo Mobile 7P**. Pan and tilt the gimbal from a laptop stick, keyboard, or gamepad over Bluetooth.

DJI does not ship an SDK for this product. The app talks the reverse-engineered Osmo Mobile **DUML-over-BLE** protocol: an Electron UI plus a Python [Bleak](https://github.com/hbldh/bleak) sidecar on BlueZ.

**Status:** pan/tilt, recenter, and follow/lock/FPV work on a real OM7P. Extra gimbal settings (calibrate, invert, sleep, wheel, …) replay once you map their hex. Treat the protocol as unofficial and firmware-dependent.

Shoot with the **phone camera** (stock, a third-party app, or DroidCam). People-tracking without DJI Mimo is the **Multifunctional Module**. This app does not replace Mimo’s camera UI.

## Features

- Scan and connect over BLE (GATT `fff0` / `fff4` / `fff5`)
- On-screen analog stick, WASD/arrows, USB gamepad
- Compact **Overlay** window and **On top** for use beside OBS
- Speed slider (slow crawl to fast slew)
- Recenter, follow / lock / FPV, apply-on-connect profile
- SPEED commands (proven on OM7P) with PWM joystick as a fallback
- Named settings catalog + raw DUML replay
- `decode-capture` for Android HCI snoop logs, sniff JSON, or hex dumps
- Wheel sniffing for later zoom/focus mapping

## Not in this version

- DJI Mimo, Mimo ActiveTrack 7.0, or a live view on the laptop
- Photo aspect / grid / selfie flip (set those in the phone camera app)
- Zoom/focus until `sidecar/wheel_map.json` has captured commands
- Fill light control until mapped
- Using another BLE central **on the gimbal** at the same time (phone bonded to OM7P, KDE, or Mimo). Phone Bluetooth can stay on for microphones.

## Requirements

- Linux with BlueZ (developed on Kubuntu)
- Python 3.12+
- Node.js 22+ (for Electron / Vite)
- The gimbal powered on. The laptop must own the gimbal GATT session. Phone Bluetooth can stay on for mics if the **OM7P is unpaired on the phone**.

## Setup

```bash
git clone https://github.com/shaun-xenon/osmo-remote.git
cd osmo-remote
npm run sidecar:setup
npm install
```

If Bluetooth is soft-blocked:

```bash
rfkill unblock bluetooth
```

Optional KDE launcher (writes a `.desktop` file for *this* checkout):

```bash
npm run desktop
```

## Run

```bash
npm run dev
```

Or `npm start` for a production renderer build. Electron is launched with `--no-sandbox` on Linux because Chromium’s SUID helper in `node_modules` is not root-owned.

```bash
npm test
```

## Using it

1. On the **phone**, unpair **only** the Osmo/OM7P device. Leave Bluetooth on for microphones. Do not open Mimo.
2. **Scan** in this app. Scan disconnects the gimbal and **untrusts** it in BlueZ so KDE should not auto-connect. That is not Forget on the PC.
3. Power the gimbal. Reset BLE if needed (switch + shutter + trigger held together) so it drops the last phone bond.
4. **Connect** → drag the stick. Recenter / Lock / FPV are live. PTF is already applied on connect.
5. For OBS or a busy desktop, click **Overlay** (and **On top**) so the stick stays on the picture.

### Seeing the picture

This app only moves the gimbal. It does not carry video.

| Setup | Picture on the laptop | Notes |
|------|------------------------|-------|
| Android **Professional Camera** (or the stock camera) | No | Best files on the phone. You are flying blind unless you can see the panel. |
| **scrcpy** | Yes, usually the snappiest | USB preferred. Good “see what I am framing” monitor. Record on the phone, not via the desktop encode. |
| **DroidCam + OBS** | Yes | Fine for monitoring. Recording in OBS adds encode latency. That is DroidCam/OBS/CPU, not the BLE stick. |
| **Multifunctional Module** | No extra video here | Trigger/gestures track people in the phone camera app without Mimo. |

OBS dropped frames and mushy recording on a loaded machine (Chrome, torrents, Docker, Discord, other Electron apps) are expected. Pause the extras if you need a clean OBS encode. The gimbal stick is cheap; the video pipeline is not.

If Connect fails after a previous session:

```bash
bluetoothctl disconnect AA:BB:CC:DD:EE:FF
```

Then Scan again.

### Stick commands

| Mode | Meaning |
|------|---------|
| **SPEED (OM2–4)** | Default. Stick deflection is rotation *rate*. Proven on OM7P. |
| **PWM joystick** | Fallback. Stick deflection is a PWM-style channel (center 1024). |

Stick up / forward pitches the camera down (nose dive).

### Settings mapping

Proven commands (recenter, follow/lock/FPV) are built in. Other gimbal firmware settings need a captured frame:

```bash
sidecar/.venv/bin/python -m osmo_sidecar features
sidecar/.venv/bin/python -m osmo_sidecar decode-capture /path/to/btsnoop_hci.log
sidecar/.venv/bin/python -m osmo_sidecar apply AA:BB:CC:DD:EE:FF mode_follow
```

Copy `sidecar/settings_map.example.json` to `sidecar/settings_map.json` and paste hex next to each setting. Connect runs `apply_on_connect` (default: `mode_follow` / PTF).

Five Mimo screenshots (16 Sep 2026, capture time) are the defaults dump: Gimbal 17:49:08 + 17:50:06, ActiveTrack 17:50:38, General 17:51:09 + 17:51:31. `python -m osmo_sidecar inventory` prints that table. HCI snoop is still pending — enable Bluetooth HCI snoop on the phone, toggle one gimbal setting, then:

```bash
sidecar/.venv/bin/python -m osmo_sidecar decode-capture /path/to/btsnoop_hci.log
sidecar/.venv/bin/python -m osmo_sidecar diff-captures before.json after.json
```

Paste the new hex into `settings_map.json`. Day-to-day shooting does not use Mimo. ActiveTrack and photo grid/aspect/selfie-flip stay on the Multifunctional Module and the phone camera app.

### Zoom / focus

```bash
sidecar/.venv/bin/python -m osmo_sidecar sniff AA:BB:CC:DD:EE:FF --seconds 15
```

Copy confirmed `zoom_in` / `zoom_out` hex into `sidecar/wheel_map.json` (see `sidecar/wheel_map.example.json`).

## Layout

```
electron/     main process, spawns the sidecar
renderer/     stick / wheel / settings UI (Vite + React)
sidecar/      Bleak driver, DUML codec, capture decoder, JSON-lines server
packaging/    icon + desktop template
scripts/      BLE bring-up, app launcher, KDE install
```

## Protocol

DUML CRC and Osmo Mobile rotate packets follow [alkersan/om-research](https://github.com/alkersan/om-research) (MIT), tested there on OM2/OM3/OM4. This project sends those SPEED/PWM commands to an OM7P.

This is interoperability work. No DJI firmware or Mimo binaries are included.

## License

[MIT](LICENSE.md)
