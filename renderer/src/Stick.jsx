import { useCallback, useEffect, useRef, useState } from "react";

export function Stick({ value, onChange, disabled }) {
  const areaRef = useRef(null);
  const dragging = useRef(false);

  const setFromEvent = useCallback(
    (event) => {
      const area = areaRef.current;
      if (!area || disabled) {
        return;
      }
      const rect = area.getBoundingClientRect();
      const dx = event.clientX - (rect.left + rect.width / 2);
      const dy = event.clientY - (rect.top + rect.height / 2);
      const radius = rect.width / 2 - 8;
      const mag = Math.hypot(dx, dy);
      const scale = mag > radius ? radius / mag : 1;
      const x = (dx * scale) / radius;
      const y = (dy * scale) / radius;
      onChange({ x, y: -y });
    },
    [disabled, onChange],
  );

  const endDrag = useCallback(() => {
    dragging.current = false;
    onChange({ x: 0, y: 0 });
  }, [onChange]);

  useEffect(() => {
    const move = (event) => {
      if (dragging.current) {
        setFromEvent(event);
      }
    };
    const up = () => {
      if (dragging.current) {
        endDrag();
      }
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
  }, [endDrag, setFromEvent]);

  const knobX = value.x * 42;
  const knobY = -value.y * 42;

  return (
    <div
      ref={areaRef}
      className={`stick ${disabled ? "is-disabled" : ""}`}
      onPointerDown={(event) => {
        if (disabled) {
          return;
        }
        event.currentTarget.setPointerCapture(event.pointerId);
        dragging.current = true;
        setFromEvent(event);
      }}
    >
      <div className="stick-cross" />
      <div className="stick-knob" style={{ transform: `translate(${knobX}px, ${knobY}px)` }} />
    </div>
  );
}
