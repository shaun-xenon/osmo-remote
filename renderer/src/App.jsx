import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Settings } from "./Settings.jsx";
import { Stick } from "./Stick.jsx";
import { Wheel } from "./Wheel.jsx";

const DEADZONE = 0.06;
const DEFAULT_WHEEL_REASON =
  "Zoom/focus is not mapped. Sniff the physical wheel while this app is connected, or decode an HCI capture, then put hex in sidecar/wheel_map.json.";

function request(cmd, payload = {}) {
  if (!window.osmo?.request) {
    return Promise.reject(new Error("Not running inside Electron"));
  }
  return window.osmo.request({ cmd, ...payload });
}

function combineAxes(stick, keys, pad) {
  const x = clamp(stick.x + keys.x + pad.x);
  const y = clamp(stick.y + keys.y + pad.y);
  return { x, y };
}

function clamp(value) {
  return Math.max(-1, Math.min(1, value));
}

function padAxes() {
  const pads = navigator.getGamepads?.() ?? [];
  const pad = [...pads].find((item) => item);
  if (!pad) {
    return { x: 0, y: 0, connected: false, id: "" };
  }
  const x = applyDeadzone(pad.axes[0] ?? 0);
  const y = applyDeadzone(-(pad.axes[1] ?? 0));
  return { x, y, connected: true, id: pad.id };
}

function samePad(left, right) {
  return (
    left.connected === right.connected &&
    left.id === right.id &&
    left.x === right.x &&
    left.y === right.y
  );
}

function applyDeadzone(value) {
  return Math.abs(value) < DEADZONE ? 0 : value;
}

export function App() {
  const [devices, setDevices] = useState([]);
  const [selected, setSelected] = useState("");
  const [scanning, setScanning] = useState(false);
  const [connected, setConnected] = useState(false);
  const [status, setStatus] = useState({
    battery: null,
    charging: null,
    name: "",
    wheel_supported: false,
    wheel_reason: DEFAULT_WHEEL_REASON,
  });
  const [stick, setStick] = useState({ x: 0, y: 0 });
  const [keys, setKeys] = useState({ x: 0, y: 0 });
  const [pad, setPad] = useState({ x: 0, y: 0, connected: false, id: "" });
  const [speed, setSpeed] = useState(0.7);
  const [method, setMethod] = useState("speed");
  const [invertPitch, setInvertPitch] = useState(false);
  const [logs, setLogs] = useState([]);
  const [busy, setBusy] = useState(false);
  const [sniffing, setSniffing] = useState(false);
  const [overlay, setOverlay] = useState(false);
  const [onTop, setOnTop] = useState(false);
  const [commands, setCommands] = useState([]);
  const moving = useRef(false);
  const axesRef = useRef({ x: 0, y: 0 });
  const sending = useRef(false);

  const pushLog = useCallback((message) => {
    setLogs((current) => [`${new Date().toLocaleTimeString()} ${message}`, ...current].slice(0, 80));
  }, []);

  const axes = useMemo(() => combineAxes(stick, keys, pad), [stick, keys, pad]);
  axesRef.current = axes;

  useEffect(() => {
    if (!window.osmo) {
      return undefined;
    }
    const offStatus = window.osmo.onStatus((data) => {
      setConnected(Boolean(data.connected));
      setStatus((current) => ({ ...current, ...data }));
    });
    const offPacket = window.osmo.onPacket((data) => {
      pushLog(data.summary || `packet ${data.cmd_set}/${data.cmd}`);
    });
    const offLog = window.osmo.onLog((data) => {
      if (data?.message) {
        pushLog(data.message);
      }
    });
    return () => {
      offStatus();
      offPacket();
      offLog();
    };
  }, [pushLog]);

  const refreshCommands = useCallback(() => {
    // The sidecar re-reads settings_map.json on every request, so re-fetching
    // here picks up edits made while the app is open.
    request("settings")
      .then((response) => {
        if (response.ok) {
          setCommands(response.result.commands ?? []);
        }
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    refreshCommands();
  }, [refreshCommands]);

  useEffect(() => {
    const down = (event) => {
      if (
        event.repeat ||
        event.target instanceof HTMLInputElement ||
        event.target instanceof HTMLTextAreaElement
      ) {
        return;
      }
      setKeys((current) => nextKeys(current, event.code, true));
    };
    const up = (event) => setKeys((current) => nextKeys(current, event.code, false));
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, []);

  useEffect(() => {
    const id = window.setInterval(() => {
      const next = padAxes();
      setPad((current) => (samePad(current, next) ? current : next));
      const current = axesRef.current;
      const mag = Math.hypot(current.x, current.y);
      if (connected && mag > DEADZONE) {
        if (sending.current) {
          return;
        }
        moving.current = true;
        sending.current = true;
        request("joystick", {
          yaw: current.x,
          pitch: current.y,
          max_speed: Math.round(80 + speed * 1720),
          method,
          invert_pitch: invertPitch,
        })
          .catch((error) => pushLog(error.message))
          .finally(() => {
            sending.current = false;
          });
      } else if (moving.current) {
        moving.current = false;
        request("stop").catch((error) => pushLog(error.message));
      }
    }, 50);
    return () => window.clearInterval(id);
  }, [connected, invertPitch, method, pushLog, speed]);

  async function scan() {
    setScanning(true);
    pushLog(
      "Scanning BLE… kicking KDE off the gimbal (untrust, not forget). On the phone, unpair only the OM7P — keep Bluetooth on for mics.",
    );
    try {
      const response = await request("scan", { timeout: 10 });
      if (!response.ok) {
        throw new Error(response.error);
      }
      const list = response.result.devices ?? [];
      setDevices(list);
      const preferred = list.find((item) => item.likely) ?? list[0];
      if (preferred) {
        setSelected(preferred.address);
      }
      pushLog(`Found ${list.length} device(s).`);
    } catch (error) {
      pushLog(error.message);
    } finally {
      setScanning(false);
    }
  }

  async function connect() {
    if (!selected) {
      return;
    }
    setBusy(true);
    const device = devices.find((item) => item.address === selected);
    try {
      const response = await request("connect", {
        address: selected,
        name: device?.name,
      });
      if (!response.ok) {
        throw new Error(response.error);
      }
      const info = response.result;
      pushLog(
        `GATT fff0=${info.has_fff0} fff4=${info.has_fff4} fff5=${info.has_fff5} mtu=${info.mtu}`,
      );
      const profile = info.profile;
      if (profile?.applied?.length) {
        pushLog(`Profile applied: ${profile.applied.join(", ")}`);
      }
      if (profile?.skipped?.length) {
        pushLog(`Profile skipped: ${profile.skipped.map((row) => row.id).join(", ")}`);
      }
      setConnected(true);
      refreshCommands();
    } catch (error) {
      pushLog(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    setBusy(true);
    try {
      await request("disconnect");
      setConnected(false);
    } catch (error) {
      pushLog(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function recenter() {
    try {
      const response = await request("recenter");
      if (!response.ok) {
        throw new Error(response.error);
      }
      pushLog("Recenter sent");
    } catch (error) {
      pushLog(error.message);
    }
  }

  async function setMode(mode) {
    try {
      const response = await request("set_mode", { mode });
      if (!response.ok) {
        throw new Error(response.error);
      }
      pushLog(`Mode ${mode} sent`);
    } catch (error) {
      pushLog(error.message);
    }
  }

  async function pairProbe() {
    try {
      const response = await request("pair_probe");
      if (!response.ok) {
        throw new Error(response.error);
      }
      pushLog("Pairing poke written to fff4");
    } catch (error) {
      pushLog(error.message);
    }
  }

  async function toggleSniff() {
    try {
      if (!sniffing) {
        const response = await request("sniff_start");
        if (!response.ok) {
          throw new Error(response.error);
        }
        setSniffing(true);
        pushLog("Sniffing DUML — turn the physical side wheel.");
        return;
      }
      const response = await request("sniff_stop");
      if (!response.ok) {
        throw new Error(response.error);
      }
      setSniffing(false);
      const analysis = response.result.analysis;
      if (analysis?.wheel_reason) {
        setStatus((current) => ({
          ...current,
          wheel_supported: analysis.wheel_supported,
          wheel_reason: analysis.wheel_reason,
        }));
      }
      pushLog(
        `Sniff done: ${analysis?.total ?? 0} packets, interesting=${analysis?.interesting?.length ?? 0}`,
      );
    } catch (error) {
      setSniffing(false);
      pushLog(error.message);
    }
  }

  async function applySetting(id) {
    try {
      const response = await request("apply_setting", { id });
      if (!response.ok) {
        throw new Error(response.error);
      }
      pushLog(`Applied ${id}`);
    } catch (error) {
      pushLog(error.message);
    }
  }

  async function applyProfile() {
    try {
      const response = await request("apply_profile");
      if (!response.ok) {
        throw new Error(response.error);
      }
      const result = response.result;
      pushLog(`Profile applied: ${(result.applied ?? []).join(", ") || "nothing"}`);
      if (result.skipped?.length) {
        pushLog(`Skipped: ${result.skipped.map((row) => row.id).join(", ")}`);
      }
      refreshCommands();
    } catch (error) {
      pushLog(error.message);
    }
  }

  async function sendRaw(hex) {
    try {
      const response = await request("send_raw", { hex });
      if (!response.ok) {
        throw new Error(response.error);
      }
      pushLog(`Sent ${response.result.bytes} bytes`);
    } catch (error) {
      pushLog(error.message);
    }
  }

  async function decodeHex(hex) {
    try {
      const response = await request("decode", { hex });
      if (!response.ok) {
        throw new Error(response.error);
      }
      const result = response.result;
      pushLog(`Decode: ${result.total} frames, interesting=${result.interesting?.length ?? 0}`);
      for (const row of result.interesting ?? []) {
        pushLog(row.summary);
      }
    } catch (error) {
      pushLog(error.message);
    }
  }

  async function wheelDelta(delta) {
    try {
      const response = await request("wheel", { delta });
      if (!response.ok) {
        throw new Error(response.error);
      }
    } catch (error) {
      pushLog(error.message);
    }
  }

  async function toggleOverlay() {
    const next = !overlay;
    setOverlay(next);
    if (next && !onTop) {
      setOnTop(true);
      await window.osmo?.setAlwaysOnTop?.(true);
    }
    await window.osmo?.setCompact?.(next);
  }

  async function toggleOnTop() {
    const next = !onTop;
    setOnTop(next);
    await window.osmo?.setAlwaysOnTop?.(next);
  }

  const batteryLabel =
    status.battery == null ? "Battery n/a" : `Battery ${status.battery}%${status.charging ? " charging" : ""}`;

  return (
    <div className={`app ${overlay ? "is-overlay" : ""}`}>
      <header className="top">
        <div>
          <h1>Osmo Remote</h1>
          <p>Phone records. This app only flies the gimbal. Keep phone Bluetooth for mics; unpair only the OM7P.</p>
        </div>
        <div className="top-actions">
          <button type="button" className={overlay ? "is-active" : ""} onClick={toggleOverlay}>
            Overlay
          </button>
          <button type="button" className={onTop ? "is-active" : ""} onClick={toggleOnTop}>
            On top
          </button>
          <div className={`pill ${connected ? "ok" : ""}`}>{connected ? "Connected" : "Disconnected"}</div>
        </div>
      </header>

      <section className="connect-row">
        <button type="button" onClick={scan} disabled={scanning || connected}>
          {scanning ? "Scanning…" : "Scan"}
        </button>
        <select
          value={selected}
          onChange={(event) => setSelected(event.target.value)}
          disabled={connected || devices.length === 0}
        >
          <option value="">Select a device</option>
          {devices.map((device) => (
            <option key={device.address} value={device.address}>
              {device.likely ? "★ " : ""}
              {device.name} — {device.address}
            </option>
          ))}
        </select>
        {connected ? (
          <button type="button" onClick={disconnect} disabled={busy}>
            Disconnect
          </button>
        ) : (
          <button type="button" onClick={connect} disabled={busy || !selected}>
            Connect
          </button>
        )}
        <span className="meta">{batteryLabel}</span>
      </section>

      <div className="layout">
        <section className="stick-panel">
          <Stick value={axes} onChange={setStick} disabled={!connected} />
          <p className="hint">Drag the stick, use WASD / arrows, or a USB gamepad.</p>
          <label className="speed">
            Speed
            <input
              type="range"
              min="0.05"
              max="1"
              step="0.05"
              value={speed}
              onChange={(event) => setSpeed(Number(event.target.value))}
            />
          </label>
          <label className="method">
            Command
            <select value={method} onChange={(event) => setMethod(event.target.value)}>
              <option value="speed">SPEED (OM2–4)</option>
              <option value="pwm">PWM joystick</option>
            </select>
          </label>
          <label className="method">
            <input
              type="checkbox"
              checked={invertPitch}
              onChange={(event) => setInvertPitch(event.target.checked)}
            />
            PC invert pitch (Mimo handle invert is Vertical)
          </label>
          <p className="hint">
            Live packets: Recenter, PTF, Lock, FPV. PTF is already sent on connect, so that button
            can look like a no-op. Lock should freeze follow. Zoom/focus, cal, invert, sleep are
            listed on the right until we map them.
          </p>
          <div className="actions">
            <button type="button" disabled={!connected} onClick={recenter}>
              Recenter
            </button>
            <button type="button" disabled={!connected} onClick={() => setMode("follow")}>
              PTF
            </button>
            <button type="button" disabled={!connected} onClick={() => setMode("lock")}>
              Lock
            </button>
            <button type="button" disabled={!connected} onClick={() => setMode("fpv")}>
              FPV
            </button>
          </div>
          <details className="extras">
            <summary>Lab (no visible gimbal move)</summary>
            <p className="hint">
              Pairing poke is a Pocket leftover. Sniff only logs DUML while you turn the side wheel.
            </p>
            <div className="actions">
              <button type="button" disabled={!connected} onClick={pairProbe}>
                Pairing poke
              </button>
              <button type="button" disabled={!connected} onClick={toggleSniff}>
                {sniffing ? "Stop sniff" : "Sniff wheel"}
              </button>
            </div>
          </details>
          <p className="gamepad">{pad.connected ? `Gamepad: ${pad.id}` : "No gamepad"}</p>
        </section>

        <div className="side-column">
          <Wheel
            disabled={!status.wheel_supported}
            reason={status.wheel_reason || DEFAULT_WHEEL_REASON}
            onDelta={wheelDelta}
          />
          <Settings
            connected={connected}
            commands={commands}
            onApply={applySetting}
            onApplyProfile={applyProfile}
            onSendRaw={sendRaw}
            onDecode={decodeHex}
          />
        </div>
      </div>

      <section className="log">
        {logs.map((line, index) => (
          <div key={`${line}-${index}`}>{line}</div>
        ))}
      </section>
    </div>
  );
}

function nextKeys(current, code, down) {
  const next = { ...current };
  const value = down ? 1 : 0;
  if (code === "KeyA" || code === "ArrowLeft") {
    next.x = down ? -1 : 0;
  } else if (code === "KeyD" || code === "ArrowRight") {
    next.x = value;
  } else if (code === "KeyW" || code === "ArrowUp") {
    next.y = value;
  } else if (code === "KeyS" || code === "ArrowDown") {
    next.y = down ? -1 : 0;
  }
  return next;
}
