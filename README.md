# Inductor Designer

A FreeCAD macro for designing air-core inductors: pick a shape, enter dimensions
(mm) and a target inductance, get turns and pitch from Wheeler-family formulas,
build the coil form in FreeCAD, then log your measured inductance against the
prediction. FreeCAD is the only dependency. See [PLAN.md](PLAN.md).

## Status

- **Phase 1, calculation core: done.** `InductorDesigner/inductor_core.py` uses
  only the Python standard library and has no FreeCAD imports.
- Phase 2 (dialog UI) and Phase 3 (FreeCAD modelling): not started.

## Using the core from Python

```python
import inductor_core as ic

spec = ic.SolenoidSpec(form_diameter_mm=20, wire=ic.Wire(copper_d_mm=0.8, overall_d_mm=0.86))
res = ic.design(spec, target_uH=10.0)
print(res.turns, res.pitch_mm, res.coil_length_mm, res.predicted_uH, res.error_pct)
# 28.0 0.86 24.08 10.03 0.33
```

Shapes: `SolenoidSpec` (close-wound / fixed pitch / fixed length),
`MultilayerSpec`, `FlatSpiralSpec` (close-wound / fixed pitch), `ToroidSpec`.

## Tests

```
python3 -m unittest discover -s tests -v
```
