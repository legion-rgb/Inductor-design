"""Offscreen smoke tests for the dialog. Skipped when no PySide is installed."""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "InductorDesigner"))

try:
    import inductor_ui as ui
except ImportError as exc:  # no PySide6/PySide2 available
    ui = None
    SKIP_REASON = f"Qt bindings not available: {exc}"
else:
    SKIP_REASON = ""

from inductor_core import PitchMode, Shape  # noqa: E402


@unittest.skipIf(ui is None, SKIP_REASON)
class TestDesignerWidget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = ui.QtWidgets.QApplication.instance() or ui.QtWidgets.QApplication([])

    def setUp(self):
        self.built = []
        self.w = ui.DesignerWidget(build_callback=lambda s, r: self.built.append((s, r)))

    def test_drop_down_lists_all_shapes(self):
        items = [self.w.shape_combo.itemText(i) for i in range(self.w.shape_combo.count())]
        self.assertEqual(items, list(ui.ic.SHAPE_LABELS.values()))

    def test_defaults_produce_result_for_every_shape(self):
        for shape in Shape:
            self.w.set_shape(shape)
            self.assertIsNotNone(self.w.result, shape)
            self.assertEqual(self.w.result.shape, shape)
            self.assertIn("Turns", self.w.results_label.text())
            self.assertEqual(self.w.error_label.text(), "")

    def test_mode_switch_shows_relevant_fields(self):
        self.w.set_shape(Shape.SOLENOID)
        spins = self.w._spins[Shape.SOLENOID]
        self.w.show()
        self.assertFalse(spins["pitch_mm"].isVisible())
        self.w.set_mode(PitchMode.FIXED_PITCH)
        self.assertTrue(spins["pitch_mm"].isVisible())
        self.assertFalse(spins["length_mm"].isVisible())
        self.assertEqual(self.w.result.pitch_mm, spins["pitch_mm"].value())
        self.w.set_mode(PitchMode.FIXED_LENGTH)
        self.assertTrue(spins["length_mm"].isVisible())
        self.assertEqual(self.w.result.coil_length_mm, spins["length_mm"].value())

    def test_invalid_input_shows_error_and_disables_build(self):
        self.w.set_shape(Shape.SOLENOID)
        self.w.set_mode(PitchMode.FIXED_PITCH)
        self.w.set_value("pitch_mm", 0.1)  # thinner than 0.8 mm wire
        self.assertIsNone(self.w.result)
        self.assertIn("smaller than the wire", self.w.error_label.text())
        self.assertFalse(self.w.build_button.isEnabled())

    def test_bad_copper_text(self):
        self.w.copper_combo.setCurrentText("abc")
        self.assertIsNone(self.w.result)
        self.assertIn("not a number", self.w.error_label.text())

    def test_unit_change_keeps_target(self):
        target = self.w.result.target_uH
        self.w.unit_combo.setCurrentText("nH")
        self.assertAlmostEqual(self.w.target_spin.value(), target * 1000)
        self.assertAlmostEqual(self.w.result.target_uH, target)
        self.assertIn("nH", self.w.results_label.text())

    def test_build_button_calls_callback(self):
        self.assertTrue(self.w.build_button.isEnabled())
        self.w.build_button.click()
        self.assertEqual(len(self.built), 1)
        self.assertIs(self.built[0][1], self.w.result)

    def test_build_disabled_without_callback(self):
        w = ui.DesignerWidget()
        self.assertFalse(w.build_button.isEnabled())

    def test_sketch_paints_every_shape(self):
        for shape in Shape:
            self.w.set_shape(shape)
            self.assertFalse(self.w.sketch.grab().isNull())


if __name__ == "__main__":
    unittest.main()
