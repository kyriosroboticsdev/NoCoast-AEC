"""Layer segments → a slicer-style preview G-code (travel + draw moves per layer).

Visualization only: no E axis, feed rates, or bead width — it exists so the layer
walkthrough has something inspectable/downloadable, not to run on any machine.
"""

from __future__ import annotations

from slicer.slice import LayerSlice


def to_gcode(layers: list[LayerSlice]) -> str:
    lines = [
        "; NoCoast-AEC slice preview -- visualization only, not tuned for any printer or robot",
        "; coordinates are metres (BuildingSpec's unit), not the usual G-code millimetres",
        "G90 ; absolute positioning",
    ]
    phase = None
    for i, layer in enumerate(layers):
        if layer.phase != phase:
            phase = layer.phase
            lines.append(f"; --- phase: {phase} ---")
        lines.append(f"; layer {i} z={layer.z:.3f}")
        lines.append(f"G0 Z{layer.z:.3f}")
        for x1, y1, x2, y2 in layer.segments:
            lines.append(f"G0 X{x1:.3f} Y{y1:.3f}")
            lines.append(f"G1 X{x2:.3f} Y{y2:.3f}")
    return "\n".join(lines) + "\n"
