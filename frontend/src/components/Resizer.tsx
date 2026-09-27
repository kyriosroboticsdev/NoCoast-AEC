import { useRef, type KeyboardEvent, type PointerEvent } from "react";

/** One axis of a drag handle. `dir` is +1 when dragging towards larger client coordinates grows the panel. */
export interface ResizeAxis {
  value: number;
  dir: 1 | -1;
  min: number;
  max: number;
  onChange: (value: number) => void;
}

interface Props {
  /** Placement class, e.g. `resizer-sidebar`. */
  className: string;
  label: string;
  width?: ResizeAxis;
  height?: ResizeAxis;
  /** Double-click, or Home while focused. */
  onReset?: () => void;
  /** Keyboard increment. */
  step?: number;
}

/**
 * A grab handle on the edge (or corner) of a panel: pointer drag, arrow keys for
 * fine adjustment, double-click to go back to the default size.
 */
export function Resizer({ className, label, width, height, onReset, step = 16 }: Props) {
  const from = useRef<{ x: number; y: number; w: number; h: number } | null>(null);
  const cursor = width && height ? (width.dir === height.dir ? "nwse-resize" : "nesw-resize") : width ? "col-resize" : "row-resize";

  const down = (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    e.preventDefault();
    from.current = { x: e.clientX, y: e.clientY, w: width?.value ?? 0, h: height?.value ?? 0 };
    e.currentTarget.setPointerCapture(e.pointerId);
    document.body.style.setProperty("--drag-cursor", cursor);
    document.body.classList.add("resizing");
  };

  const move = (e: PointerEvent<HTMLDivElement>) => {
    const start = from.current;
    if (!start) return;
    width?.onChange(start.w + (e.clientX - start.x) * width.dir);
    height?.onChange(start.h + (e.clientY - start.y) * height.dir);
  };

  const up = (e: PointerEvent<HTMLDivElement>) => {
    if (!from.current) return;
    from.current = null;
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
    document.body.classList.remove("resizing");
  };

  const key = (e: KeyboardEvent<HTMLDivElement>) => {
    const by = e.shiftKey ? step * 4 : step;
    const nudge = (axis: ResizeAxis | undefined, towards: 1 | -1) => {
      if (!axis) return;
      e.preventDefault();
      axis.onChange(axis.value + by * towards * axis.dir);
    };
    if (e.key === "ArrowLeft") nudge(width, -1);
    else if (e.key === "ArrowRight") nudge(width, 1);
    else if (e.key === "ArrowUp") nudge(height, -1);
    else if (e.key === "ArrowDown") nudge(height, 1);
    else if ((e.key === "Home" || e.key === "Enter") && onReset) {
      e.preventDefault();
      onReset();
    }
  };

  const axis = width ?? height!;
  return (
    <div
      className={`resizer ${className}`}
      style={{ cursor }}
      role="separator"
      aria-orientation={width ? "vertical" : "horizontal"}
      aria-label={label}
      aria-valuenow={Math.round(axis.value)}
      aria-valuemin={axis.min}
      aria-valuemax={axis.max}
      title={`${label} — drag, arrow keys, or double-click to reset`}
      tabIndex={0}
      onPointerDown={down}
      onPointerMove={move}
      onPointerUp={up}
      onPointerCancel={up}
      onDoubleClick={onReset}
      onKeyDown={key}
    />
  );
}
