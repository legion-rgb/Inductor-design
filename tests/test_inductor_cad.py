"""Coil-form geometry tests. Need FreeCAD; skipped when it cannot be imported.

Run with FreeCAD's Python, e.g. (conda-forge FreeCAD):
    FREECAD_LIB=/path/to/freecad/lib python -m unittest tests.test_inductor_cad -v
"""

import math
import os
import sys
import unittest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "InductorDesigner"))
for path in filter(None, os.environ.get("FREECAD_LIB", "").split(os.pathsep)):
    sys.path.append(path)

try:
    import FreeCAD  # noqa: F401
    import Part  # noqa: F401
except ImportError:
    FreeCAD = None

import inductor_cad as cad  # noqa: E402
import inductor_core as ic  # noqa: E402
from inductor_core import PitchMode  # noqa: E402

WIRE = ic.Wire(0.8, 0.86)


def bbox(shape):
    return shape.optimalBoundingBox()


class TestPureHelpers(unittest.TestCase):
    """Parts of inductor_cad that do not need FreeCAD."""

    def test_spiral_half_turns_advance_one_pitch_per_turn(self):
        arcs = cad.spiral_half_turns(10.0, 2.0, 3)
        self.assertEqual(len(arcs), 6)
        self.assertEqual([a[1] for a in arcs[::2]], [10.0, 12.0, 14.0])
        for (cx0, r0, s0, sp0), (cx1, r1, s1, _) in zip(arcs, arcs[1:]):
            a0, a1 = math.radians(s0 + sp0), math.radians(s1)
            end = (cx0 + r0 * math.cos(a0), r0 * math.sin(a0))
            start = (cx1 + r1 * math.cos(a1), r1 * math.sin(a1))
            self.assertAlmostEqual(end[0], start[0])  # arcs join up
            self.assertAlmostEqual(end[1], start[1])

    def test_spiral_fractional_turns(self):
        arcs = cad.spiral_half_turns(10.0, 2.0, 1.25)
        self.assertEqual([a[3] for a in arcs], [180.0, 180.0, 90.0])

    def test_options_from_dict_ignores_unknown(self):
        opt = cad.CadOptions.from_dict({"wall_mm": 3.0, "colour": "red"})
        self.assertEqual(opt.wall_mm, 3.0)

    def test_spec_to_dict_is_plain(self):
        d = cad.spec_to_dict(ic.SolenoidSpec(20, WIRE))
        self.assertEqual(d["shape"], "solenoid")
        self.assertEqual(d["mode"], "close_wound")
        self.assertEqual(d["wire"]["overall_d_mm"], 0.86)


@unittest.skipIf(FreeCAD is None, "FreeCAD not importable (set FREECAD_LIB)")
class TestCoilForms(unittest.TestCase):
    def build(self, spec, target, step=1.0, **opts):
        res = ic.design(spec, target, turns_step=step)
        shapes, notes = cad.make_shapes(spec, res, cad.CadOptions(**opts))
        for name, shape in shapes.items():
            self.assertEqual(cad.check_shape(shape), [], name)
        return res, shapes, notes

    def assertNoOverlap(self, shapes):
        if "WireModel" in shapes:
            overlap = shapes["CoilForm"].common(shapes["WireModel"]).Volume
            self.assertLess(overlap, 1e-3 * shapes["WireModel"].Volume)

    def test_solenoid_close_wound_is_plain_cylinder(self):
        res, shapes, notes = self.build(ic.SolenoidSpec(20, WIRE), 10)
        self.assertTrue(any("no groove" in n for n in notes))
        bb = bbox(shapes["CoilForm"])
        flange_r = 10 + 0.86 + 2
        self.assertAlmostEqual(bb.XLength, 2 * flange_r, places=2)
        self.assertAlmostEqual(bb.ZLength, 2 * (2 + 3) + res.turns * 0.86, places=2)
        wire_bb = bbox(shapes["WireModel"])
        self.assertAlmostEqual(wire_bb.XLength, 20 + 0.86 + 0.98 * 0.86, places=1)
        self.assertNoOverlap(shapes)

    def test_solenoid_grooved_seats_wire_at_design_radius(self):
        spec = ic.SolenoidSpec(20, WIRE, PitchMode.FIXED_PITCH, pitch_mm=1.5)
        res, shapes, notes = self.build(spec, 3.0)
        self.assertFalse(any("no groove" in n for n in notes))
        form = shapes["CoilForm"]
        plain = Part.makeCylinder(10 + 0.6 * 0.86, 2 * 5 + res.turns * 1.5)
        self.assertLess(form.Volume, plain.Volume)  # groove, bore and holes removed
        self.assertNoOverlap(shapes)
        # The wire sits in the groove: wire model reaches the design radius.
        wire_bb = bbox(shapes["WireModel"])
        self.assertAlmostEqual(wire_bb.XLength / 2, 10 + 0.43 + 0.49 * 0.86, places=1)

    def test_solenoid_quarter_turns_fixed_length(self):
        spec = ic.SolenoidSpec(20, WIRE, PitchMode.FIXED_LENGTH, length_mm=30)
        res, shapes, _ = self.build(spec, 3.0, step=0.25, add_wire_model=False)
        self.assertNotIn("WireModel", shapes)
        self.assertAlmostEqual(bbox(shapes["CoilForm"]).ZLength, 30 + 2 * 5, places=2)

    def test_solenoid_solid_rod(self):
        spec = ic.SolenoidSpec(6, WIRE, PitchMode.FIXED_PITCH, pitch_mm=1.5)
        _, _, notes = self.build(spec, 0.5, wall_mm=0, add_wire_model=False)
        self.assertTrue(any("Solid rod" in n for n in notes))

    def test_multilayer_bobbin(self):
        spec = ic.MultilayerSpec(10, 15, ic.Wire(0.3, 0.33))
        res, shapes, _ = self.build(spec, 500)
        bb = bbox(shapes["CoilForm"])
        flange_r = 5 + res.details["layers"] * 0.33 + 2
        self.assertAlmostEqual(bb.XLength, 2 * flange_r, places=2)
        self.assertAlmostEqual(bb.ZLength, 15 + 2 * 2, places=2)
        self.assertNoOverlap(shapes)

    def test_flat_spiral_grooved(self):
        spec = ic.FlatSpiralSpec(20, ic.Wire(1.0, 1.06), PitchMode.FIXED_PITCH, pitch_mm=2)
        res, shapes, notes = self.build(spec, 15)
        self.assertFalse(any("no groove" in n for n in notes))
        bb = bbox(shapes["CoilForm"])
        disc_r = 10 + 0.53 + res.turns * 2 + 0.53 + 2
        self.assertAlmostEqual(bb.XLength, 2 * disc_r, places=2)
        self.assertAlmostEqual(bb.ZLength, 2 + 0.6 * 1.06, places=2)
        self.assertNoOverlap(shapes)

    def test_flat_spiral_close_wound_is_flat(self):
        _, shapes, notes = self.build(ic.FlatSpiralSpec(20, ic.Wire(1.0, 1.06)), 15)
        self.assertTrue(any("no groove" in n for n in notes))
        self.assertAlmostEqual(bbox(shapes["CoilForm"]).ZLength, 2.0, places=2)

    def test_toroid_notches(self):
        spec = ic.ToroidSpec(20, 40, 10, ic.Wire(0.5, 0.55))
        res, shapes, _ = self.build(spec, 1.0)
        ring = Part.makeCylinder(20, 10).cut(Part.makeCylinder(10, 12, FreeCAD.Vector(0, 0, -1)))
        notch = 0.6 * 0.55 * (0.55 + 0.2) * 10  # depth x width x height (approx.)
        removed = ring.Volume - shapes["CoilForm"].Volume
        self.assertAlmostEqual(removed / (math.ceil(res.turns) * notch), 1, delta=0.05)

    def test_toroid_too_many_turns_for_notches(self):
        spec = ic.ToroidSpec(10, 14, 10, ic.Wire(1.0, 1.06))
        _, _, notes = self.build(spec, 20)
        self.assertTrue(any("notches" in n for n in notes))

    def test_build_adds_objects_and_properties(self):
        doc = FreeCAD.newDocument("InductorTest")
        try:
            spec = ic.SolenoidSpec(20, WIRE)
            res = ic.design(spec, 10)
            message = cad.build(spec, res, doc=doc)
            self.assertIn("File → Export", message)
            form = doc.getObject("CoilForm")
            self.assertEqual(form.Turns, res.turns)
            self.assertAlmostEqual(form.PredictedL_uH, res.predicted_uH)
            self.assertEqual(form.CoilShape, "Single-layer solenoid")
            self.assertIn('"turns"', form.DesignJSON)
            self.assertIsNotNone(doc.getObject("WireModel"))
            group = doc.getObject("InductorSolenoid")
            self.assertEqual(len(group.Group), 2)
        finally:
            FreeCAD.closeDocument(doc.Name)


if __name__ == "__main__":
    unittest.main()
