"""CLI for scan / connect / inspect / pulse / sniff / decode / serve."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from osmo_sidecar.capture import decode_capture, diff_captures
from osmo_sidecar.features import build_inventory, load_catalog, summarize_layers
from osmo_sidecar.gimbal import Gimbal, inspect_to_dict
from osmo_sidecar.profile import list_commands
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

    decode = sub.add_parser(
        "decode-capture",
        help="Extract labeled DUML from a btsnoop HCI log, sniff JSON, or hex dump",
    )
    decode.add_argument("path", type=Path)
    decode.add_argument("--out", type=Path, default=None)

    diff = sub.add_parser(
        "diff-captures",
        help="Show non-telemetry DUML added in the second capture (one setting toggle)",
    )
    diff.add_argument("before", type=Path)
    diff.add_argument("after", type=Path)

    send_raw = sub.add_parser("send-raw", help="Connect and replay a DUML hex frame")
    send_raw.add_argument("address")
    send_raw.add_argument("hex")

    apply_cmd = sub.add_parser("apply", help="Connect and replay a named setting or builtin")
    apply_cmd.add_argument("address")
    apply_cmd.add_argument("name")

    sub.add_parser("features", help="Print the Mimo-free feature catalog")
    sub.add_parser("inventory", help="Print the screenshot defaults dump and mapping status")
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
    if args.cmd == "features":
        catalog = load_catalog()
        print(catalog.get("shooting", ""))
        print(f"layers: {summarize_layers()}")
        for row in list_commands():
            flag = "ready" if row["ready"] else row["status"]
            print(f"{row['id']:32} {row['layer']:8} {flag:14} {row.get('summary') or ''}")
        return
    if args.cmd == "inventory":
        inventory = build_inventory()
        print(json.dumps(inventory, indent=2))
        return
    if args.cmd == "diff-captures":
        result = diff_captures(args.before, args.after)
        print(json.dumps(result, indent=2))
        print(f"added {result['added_count']} non-telemetry frame(s)", file=sys.stderr)
        return
    if args.cmd == "decode-capture":
        result = decode_capture(args.path)
        text = json.dumps(result, indent=2)
        if args.out:
            args.out.write_text(text)
            print(f"Wrote {args.out}", file=sys.stderr)
        else:
            print(text)
        print(
            f"{result['kind']}: {result['total']} DUML frames, "
            f"{len(result['interesting'])} non-telemetry, crc_ok={result['crc_ok']}",
            file=sys.stderr,
        )
        return

    gimbal = Gimbal()
    if args.cmd == "scan":
        devices = await gimbal.scan(timeout=args.timeout)
        if not devices:
            print(
                "No BLE advertisements seen. Power the gimbal. Scan already untrusts the OM7P in BlueZ; "
                "on the phone, unpair only the gimbal."
            )
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
        elif args.cmd == "send-raw":
            sent = await gimbal.send_raw(args.hex)
            print(json.dumps(sent, indent=2))
        elif args.cmd == "apply":
            result = await gimbal.apply_setting(args.name)
            print(json.dumps(result, indent=2))
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
