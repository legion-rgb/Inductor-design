"""Tests for the dialog's input tables and result formatting (no Qt needed)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "InductorDesigner"))

import inductor_core as ic  # noqa: E402
import inductor_inputs as fi  # noqa: E402
from inductor_core import PitchMode, Shape  # noqa: E402


def defaults(shape):
    return {f.key: f.default for f in fi.SHAPE_FIELDS[shape]}


class TestTables(unittest.TestCase):
    def test_every_shape_has_fields_and_modes(self):
        self.assertEqual(set(fi.SHAPE_FIELDS), set(Shape))
        self.assertEqual(set(fi.SHAPE_MODES), set(Shape))

    def test_field_defaults_within_range(self):
        for fields in fi.SHAPE_FIELDS.values():
            for f in fields:
                self.assertLessEqual(f.minimum, f.default, f.key)
                self.assertLessEqual(f.default, f.maximum, f.key)

    def test_mode_specific_fields_reference_offered_modes(self):
        for shape, fields in fi.SHAPE_FIELDS.items():
            for f in fields:
                for mode in f.modes or ():
                    self.assertIn(mode, fi.SHAPE_MODES[shape])

    def test_default_inputs_give_a_design_for_every_shape_and_mode(self):
        wire = fi.make_wire(fi.DEFAULT_WIRE_COPPER_MM, 0)
        for shape in Shape:
            for mode in fi.SHAPE_MODES[shape] or [None]:
                spec = fi.build_spec(shape, defaults(shape), wire, mode)
                res = ic.design(spec, fi.DEFAULT_TARGET)
                self.assertGreater(res.turns, 0, (shape, mode))
                rows = fi.result_rows(res)
                self.assertEqual(rows[0][0], "Turns")


class TestBuildSpec(unittest.TestCase):
    wire = ic.Wire(0.5, 0.55)

    def test_solenoid_modes_use_only_relevant_values(self):
        values = defaults(Shape.SOLENOID)
        close = fi.build_spec(Shape.SOLENOID, values, self.wire, PitchMode.CLOSE_WOUND)
        self.assertIsNone(close.pitch_mm)
        self.assertIsNone(close.length_mm)
        fixed = fi.build_spec(Shape.SOLENOID, values, self.wire, PitchMode.FIXED_LENGTH)
        self.assertEqual(fixed.length_mm, values["length_mm"])
        self.assertIsNone(fixed.pitch_mm)

    def test_default_mode_is_first(self):
        spec = fi.build_spec(Shape.FLAT_SPIRAL, defaults(Shape.FLAT_SPIRAL), self.wire)
        self.assertIs(spec.mode, PitchMode.CLOSE_WOUND)

    def test_mode_not_offered(self):
        with self.assertRaises(ic.DesignError):
            fi.build_spec(Shape.FLAT_SPIRAL, defaults(Shape.FLAT_SPIRAL), self.wire,
                          PitchMode.FIXED_LENGTH)

    def test_missing_value(self):
        with self.assertRaises(ic.DesignError):
            fi.build_spec(Shape.TOROID, {"inner_diameter_mm": 10}, self.wire)

    def test_make_wire_auto(self):
        self.assertAlmostEqual(fi.make_wire(1.0, 0).d, ic.estimate_overall_diameter(1.0))
        self.assertEqual(fi.make_wire(1.0, 1.1).d, 1.1)


class TestDiameterRef(unittest.TestCase):
    wire = ic.Wire(1.0, 1.1)

    def test_conversion_to_form_diameter(self):
        self.assertEqual(fi.form_diameter_mm(20, fi.DiameterRef.INSIDE, 1.1), 20)
        self.assertAlmostEqual(fi.form_diameter_mm(20, fi.DiameterRef.CENTRE, 1.1), 18.9)
        self.assertAlmostEqual(fi.form_diameter_mm(20, fi.DiameterRef.OUTSIDE, 1.1), 17.8)

    def test_all_refs_give_same_design_for_same_coil(self):
        values = defaults(Shape.SOLENOID)
        results = []
        for ref, dia in [(fi.DiameterRef.INSIDE, 20), (fi.DiameterRef.CENTRE, 21.1),
                         (fi.DiameterRef.OUTSIDE, 22.2)]:
            values["diameter_mm"] = dia
            spec = fi.build_spec(Shape.SOLENOID, values, self.wire, diameter_ref=ref)
            self.assertAlmostEqual(spec.form_diameter_mm, 20)
            results.append(ic.design(spec, 10).turns_exact)
        self.assertAlmostEqual(results[0], results[1])
        self.assertAlmostEqual(results[0], results[2])

    def test_diameter_too_small_for_wire(self):
        with self.assertRaises(ic.DesignError):
            fi.form_diameter_mm(2.0, fi.DiameterRef.OUTSIDE, 1.1)

    def test_result_rows_show_all_three_diameters(self):
        spec = fi.build_spec(Shape.SOLENOID, defaults(Shape.SOLENOID), self.wire)
        rows = dict(fi.result_rows(ic.design(spec, 10)))
        self.assertEqual(rows["Form diameter (under wire)"], "20 mm")
        self.assertEqual(rows["Mean diameter (wire centre)"], "21.1 mm")
        self.assertEqual(rows["Outer diameter (with wire)"], "22.2 mm")


class TestFormatting(unittest.TestCase):
    def test_inductance(self):
        self.assertEqual(fi.format_inductance(10.033, "µH"), "10.03 µH")
        self.assertEqual(fi.format_inductance(0.47, "nH"), "470 nH")
        self.assertEqual(fi.format_inductance(2200, "mH"), "2.2 mH")

    def test_length_and_resistance(self):
        self.assertEqual(fi.format_length(24.08), "24.08 mm")
        self.assertEqual(fi.format_length(1835.2), "1.84 m")
        self.assertEqual(fi.format_resistance(0.0632), "63.2 mΩ")
        self.assertEqual(fi.format_resistance(2.679), "2.679 Ω")

    def test_rows_include_shape_details(self):
        spec = ic.MultilayerSpec(10, 15, ic.Wire(0.3, 0.33))
        labels = [label for label, _ in fi.result_rows(ic.design(spec, 500))]
        self.assertIn("Layers", labels)
        self.assertIn("Winding length", labels)
        toroid = ic.ToroidSpec(20, 40, 10, ic.Wire(0.5))
        labels = [label for label, _ in fi.result_rows(ic.design(toroid, 1))]
        self.assertIn("Max single-layer turns", labels)
        self.assertNotIn("Coil length", labels)


if __name__ == "__main__":
    unittest.main()
