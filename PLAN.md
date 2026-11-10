# Inductor Designer: Development Action Plan (rev 2)

## 1. Goal

A tool where the user:

1. **Picks the inductor shape from a drop-down** and enters its dimensions.
2. Enters a target inductance.
3. Gets the required **turns (N)** and **pitch (p)**, worked out with Wheeler-family formulas.
4. Has the coil form **modelled in FreeCAD**. The user then **exports it from FreeCAD** (STEP/STL/...) through FreeCAD's own File → Export.
5. Winds the coil, measures it, and **enters the measured inductance**. The app compares it with the prediction and keeps a history.

### Decisions so far

| # | Decision |
|---|---|
| 1 | Shape is chosen from a **drop-down** |
| 2 | **Export is done by the user in FreeCAD**, so the app has no export code |
| 3 | **Keep dependencies to a minimum.** MCP is *not* required (see §3) |
| 4 | **Metric units everywhere**: mm for lengths, nH/µH/mH for inductance, mm for wire diameter (no AWG) |

v1 covers **air-core** inductors only.

---

## 2. Supported shapes (drop-down entries) and formulas

The classic Wheeler formulas are written in inches. They are restated here **in millimetres → µH**. The conversion was checked numerically: r = 25.4 mm, ℓ = 50.8 mm, N = 20 → 13.79 µH, the same as the inch form. `r` is always measured to the **wire centre** (form radius + d/2).

| Drop-down entry | Inputs (mm) | Formula (mm → µH) | Notes |
|---|---|---|---|
| Single-layer solenoid | form Ø, wire Ø d, *either* length ℓ *or* pitch p (or "close-wound") | `L = r²N² / (228.6·r + 254·ℓ)` | ~1% accurate for ℓ > 0.8r |
| Multi-layer solenoid | mean radius r, length ℓ, winding depth b | `L = r²N² / (190.5·r + 285.75·ℓ + 317.5·b)` | Wheeler's 0.8 factor is already folded into the constants |
| Flat spiral (pancake) | inner Ø, wire Ø d, pitch p | `L = r²N² / (203.2·r + 279.4·w)`, r = mean radius, w = N·p | Solved numerically |
| Toroid, rectangular section | inner Ø, outer Ø, height h | `L = µ₀N²h·ln(rₒ/rᵢ) / 2π` | Exact for an ideal winding |

The PCB planar spiral (Mohan's modified Wheeler) moves to *Future*. It doesn't need a 3-D coil form.

### 2.1 Solving for N and pitch

| Shape / mode | Solution |
|---|---|
| Solenoid, length ℓ fixed | `N = √(L·(228.6r + 254ℓ)) / r`, then `p = ℓ/N`. Check `p ≥ d` |
| Solenoid, pitch p fixed (close-wound means p = d) | ℓ = N·p gives the quadratic `r²N² − 254·L·p·N − 228.6·L·r = 0` → **`N = [254·L·p + √((254·L·p)² + 914.4·L·r³)] / (2r²)`** |
| Flat spiral, multi-layer | r and w depend on N, so use bisection on `L(N) − L_target`. L(N) increases with N, so there is a single answer, and bisection needs only the standard `math` module |
| Toroid | `N = √(2π·L / (µ₀·h·ln(rₒ/rᵢ)))` |

**Post-processing, every shape:** round N to a buildable value (whole turns by default; ½ and ¼ turns optional), recompute L, and show the rounding error in %. Also report coil length, wire length, and DC resistance (ρ_Cu = 1.72×10⁻⁸ Ω·m, from wire Ø). Show validity warnings, for example ℓ/r < 0.8.

---

## 3. Minimising dependencies: run inside FreeCAD, no MCP needed

The app doesn't need MCP to build the model. **The app can run *inside* FreeCAD as a macro**, which already bundles everything needed:

| Need | Provided by (bundled with FreeCAD) |
|---|---|
| GUI: drop-down, input fields, buttons | **PySide (Qt)**: `QComboBox`, `QStackedWidget`, `QFormLayout` |
| 3-D modelling | **FreeCAD `Part` module**: `makeHelix`, `makePipeShell`, booleans |
| Maths | Python standard library: `math` |
| Measurement log | Python standard library: `csv` / `json` |
| Export | FreeCAD File → Export (done by the user) |

**Runtime dependencies beyond FreeCAD: zero.** No pip installs, no server, no MCP plugin, no internet.

### Comparing the options

| Option | Extra dependencies | Verdict |
|---|---|---|
| **A. FreeCAD macro with a Qt dialog** | None | ✅ **Recommended (primary)** |
| B. Separate app that writes an `.FCMacro` file for the user to run | None, but two steps for the user | Fallback / CLI mode |
| C. Separate app driving FreeCAD through [neka-nat/freecad-mcp](https://github.com/neka-nat/freecad-mcp) | MCP addon + `mcp` SDK + server process | ❌ Not needed for the app |

### Where the existing MCP plugin still helps (optional, no code changes)

The CAD builder is plain FreeCAD Python. That means **Claude (or any MCP client) can drive it through freecad-mcp's `execute_code` tool** without anything extra in the app: for example *"design a 10 µH solenoid on a 20 mm form"* → Claude calls `execute_code` with `import inductor_cad; inductor_cad.build(...)`, then `get_view` to show a screenshot. The app never imports or requires MCP; this is just a free bonus for the setup you already have.

### Architecture

```
FreeCAD (only dependency)
└── Macro: InductorDesigner.FCMacro
      ├── inductor_core.py   pure Python + math only. Formulas, solvers, validation.
      │                      Has no FreeCAD imports, so it is testable with plain `python3`.
      ├── inductor_cad.py    FreeCAD Part code: build_solenoid_form(), build_spiral_form(), ...
      ├── inductor_ui.py     PySide dialog (drop-down → per-shape input page → results)
      └── inductor_log.py    measurement history (CSV in FreeCAD's user data dir)
```

Distribution: copy the folder into FreeCAD's `Macro/` directory, or install it with the **Addon Manager** from this GitHub repo (add a `package.xml`).

---

## 4. Phased action plan

### Phase 0: Project setup (½ day)
- [ ] Repo layout as above; `package.xml` for Addon Manager.
- [ ] Target **FreeCAD 1.0.x** (Python 3.11, PySide2/6 through FreeCAD's `PySide` shim).
- [x] Tests use the standard-library **`unittest`**, so there is no pytest dependency.
- [ ] GitHub Actions: (1) core tests with plain Python ✅, (2) CAD smoke tests with **`freecadcmd`** (headless FreeCAD, installed only in CI).

### Phase 1: Calculation core, `inductor_core.py` (3 days) ✅ done
- [x] `Shape` enum: `SOLENOID`, `MULTILAYER`, `FLAT_SPIRAL`, `TOROID`.
- [x] Input dataclasses per shape, all in mm / µH (SI internally for µ₀).
- [x] Forward `L(N, dims)` and inverse `N(L_target, dims)` for each shape (§2.1).
- [x] Pitch modes: fixed length / fixed pitch / close-wound.
- [x] Rounding + recomputed L + error %, wire length, DCR, warnings.
- [x] Table of nominal metric wire sizes (Ø 0.10 … 2.00 mm, IEC R20). Insulated Ø is entered by the user or roughly estimated (measure with calipers for accuracy).
- **Tests:** reference value 25.4 / 50.8 mm, N = 20 → 13.79 µH; forward/inverse round trips for every shape; errors for impossible inputs (wire wider than pitch, target too large for the form).
- **Done when:** all shapes round-trip to better than 1e-9 relative error.

### Phase 2: Dialog UI, `inductor_ui.py` (2–3 days) ✅ done
- [x] **Shape drop-down (`QComboBox`)** at the top. Changing it switches a `QStackedWidget` to that shape's input page, with a labelled dimension sketch per shape (drawn with `QPainter`, so there are no image files).
- [x] Input fields as `QDoubleSpinBox` with **"mm" suffixes** and sensible ranges. Inductance field with an nH/µH/mH unit drop-down (switching units converts the value).
- [x] Pitch-mode drop-down (close-wound / fixed pitch / fixed length) for solenoid and spiral; only the relevant fields are shown.
- [x] **Live results** (recalculated on every change, instead of a Calculate button): N (exact and rounded), pitch, coil length, wire length, DCR, predicted L at the rounded N, error %, shape details, warnings in amber, input errors in red.
- [x] **Build in FreeCAD** button (calls a build callback; stays disabled until Phase 3 provides one).
- [x] Opens as a docked Task Panel in FreeCAD (`InductorDesigner.FCMacro`), or as a standalone window for development.
- Field tables and result formatting live in Qt-free `inductor_inputs.py` (unit-tested); the dialog has offscreen PySide6 smoke tests (CI only).

### Phase 3: Coil-form modelling, `inductor_cad.py` (4–5 days) ✅ done
- [x] **Solenoid form:** "Form diameter" is the diameter the wire lies on, so on the grooved form it is the **groove bottom**; the ridges stand 60% of the wire diameter higher. Tube (bore + wall) with a helical groove (circle Ø d + clearance swept along `Part.makeHelix`, **one turn per sweep**, since cutting a stack of one-turn sweeps is ~5× faster than one long sweep), end flanges, and radial wire-exit holes into the bore. If the pitch leaves less than 0.4 mm between grooves (e.g. close-wound), the form is a plain cylinder and the user is told.
- [x] **Multi-layer form:** bobbin (core tube + two flanges sized for the layer count), with a wire slot in one flange.
- [x] **Flat spiral form:** disc with a spiral groove and exit holes. The spiral is built from **semicircles on two alternating centres** (half-tori grooves) instead of a B-spline sweep: B-spline sweeps made FreeCAD's booleans fail. Each turn still advances exactly one pitch.
- [x] **Toroid form:** rectangular-section ring with one guide notch per turn on the outer edge (skipped with a note if they don't fit).
- [x] Optional copper "WireModel" solid (solenoid, multi-layer, spiral), for viewing only.
- [x] Design stored on the CoilForm as **custom properties** (turns, pitch, target/predicted L, wire, DCR, warnings) plus a full `DesignJSON` record, so a saved `.FCStd` carries its design.
- [x] Builder never exports anything. **The user exports with File → Export** (STEP/STL/...).
- [x] Validity checks after each build (`isValid`, has a solid, volume > 0); errors are shown in the panel.
- [x] "3-D form options" in the dialog: groove clearance and depth, wall, end margin, flange thickness and height, spiral base, wire model on/off.
- **Tests:** `tests/test_inductor_cad.py` checks every shape in FreeCAD 1.0: valid solids, dimensions from the optimal bounding box, and **no overlap between the wire model and the form** (the wire sits exactly in the groove). Also checked end-to-end in the FreeCAD 1.0 GUI (offscreen): macro → Task Panel → Build → objects and properties in the document.
- **CI:** a job installs FreeCAD 1.0 from conda-forge and runs the CAD tests.

### Phase 4: Measurement and comparison, `inductor_log.py` (2 days)
- [ ] **Log measurement** form: measured L (nH/µH/mH), test frequency (kHz), instrument, notes.
- [ ] Each entry links to its design: shape, dims, N, pitch, predicted L.
- [ ] Comparison: predicted vs measured, error %, and a ±tolerance band (default ±5%) shown green or red.
- [ ] History table, filterable by shape; mean/σ of the error per shape.
- [ ] Optional chart of predicted vs measured: matplotlib is used **only if it is already present** (most FreeCAD builds include it). Otherwise the table is shown alone.
- [ ] **Calibration:** per-shape correction factor (mean measured/predicted) offered as an opt-in "corrected" target.
- [ ] Measurement tips: measure well below self-resonance, null the test leads, keep metal away.
- Storage: CSV in `FreeCAD.getUserAppDataDir()/InductorDesigner/measurements.csv`, readable in any spreadsheet.

### Phase 5: Polish and release (2 days)
- [ ] Input validation, tooltips, remember last-used values (`FreeCAD.ParamGet`).
- [ ] Save/load a design as JSON.
- [ ] README: install (Macro folder / Addon Manager), usage with screenshots, formula references.
- [ ] Optional section: *"Using with freecad-mcp"*, with example prompts for driving `inductor_cad` through `execute_code`.
- [ ] Tag **v1.0**.

### Phase 6: Future
- Ferrite/powder cores (A_L / µᵣ), Q factor and AC resistance, self-resonance estimate.
- PCB planar spiral (Mohan modified Wheeler) → sketch/DXF output.
- Lundin / Nagaoka cross-check for short solenoids.
- Optimisation: minimise DCR for a given L and maximum size.

---

## 5. Data model (draft)

```python
@dataclass
class CoilDesign:
    shape: Shape                  # SOLENOID | MULTILAYER | FLAT_SPIRAL | TOROID
    dims_mm: dict[str, float]     # shape-specific, always mm
    wire_d_mm: float
    target_uH: float
    turns: float                  # rounded, buildable
    pitch_mm: float
    predicted_uH: float           # at the rounded N
    warnings: list[str]

@dataclass
class Measurement:
    design: CoilDesign
    measured_uH: float
    freq_kHz: float
    instrument: str
    notes: str
    timestamp: str                # ISO 8601
```

---

## 6. Risks

| Risk | Mitigation |
|---|---|
| Helical/spiral sweeps fail at tight pitch/profile ratios | Enforce pitch ≥ groove Ø + 0.1 mm; Frenet mode; validate the shape; clear error message |
| PySide2 vs PySide6 differences between FreeCAD versions | Import only through FreeCAD's `PySide` compatibility module |
| Wheeler error for short or very long coils | Validity warnings; measured-data calibration (Phase 4) |
| Measurement setup errors | Record frequency and instrument; tips shown in the UI |

---

## 7. Timeline

| Week | Milestone |
|---|---|
| 1 | Phase 0 + Phase 1 (core maths, fully tested) |
| 2 | Phase 2 (dialog with shape drop-down) + solenoid form |
| 3 | Rest of Phase 3 (all shapes) + Phase 4 (measurement log) |
| 4 | Phase 5 → v1.0 |
