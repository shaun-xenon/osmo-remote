# Osmo Remote

A Kubuntu desktop remote for the **DJI Osmo Mobile 7P**. Pan and tilt the gimbal from a laptop stick, keyboard, or gamepad over Bluetooth.

DJI does not ship an SDK for this product. The app talks the reverse-engineered Osmo Mobile **DUML-over-BLE** protocol: an Electron UI plus a Python [Bleak](https://github.com/hbldh/bleak) sidecar on BlueZ.

**Status:** pan/tilt works on a real OM7P. Zoom/focus is not mapped yet. Treat the protocol as unofficial and firmware-dependent.

## Features

- Scan and connect over BLE (GATT `fff0` / `fff4` / `fff5`)
- On-screen analog stick, WASD/arrows, USB gamepad
- Speed slider (slow crawl to fast slew)
- Recenter, follow / lock / FPV mode packets
- SPEED commands (proven on OM7P) with PWM joystick as a fallback
- Wheel sniffing CLI for later zoom/focus mapping

## Not in this version

- DJI Mimo, ActiveTrack, or a live view on the laptop
- Zoom/focus until `sidecar/wheel_map.json` has captured commands
- Fill light / Multifunctional Module
- Using Mimo and this app at the same time (one BLE central only)

## Requirements

- Linux with BlueZ (developed on Kubuntu)
- Python 3.12+
- Node.js 22+ (for Electron / Vite)
- The gimbal powered on, **not** connected to a phone, KDE Bluetooth, or DJI Mimo

## Setup

```bash
git clone <this-repo> osmo-remote
cd osmo-remote
npm run sidecar:setup
npm install
```

If Bluetooth is soft-blocked:

```bash
rfkill unblock bluetooth
```

Optional KDE launcher:

```bash
cp packaging/osmo-remote.desktop ~/.local/share/applications/
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

1. Forget/unpair the gimbal on the phone. Close Mimo.
2. In **KDE Bluetooth**, disconnect or unpair it. Plasma will steal the GATT session if it auto-connects; Scan will still see the device and Connect will fail.
3. Power the gimbal. Reset BLE if needed (switch + shutter + trigger).
4. In the app: **Scan** → **Connect** → drag the stick.

The phone can stay on the clamp and record with the native camera. It must not own Bluetooth.

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

### Zoom / focus

The 7P side wheel is documented by DJI as a Mimo feature. The UI stays disabled until you capture packets:

```bash
sidecar/.venv/bin/python -m osmo_sidecar sniff AA:BB:CC:DD:EE:FF --seconds 15
```

Copy confirmed `zoom_in` / `zoom_out` hex into `sidecar/wheel_map.json` (see `sidecar/wheel_map.example.json`).

## Layout

```
electron/     main process, spawns the sidecar
renderer/     stick / wheel UI (Vite + React)
sidecar/      Bleak driver, DUML codec, JSON-lines server
packaging/    .desktop launcher + icon
scripts/      BLE bring-up helper
```

## Protocol

DUML CRC and Osmo Mobile rotate packets follow [alkersan/om-research](https://github.com/alkersan/om-research) (MIT), tested there on OM2/OM3/OM4. This project sends those SPEED/PWM commands to an OM7P.

This is interoperability work. No DJI firmware or Mimo binaries are included.

## License

[MIT](LICENSE.md)
