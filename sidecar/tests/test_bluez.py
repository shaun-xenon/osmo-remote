from osmo_sidecar.bluez import (
    BluezDevice,
    is_osmo_device,
    is_osmo_gimbal,
    parse_device_lines,
    parse_uuids,
)


def test_parse_bluetoothctl_devices() -> None:
    text = """
Device 12:34:56:78:9A:BC OM7P-307GHV
Device AA:BB:CC:DD:EE:FF Headphones
"""
    rows = parse_device_lines(text)
    assert rows[0].address == "12:34:56:78:9A:BC"
    assert rows[0].name == "OM7P-307GHV"
    assert is_osmo_device(rows[0]) is True
    assert is_osmo_device(BluezDevice("AA:BB:CC:DD:EE:FF", "Headphones")) is False


def test_reclaim_match_is_gimbal_not_dji_accessory() -> None:
    gimbal = BluezDevice("12:34:56:78:9A:BC", "OM7P-307GHV")
    mic = BluezDevice("AA:BB:CC:DD:EE:FF", "DJI Mic Mini")
    headphones = BluezDevice("11:22:33:44:55:66", "Headphones")
    osmo = BluezDevice("77:88:99:AA:BB:CC", "Osmo Mobile 7P")
    assert is_osmo_gimbal(gimbal) is True
    assert is_osmo_gimbal(osmo) is True
    assert is_osmo_gimbal(mic) is False
    assert is_osmo_gimbal(headphones) is False
    assert is_osmo_device(mic) is True  # scan ranking only


def test_reclaim_does_not_fire_on_other_osmo_product_names() -> None:
    # Destructive reclaim (disconnect + untrust) must not touch other DJI gear
    # that merely shares the Osmo branding; only the fff0 service UUID may
    # promote those names to a gimbal match.
    pocket = BluezDevice("22:33:44:55:66:77", "Osmo Pocket")
    action = BluezDevice("33:44:55:66:77:88", "DJI Osmo Action 4")
    assert is_osmo_gimbal(pocket) is False
    assert is_osmo_gimbal(action) is False
    assert is_osmo_gimbal(pocket, ["0000fff0-0000-1000-8000-00805f9b34fb"]) is True


def test_fff0_uuid_marks_gimbal_even_without_name() -> None:
    unnamed = BluezDevice("12:34:56:78:9A:BC", "")
    assert is_osmo_gimbal(unnamed) is False
    assert is_osmo_gimbal(unnamed, ["0000fff0-0000-1000-8000-00805f9b34fb"]) is True
    mic = BluezDevice("AA:BB:CC:DD:EE:FF", "DJI Mic Mini")
    info = "UUID: Vendor specific (0000fff5-0000-1000-8000-00805f9b34fb)"
    assert is_osmo_gimbal(mic, parse_uuids(info)) is False
