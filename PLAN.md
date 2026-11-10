# Inductor Designer: Development Action Plan

## 1. Goal

A tool where the user:

1. Picks an inductor geometry and enters its dimensions.
2. Enters a target inductance.
3. Gets the required **turns (N)** and **pitch (p)**, worked out with Wheeler-family formulas.
4. Has the coil form (and, optionally, the wire path) built in **FreeCAD through an MCP server**, ready to export as STEP/STL for printing or machining.
5. Winds the coil, measures it, and **enters the measured inductance**. The app then compares it with the prediction and keeps a history.

Scope for v1 is **air-core** inductors only. Ferrite/powder cores come later (Phase 7).

---

## 2. Supported geometries and formulas

All Wheeler formulas below take dimensions in **inches** and return **µH**. Internally the app works in SI and converts at the boundary. `r` is always measured to the **wire centre**.

| Geometry | Inputs | Formula | Notes |
|---|---|---|---|
| Single-layer solenoid | form diameter D, wire dia d, *either* length ℓ *or* pitch p | `L = r²N² / (9r + 10ℓ)` | ~1% accurate for ℓ > 0.8r |
| Multi-layer solenoid | mean radius r, length ℓ, winding depth b | `L = 0.8 r²N² / (6r + 9ℓ + 10b)` | ~1% when the three denominator terms are similar in size |
| Flat spiral (pancake) | inner radius rᵢ, wire d, pitch p | `L = r²N² / (8r + 11w)`, r = mean radius, w = winding width | w = N·p, so N must be solved numerically |
| Toroid, rectangular cross-section | rᵢ, rₒ, height h | `L = µ₀N²h·ln(rₒ/rᵢ) / 2π` | Exact for an ideal winding (not Wheeler) |
| Planar spiral, square/hex/octagon (PCB) | d_out, d_in, trace w/s | Modified Wheeler (Mohan 1999): `L = K₁µ₀N²d_avg / (1 + K₂ρ)` | K₁/K₂ table: square 2.34/2.75, hex 2.33/3.82, oct 2.25/3.55 |

### 2.1 Solving for N and pitch (the core maths)

**Single-layer solenoid, user fixes length ℓ:**
`N = √(L(9r + 10ℓ)) / r`, then `p = ℓ / N`. Check that `p ≥ d` (the wire fits).

**Single-layer solenoid, user fixes pitch p (or close-wound, p = d):** since ℓ = N·p, this becomes a quadratic in N:
`r²N² − 10LpN − 9Lr = 0` → `N = [10Lp + √(100L²p² + 36Lr³)] / (2r²)`.

**Flat spiral / multi-layer:** r and w depend on N, so use a 1-D root find on `f(N) = L_formula(N) − L_target` (Brent's method; f increases with N, so the root is unique).

**Toroid:** `N = √(2πL / (µ₀h·ln(rₒ/rᵢ)))`.

**Post-processing, every geometry:**
- Round N to a buildable value (whole turns, or ¼/½ turns where the user allows it), recompute L, and show the **rounding error in %**.
- Report the derived values: coil length, wire length (helix length plus leads), DC resistance (from AWG/diameter and copper resistivity), and, optionally, a self-resonant frequency estimate (Medhurst).
- Show the formula's **validity warnings** (for example "ℓ/r < 0.8, Wheeler error may exceed 1%; Nagaoka/Lundin cross-check shown").

**Optional accuracy upgrade:** a Lundin or Nagaoka-coefficient calculation, shown next to Wheeler as a cross-check for short solenoids.

---

## 3. Architecture

```
┌──────────────┐    ┌────────────────────┐    ┌──────────────────────┐
│  UI          │──▶ │  Design core       │──▶ │  CAD generator       │
│ (Streamlit / │    │  (pure Python lib) │    │  builds FreeCAD      │
│  web form)   │    │  formulas, solver, │    │  Python script /     │
│              │    │  units, validation │    │  ops for geometry    │
└──────┬───────┘    └────────────────────┘    └─────────┬────────────┘
       │                                                │ MCP client (python `mcp` SDK)
       │                                                ▼
       │                                     ┌──────────────────────┐
       │                                     │ FreeCAD MCP server   │
       │                                     │ (runs inside FreeCAD)│
       │                                     └──────────────────────┘
       ▼
┌──────────────────────┐
│ Measurement store    │  SQLite: design params, predicted L,
│ + comparison/plots   │  measured L, test freq, instrument, notes
└──────────────────────┘
```

**Stack:** Python 3.11+ everywhere, since FreeCAD's own scripting is Python.
- `inductor_core/`: formulas, solvers, units (`pint`), validation. No I/O. 100% unit-tested.
- `inductor_cad/`: turns a `CoilDesign` into FreeCAD operations. Two back ends behind one interface:
  - **MCP back end**: talks to a FreeCAD MCP server (for example an addon that exposes `execute_code` / object-creation tools).
  - **Headless back end**: runs the same script with `freecadcmd`, for CI and for users without MCP.
- `inductor_app/`: the UI (Streamlit to start; can move to FastAPI + a web front end later).
- `inductor_data/`: SQLite persistence and comparison analytics.

---

## 4. Phased action plan

### Phase 0: Project setup (≈1 day)
- [ ] Repository layout (packages above), `pyproject.toml`, `ruff`, `mypy`, `pytest`.
- [ ] GitHub Actions CI running lint, type checks and tests.
- [ ] Pick and pin the FreeCAD version (1.0.x) and the FreeCAD MCP server, and record the install steps in the README.
- **Done when:** CI is green on an empty test suite.

### Phase 1: Calculation core (≈3–4 days)
- [ ] A `Geometry` enum and input dataclasses for each geometry, with unit-aware fields.
- [ ] Forward formulas `L(N, dims)` for every geometry in §2.
- [ ] Inverse solvers `N(L_target, dims)`: closed form where possible, Brent's method otherwise.
- [ ] Pitch/length resolution modes: fixed length, fixed pitch, close-wound (from wire gauge).
- [ ] Rounding, recomputed L, error %, wire length, DCR, validity warnings.
- [ ] Wire table (AWG/SWG to diameter including enamel).
- **Tests:** published reference values, for example r = 1 in, ℓ = 2 in, N = 20 → `L = 400/29 = 13.79 µH`; forward/inverse round-trip property tests (Hypothesis); edge cases (wire too thick for the requested pitch, impossible targets).
- **Done when:** every geometry round-trips to within 1e-9 relative error and matches reference examples to within 0.5%.

### Phase 2: CLI and minimal UI (≈2 days)
- [ ] `inductor design --geometry solenoid --diameter 25mm --wire 0.8mm --target 10uH`
- [ ] Streamlit form: geometry selector → dynamic dimension fields → target L → results card (N, p, ℓ, wire length, DCR, warnings) plus a 2-D sketch.
- **Done when:** a user can produce a design from the browser with no CAD installed.

### Phase 3: FreeCAD geometry generation (≈4–5 days)
- [ ] Parametric coil-form builders:
  - **Solenoid form:** a tube (`Part.makeCylinder`, bore cut) with a **helical groove**: `Part.makeHelix(pitch, length, r)`, a circular profile of diameter ≈ d + clearance, swept with `Part.Wire.makePipeShell(..., isFrenet=True)` and then cut from the tube. Add end flanges and wire-exit holes.
  - **Flat spiral:** a disc with an Archimedean spiral groove (a spiral wire from points/B-spline, profile swept).
  - **Toroid:** a rectangular-section ring with N radial guide slots on the outer edge.
  - **Planar PCB spiral:** export the trace polygon as DXF/KiCad footprint instead of a 3-D form.
- [ ] Optional: a "wire" solid for visualisation, in a different colour.
- [ ] Each object gets named, parametric properties (spreadsheet-driven) so the user can tweak them in FreeCAD.
- [ ] Export STEP and STL.
- [ ] Get this working first through the **headless `freecadcmd` back end**, so CI can check the output: the shape is valid, the volume is above 0, and the bounding box matches the design.
- **Done when:** CI produces valid STEP/STL for each geometry from sample designs.

### Phase 4: MCP integration (≈3 days)
- [ ] Install and configure the FreeCAD MCP server addon, and confirm its tool list (document creation, code execution, screenshot/view).
- [ ] Write `McpCadBackend` with the Python `mcp` client SDK: connect, create a document, send the generated build script, fetch a screenshot back for the UI preview, and trigger the export.
- [ ] Error handling: FreeCAD not running, script exceptions sent back to the UI, timeouts.
- [ ] "Generate in FreeCAD" button in the UI, plus an "Open STEP" / download link.
- [ ] Also allow the flow to be driven from an LLM client (Claude Desktop/Code) that has both the FreeCAD MCP and an **inductor-design MCP server** this app exposes (`design_inductor`, `build_coil_form`, `log_measurement` tools).
- **Done when:** one click in the UI produces the coil form in a running FreeCAD session.

### Phase 5: Measurement and comparison (≈2–3 days)
- [ ] Measurement form: measured L, test frequency, instrument (LCR meter / VNA / nanoVNA), lead-length compensation (yes/no), notes, photo.
- [ ] Store each design and measurement pair in SQLite.
- [ ] Comparison view: predicted vs measured, error %, a pass/fail band (for example ±5%), and the Wheeler/Lundin cross-check.
- [ ] History dashboard: error by geometry and by ℓ/r ratio (shows where Wheeler drifts), scatter of predicted vs measured.
- [ ] **Calibration:** fit a per-geometry correction factor from the logged data and offer "corrected design" mode.
- [ ] Measurement tips in the UI: measure well below the SRF, keep metal away, null the test leads.
- **Done when:** a logged measurement shows up in the comparison and history views.

### Phase 6: Hardening and release (≈2 days)
- [ ] Input validation and clear error messages; unit selector (mm/in, nH/µH/mH).
- [ ] Save/load designs as JSON; export a design report as PDF/Markdown.
- [ ] Docs: user guide, formula references, FreeCAD and MCP setup guide.
- [ ] Packaging: `pip install`, plus Docker for the UI (FreeCAD stays on the host).
- **Done when:** v1.0 is tagged.

### Phase 7: Future
- Ferrite/powder toroids (A_L value / µᵣ), with core-material libraries.
- Q factor and AC resistance (skin/proximity effect), and SRF from self-capacitance models.
- Optimisation: given L, a max size and a wire, minimise DCR or maximise Q.
- Coupled coils / mutual inductance (wireless power, transformers).
- FEM check via FreeCAD FEM / Elmer, or FEMM.

---

## 5. Data model (draft)

```python
@dataclass
class CoilDesign:
    id: UUID
    geometry: Geometry            # SOLENOID, MULTILAYER, SPIRAL, TOROID, PLANAR
    dims: dict[str, Quantity]     # geometry-specific inputs
    wire_diameter: Quantity
    target_L: Quantity
    turns: float                  # rounded, buildable
    pitch: Quantity
    predicted_L: Quantity         # at the rounded N
    formula: str                  # "wheeler_single_layer", ...
    warnings: list[str]
    cad_files: list[Path]

@dataclass
class Measurement:
    design_id: UUID
    measured_L: Quantity
    frequency: Quantity
    instrument: str
    notes: str
    timestamp: datetime
```

---

## 6. Risks and open questions

| Risk / question | Mitigation |
|---|---|
| Which FreeCAD MCP server to standardise on (tool names differ between projects) | Hide it behind the `CadBackend` interface; keep the headless back end as a guaranteed fallback |
| Helical sweeps in FreeCAD can fail for tight pitch/profile ratios | Enforce pitch ≥ groove width + margin; use Frenet mode; validate the shape after every build |
| Wheeler error for short or very long coils | Show validity warnings and the Lundin/Nagaoka cross-check; use the measured-data calibration |
| Measurement error (leads, frequency near SRF) | Record test conditions; guidance in the UI; lead-compensation field |
| UI choice (desktop vs web) | Start with Streamlit; the core and CAD packages stay UI-independent |

**Decisions needed from the owner:**
1. Which geometries matter most for v1? (Suggestion: single-layer solenoid → flat spiral → toroid.)
2. Target manufacturing: 3D-printed forms (STL) or machined (STEP)?
3. Should the app be usable by an AI agent over MCP (expose our own MCP server), or only by people?
4. Preferred units and wire standard (AWG vs metric).

---

## 7. Suggested milestone timeline

| Week | Milestone |
|---|---|
| 1 | Phase 0 + Phase 1 (core maths fully tested) |
| 2 | Phase 2 (UI) + start of Phase 3 (solenoid form in headless FreeCAD) |
| 3 | Phase 3 complete (all geometries) + Phase 4 (MCP) |
| 4 | Phase 5 (measurement and comparison) + Phase 6 (release v1.0) |
