from osmo_sidecar.gimbal import Gimbal


def test_analyze_sniff_ignores_telemetry() -> None:
    gimbal = Gimbal()
    packets = [
        {"cmd_set": 0x04, "cmd": 0x05, "telemetry": True, "payload": ""},
        {"cmd_set": 0x04, "cmd": 0x27, "telemetry": True, "payload": ""},
        {"cmd_set": 0x05, "cmd": 0x06, "telemetry": True, "payload": "50"},
    ]
    analysis = gimbal.analyze_sniff(packets)
    assert analysis["wheel_supported"] is False
    assert analysis["total"] == 3
    assert "wheel_map.json" in analysis["wheel_reason"]


def test_analyze_sniff_does_not_enable_wheel_without_map() -> None:
    gimbal = Gimbal()
    packets = [
        {
            "cmd_set": 0x01,
            "cmd": 0x80,
            "telemetry": False,
            "payload": "0100",
            "raw": "",
        }
    ]
    analysis = gimbal.analyze_sniff(packets)
    assert analysis["wheel_supported"] is False
    assert "wheel_map.json" in analysis["wheel_reason"]
