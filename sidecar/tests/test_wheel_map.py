from osmo_sidecar.gimbal import Gimbal, load_wheel_map


def test_wheel_map_enables_controls(tmp_path, monkeypatch) -> None:
    mapping = tmp_path / "wheel_map.json"
    mapping.write_text(
        '{"zoom_in": "551504a9", "zoom_out": "551504a9", "note": "fixture map"}',
        encoding="utf-8",
    )
    monkeypatch.setattr("osmo_sidecar.gimbal.WHEEL_MAP_PATH", mapping)
    gimbal = Gimbal()
    assert gimbal.state.wheel_supported is True
    assert gimbal.state.wheel_reason == "fixture map"
    loaded = load_wheel_map()
    assert loaded is not None
    assert loaded["zoom_in"] == "551504a9"
