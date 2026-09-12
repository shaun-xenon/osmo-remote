"""CLI for scan / connect / inspect / pulse / sniff / serve."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from osmo_sidecar.gimbal import Gimbal, inspect_to_dict
from osmo_sidecar.server import SidecarServer


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="osmo-sidecar", description="Osmo Mobile BLE sidecar")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    scan = sub.add_parser("scan", help="Scan for BLE gimbals")
    scan.add_argument("--timeout", type=float, default=8.0)

    connect = sub.add_parser("inspect", help="Connect and dump GATT (fff0/fff4/fff5)")
    connect.add_argument("address")
    connect.add_argument("--timeout", type=float, default=20.0)

    pulse = sub.add_parser("pulse", help="Connect and send a short yaw SPEED pulse")
    pulse.add_argument("address")
    pulse.add_argument("--yaw", type=int, default=800)
    pulse.add_argument("--seconds", type=float, default=0.8)

    sniff = sub.add_parser("sniff", help="Connect and log DUML while you turn the side wheel")
    sniff.add_argument("address")
    sniff.add_argument("--seconds", type=float, default=15.0)
    sniff.add_argument("--out", type=Path, default=None)

    pair = sub.add_parser("pair-probe", help="Write Pocket-3 pairing poke to fff4")
    pair.add_argument("address")

    sub.add_parser("serve", help="JSON-lines stdio server for the Electron app")

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    try:
        asyncio.run(_dispatch(args))
    except Exception as exc:  # noqa: BLE001
        print(exc, file=sys.stderr)
        raise SystemExit(1) from exc


async def _dispatch(args: argparse.Namespace) -> None:
    if args.cmd == "serve":
        await SidecarServer().run()
        return

    gimbal = Gimbal()
    if args.cmd == "scan":
        devices = await gimbal.scan(timeout=args.timeout)
        if not devices:
            print("No BLE advertisements seen. Power the gimbal, disconnect Mimo, and unpair in KDE.")
            return
        for device in devices:
            mark = "*" if device.likely else " "
            rssi = f"{device.rssi:>4}" if device.rssi is not None else "  n/a"
            print(f"{mark} {device.address}  rssi={rssi}  {device.name}")
        return

    try:
        inspect = await gimbal.connect(args.address)
        info = inspect_to_dict(inspect)
        print(json.dumps(info, indent=2))
        _print_gatt_summary(info)

        if args.cmd == "pulse":
            print(f"Sending SPEED yaw={args.yaw} for {args.seconds}s …", file=sys.stderr)
            await gimbal.pulse(yaw=args.yaw, seconds=args.seconds)
            print("Pulse sent. Did the gimbal pan?", file=sys.stderr)
        elif args.cmd == "pair-probe":
            await gimbal.pair_probe()
            print("Wrote [0x01, 0x00] to fff4.", file=sys.stderr)
        elif args.cmd == "sniff":
            print(
                f"Sniffing {args.seconds}s — turn the physical zoom/focus wheel now.",
                file=sys.stderr,
            )
            gimbal.start_sniff()
            await asyncio.sleep(args.seconds)
            packets = gimbal.stop_sniff()
            analysis = gimbal.analyze_sniff(packets)
            payload = {"packets": packets, "analysis": analysis}
            text = json.dumps(payload, indent=2)
            if args.out:
                args.out.write_text(text)
                print(f"Wrote {args.out}", file=sys.stderr)
            else:
                print(text)
            print(analysis["wheel_reason"], file=sys.stderr)
    finally:
        await gimbal.disconnect()


def _print_gatt_summary(info: dict) -> None:
    print(
        "GATT: "
        f"fff0={'yes' if info['has_fff0'] else 'NO'} "
        f"fff4={'yes' if info['has_fff4'] else 'NO'} "
        f"fff5={'yes' if info['has_fff5'] else 'NO'} "
        f"mtu={info.get('mtu')}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
