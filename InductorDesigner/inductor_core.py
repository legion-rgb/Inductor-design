"""Inductor design core: Wheeler-family formulas and turn/pitch solvers.

Pure Python (standard library only) with no FreeCAD imports, so it can be
tested with a plain ``python3`` and reused by the FreeCAD macro.

Units used throughout:
    lengths, diameters  -> mm
    inductance          -> uH (use ``to_uH`` / ``from_uH`` for nH and mH)
    resistance          -> ohm

Radii passed to the formulas are measured to the *wire centre*.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, ClassVar, Union

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MU0 = 1.25663706212e-6  # vacuum permeability, H/m (CODATA 2018)
RHO_CU = 1.724e-8  # resistivity of annealed copper at 20 degC, ohm*m (IACS)
MAX_TURNS = 100_000  # solver gives up beyond this

# Nominal copper diameters of enamelled round wire (IEC R20 series), mm.
NOMINAL_WIRE_DIAMETERS_MM = (
    0.10, 0.112, 0.125, 0.14, 0.16, 0.18, 0.20, 0.224, 0.25, 0.28,
    0.315, 0.355, 0.40, 0.45, 0.50, 0.56, 0.63, 0.71, 0.80, 0.90,
    1.00, 1.12, 1.25, 1.40, 1.60, 1.80, 2.00,
)

# Inductance unit factors relative to uH.
_UNIT_FACTORS = {"nH": 1e-3, "uH": 1.0, "µH": 1.0, "mH": 1e3}


class DesignError(ValueError):
    """Raised when inputs are invalid or the requested coil cannot be built."""


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

def to_uH(value: float, unit: str) -> float:
    """Convert ``value`` given in ``unit`` (nH, uH/µH, mH) to uH."""
    try:
        return value * _UNIT_FACTORS[unit]
    except KeyError:
        raise DesignError(f"Unknown inductance unit {unit!r}") from None


def from_uH(value_uH: float, unit: str) -> float:
    """Convert a value in uH to ``unit`` (nH, uH/µH, mH)."""
    try:
        return value_uH / _UNIT_FACTORS[unit]
    except KeyError:
        raise DesignError(f"Unknown inductance unit {unit!r}") from None


# ---------------------------------------------------------------------------
# Enums and inputs
# ---------------------------------------------------------------------------

class Shape(Enum):
    SOLENOID = "solenoid"
    MULTILAYER = "multilayer"
    FLAT_SPIRAL = "flat_spiral"
    TOROID = "toroid"


#: Labels for the shape drop-down, in display order.
SHAPE_LABELS = {
    Shape.SOLENOID: "Single-layer solenoid",
    Shape.MULTILAYER: "Multi-layer solenoid",
    Shape.FLAT_SPIRAL: "Flat spiral (pancake)",
    Shape.TOROID: "Toroid (rectangular section)",
}


class PitchMode(Enum):
    CLOSE_WOUND = "close_wound"  # pitch = overall wire diameter
    FIXED_PITCH = "fixed_pitch"  # user gives the pitch
    FIXED_LENGTH = "fixed_length"  # user gives the coil length (solenoid only)


def _require_positive(**values: float | None) -> None:
    for name, value in values.items():
        if value is None or not math.isfinite(value) or value <= 0:
            raise DesignError(f"{name} must be a positive number (got {value!r})")


def estimate_overall_diameter(copper_d_mm: float) -> float:
    """Rough enamelled-wire overall diameter (grade 1) from copper diameter.

    Only an estimate; measure the real wire with calipers when you can.
    """
    return copper_d_mm * 1.06 + 0.012


@dataclass(frozen=True)
class Wire:
    """Round enamelled wire. ``overall_d_mm`` includes the insulation."""

    copper_d_mm: float
    overall_d_mm: float | None = None

    def __post_init__(self) -> None:
        _require_positive(copper_d_mm=self.copper_d_mm)
        if self.overall_d_mm is None:
            object.__setattr__(
                self, "overall_d_mm", estimate_overall_diameter(self.copper_d_mm)
            )
        _require_positive(overall_d_mm=self.overall_d_mm)
        if self.overall_d_mm < self.copper_d_mm:
            raise DesignError("overall wire diameter cannot be smaller than copper diameter")

    @property
    def d(self) -> float:
        """Overall diameter, mm (what sets pitch and fit)."""
        return float(self.overall_d_mm)  # type: ignore[arg-type]


@dataclass(frozen=True)
class SolenoidSpec:
    """Single-layer solenoid wound on a cylindrical form."""

    shape: ClassVar[Shape] = Shape.SOLENOID
    form_diameter_mm: float
    wire: Wire
    mode: PitchMode = PitchMode.CLOSE_WOUND
    pitch_mm: float | None = None  # required for FIXED_PITCH
    length_mm: float | None = None  # required for FIXED_LENGTH


@dataclass(frozen=True)
class MultilayerSpec:
    """Multi-layer solenoid on a bobbin core of given diameter and winding length."""

    shape: ClassVar[Shape] = Shape.MULTILAYER
    core_diameter_mm: float
    winding_length_mm: float
    wire: Wire


@dataclass(frozen=True)
class FlatSpiralSpec:
    """Flat (pancake) spiral starting at ``inner_diameter_mm``."""

    shape: ClassVar[Shape] = Shape.FLAT_SPIRAL
    inner_diameter_mm: float
    wire: Wire
    mode: PitchMode = PitchMode.CLOSE_WOUND
    pitch_mm: float | None = None  # required for FIXED_PITCH


@dataclass(frozen=True)
class ToroidSpec:
    """Toroid on a rectangular-section ring (air or non-magnetic core)."""

    shape: ClassVar[Shape] = Shape.TOROID
    inner_diameter_mm: float
    outer_diameter_mm: float
    height_mm: float
    wire: Wire


Spec = Union[SolenoidSpec, MultilayerSpec, FlatSpiralSpec, ToroidSpec]


@dataclass
class DesignResult:
    shape: Shape
    target_uH: float
    turns_exact: float  # unrounded solution
    turns: float  # rounded, buildable
    pitch_mm: float | None
    coil_length_mm: float | None  # axial length (solenoids) or radial width (spiral)
    predicted_uH: float  # at the rounded turn count
    error_pct: float  # (predicted - target) / target * 100
    wire_length_mm: float
    dcr_ohm: float
    warnings: list[str] = field(default_factory=list)
    details: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Forward formulas (mm -> uH)
# ---------------------------------------------------------------------------
# Wheeler's formulas in inches -> uH, rescaled to mm by 1 in = 25.4 mm:
#   single layer : r^2 N^2 / (9r + 10l)          -> r^2 N^2 / (228.6r + 254l)
#   multi layer  : 0.8 r^2 N^2 / (6r + 9l + 10b) -> r^2 N^2 / (190.5r + 285.75l + 317.5b)
#   flat spiral  : r^2 N^2 / (8r + 11w)          -> r^2 N^2 / (203.2r + 279.4w)

def solenoid_L_uH(r_mm: float, length_mm: float, turns: float) -> float:
    """Wheeler single-layer solenoid. ``r_mm`` to wire centre, ``length_mm`` winding length."""
    return r_mm**2 * turns**2 / (228.6 * r_mm + 254.0 * length_mm)


def multilayer_L_uH(r_mm: float, length_mm: float, depth_mm: float, turns: float) -> float:
    """Wheeler multi-layer solenoid. ``r_mm`` mean radius, ``depth_mm`` winding depth."""
    return r_mm**2 * turns**2 / (190.5 * r_mm + 285.75 * length_mm + 317.5 * depth_mm)


def flat_spiral_L_uH(r_mm: float, width_mm: float, turns: float) -> float:
    """Wheeler flat spiral. ``r_mm`` mean radius, ``width_mm`` radial winding width."""
    return r_mm**2 * turns**2 / (203.2 * r_mm + 279.4 * width_mm)


def toroid_L_uH(ri_mm: float, ro_mm: float, height_mm: float, turns: float) -> float:
    """Ideal toroid of rectangular cross-section: mu0 N^2 h ln(ro/ri) / 2pi."""
    henry = MU0 * turns**2 * (height_mm * 1e-3) * math.log(ro_mm / ri_mm) / (2 * math.pi)
    return henry * 1e6


# ---------------------------------------------------------------------------
# Inverse solvers (uH -> turns)
# ---------------------------------------------------------------------------

def solenoid_turns_fixed_length(L_uH: float, r_mm: float, length_mm: float) -> float:
    """N for a solenoid of fixed winding length."""
    return math.sqrt(L_uH * (228.6 * r_mm + 254.0 * length_mm)) / r_mm


def solenoid_turns_fixed_pitch(L_uH: float, r_mm: float, pitch_mm: float) -> float:
    """N for a solenoid of fixed pitch (length = N * pitch).

    Solves r^2 N^2 - 254 L p N - 228.6 L r = 0 for the positive root.
    """
    a = 254.0 * L_uH * pitch_mm
    return (a + math.sqrt(a * a + 4 * r_mm**2 * 228.6 * L_uH * r_mm)) / (2 * r_mm**2)


def toroid_turns(L_uH: float, ri_mm: float, ro_mm: float, height_mm: float) -> float:
    """N for an ideal rectangular-section toroid."""
    per_turn2 = toroid_L_uH(ri_mm, ro_mm, height_mm, 1.0)
    return math.sqrt(L_uH / per_turn2)


def solve_turns(L_of_N: Callable[[float], float], target_uH: float) -> float:
    """Find N > 0 with ``L_of_N(N) == target_uH`` for increasing ``L_of_N``.

    Uses bracketing by doubling, then bisection (standard library only).
    """
    lo, hi = 0.0, 1.0
    while L_of_N(hi) < target_uH:
        lo, hi = hi, hi * 2
        if hi > MAX_TURNS:
            raise DesignError(
                f"target needs more than {MAX_TURNS} turns; enlarge the geometry"
            )
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if L_of_N(mid) < target_uH:
            lo = mid
        else:
            hi = mid
        if hi - lo <= 1e-13 * hi:
            break
    return 0.5 * (lo + hi)


# ---------------------------------------------------------------------------
# Wire helpers
# ---------------------------------------------------------------------------

def dcr_ohm(wire_length_mm: float, copper_d_mm: float) -> float:
    """DC resistance of copper wire at 20 degC."""
    area_m2 = math.pi * (copper_d_mm * 1e-3 / 2) ** 2
    return RHO_CU * (wire_length_mm * 1e-3) / area_m2


def helix_length_mm(r_mm: float, pitch_mm: float, turns: float) -> float:
    return turns * math.hypot(2 * math.pi * r_mm, pitch_mm)


def archimedean_spiral_length_mm(r0_mm: float, pitch_mm: float, turns: float) -> float:
    """Arc length of r = r0 + (pitch / 2pi) * theta over ``turns`` turns."""
    b = pitch_mm / (2 * math.pi)
    r1 = r0_mm + pitch_mm * turns

    def antiderivative(u: float) -> float:
        s = math.hypot(u, b)
        return 0.5 * u * s + 0.5 * b * b * math.log(u + s)

    return (antiderivative(r1) - antiderivative(r0_mm)) / b


def round_turns(turns: float, step: float = 1.0) -> float:
    """Round to the nearest multiple of ``step`` (half up), at least one step."""
    _require_positive(step=step)
    return max(step, math.floor(turns / step + 0.5) * step)


# ---------------------------------------------------------------------------
# Design entry point
# ---------------------------------------------------------------------------

def design(
    spec: Spec,
    target_uH: float,
    turns_step: float = 1.0,
    lead_length_mm: float = 0.0,
) -> DesignResult:
    """Compute turns, pitch and derived values for ``spec`` and ``target_uH``.

    ``turns_step`` sets the rounding (1 = whole turns, 0.5, 0.25 ...).
    ``lead_length_mm`` (total of both leads) is added to wire length / DCR.
    """
    _require_positive(target_uH=target_uH, turns_step=turns_step)
    if lead_length_mm < 0:
        raise DesignError("lead_length_mm cannot be negative")

    if isinstance(spec, SolenoidSpec):
        result = _design_solenoid(spec, target_uH, turns_step)
    elif isinstance(spec, MultilayerSpec):
        result = _design_multilayer(spec, target_uH, turns_step)
    elif isinstance(spec, FlatSpiralSpec):
        result = _design_flat_spiral(spec, target_uH, turns_step)
    elif isinstance(spec, ToroidSpec):
        result = _design_toroid(spec, target_uH, turns_step)
    else:
        raise DesignError(f"unsupported spec type {type(spec).__name__}")

    result.wire_length_mm += lead_length_mm
    result.dcr_ohm = dcr_ohm(result.wire_length_mm, spec.wire.copper_d_mm)
    result.error_pct = (result.predicted_uH - target_uH) / target_uH * 100.0
    if abs(result.error_pct) > 2.0:
        result.warnings.append(
            f"Rounding to {result.turns:g} turns changes L by {result.error_pct:+.1f}%; "
            "use a finer turns step or adjust the dimensions."
        )
    return result


def _resolve_pitch(mode: PitchMode, pitch_mm: float | None, wire: Wire) -> float:
    if mode is PitchMode.CLOSE_WOUND:
        return wire.d
    if mode is PitchMode.FIXED_PITCH:
        _require_positive(pitch_mm=pitch_mm)
        assert pitch_mm is not None
        if pitch_mm < wire.d:
            raise DesignError(
                f"pitch {pitch_mm:g} mm is smaller than the wire diameter {wire.d:g} mm"
            )
        return pitch_mm
    raise DesignError(f"pitch mode {mode.value} is not valid here")


def _design_solenoid(spec: SolenoidSpec, target: float, step: float) -> DesignResult:
    _require_positive(form_diameter_mm=spec.form_diameter_mm)
    d = spec.wire.d
    r = spec.form_diameter_mm / 2 + d / 2
    warnings: list[str] = []

    if spec.mode is PitchMode.FIXED_LENGTH:
        _require_positive(length_mm=spec.length_mm)
        length = float(spec.length_mm)  # type: ignore[arg-type]
        n_exact = solenoid_turns_fixed_length(target, r, length)
        if length / n_exact < d:
            raise DesignError(
                f"{n_exact:.1f} turns do not fit in {length:g} mm with {d:g} mm wire "
                f"(pitch would be {length / n_exact:.3f} mm); "
                "increase the length or use thinner wire"
            )
        n = round_turns(n_exact, step)
        if length / n < d:  # rounding up broke the fit; round down instead
            n = math.floor(n_exact / step) * step
            if n < step:
                raise DesignError("coil cannot be built at this turns step")
        pitch = length / n
    else:
        pitch = _resolve_pitch(spec.mode, spec.pitch_mm, spec.wire)
        n_exact = solenoid_turns_fixed_pitch(target, r, pitch)
        n = round_turns(n_exact, step)
        length = n * pitch

    predicted = solenoid_L_uH(r, length, n)
    if length < 0.8 * r:
        warnings.append(
            f"Coil length/radius = {length / r:.2f} < 0.8: Wheeler's formula is "
            "outside its ~1% accuracy range (short coil)."
        )
    return DesignResult(
        shape=Shape.SOLENOID,
        target_uH=target,
        turns_exact=n_exact,
        turns=n,
        pitch_mm=pitch,
        coil_length_mm=length,
        predicted_uH=predicted,
        error_pct=0.0,
        wire_length_mm=helix_length_mm(r, pitch, n),
        dcr_ohm=0.0,
        warnings=warnings,
        details={
            "mean_radius_mm": r,
            "outer_diameter_mm": spec.form_diameter_mm + 2 * d,
        },
    )


def _design_multilayer(spec: MultilayerSpec, target: float, step: float) -> DesignResult:
    _require_positive(
        core_diameter_mm=spec.core_diameter_mm,
        winding_length_mm=spec.winding_length_mm,
    )
    d = spec.wire.d
    length = spec.winding_length_mm
    r_core = spec.core_diameter_mm / 2
    turns_per_layer = math.floor(length / d + 1e-9)
    if turns_per_layer < 1:
        raise DesignError("winding length is shorter than one wire diameter")

    # Continuous (square-packing) model: winding cross-section l*b holds N*d^2.
    def geometry(n: float) -> tuple[float, float]:
        depth = n * d * d / length
        return r_core + depth / 2, depth

    def L_of_N(n: float) -> float:
        r, depth = geometry(n)
        return multilayer_L_uH(r, length, depth, n)

    n_exact = solve_turns(L_of_N, target)
    n = round_turns(n_exact, step)
    r, depth = geometry(n)
    predicted = multilayer_L_uH(r, length, depth, n)
    layers = math.ceil(n / turns_per_layer - 1e-9)

    warnings: list[str] = []
    terms = (6 * r, 9 * length, 10 * depth)
    if max(terms) > 3 * min(terms):
        warnings.append(
            "Radius, length and depth are far from balanced; Wheeler's multi-layer "
            "formula is most accurate (~1%) when 6r, 9l and 10b are similar."
        )
    return DesignResult(
        shape=Shape.MULTILAYER,
        target_uH=target,
        turns_exact=n_exact,
        turns=n,
        pitch_mm=d,
        coil_length_mm=length,
        predicted_uH=predicted,
        error_pct=0.0,
        wire_length_mm=n * 2 * math.pi * r,
        dcr_ohm=0.0,
        warnings=warnings,
        details={
            "mean_radius_mm": r,
            "winding_depth_mm": depth,
            "turns_per_layer": float(turns_per_layer),
            "layers": float(layers),
            "outer_diameter_mm": spec.core_diameter_mm + 2 * layers * d,
        },
    )


def _design_flat_spiral(spec: FlatSpiralSpec, target: float, step: float) -> DesignResult:
    _require_positive(inner_diameter_mm=spec.inner_diameter_mm)
    if spec.mode is PitchMode.FIXED_LENGTH:
        raise DesignError("flat spiral supports close-wound or fixed-pitch mode only")
    d = spec.wire.d
    pitch = _resolve_pitch(spec.mode, spec.pitch_mm, spec.wire)
    r0 = spec.inner_diameter_mm / 2 + d / 2  # centre of the first turn

    def L_of_N(n: float) -> float:
        width = n * pitch
        return flat_spiral_L_uH(r0 + width / 2, width, n)

    n_exact = solve_turns(L_of_N, target)
    n = round_turns(n_exact, step)
    width = n * pitch
    r_mean = r0 + width / 2
    predicted = flat_spiral_L_uH(r_mean, width, n)

    warnings: list[str] = []
    if width < 0.2 * r_mean:
        warnings.append(
            "Winding width < 0.2 x mean radius: Wheeler's flat-spiral formula is "
            "commonly quoted as accurate to ~5% only above this ratio."
        )
    return DesignResult(
        shape=Shape.FLAT_SPIRAL,
        target_uH=target,
        turns_exact=n_exact,
        turns=n,
        pitch_mm=pitch,
        coil_length_mm=width,
        predicted_uH=predicted,
        error_pct=0.0,
        wire_length_mm=archimedean_spiral_length_mm(r0, pitch, n),
        dcr_ohm=0.0,
        warnings=warnings,
        details={
            "mean_radius_mm": r_mean,
            "outer_diameter_mm": 2 * (r0 + width) + d,
        },
    )


def _design_toroid(spec: ToroidSpec, target: float, step: float) -> DesignResult:
    _require_positive(
        inner_diameter_mm=spec.inner_diameter_mm,
        outer_diameter_mm=spec.outer_diameter_mm,
        height_mm=spec.height_mm,
    )
    if spec.outer_diameter_mm <= spec.inner_diameter_mm:
        raise DesignError("outer diameter must be larger than inner diameter")
    d = spec.wire.d
    if spec.inner_diameter_mm <= 2 * d:
        raise DesignError("inner diameter is too small for the wire")
    ri, ro, h = spec.inner_diameter_mm / 2, spec.outer_diameter_mm / 2, spec.height_mm

    n_exact = toroid_turns(target, ri, ro, h)
    n = round_turns(n_exact, step)
    predicted = toroid_L_uH(ri, ro, h, n)

    # Single layer limit: wire centres on the inner circumference at radius ri - d/2.
    max_single_layer = math.floor(2 * math.pi * (ri - d / 2) / d)
    warnings: list[str] = []
    if n > max_single_layer:
        warnings.append(
            f"{n:g} turns exceed the single-layer limit of {max_single_layer} turns "
            "on the inner edge; use thinner wire or a larger inner diameter."
        )
    turn_length = 2 * ((ro - ri) + h) + math.pi * d  # rectangle offset by d/2
    return DesignResult(
        shape=Shape.TOROID,
        target_uH=target,
        turns_exact=n_exact,
        turns=n,
        pitch_mm=2 * math.pi * (ri - d / 2) / n,  # spacing along the inner edge
        coil_length_mm=None,
        predicted_uH=predicted,
        error_pct=0.0,
        wire_length_mm=n * turn_length,
        dcr_ohm=0.0,
        warnings=warnings,
        details={
            "max_single_layer_turns": float(max_single_layer),
            "outer_diameter_mm": spec.outer_diameter_mm + 2 * d,
        },
    )
