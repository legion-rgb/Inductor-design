"""Unit tests for inductor_core (standard-library unittest, no FreeCAD needed).

Run from the repository root:
    python3 -m unittest discover -s tests -v
"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "InductorDesigner"))

import inductor_core as ic  # noqa: E402

IN = 25.4  # mm per inch


class TestForwardFormulas(unittest.TestCase):
    def test_solenoid_reference_value(self):
        # r = 1 in, l = 2 in, N = 20 -> 400 / 29 uH (classic Wheeler example)
        self.assertAlmostEqual(ic.solenoid_L_uH(1 * IN, 2 * IN, 20), 400 / 29, places=9)

    def test_metric_forms_match_inch_forms(self):
        for r, l, b, w, n in [(10, 30, 4, 8, 15), (3.2, 7.5, 1.1, 2.0, 42), (50, 5, 20, 40, 3)]:
            ri, li, bi, wi = r / IN, l / IN, b / IN, w / IN
            self.assertAlmostEqual(
                ic.solenoid_L_uH(r, l, n), ri**2 * n**2 / (9 * ri + 10 * li), places=9)
            self.assertAlmostEqual(
                ic.multilayer_L_uH(r, l, b, n),
                0.8 * ri**2 * n**2 / (6 * ri + 9 * li + 10 * bi), places=9)
            self.assertAlmostEqual(
                ic.flat_spiral_L_uH(r, w, n), ri**2 * n**2 / (8 * ri + 11 * wi), places=9)

    def test_toroid_reference_value(self):
        # mu0/(2pi) = 2e-7 H/m -> L = 2e-4 * N^2 * h[mm] * ln(ro/ri) uH
        expected = 2e-4 * 100**2 * 10 * math.log(2)
        self.assertAlmostEqual(ic.toroid_L_uH(10, 20, 10, 100), expected, places=6)


class TestInverseSolvers(unittest.TestCase):
    CASES = [(0.05, 2.0, 3.0), (1.0, 10.0, 25.0), (47.0, 12.5, 40.0), (1000.0, 30.0, 80.0)]

    def assertRelClose(self, a, b, rel=1e-9):
        self.assertLessEqual(abs(a - b), rel * abs(b), f"{a} != {b}")

    def test_solenoid_fixed_length_round_trip(self):
        for L, r, l in self.CASES:
            n = ic.solenoid_turns_fixed_length(L, r, l)
            self.assertRelClose(ic.solenoid_L_uH(r, l, n), L)

    def test_solenoid_fixed_pitch_round_trip(self):
        for L, r, p in [(0.05, 2.0, 0.3), (1.0, 10.0, 1.0), (47.0, 12.5, 0.5), (1000, 30, 0.25)]:
            n = ic.solenoid_turns_fixed_pitch(L, r, p)
            self.assertRelClose(ic.solenoid_L_uH(r, n * p, n), L)

    def test_toroid_round_trip(self):
        for L in (0.1, 5.0, 330.0):
            n = ic.toroid_turns(L, 8.0, 15.0, 6.0)
            self.assertRelClose(ic.toroid_L_uH(8.0, 15.0, 6.0, n), L)

    def test_bisection_solver(self):
        n = ic.solve_turns(lambda x: 3 * x**2 + x, 1234.5)
        self.assertRelClose(3 * n**2 + n, 1234.5, rel=1e-11)

    def test_bisection_gives_up_on_huge_targets(self):
        with self.assertRaises(ic.DesignError):
            ic.solve_turns(lambda x: 1e-12 * x, 1.0)


class TestHelpers(unittest.TestCase):
    def test_units(self):
        self.assertAlmostEqual(ic.to_uH(470, "nH"), 0.47)
        self.assertEqual(ic.to_uH(2.2, "mH"), 2200)
        self.assertEqual(ic.to_uH(10, "µH"), 10)
        self.assertAlmostEqual(ic.from_uH(0.47, "nH"), 470)
        with self.assertRaises(ic.DesignError):
            ic.to_uH(1, "H")

    def test_dcr_one_metre_of_1mm_copper(self):
        self.assertAlmostEqual(ic.dcr_ohm(1000, 1.0), 0.021951, places=5)

    def test_round_turns(self):
        self.assertEqual(ic.round_turns(12.4), 12)
        self.assertEqual(ic.round_turns(12.5), 13)
        self.assertEqual(ic.round_turns(12.3, 0.25), 12.25)
        self.assertEqual(ic.round_turns(12.4, 0.5), 12.5)
        self.assertEqual(ic.round_turns(0.1), 1)

    def test_spiral_length_close_to_concentric_rings(self):
        # For small pitch the spiral is nearly N rings at the mean radius.
        r0, p, n = 10.0, 0.5, 20
        approx = n * 2 * math.pi * (r0 + n * p / 2)
        self.assertAlmostEqual(ic.archimedean_spiral_length_mm(r0, p, n) / approx, 1, places=3)

    def test_helix_length(self):
        self.assertAlmostEqual(ic.helix_length_mm(10, 0, 3), 3 * 2 * math.pi * 10)

    def test_wire_overall_estimate_and_validation(self):
        w = ic.Wire(0.5)
        self.assertGreater(w.d, 0.5)
        self.assertEqual(ic.Wire(0.5, 0.56).d, 0.56)
        with self.assertRaises(ic.DesignError):
            ic.Wire(0.5, 0.4)
        with self.assertRaises(ic.DesignError):
            ic.Wire(-1)

    def test_shape_labels_cover_all_shapes(self):
        self.assertEqual(set(ic.SHAPE_LABELS), set(ic.Shape))


class TestSolenoidDesign(unittest.TestCase):
    wire = ic.Wire(0.8, 0.86)

    def test_close_wound(self):
        spec = ic.SolenoidSpec(form_diameter_mm=20, wire=self.wire)
        res = ic.design(spec, 10.0)
        r = 10 + 0.43
        self.assertAlmostEqual(res.pitch_mm, 0.86)
        self.assertAlmostEqual(ic.solenoid_L_uH(r, res.turns_exact * 0.86, res.turns_exact), 10)
        self.assertEqual(res.turns, round(res.turns_exact))
        self.assertAlmostEqual(res.coil_length_mm, res.turns * 0.86)
        self.assertAlmostEqual(res.predicted_uH, ic.solenoid_L_uH(r, res.coil_length_mm, res.turns))
        self.assertAlmostEqual(res.error_pct, (res.predicted_uH - 10) / 10 * 100)
        self.assertGreater(res.dcr_ohm, 0)

    def test_fixed_length(self):
        spec = ic.SolenoidSpec(20, self.wire, ic.PitchMode.FIXED_LENGTH, length_mm=40)
        res = ic.design(spec, 5.0, turns_step=0.25)
        self.assertEqual(res.coil_length_mm, 40)
        self.assertAlmostEqual(res.pitch_mm, 40 / res.turns)
        self.assertEqual(res.turns % 0.25, 0)
        self.assertGreaterEqual(res.pitch_mm, self.wire.d)

    def test_fixed_length_too_short(self):
        spec = ic.SolenoidSpec(20, self.wire, ic.PitchMode.FIXED_LENGTH, length_mm=5)
        with self.assertRaises(ic.DesignError):
            ic.design(spec, 100.0)

    def test_fixed_pitch(self):
        spec = ic.SolenoidSpec(20, self.wire, ic.PitchMode.FIXED_PITCH, pitch_mm=1.5)
        res = ic.design(spec, 3.3)
        self.assertEqual(res.pitch_mm, 1.5)
        self.assertAlmostEqual(res.coil_length_mm, res.turns * 1.5)

    def test_pitch_smaller_than_wire(self):
        spec = ic.SolenoidSpec(20, self.wire, ic.PitchMode.FIXED_PITCH, pitch_mm=0.5)
        with self.assertRaises(ic.DesignError):
            ic.design(spec, 1.0)

    def test_missing_pitch(self):
        spec = ic.SolenoidSpec(20, self.wire, ic.PitchMode.FIXED_PITCH)
        with self.assertRaises(ic.DesignError):
            ic.design(spec, 1.0)

    def test_short_coil_warning(self):
        spec = ic.SolenoidSpec(100, self.wire)
        res = ic.design(spec, 0.5)
        self.assertTrue(any("0.8" in w for w in res.warnings))

    def test_leads_add_resistance(self):
        spec = ic.SolenoidSpec(20, self.wire)
        a = ic.design(spec, 10.0)
        b = ic.design(spec, 10.0, lead_length_mm=100)
        self.assertAlmostEqual(b.wire_length_mm - a.wire_length_mm, 100)
        self.assertGreater(b.dcr_ohm, a.dcr_ohm)

    def test_invalid_inputs(self):
        with self.assertRaises(ic.DesignError):
            ic.design(ic.SolenoidSpec(-5, self.wire), 1.0)
        with self.assertRaises(ic.DesignError):
            ic.design(ic.SolenoidSpec(20, self.wire), 0.0)
        with self.assertRaises(ic.DesignError):
            ic.design(ic.SolenoidSpec(20, self.wire), float("nan"))


class TestMultilayerDesign(unittest.TestCase):
    def test_round_trip_and_layers(self):
        wire = ic.Wire(0.3, 0.33)
        spec = ic.MultilayerSpec(core_diameter_mm=10, winding_length_mm=15, wire=wire)
        res = ic.design(spec, 500.0)
        depth = res.turns_exact * 0.33**2 / 15
        r = 5 + depth / 2
        self.assertAlmostEqual(ic.multilayer_L_uH(r, 15, depth, res.turns_exact), 500, places=6)
        tpl = res.details["turns_per_layer"]
        self.assertEqual(tpl, math.floor(15 / 0.33))
        self.assertEqual(res.details["layers"], math.ceil(res.turns / tpl))

    def test_winding_too_short(self):
        spec = ic.MultilayerSpec(10, 0.2, ic.Wire(0.3, 0.33))
        with self.assertRaises(ic.DesignError):
            ic.design(spec, 1.0)


class TestFlatSpiralDesign(unittest.TestCase):
    def test_close_wound_round_trip(self):
        wire = ic.Wire(1.0, 1.06)
        spec = ic.FlatSpiralSpec(inner_diameter_mm=20, wire=wire)
        res = ic.design(spec, 15.0)
        r0 = 10 + 0.53
        w = res.turns_exact * 1.06
        self.assertAlmostEqual(ic.flat_spiral_L_uH(r0 + w / 2, w, res.turns_exact), 15, places=6)
        self.assertAlmostEqual(res.coil_length_mm, res.turns * 1.06)
        self.assertAlmostEqual(res.details["outer_diameter_mm"], 2 * (r0 + res.turns * 1.06) + 1.06)

    def test_fixed_pitch(self):
        spec = ic.FlatSpiralSpec(20, ic.Wire(1.0, 1.06), ic.PitchMode.FIXED_PITCH, pitch_mm=2)
        res = ic.design(spec, 15.0)
        self.assertEqual(res.pitch_mm, 2)

    def test_fixed_length_not_allowed(self):
        spec = ic.FlatSpiralSpec(20, ic.Wire(1.0), ic.PitchMode.FIXED_LENGTH)
        with self.assertRaises(ic.DesignError):
            ic.design(spec, 1.0)


class TestToroidDesign(unittest.TestCase):
    def test_round_trip(self):
        spec = ic.ToroidSpec(20, 40, 10, ic.Wire(0.5, 0.55))
        res = ic.design(spec, 1.0)
        self.assertAlmostEqual(ic.toroid_L_uH(10, 20, 10, res.turns_exact), 1.0, places=9)
        self.assertEqual(res.warnings, [])

    def test_single_layer_overflow_warning(self):
        spec = ic.ToroidSpec(10, 40, 5, ic.Wire(1.0, 1.06))
        res = ic.design(spec, 50.0)
        self.assertTrue(any("single-layer" in w for w in res.warnings))

    def test_invalid_diameters(self):
        with self.assertRaises(ic.DesignError):
            ic.design(ic.ToroidSpec(40, 20, 10, ic.Wire(0.5)), 1.0)
        with self.assertRaises(ic.DesignError):
            ic.design(ic.ToroidSpec(1, 20, 10, ic.Wire(0.5)), 1.0)


if __name__ == "__main__":
    unittest.main()
