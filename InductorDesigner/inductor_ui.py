"""Inductor Designer dialog (PySide/Qt).

Runs inside FreeCAD as a Task Panel, or standalone for development:

    python3 InductorDesigner/inductor_ui.py      # needs PySide6 or PySide2

The widget is built from the tables in ``inductor_inputs`` and recalculates
the design live through ``inductor_core`` whenever an input changes.
"""

from __future__ import annotations

import math
import sys
from typing import Callable, Optional

try:  # FreeCAD's PySide shim matches whatever Qt FreeCAD was built with
    from PySide import QtCore, QtGui, QtWidgets  # type: ignore[import-not-found]
except ImportError:
    try:
        from PySide6 import QtCore, QtGui, QtWidgets  # type: ignore[no-redef]
    except ImportError:
        from PySide2 import QtCore, QtGui, QtWidgets  # type: ignore[no-redef]

import inductor_core as ic
import inductor_inputs as fi
from inductor_core import PitchMode, Shape

BuildCallback = Callable[[ic.Spec, ic.DesignResult], None]

COPPER = QtGui.QColor(184, 115, 51)
WARN_COLOR = "#b26a00"
ERROR_COLOR = "#c62828"


# ---------------------------------------------------------------------------
# Shape sketch
# ---------------------------------------------------------------------------

class ShapeSketch(QtWidgets.QWidget):
    """Small labelled drawing of the selected shape and its dimensions."""

    W, H = 260.0, 150.0  # logical drawing size

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.shape = Shape.SOLENOID
        self.setMinimumSize(220, 130)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.setFixedHeight(150)

    def set_shape(self, shape: Shape) -> None:
        self.shape = shape
        self.update()

    # drawing helpers ------------------------------------------------------
    def _dim(self, p: QtGui.QPainter, x1: float, y1: float, x2: float, y2: float,
             text: str, text_dx: float = 0.0, text_dy: float = 0.0) -> None:
        """Dimension line with end ticks and a label at its midpoint."""
        p.drawLine(QtCore.QPointF(x1, y1), QtCore.QPointF(x2, y2))
        dx, dy = x2 - x1, y2 - y1
        n = math.hypot(dx, dy) or 1.0
        tx, ty = -dy / n * 4, dx / n * 4  # perpendicular tick
        for x, y in ((x1, y1), (x2, y2)):
            p.drawLine(QtCore.QPointF(x - tx, y - ty), QtCore.QPointF(x + tx, y + ty))
        p.drawText(QtCore.QPointF((x1 + x2) / 2 + text_dx, (y1 + y2) / 2 + text_dy), text)

    def _wire(self, p: QtGui.QPainter, x: float, y: float, r: float = 4.0) -> None:
        p.save()
        p.setBrush(COPPER)
        p.setPen(QtGui.QPen(COPPER.darker(140), 1))
        p.drawEllipse(QtCore.QPointF(x, y), r, r)
        p.restore()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        scale = min(self.width() / self.W, self.height() / self.H)
        p.translate((self.width() - self.W * scale) / 2, (self.height() - self.H * scale) / 2)
        p.scale(scale, scale)
        fg = self.palette().color(self.foregroundRole())
        p.setPen(QtGui.QPen(fg, 1.2))
        font = p.font()
        font.setPointSizeF(8.0)
        p.setFont(font)
        {
            Shape.SOLENOID: self._draw_solenoid,
            Shape.MULTILAYER: self._draw_multilayer,
            Shape.FLAT_SPIRAL: self._draw_spiral,
            Shape.TOROID: self._draw_toroid,
        }[self.shape](p)
        p.end()

    def _draw_solenoid(self, p: QtGui.QPainter) -> None:
        p.drawRect(QtCore.QRectF(50, 50, 170, 50))  # form, side view
        xs = [62 + 13 * i for i in range(12)]
        for x in xs:
            self._wire(p, x, 46)
            self._wire(p, x, 104)
        self._dim(p, 32, 50, 32, 100, "Ø form", -30, -30)
        self._dim(p, xs[0], 128, xs[-1], 128, "coil length ℓ", -30, 14)
        self._dim(p, xs[0], 28, xs[1], 28, "pitch p", 16, 4)

    def _draw_multilayer(self, p: QtGui.QPainter) -> None:
        p.drawRect(QtCore.QRectF(60, 62, 150, 26))  # core
        p.drawRect(QtCore.QRectF(54, 20, 6, 110))  # flanges
        p.drawRect(QtCore.QRectF(210, 20, 6, 110))
        for row in range(3):
            for i in range(15):
                x = 65 + 10 * i
                self._wire(p, x, 57 - 9 * row, 4.5)
                self._wire(p, x, 93 + 9 * row, 4.5)
        self._dim(p, 36, 62, 36, 88, "Ø core", -32, -20)
        self._dim(p, 60, 140, 210, 140, "winding length ℓ", -45, -3)
        self._dim(p, 232, 62, 232, 34, "depth b", 6, 4)

    def _draw_spiral(self, p: QtGui.QPainter) -> None:
        cx, cy, r0, pitch, turns = 120.0, 75.0, 16.0, 12.0, 4.5
        p.save()
        p.setPen(QtGui.QPen(COPPER, 3))
        path = QtGui.QPainterPath()
        steps = 360
        for i in range(steps + 1):
            th = 2 * math.pi * turns * i / steps
            r = r0 + pitch * th / (2 * math.pi)
            pt = QtCore.QPointF(cx + r * math.cos(th), cy + r * math.sin(th))
            path.moveTo(pt) if i == 0 else path.lineTo(pt)
        p.drawPath(path)
        p.restore()
        self._dim(p, cx - r0, cy, cx + r0, cy, "Ø inner", -14, -6)
        self._dim(p, cx + r0 + 2 * pitch, cy - 4, cx + r0 + 3 * pitch, cy - 4, "p", -3, -6)
        p.drawText(QtCore.QPointF(185, 140), "top view")

    def _draw_toroid(self, p: QtGui.QPainter) -> None:
        p.save()
        p.setPen(QtGui.QPen(p.pen().color(), 1, QtCore.Qt.DashLine))
        p.drawLine(QtCore.QPointF(130, 15), QtCore.QPointF(130, 120))  # axis
        p.restore()
        for x0 in (60.0, 165.0):  # ring cross-section, both sides of the axis
            p.drawRect(QtCore.QRectF(x0, 35, 35, 60))
            for i in range(4):
                self._wire(p, x0 - 4, 42 + 15 * i, 3.5)
                self._wire(p, x0 + 39, 42 + 15 * i, 3.5)
        self._dim(p, 95, 108, 165, 108, "ID", 5, 13)
        self._dim(p, 60, 132, 200, 132, "OD", -6, 12)
        self._dim(p, 222, 35, 222, 95, "h", 6, 4)
        p.drawText(QtCore.QPointF(4, 20), "section through axis")


# ---------------------------------------------------------------------------
# Designer widget
# ---------------------------------------------------------------------------

def _set_row_visible(form: QtWidgets.QFormLayout, field: QtWidgets.QWidget, visible: bool) -> None:
    """QFormLayout.setRowVisible only exists in Qt >= 6.4; do it by hand."""
    label = form.labelForField(field)
    if label is not None:
        label.setVisible(visible)
    field.setVisible(visible)


class DesignerWidget(QtWidgets.QWidget):
    """Shape drop-down, inputs, live results and the Build button."""

    def __init__(self, build_callback: Optional[BuildCallback] = None,
                 parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Inductor Designer")
        self.build_callback = build_callback
        self.spec: Optional[ic.Spec] = None
        self.result: Optional[ic.DesignResult] = None
        self._unit = fi.DEFAULT_UNIT
        self._spins: dict[Shape, dict[str, QtWidgets.QDoubleSpinBox]] = {}
        self._mode_combos: dict[Shape, QtWidgets.QComboBox] = {}
        self._page_forms: dict[Shape, QtWidgets.QFormLayout] = {}

        root = QtWidgets.QVBoxLayout(self)

        # Shape drop-down ---------------------------------------------------
        top = QtWidgets.QFormLayout()
        self.shape_combo = QtWidgets.QComboBox()
        for shape, label in ic.SHAPE_LABELS.items():
            self.shape_combo.addItem(label, shape.value)
        top.addRow("Shape", self.shape_combo)
        root.addLayout(top)

        self.sketch = ShapeSketch()
        root.addWidget(self.sketch)

        # Dimensions: one page per shape --------------------------------------
        dims_box = QtWidgets.QGroupBox("Dimensions")
        dims_layout = QtWidgets.QVBoxLayout(dims_box)
        self.pages = QtWidgets.QStackedWidget()
        for shape in ic.SHAPE_LABELS:
            self.pages.addWidget(self._make_page(shape))
        dims_layout.addWidget(self.pages)
        root.addWidget(dims_box)

        # Wire ----------------------------------------------------------------
        wire_box = QtWidgets.QGroupBox("Wire")
        wire_form = QtWidgets.QFormLayout(wire_box)
        self.copper_combo = QtWidgets.QComboBox()
        self.copper_combo.setEditable(True)
        for d in ic.NOMINAL_WIRE_DIAMETERS_MM:
            self.copper_combo.addItem(f"{d:g}")
        self.copper_combo.setCurrentText(f"{fi.DEFAULT_WIRE_COPPER_MM:g}")
        self.copper_combo.setToolTip("Bare copper diameter in mm. Pick a standard size or type one.")
        wire_form.addRow("Copper Ø (mm)", self.copper_combo)
        self.overall_spin = self._spin(0.0, 0.0, 12.0, step=0.01, decimals=3)
        self.overall_spin.setSpecialValueText("auto (estimate)")
        self.overall_spin.setToolTip(
            "Diameter over the enamel. Measure it with calipers for best accuracy; "
            "leave at 0 for a rough estimate.")
        wire_form.addRow("Overall Ø", self.overall_spin)
        root.addWidget(wire_box)

        # Target ----------------------------------------------------------------
        target_box = QtWidgets.QGroupBox("Target")
        target_form = QtWidgets.QFormLayout(target_box)
        row = QtWidgets.QHBoxLayout()
        self.target_spin = self._spin(fi.DEFAULT_TARGET, 0.0001, 1e7, step=1.0, decimals=4, suffix="")
        self.unit_combo = QtWidgets.QComboBox()
        self.unit_combo.addItems(fi.INDUCTANCE_UNITS)
        self.unit_combo.setCurrentText(fi.DEFAULT_UNIT)
        row.addWidget(self.target_spin, 1)
        row.addWidget(self.unit_combo)
        target_form.addRow("Inductance", row)
        self.step_combo = QtWidgets.QComboBox()
        for label, step in fi.TURNS_STEPS:
            self.step_combo.addItem(label, step)
        target_form.addRow("Round to", self.step_combo)
        self.leads_spin = self._spin(0.0, 0.0, 5000.0, step=10.0, decimals=0)
        self.leads_spin.setToolTip("Total length of both leads, added to wire length and DC resistance.")
        target_form.addRow("Lead length (total)", self.leads_spin)
        root.addWidget(target_box)

        # Results ---------------------------------------------------------------
        results_box = QtWidgets.QGroupBox("Results")
        results_layout = QtWidgets.QVBoxLayout(results_box)
        self.results_label = QtWidgets.QLabel()
        self.results_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.warnings_label = QtWidgets.QLabel()
        self.warnings_label.setWordWrap(True)
        self.error_label = QtWidgets.QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet(f"color: {ERROR_COLOR};")
        for w in (self.results_label, self.warnings_label, self.error_label):
            results_layout.addWidget(w)
        root.addWidget(results_box)

        self.build_button = QtWidgets.QPushButton("Build in FreeCAD")
        root.addWidget(self.build_button)
        root.addStretch(1)

        # Signals -------------------------------------------------------------
        self.shape_combo.currentIndexChanged.connect(self._on_shape_changed)
        self.copper_combo.editTextChanged.connect(self.recalculate)
        self.copper_combo.currentIndexChanged.connect(self.recalculate)
        self.overall_spin.valueChanged.connect(self.recalculate)
        self.target_spin.valueChanged.connect(self.recalculate)
        self.unit_combo.currentIndexChanged.connect(self._on_unit_changed)
        self.step_combo.currentIndexChanged.connect(self.recalculate)
        self.leads_spin.valueChanged.connect(self.recalculate)
        self.build_button.clicked.connect(self._on_build)

        self._on_shape_changed()

    # construction helpers --------------------------------------------------
    def _spin(self, value: float, minimum: float, maximum: float, step: float = 0.5,
              decimals: int = 2, suffix: str = " mm") -> QtWidgets.QDoubleSpinBox:
        spin = QtWidgets.QDoubleSpinBox()
        spin.setDecimals(decimals)
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setSuffix(suffix)
        spin.setValue(value)
        spin.setKeyboardTracking(True)
        return spin

    def _make_page(self, shape: Shape) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        self._page_forms[shape] = form
        modes = fi.SHAPE_MODES[shape]
        if modes:
            combo = QtWidgets.QComboBox()
            for mode in modes:
                combo.addItem(fi.MODE_LABELS[mode], mode.value)
            combo.currentIndexChanged.connect(self._on_mode_changed)
            form.addRow("Winding", combo)
            self._mode_combos[shape] = combo
        spins = {}
        for f in fi.SHAPE_FIELDS[shape]:
            spin = self._spin(f.default, f.minimum, f.maximum, f.step, f.decimals)
            spin.setToolTip(f.tooltip)
            spin.valueChanged.connect(self.recalculate)
            form.addRow(f.label, spin)
            spins[f.key] = spin
        self._spins[shape] = spins
        return page

    # state -------------------------------------------------------------------
    @property
    def current_shape(self) -> Shape:
        return Shape(self.shape_combo.currentData())

    def current_mode(self) -> Optional[PitchMode]:
        combo = self._mode_combos.get(self.current_shape)
        return PitchMode(combo.currentData()) if combo else None

    def set_shape(self, shape: Shape) -> None:
        self.shape_combo.setCurrentIndex(self.shape_combo.findData(shape.value))

    def set_mode(self, mode: PitchMode) -> None:
        combo = self._mode_combos[self.current_shape]
        combo.setCurrentIndex(combo.findData(mode.value))

    def set_value(self, key: str, value: float) -> None:
        self._spins[self.current_shape][key].setValue(value)

    def _copper_d(self) -> float:
        text = self.copper_combo.currentText().strip().replace(",", ".")
        try:
            return float(text)
        except ValueError:
            raise ic.DesignError(f"copper diameter {text!r} is not a number") from None

    # slots -------------------------------------------------------------------
    def _on_shape_changed(self, *_args) -> None:
        shape = self.current_shape
        self.pages.setCurrentIndex(list(ic.SHAPE_LABELS).index(shape))
        self.sketch.set_shape(shape)
        self._on_mode_changed()

    def _on_mode_changed(self, *_args) -> None:
        shape, mode = self.current_shape, self.current_mode()
        form = self._page_forms[shape]
        for f in fi.SHAPE_FIELDS[shape]:
            visible = f.modes is None or mode in f.modes
            _set_row_visible(form, self._spins[shape][f.key], visible)
        self.recalculate()

    def _on_unit_changed(self, *_args) -> None:
        new_unit = self.unit_combo.currentText()
        value_uH = ic.to_uH(self.target_spin.value(), self._unit)
        self._unit = new_unit
        self.target_spin.blockSignals(True)
        self.target_spin.setValue(ic.from_uH(value_uH, new_unit))
        self.target_spin.blockSignals(False)
        self.recalculate()

    def _on_build(self) -> None:
        if self.build_callback and self.spec and self.result:
            try:
                self.build_callback(self.spec, self.result)
            except Exception as exc:  # show CAD errors in the panel, don't crash
                self.error_label.setText(f"Build failed: {exc}")

    def recalculate(self, *_args) -> None:
        """Rebuild the spec from the inputs and refresh the results panel."""
        shape = self.current_shape
        values = {k: s.value() for k, s in self._spins[shape].items()}
        try:
            wire = fi.make_wire(self._copper_d(), self.overall_spin.value())
            spec = fi.build_spec(shape, values, wire, self.current_mode())
            target = ic.to_uH(self.target_spin.value(), self._unit)
            result = ic.design(spec, target, turns_step=self.step_combo.currentData(),
                               lead_length_mm=self.leads_spin.value())
        except ic.DesignError as exc:
            self.spec = self.result = None
            self.results_label.setText("")
            self.warnings_label.setText("")
            self.error_label.setText(str(exc)[:1].upper() + str(exc)[1:])
        else:
            self.spec, self.result = spec, result
            self.error_label.setText("")
            self.results_label.setText(self._results_html(result))
            self.warnings_label.setText("".join(
                f'<p style="color:{WARN_COLOR}">⚠ {w}</p>' for w in result.warnings))
        self._update_build_button()

    def _results_html(self, result: ic.DesignResult) -> str:
        rows = fi.result_rows(result, self._unit)
        cells = "".join(
            f'<tr><td style="padding-right:12px">{label}</td><td><b>{value}</b></td></tr>'
            for label, value in rows)
        return f"<table>{cells}</table>"

    def _update_build_button(self) -> None:
        if self.build_callback is None:
            self.build_button.setEnabled(False)
            self.build_button.setToolTip("3-D modelling arrives in Phase 3.")
        else:
            self.build_button.setEnabled(self.result is not None)
            self.build_button.setToolTip("Create the coil form in the active FreeCAD document.")


# ---------------------------------------------------------------------------
# FreeCAD Task Panel and entry points
# ---------------------------------------------------------------------------

class InductorTaskPanel:
    """FreeCAD Task Panel wrapper (``FreeCADGui.Control.showDialog``)."""

    def __init__(self, build_callback: Optional[BuildCallback] = None) -> None:
        self.form = DesignerWidget(build_callback)

    def getStandardButtons(self):  # noqa: N802 (FreeCAD API)
        return QtWidgets.QDialogButtonBox.Close

    def reject(self) -> None:
        import FreeCADGui  # type: ignore[import-not-found]

        FreeCADGui.Control.closeDialog()

    accept = reject


def _freecad_gui_up() -> bool:
    try:
        import FreeCAD  # type: ignore[import-not-found]
    except ImportError:
        return False
    return bool(getattr(FreeCAD, "GuiUp", False))


def show(build_callback: Optional[BuildCallback] = None):
    """Open the designer: as a Task Panel in FreeCAD, else as a window."""
    if _freecad_gui_up():
        import FreeCADGui  # type: ignore[import-not-found]

        if FreeCADGui.Control.activeDialog():
            FreeCADGui.Control.closeDialog()
        panel = InductorTaskPanel(build_callback)
        FreeCADGui.Control.showDialog(panel)
        return panel
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    widget = DesignerWidget(build_callback)
    widget.show()
    run = getattr(app, "exec", None) or getattr(app, "exec_")
    run()
    return widget


if __name__ == "__main__":
    show()
