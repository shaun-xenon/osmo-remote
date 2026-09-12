export function Wheel({ disabled, reason, onDelta }) {
  return (
    <section className={`wheel-panel ${disabled ? "is-disabled" : ""}`}>
      <header>
        <h2>Zoom / focus wheel</h2>
        <span className="badge">{disabled ? "Not mapped" : "Experimental"}</span>
      </header>
      <p className="note">{reason}</p>
      <div className="wheel-buttons">
        <button type="button" disabled={disabled} onClick={() => onDelta(-1)}>
          Focus / zoom −
        </button>
        <button type="button" disabled={disabled} onClick={() => onDelta(1)}>
          Focus / zoom +
        </button>
      </div>
    </section>
  );
}
