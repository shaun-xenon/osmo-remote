const TABS = ["gimbal", "activetrack", "general"];

export function partitionSettings(commands = []) {
  const ready = commands.filter((row) => row.ready && row.builtin !== "joystick");
  const pending = commands.filter((row) => row.layer === "ble" && !row.ready);
  const other = commands.filter((row) => row.layer !== "ble");
  return { ready, pending, other };
}

export function Settings({ connected, commands, onApply, onApplyProfile, onSendRaw, onDecode }) {
  const { ready, pending, other } = partitionSettings(commands);

  return (
    <section className="settings-panel">
      <header>
        <h2>Gimbal profile</h2>
        <button type="button" disabled={!connected} onClick={onApplyProfile}>
          Apply profile
        </button>
      </header>
      <p className="hint">
        Blue buttons send proven gimbal packets. The lists below are the Mimo screenshot inventory —
        they are not controls until hex is mapped.
      </p>
      <div className="setting-group">
        {ready.map((row) => (
          <button
            key={row.id}
            type="button"
            disabled={!connected}
            onClick={() => onApply(row.id)}
            title={row.summary}
          >
            {row.mimo_label || label(row.id)}
          </button>
        ))}
      </div>
      {pending.length > 0 ? (
        <details>
          <summary>Unmapped gimbal settings ({pending.length})</summary>
          <ul className="setting-list">
            {pending.map((row) => (
              <li key={row.id}>
                <strong>{row.mimo_label || label(row.id)}</strong>
                {row.observed ? ` (${row.observed})` : ""} — {row.summary}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      <details>
        <summary>Phone / module (not BLE)</summary>
        <ul className="setting-list">
          {other.map((row) => (
            <li key={row.id}>
              <strong>{row.mimo_label || label(row.id)}</strong> [{row.layer}]
              {row.observed ? ` (${row.observed})` : ""} — {row.summary}
            </li>
          ))}
        </ul>
        <p className="hint">Tabs in Mimo were {TABS.join(", ")}. Only the gimbal tab is this app.</p>
      </details>
      <RawLab connected={connected} onSendRaw={onSendRaw} onDecode={onDecode} />
    </section>
  );
}

function RawLab({ connected, onSendRaw, onDecode }) {
  return (
    <form
      className="raw-lab"
      onSubmit={(event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const hex = new FormData(form).get("hex");
        if (typeof hex === "string" && hex.trim()) {
          onSendRaw(hex.trim());
        }
      }}
    >
      <label>
        Replay DUML hex
        <textarea name="hex" rows={3} spellCheck="false" placeholder="55 …" />
      </label>
      <div className="actions">
        <button type="submit" disabled={!connected}>
          Send raw
        </button>
        <button
          type="button"
          onClick={(event) => {
            const form = event.currentTarget.form;
            const hex = new FormData(form).get("hex");
            if (typeof hex === "string" && hex.trim()) {
              onDecode(hex.trim());
            }
          }}
        >
          Decode
        </button>
      </div>
    </form>
  );
}

function label(id) {
  return id.replace(/_/g, " ");
}
