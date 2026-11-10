"""Build coil forms in FreeCAD from an Inductor Designer result.

Only FreeCAD's own ``Part`` module is used. FreeCAD is imported inside the
functions, so this module (and ``CadOptions``) can be imported anywhere; the
geometry functions need to run inside FreeCAD or ``freecadcmd``.

What gets built (all dimensions in mm, coil axis = Z):

* Single-layer solenoid: a tube with a helical groove that seats the wire at
  the design radius, end flanges, and wire-exit holes into the bore. When the
  pitch leaves no room for a land between grooves (e.g. close-wound) the form
  is a plain cylinder of the form diameter.
* Multi-layer solenoid: a bobbin (core tube plus two flanges) with a wire slot.
* Flat spiral: a disc with a spiral groove and exit holes. The spiral is
  built from semicircles (see ``spiral_half_turns``), which follows the
  Archimedean spiral closely and keeps FreeCAD's booleans reliable.
* Toroid: a rectangular-section ring with one guide notch per turn on the
  outer edge.

The optional "WireModel" solid shows where the wire goes; it is only for
looking at and is not meant to be exported.

Exporting is left to the user (File > Export in FreeCAD).
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, fields
from enum import Enum
from typing import Any

import inductor_core as ic
from inductor_core import Shape

COPPER_RGB = (0.72, 0.45, 0.20)
FORM_RGB = (0.80, 0.80, 0.78)
SHAPE_NAMES = {
    Shape.SOLENOID: "Solenoid",
    Shape.MULTILAYER: "Multilayer",
    Shape.FLAT_SPIRAL: "FlatSpiral",
    Shape.TOROID: "Toroid",
}


class CadError(RuntimeError):
    """Raised when a coil form cannot be built or comes out invalid."""


@dataclass
class CadOptions:
    """Coil-form construction options (mm unless stated otherwise)."""

    groove_clearance_mm: float = 0.2  # groove diameter = wire diameter + this
    groove_depth_pct: float = 60.0  # land height above groove bottom, % of wire diameter
    min_land_mm: float = 0.4  # thinnest ridge allowed between grooves/notches
    wall_mm: float = 2.0  # wall under the groove; 0 = solid rod
    end_margin_mm: float = 3.0  # plain length before the first / after the last turn
    flange_mm: float = 2.0  # flange thickness; 0 = no flanges (solenoid)
    flange_extra_mm: float = 2.0  # flange / rim height beyond the wire
    base_mm: float = 2.0  # spiral disc thickness under the groove
    hole_clearance_mm: float = 0.4  # exit hole diameter = wire diameter + this
    add_wire_model: bool = True

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "CadOptions":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in values.items() if k in known})


# ---------------------------------------------------------------------------
# Geometry (needs FreeCAD)
# ---------------------------------------------------------------------------

def _fc():
    try:
        import FreeCAD  # type: ignore[import-not-found]
        import Part  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise CadError("FreeCAD is required to build the coil form") from exc
    return FreeCAD, Part


def _cylinder(r: float, h: float, z: float = 0.0):
    App, Part = _fc()
    return Part.makeCylinder(r, h, App.Vector(0, 0, z), App.Vector(0, 0, 1))


def _sweep_circle(spine, radius: float, start, tangent):
    """Sweep a circle of ``radius`` (centred at ``start``, normal ``tangent``) along ``spine``."""
    App, Part = _fc()
    profile = Part.Wire(Part.makeCircle(radius, start, tangent))
    solid = spine.makePipeShell([profile], True, True)  # solid, Frenet
    if solid.ShapeType != "Solid" and solid.Solids:
        solid = solid.Solids[0]
    return solid


def _helix_sweep(r: float, pitch: float, turns: float, z0: float, profile_r: float):
    App, Part = _fc()
    helix = Part.makeHelix(pitch, pitch * turns, r)
    helix.translate(App.Vector(0, 0, z0))
    start = App.Vector(r, 0, z0)
    tangent = App.Vector(0, 2 * math.pi * r, pitch)
    return _sweep_circle(helix, profile_r, start, tangent)


def _helix_groove(r: float, pitch: float, turns: float, z0: float, profile_r: float):
    """Helical sweep built one turn at a time.

    Cutting a stack of one-turn sweeps is several times faster in OpenCASCADE
    than cutting a single many-turn sweep, and gives the same solid.
    """
    App, _ = _fc()
    full = int(math.floor(turns + 1e-9))
    pieces = []
    if full:
        one = _helix_sweep(r, pitch, 1.0, z0, profile_r)
        for k in range(full):
            piece = one.copy()
            piece.translate(App.Vector(0, 0, k * pitch))
            pieces.append(piece)
    rest = turns - full
    if rest > 1e-6:
        pieces.append(_helix_sweep(r, pitch, rest, z0 + full * pitch, profile_r))
    return pieces


def spiral_half_turns(r0: float, pitch: float, turns: float):
    """Spiral made of semicircles: list of (centre_x, radius, start_deg, span_deg).

    Half-turn k is centred on (0, 0) for even k and on (pitch/2, 0) for odd k,
    with the radius growing by pitch/2 each half turn. Consecutive arcs meet
    on the x axis with a common tangent, and each full turn moves out by
    exactly ``pitch``, so the result follows the Archimedean spiral
    r = r0 + pitch * theta / 2pi closely while every piece stays a simple arc.
    """
    halves = 2.0 * turns
    arcs = []
    k = 0
    while halves - k > 1e-9:
        span = 180.0 * min(1.0, halves - k)
        if k % 2 == 0:
            arcs.append((0.0, r0 + (k // 2) * pitch, 0.0, span))
        else:
            arcs.append((pitch / 2, r0 + (k // 2) * pitch + pitch / 2, 180.0, span))
        k += 1
    return arcs


def _arc_point(cx: float, radius: float, deg: float, z: float):
    App, _ = _fc()
    a = math.radians(deg)
    return App.Vector(cx + radius * math.cos(a), radius * math.sin(a), z)


def _spiral_sweep(r0: float, pitch: float, turns: float, z: float, profile_r: float):
    """Round-section groove/wire along the semicircle spiral: list of half-tori."""
    App, Part = _fc()
    pieces = []
    for cx, radius, start, span in spiral_half_turns(r0, pitch, turns):
        a = math.radians(start)
        centre = _arc_point(cx, radius, start, z)
        normal = App.Vector(-math.sin(a), math.cos(a), 0)
        face = Part.Face(Part.Wire(Part.makeCircle(profile_r, centre, normal)))
        pieces.append(face.revolve(App.Vector(cx, 0, z), App.Vector(0, 0, 1), span))
    return pieces


def spiral_end_points(r0: float, pitch: float, turns: float):
    """(x, y) of the first and last point of the semicircle spiral."""
    arcs = spiral_half_turns(r0, pitch, turns)
    cx, radius, start, span = arcs[-1]
    end = _arc_point(cx, radius, start + span, 0.0)
    return (r0, 0.0), (end.x, end.y)


def _radial_hole(radius: float, length: float, z: float, angle_rad: float):
    App, Part = _fc()
    direction = App.Vector(math.cos(angle_rad), math.sin(angle_rad), 0)
    return Part.makeCylinder(radius, length, App.Vector(0, 0, z), direction)


def _cut_all(body, tools):
    """Cut every tool from ``body`` in one boolean (tools may overlap)."""
    tools = [t for t in tools if t is not None]
    return body.cut(tools) if tools else body


def _solenoid(spec: ic.SolenoidSpec, res: ic.DesignResult, opt: CadOptions):
    _, Part = _fc()
    notes: list[str] = []
    d, n, p = spec.wire.d, res.turns, float(res.pitch_mm)
    form_r = spec.form_diameter_mm / 2
    g = d + opt.groove_clearance_mm
    grooved = p - g >= opt.min_land_mm
    outer_r = form_r + opt.groove_depth_pct / 100 * d if grooved else form_r
    if not grooved:
        notes.append(
            f"Pitch {p:.3g} mm leaves less than {opt.min_land_mm:g} mm between "
            f"{g:.3g} mm grooves, so the form is a plain {spec.form_diameter_mm:g} mm "
            "cylinder with no groove. Use fixed pitch with some spacing to get a groove."
        )
    zf = max(opt.flange_mm, 0.0)
    z0 = zf + opt.end_margin_mm
    total = 2 * z0 + n * p

    body = _cylinder(outer_r, total)
    if zf > 0:
        flange_r = max(outer_r, form_r + d) + opt.flange_extra_mm
        body = body.fuse([_cylinder(flange_r, zf), _cylinder(flange_r, zf, total - zf)])
    tools = []
    if grooved:
        tools += _helix_groove(form_r + g / 2, p, n, z0, g / 2)
    bore_r = form_r - opt.wall_mm
    if opt.wall_mm > 0 and bore_r >= 0.5:
        tools.append(_cylinder(bore_r, total + 2, -1))
        hole_r = (d + opt.hole_clearance_mm) / 2
        reach = outer_r + opt.flange_extra_mm + d + 5
        end_angle = 2 * math.pi * (n % 1.0)
        tools.append(_radial_hole(hole_r, reach, z0, 0.0))
        tools.append(_radial_hole(hole_r, reach, z0 + n * p, end_angle))
    else:
        notes.append("Solid rod (no bore), so no wire-exit holes were cut.")
    form = _cut_all(body, tools).removeSplitter()

    shapes = {"CoilForm": form}
    if opt.add_wire_model:
        shapes["WireModel"] = _helix_sweep(form_r + d / 2, p, n, z0, 0.49 * d)
    return shapes, notes


def _multilayer(spec: ic.MultilayerSpec, res: ic.DesignResult, opt: CadOptions):
    App, Part = _fc()
    notes: list[str] = []
    d = spec.wire.d
    rc, length = spec.core_diameter_mm / 2, spec.winding_length_mm
    layers = res.details["layers"]
    zf = max(opt.flange_mm, 1.5)
    flange_r = rc + layers * d + opt.flange_extra_mm
    total = length + 2 * zf

    body = _cylinder(rc, total).fuse(
        [_cylinder(flange_r, zf), _cylinder(flange_r, zf, total - zf)]
    )
    tools = []
    bore_r = rc - opt.wall_mm
    if opt.wall_mm > 0 and bore_r >= 0.5:
        tools.append(_cylinder(bore_r, total + 2, -1))
    slot_w = d + opt.hole_clearance_mm
    tools.append(Part.makeBox(flange_r + 1 - rc, slot_w, zf + 0.01,
                              App.Vector(rc, -slot_w / 2, -0.01)))
    form = _cut_all(body, tools).removeSplitter()
    notes.append(f"Wind {res.turns:g} turns in about {layers:g} layers "
                 f"of {res.details['turns_per_layer']:g} turns.")

    shapes = {"CoilForm": form}
    if opt.add_wire_model:
        depth = res.details["winding_depth_mm"]
        outer = _cylinder(rc + depth, length, zf)
        shapes["WireModel"] = outer.cut(_cylinder(rc, length + 2, zf - 1))
    return shapes, notes


def _flat_spiral(spec: ic.FlatSpiralSpec, res: ic.DesignResult, opt: CadOptions):
    App, Part = _fc()
    notes: list[str] = []
    d, n, p = spec.wire.d, res.turns, float(res.pitch_mm)
    r0 = spec.inner_diameter_mm / 2 + d / 2
    g = d + opt.groove_clearance_mm
    grooved = p - g >= opt.min_land_mm
    base = opt.base_mm
    thickness = base + (opt.groove_depth_pct / 100 * d if grooved else 0.0)
    disc_r = r0 + n * p + d / 2 + opt.flange_extra_mm

    body = _cylinder(disc_r, thickness)
    tools = []
    if grooved:
        tools += _spiral_sweep(r0, p, n, base + g / 2, g / 2)
    else:
        notes.append(
            f"Pitch {p:.3g} mm leaves less than {opt.min_land_mm:g} mm between "
            f"{g:.3g} mm grooves, so the disc is flat with no groove."
        )
    hole_r = (d + opt.hole_clearance_mm) / 2
    for x, y in spiral_end_points(r0, p, n):
        tools.append(Part.makeCylinder(hole_r, thickness + 2, App.Vector(x, y, -1)))
    form = _cut_all(body, tools).removeSplitter()

    shapes = {"CoilForm": form}
    if opt.add_wire_model:
        z = (base if grooved else thickness) + d / 2
        shapes["WireModel"] = Part.makeCompound(_spiral_sweep(r0, p, n, z, 0.49 * d))
    return shapes, notes


def _toroid(spec: ic.ToroidSpec, res: ic.DesignResult, opt: CadOptions):
    App, Part = _fc()
    notes: list[str] = []
    d = spec.wire.d
    ri, ro, h = spec.inner_diameter_mm / 2, spec.outer_diameter_mm / 2, spec.height_mm
    ring = _cylinder(ro, h).cut(_cylinder(ri, h + 2, -1))

    count = int(math.ceil(res.turns))
    g = d + opt.groove_clearance_mm
    depth = opt.groove_depth_pct / 100 * d
    spacing = 2 * math.pi * ro / count
    tools = []
    if spacing - g < opt.min_land_mm or depth >= ro - ri:
        notes.append(f"{count} notches of {g:.3g} mm do not fit on the outer edge; "
                     "the ring has no guide notches.")
    else:
        for k in range(count):
            notch = Part.makeBox(depth + 1, g, h + 2, App.Vector(ro - depth, -g / 2, -1))
            notch.rotate(App.Vector(0, 0, 0), App.Vector(0, 0, 1), 360.0 * k / count)
            tools.append(notch)
    form = _cut_all(ring, tools).removeSplitter()
    if opt.add_wire_model:
        notes.append("No wire model is drawn for toroids.")
    return {"CoilForm": form}, notes


_BUILDERS = {
    Shape.SOLENOID: _solenoid,
    Shape.MULTILAYER: _multilayer,
    Shape.FLAT_SPIRAL: _flat_spiral,
    Shape.TOROID: _toroid,
}


def make_shapes(spec: ic.Spec, result: ic.DesignResult, options: CadOptions | None = None):
    """Return ``({name: Part.Shape}, notes)`` for the design. Nothing is added to a document."""
    opt = options or CadOptions()
    if result.shape is not spec.shape:
        raise CadError("design result does not belong to this spec")
    try:
        return _BUILDERS[spec.shape](spec, result, opt)
    except CadError:
        raise
    except Exception as exc:  # OCC errors come through as generic exceptions
        raise CadError(f"FreeCAD could not build the {SHAPE_NAMES[spec.shape]} form: {exc}") from exc


def check_shape(shape) -> list[str]:
    """Problems with a built shape (empty list = fine)."""
    problems = []
    if shape.isNull():
        return ["shape is empty"]
    if not shape.isValid():
        problems.append("shape is not valid")
    if not shape.Solids:
        problems.append("shape has no solid")
    elif shape.Volume <= 0:
        problems.append("shape has no volume")
    return problems


# ---------------------------------------------------------------------------
# Document objects
# ---------------------------------------------------------------------------

def spec_to_dict(spec: ic.Spec) -> dict[str, Any]:
    def plain(value):
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, dict):
            return {k: plain(v) for k, v in value.items()}
        return value

    data = plain(asdict(spec))
    data["shape"] = spec.shape.value
    return data


def _add_properties(obj, spec: ic.Spec, res: ic.DesignResult, opt: CadOptions) -> None:
    group = "Inductor"
    floats = {
        "TargetL_uH": res.target_uH,
        "PredictedL_uH": res.predicted_uH,
        "RoundingError_pct": res.error_pct,
        "Turns": res.turns,
        "Pitch_mm": res.pitch_mm or 0.0,
        "CoilLength_mm": res.coil_length_mm or 0.0,
        "WireCopper_mm": spec.wire.copper_d_mm,
        "WireOverall_mm": spec.wire.d,
        "WireLength_mm": res.wire_length_mm,
        "DCR_ohm": res.dcr_ohm,
    }
    obj.addProperty("App::PropertyString", "CoilShape", group, "Inductor shape")
    obj.CoilShape = ic.SHAPE_LABELS[spec.shape]
    for name, value in floats.items():
        obj.addProperty("App::PropertyFloat", name, group, name.replace("_", " "))
        setattr(obj, name, float(value))
    design = {
        "spec": spec_to_dict(spec),
        "result": {k: v for k, v in asdict(res).items() if k != "shape"},
        "cad_options": asdict(opt),
    }
    obj.addProperty("App::PropertyString", "DesignJSON", group,
                    "Full design record (spec, result, CAD options)")
    obj.DesignJSON = json.dumps(design)
    obj.addProperty("App::PropertyStringList", "Warnings", group, "Design warnings")
    obj.Warnings = list(res.warnings)


def build(spec: ic.Spec, result: ic.DesignResult, options: CadOptions | None = None,
          doc=None) -> str:
    """Build the coil form in ``doc`` (default: active or new document).

    Returns a short message for the user. Raises ``CadError`` on failure.
    """
    App, _ = _fc()
    opt = options or CadOptions()
    shapes, notes = make_shapes(spec, result, opt)
    problems = [f"{name}: {p}" for name, s in shapes.items() for p in check_shape(s)]
    if problems:
        raise CadError("; ".join(problems))

    doc = doc or App.ActiveDocument or App.newDocument("Inductor")
    name = SHAPE_NAMES[spec.shape]
    group = doc.addObject("App::DocumentObjectGroup", f"Inductor{name}")
    group.Label = f"Inductor {name} {result.turns:g}T {result.predicted_uH:.4g}uH"
    objects = {}
    for obj_name, shape in shapes.items():
        obj = doc.addObject("Part::Feature", obj_name)
        obj.Shape = shape
        group.addObject(obj)
        objects[obj_name] = obj
    _add_properties(objects["CoilForm"], spec, result, opt)
    doc.recompute()

    if App.GuiUp:  # pragma: no cover - needs the FreeCAD GUI
        _style(objects)

    parts = ", ".join(o.Label for o in objects.values())
    lines = [f"Built {group.Label} ({parts}) in document '{doc.Label}'.",
             "Export the CoilForm with File → Export (STEP or STL)."]
    return "\n".join(lines + notes)


def _style(objects) -> None:  # pragma: no cover - needs the FreeCAD GUI
    import FreeCADGui as Gui  # type: ignore[import-not-found]

    form = objects.get("CoilForm")
    if form is not None:
        form.ViewObject.ShapeColor = FORM_RGB
    wire = objects.get("WireModel")
    if wire is not None:
        wire.ViewObject.ShapeColor = COPPER_RGB
    view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
    if view is not None:
        view.viewIsometric()
        view.fitAll()


def build_from_ui(spec: ic.Spec, result: ic.DesignResult, cad_values: dict[str, Any]) -> str:
    """Callback for the dialog's Build button."""
    return build(spec, result, CadOptions.from_dict(cad_values))
