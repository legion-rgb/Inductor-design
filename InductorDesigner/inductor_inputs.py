"""Input definitions and result formatting for the Inductor Designer dialog.

Pure Python (no Qt, no FreeCAD): the dialog in ``inductor_ui`` builds its
widgets from the tables here, so the mapping from form values to a design
spec can be unit-tested without a GUI.
"""

from __future__ import annotations

from dataclasses import dataclass

import inductor_core as ic
from inductor_core import PitchMode, Shape


@dataclass(frozen=True)
class Field:
    """One numeric input in a shape's page of the dialog (always mm)."""

    key: str
    label: str
    default: float
    minimum: float
    maximum: float
    step: float = 0.5
    decimals: int = 2
    tooltip: str = ""
    modes: tuple[PitchMode, ...] | None = None  # shown only in these pitch modes


#: Shape-specific dimension fields, in display order.
SHAPE_FIELDS: dict[Shape, list[Field]] = {
    Shape.SOLENOID: [
        Field("form_diameter_mm", "Form diameter (under wire)", 20.0, 0.5, 1000.0,
              tooltip="Diameter of the surface the wire lies on: the outside of the "
                      "tube or rod you wind on, or the bottom of the groove on a "
                      "grooved form. The wire centre sits at half this diameter "
                      "plus half the wire diameter."),
        Field("pitch_mm", "Pitch", 1.0, 0.01, 100.0, step=0.05, decimals=3,
              tooltip="Axial distance between turn centres.",
              modes=(PitchMode.FIXED_PITCH,)),
        Field("length_mm", "Coil length", 30.0, 0.5, 2000.0,
              tooltip="Axial winding length available on the form.",
              modes=(PitchMode.FIXED_LENGTH,)),
    ],
    Shape.MULTILAYER: [
        Field("core_diameter_mm", "Core diameter", 10.0, 0.5, 1000.0,
              tooltip="Diameter of the bobbin core the first layer sits on."),
        Field("winding_length_mm", "Winding length", 15.0, 0.5, 2000.0,
              tooltip="Axial length between the bobbin flanges."),
    ],
    Shape.FLAT_SPIRAL: [
        Field("inner_diameter_mm", "Inner diameter", 20.0, 0.5, 2000.0,
              tooltip="Diameter of the open centre, inside edge of the first turn."),
        Field("pitch_mm", "Pitch", 1.5, 0.01, 100.0, step=0.05, decimals=3,
              tooltip="Radial distance between turn centres.",
              modes=(PitchMode.FIXED_PITCH,)),
    ],
    Shape.TOROID: [
        Field("inner_diameter_mm", "Inner diameter (ID)", 20.0, 0.5, 2000.0,
              tooltip="Inner diameter of the ring (the hole)."),
        Field("outer_diameter_mm", "Outer diameter (OD)", 40.0, 1.0, 2000.0,
              tooltip="Outer diameter of the ring."),
        Field("height_mm", "Height (h)", 10.0, 0.5, 1000.0,
              tooltip="Axial height of the ring."),
    ],
}

#: Pitch modes offered per shape (first entry is the default). Empty = no choice.
SHAPE_MODES: dict[Shape, list[PitchMode]] = {
    Shape.SOLENOID: [PitchMode.CLOSE_WOUND, PitchMode.FIXED_PITCH, PitchMode.FIXED_LENGTH],
    Shape.MULTILAYER: [],
    Shape.FLAT_SPIRAL: [PitchMode.CLOSE_WOUND, PitchMode.FIXED_PITCH],
    Shape.TOROID: [],
}

MODE_LABELS = {
    PitchMode.CLOSE_WOUND: "Close-wound (pitch = wire diameter)",
    PitchMode.FIXED_PITCH: "Fixed pitch",
    PitchMode.FIXED_LENGTH: "Fixed coil length",
}

#: (label, step) pairs for the turns-rounding drop-down.
TURNS_STEPS = [("Whole turns", 1.0), ("Half turns", 0.5), ("Quarter turns", 0.25)]

#: Units in the inductance drop-down (display text). "µH" is the default.
INDUCTANCE_UNITS = ["nH", "µH", "mH"]
DEFAULT_UNIT = "µH"
DEFAULT_TARGET = 10.0

DEFAULT_WIRE_COPPER_MM = 0.80


def build_spec(
    shape: Shape,
    values: dict[str, float],
    wire: ic.Wire,
    mode: PitchMode | None = None,
) -> ic.Spec:
    """Turn dialog values into a design spec. Unused keys are ignored."""
    modes = SHAPE_MODES[shape]
    if mode is None:
        mode = modes[0] if modes else None
    elif mode not in modes:
        raise ic.DesignError(f"{MODE_LABELS[mode]} is not available for this shape")

    def v(key: str) -> float:
        try:
            return float(values[key])
        except KeyError:
            raise ic.DesignError(f"missing input {key!r}") from None

    if shape is Shape.SOLENOID:
        return ic.SolenoidSpec(
            form_diameter_mm=v("form_diameter_mm"),
            wire=wire,
            mode=mode,  # type: ignore[arg-type]
            pitch_mm=v("pitch_mm") if mode is PitchMode.FIXED_PITCH else None,
            length_mm=v("length_mm") if mode is PitchMode.FIXED_LENGTH else None,
        )
    if shape is Shape.MULTILAYER:
        return ic.MultilayerSpec(
            core_diameter_mm=v("core_diameter_mm"),
            winding_length_mm=v("winding_length_mm"),
            wire=wire,
        )
    if shape is Shape.FLAT_SPIRAL:
        return ic.FlatSpiralSpec(
            inner_diameter_mm=v("inner_diameter_mm"),
            wire=wire,
            mode=mode,  # type: ignore[arg-type]
            pitch_mm=v("pitch_mm") if mode is PitchMode.FIXED_PITCH else None,
        )
    if shape is Shape.TOROID:
        return ic.ToroidSpec(
            inner_diameter_mm=v("inner_diameter_mm"),
            outer_diameter_mm=v("outer_diameter_mm"),
            height_mm=v("height_mm"),
            wire=wire,
        )
    raise ic.DesignError(f"unsupported shape {shape!r}")


def make_wire(copper_d_mm: float, overall_d_mm: float | None) -> ic.Wire:
    """Wire from dialog values; ``overall_d_mm`` of 0 or None means "estimate"."""
    return ic.Wire(copper_d_mm, overall_d_mm if overall_d_mm else None)


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_inductance(value_uH: float, unit: str = DEFAULT_UNIT) -> str:
    return f"{ic.from_uH(value_uH, unit):.4g} {unit}"


def format_length(mm: float) -> str:
    return f"{mm / 1000:.3g} m" if mm >= 1000 else f"{mm:.4g} mm"


def format_resistance(ohm: float) -> str:
    if ohm < 1:
        return f"{ohm * 1000:.3g} mΩ"
    return f"{ohm:.4g} Ω"


def format_turns(turns: float) -> str:
    return f"{turns:g}"


_DETAIL_ROWS = [
    ("mean_radius_mm", "Mean radius", format_length),
    ("outer_diameter_mm", "Outer diameter (with wire)", format_length),
    ("winding_depth_mm", "Winding depth", format_length),
    ("turns_per_layer", "Turns per layer", lambda x: f"{x:g}"),
    ("layers", "Layers", lambda x: f"{x:g}"),
    ("max_single_layer_turns", "Max single-layer turns", lambda x: f"{x:g}"),
]

_LENGTH_LABEL = {
    Shape.SOLENOID: "Coil length",
    Shape.MULTILAYER: "Winding length",
    Shape.FLAT_SPIRAL: "Winding width (radial)",
}

_PITCH_LABEL = {
    Shape.SOLENOID: "Pitch",
    Shape.MULTILAYER: "Wire spacing",
    Shape.FLAT_SPIRAL: "Pitch (radial)",
    Shape.TOROID: "Spacing on inner edge",
}


def result_rows(result: ic.DesignResult, unit: str = DEFAULT_UNIT) -> list[tuple[str, str]]:
    """(label, value) rows for the results panel, in display order."""
    rows = [
        ("Turns", format_turns(result.turns)),
        ("Exact solution", f"{result.turns_exact:.3f} turns"),
    ]
    if result.pitch_mm is not None:
        rows.append((_PITCH_LABEL[result.shape], f"{result.pitch_mm:.4g} mm"))
    if result.coil_length_mm is not None:
        rows.append((_LENGTH_LABEL[result.shape], format_length(result.coil_length_mm)))
    rows += [
        ("Predicted L", format_inductance(result.predicted_uH, unit)),
        ("Rounding error", f"{result.error_pct:+.2f} %"),
        ("Wire length", format_length(result.wire_length_mm)),
        ("DC resistance (20 °C)", format_resistance(result.dcr_ohm)),
    ]
    for key, label, fmt in _DETAIL_ROWS:
        if key in result.details:
            rows.append((label, fmt(result.details[key])))
    return rows
