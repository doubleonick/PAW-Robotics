# BYOV Web — Design Specification (v1 draft)

**Purpose.** A browser-based "Build Your Own Vehicle" simulator: a modern,
maintained replacement for **BugWorks** (the unmaintained Sussex Java applet).
Students wire sensors to motors on a vehicle body and watch the resulting
Braitenberg behaviour play out in a 2D arena, then record runs for lab
write-ups.

**This is a specification, not code.** It captures the settled design so the
JavaScript/Canvas build encodes a fixed target rather than a moving one. The
existing Python BYOV (Valentino's Vehicles) is the **reference design** — its
behaviour model and physical constants are the source of truth, re-expressed in
JS. No Python is ported.

---

## 1. Deployment (settled)

- **Form:** pure client-side web app — HTML + JS + CSS + Canvas. **No backend.**
  A simulation has no hardware to talk to, so it is fully self-contained.
- **Host:** GitHub Pages **Project site** in the `Vassar-IRRL` org, in a
  dedicated public repo (e.g. `byov`). Live link:
  `https://vassar-irrl.github.io/byov/`. Entry file must be `index.html`.
- **Because it is served over https, the `file://` sandbox does NOT apply** — a
  normal multi-file structure (separate .js/.css/assets, relative paths) is
  fine. Single-file inlining is NOT required (that constraint only existed for
  the download-and-double-click model, now superseded by the hosted link).
- **Dev convenience:** may build with separate files; deployment is just
  "commit to the repo, Pages serves it."

---

## 2. What we KEEP from BugWorks

1. **A range of body plans where body SHAPE influences interaction.** The body
   is a polygon, not a point/circle; its geometry participates in collisions and
   in where sensors sit. (Mirrors the RE morphology work: polygon chassis +
   sensor mount/angle.)
2. **Flexible sensor & motor placement** on the body, where placement changes
   behaviour (a light sensor on the left vs right, angled out vs forward, etc.).
3. **Record-and-replay** so students capture a behaviour for a lab write-up
   (trail drawing + replay; optional position/heading stats).

## 3. What we DROP / SIMPLIFY from BugWorks

- **Drop the literal battery-as-constant-voltage wiring trick.** Clever but
  fiddly; not replicated. A "always-on" bias, if needed, is a simple per-motor
  constant, not a wired battery object.
- **Pare down the object/stimuli palette.** BugWorks' anything-can-be-anything
  flexibility is a major source of its confusion. We ship a small, focused,
  curated palette (see §5).

## 4. The TWO core contributions (why build this vs. reuse a generic sim)

- **C1 — Simplified, focused palette** matched to the lab, not a generic
  sandbox. Fewer, clearer choices.
- **C2 — Digital twin of the PHYSICAL PAW lab.** The simulated vehicle, sensors,
  and arena mirror the *real* AnaBBot robots and physical arenas students use.
  Same body scale, same sensor types/ranges, same arena proportions. This
  sim↔physical correspondence is the project's through-line and the reason this
  tool is worth building. Numbers below come from the real robot.

---

## 5. The palette (curated — C1)

### SENSOR FIDELITY PRINCIPLE (settled — core requirement)
Every sensor must **mathematically model its physical counterpart**, including
**directionality** and its **cone of operation**. A reading depends on the
sensor's mounted position AND angle on the body, relative to the stimulus —
both **orientation to** and **distance from** the source (this is what BYOV does
and is carried over wholesale). **Omnidirectional sensors are explicitly
forbidden** — that was BugWorks' core mistake; it erases the meaning of sensor
placement/angle and lets students build vehicles that "work" in sim but couldn't
on a real robot. Directionality is what makes "light sensor on the left, angled
outward" a consequential choice and what keeps the digital-twin contract (C2)
honest.

Consequence: sensor inputs are **continuous, physically-modelled values (0..1)**
from real geometry (angle, distance, FOV, occlusion) — NOT thresholded 0/1. The
wire's E/I header sets the input's **sign**; the **magnitude is the
physically-accurate reading** (e.g. a light 30° off-axis at mid-distance might
feed +0.4 into an E header, not +1).

### Sensors (start minimal; each maps to a REAL robot sensor — C2)
- **Light sensor (LDR).** Directional. Real analogue: wide-angle LDR, ~70° FOV
  half-angle (≈140° cone). Response = **inverse-square of distance × cosine of
  off-axis angle**, attenuated/occluded by walls. Both orientation-to and
  distance-from the light source shape the reading (carried over from BYOV).
- **Proximity sensor (IR).** Directional, NARROW. Real analogue: Sharp
  GP2Y0A21 — ~5° beam half-angle, reliable range ≈ 18–60 cm, "closer = stronger."
  Only detects obstacles nearly straight ahead of where it points.
- **(Optional later) Contact/bump sensor.** Boolean on collision.

### Motors
- **Two motors**, left and right wheels — **differential drive** (steering by
  speed difference). This matches the real robot exactly.

### Stimuli / arena objects (curated)
- **Light source(s)** — the primary stimulus (Braitenberg's classic).
- **Walls / obstacles** — arena boundary + a small number of internal walls.
- Deliberately NOT a big zoo of object types. A few, lab-relevant.

---

## 6. The wiring model (the heart of it) — SETTLED for v1

Layout mirrors the existing Python wiring editor: **sensors (top) → neurons
(middle) → motors (bottom)**, lanes running left→right. v1 KEEPS the explicit
neuron layer (it is what enables signed inputs — a sensor can excite OR inhibit).

### Connections (wires)
- A wire's **sign is determined by which neuron input header it lands on**:
  - into an **E (excitatory)** header → contributes **+1**
  - into an **I (inhibitory)** header → contributes **−1**
- **No per-wire gain in v1.** Every wire has magnitude 1. (The full model's
  colour-coded wire weights — blue/green/red = 1/2/3, mirroring AnaBBot wire
  resistances — are DROPPED for v1. Post-v1 enrichment.)
- Multiple sources may feed one neuron, mixed E and I.

### Neuron (v1 model)
Each neuron computes, per tick:

```
internal_sum = bias + (count of E wires active) − (count of I wires active)
N            = clamp(internal_sum, 0, 1)
```

- **bias** — the neuron's own trimpot (NOT wire resistance): its resting level
  before any input. **Range −1 .. +1** in v1 (a simplification of the real
  AnaBBot −4..+4). Positive bias = default-on (lets a vehicle cruise by default,
  modulated by sensors); negative bias = default-suppressed (needs excitation to
  act). Bias is near-free in the math and is what makes default/cruising
  vehicles expressible, so it is KEPT.
- **N (normal output)** — continuous, clamped 0..1 — is the **only** output in
  v1. The **T (threshold) output** (time-delayed binary firing) is DROPPED for
  v1. Post-v1 enrichment.
- Inputs are weighted by sensor signal strength where applicable (a partially-lit
  LDR contributes a fraction, not just 0/1); "count of E/I wires" above is the
  simple case — more precisely, sum the (signed) input signals, each scaled 0..1.

### Motors
Each motor command = the signal routed to it (from a neuron's N output or
directly), fed to the differential-drive update (§7). Two motors, L and R.

### Teaching bar (acceptance test for the wiring model)
The model must make the classic Braitenberg progression expressible:
**Vehicle 1** (single sensor → single motor; "alive" / getting around),
**2a/2b** (fear / aggression — uncrossed vs crossed excitatory),
**3a/3b** (love / explorer — the inhibitory variants).
**If a student can build Braitenberg Vehicles 1, 2a, 2b, 3a, and 3b, the v1
wiring model is sufficient.** (Note Vehicle 1 sets a floor: the model must handle
minimal single-sensor/single-motor wiring gracefully, not only two-sensor
crossed/uncrossed configs.)

### Deferred to post-v1 (the full BYOV model, not lost)
- Colour-coded wire gains (blue/green/red = 1/2/3).
- T (threshold) outputs with turn-on/turn-off timing.
- Full bias range (−4..+4).
- Multiple/editable body morphologies (see §10).

---

## 7. Physics / behaviour model (re-express SimpleDriveAdapter in JS — C2)

Idealised 2D differential drive; **no PyBullet**, no inertia (velocity set each
tick). Real constants from the AnaBBot (`engine/adapters/simple_drive.py`):

| Quantity | Value | Source |
|---|---|---|
| Wheelbase | 0.080 m (80 mm) | AnaBBot |
| Max linear speed @ command 1.0 | 0.175 m/s | AnaBBot CRUISE |
| Wall thickness | 0.012 m | arena model |
| Default arena | 1.2 m × 1.6 m | valentinos_arena.json |

Per tick: each motor command → wheel speeds → differential-drive pose update
(x, y, heading); robot stops at wall boundary on contact (no sliding needed for
v1). Light sensor reads inverse-square × cosine-FOV sum over light sources,
wall-attenuated. IR reads near-field obstacle distance within its narrow beam.

---

## 8. Record & replay (KEEP — serves lab write-ups)

- **Record** a run: capture the pose (x, y, heading) per tick, plus the active
  light/obstacle layout.
- **Replay** in-app: redraw the trail and re-animate.
- **Export** for the lab report: let the student **download** the recording
  (e.g. JSON of the trajectory, and/or a PNG of the trail). Download-on-demand
  works from a hosted page; no backend / no cross-session persistence needed.
- NOT in v1: accounts, server-stored history, cross-session memory.

---

## 9. UX flow (mirrors the existing VV pathway)

The VV intro → BYOV pathway, including the **Wiring Tutorial**, is the model and
is "ship as-is" in concept. Web flow:
1. (Optional) brief intro / wiring tutorial.
2. **Build:** place/angle sensors and motors on the body; draw connections with
   polarity.
3. **Run:** vehicle behaves in the arena with the chosen light/obstacle layout.
4. **Observe / iterate:** tweak wiring, re-run.
5. **Record → export** for the write-up.

---

## 10. Decisions (resolved) + remaining detail

**Resolved:**
- **Body plan:** v1 ships **ONE** tightly-AnaBBot-inspired body (the exact
  digital twin of the physical robot). Multiple/editable morphologies are
  deferred — "the real leverage of multiple morphologies is hard and should be
  done carefully once the foundations are in place." So v1 = single fixed body;
  body-plan variety is a post-v1 arc.
- **Neuron layer:** KEPT (explicit), per §6. It is what enables signed inputs.
- **Wire gains (colour weights):** DROPPED for v1 (all wires magnitude 1).
- **Threshold (T) outputs:** DROPPED for v1 (N output only).
- **Bias:** KEPT, range **−1..+1** (simplified from −4..+4).
- **Tech approach:** plain **HTML5 Canvas + vanilla JS**, no framework — best
  fit for a self-contained, dependency-free, long-lived teaching tool.

**Remaining detail (resolve during build, low-risk):**
- Exact AnaBBot body geometry/scale to mirror (pull from the physical robot /
  existing morphology data).
- Default sensor loadout on the body (how many LDR/IR, default placements/angles)
  and whether the student repositions them in v1 or accepts a fixed sane layout.
  (Flexible placement is a BugWorks strength to preserve — but could be a fast
  follow if v1 ships with good fixed positions.)
- Number of neurons exposed (the full model has 6; v1 may expose fewer).
- Exact light-source and obstacle layout(s) shipped as starting scenarios.

---

## 11. Explicit NON-goals (v1)

- No backend, accounts, or saved cloud state.
- No BLE / hardware link (that is the native instructor tools' job; the sim has
  no hardware).
- No big object/stimuli zoo (curated palette only).
- No physical inertia / advanced physics (idealised drive is the lab's model).
- Not a port of the PyGame app — a fresh build from this spec.

---

*Reference code in the existing tree: `engine/adapters/simple_drive.py` (drive
model + constants), `engine/sensors/sensor_models.py` (LDR/IR/contact specs),
`engine/builder/wiring_editor.py` (wiring layout), `games/valentinos/` (the VV
pathway and BYOV arena). These are the design source; the web build re-expresses
them in JS.*
