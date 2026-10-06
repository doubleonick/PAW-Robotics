# Future Work — design directions worth building, documented before they're lost

This file captures larger design ideas that are deliberately NOT being built
yet, so the intent survives and a future pass can pick them up. Each entry says
what it is, why it's valuable, the rough scope, and what already exists to build
on.

---

## FW-001 — Shared "Glossary / Resources" system across all games

### The idea
A reusable glossary (and, more broadly, an in-game *resources* panel) that:
- Introduces terms during play (as the Field Trip tutorial now does, with
  accent-highlighted `Term(n)` vocabulary and paged definitions), AND
- Lets the player **revisit the glossary at any time** once a term has been
  introduced — not only during the intro that first taught it.

The vision is bigger than a glossary: a common mechanism and consistent format
for *player-facing reference resources* (glossary, controls help, "what does
this sensor do", maybe a behaviour catalogue) available across every game, or
at least consistently within each collection.

### Why it's valuable
- Reference-on-demand is strong pedagogy, especially for younger players who
  meet a term once and need it again three challenges later.
- A shared format means a child who learns the resource UI in one game already
  knows it in the others — the reference panel becomes a familiar, trusted
  place, like a textbook's glossary or a game's pause-menu codex.
- It turns one-shot tutorial text into a persistent knowledge base, which
  rewards curiosity ("what was Flow-around again?") without punishing the
  player by making them replay narration.

### Rough scope (acknowledged: the full version is large)
- A `Glossary`/`Resources` class or module in `engine/` (shared, game-agnostic),
  holding entries as structured data (number, term, definition, maybe an icon
  or glyph, maybe a category).
- A standard rendering + interaction (open/close, page forward/back — the
  DialogueBox now has forward/back paging that could back this), reachable via
  a consistent affordance (a "Glossary"/"?" button) in each game's chrome.
- A notion of **unlock state**: a term becomes visitable once introduced, so
  the glossary grows as the player learns (don't reveal everything up front).
- Per-game content authored in each game's data:
  - Field Trip: the flow-style vocabulary already exists (`_TUT_GLOSSARY` in
    `engine/field_trip/challenges.py`) and would migrate to the shared system.
  - Valentino's Vehicles: needs its own glossary authored (sensors, motors,
    wiring, neuron concepts) and fitted into its flow.
  - Robot Ethology: needs its own (PyBullet/behaviour concepts) and fitted in.

### What already exists to build on
- `engine/professor.py` `DialogueBox` now supports opt-in `Term(n)` accent
  highlighting and forward/back paging (both universal). A glossary system
  could reuse these for rendering.
- Field Trip's `Challenge.narration` carries a `glossary` list today; that's the
  prototype data shape. The shared system would generalise it off the
  FT-specific `Challenge` so other games can carry glossaries too (consistent
  with the principle: game-specific data on game-specific types, shared
  mechanism in the hub/engine).

### Open questions for when this is built
- Where does "unlock state" live (per-game progress vs. a shared profile)?
- Is the glossary modal (pauses play) or a side panel (always visible)?
- One glossary per game, or per collection, or a shared core + per-game extras?
- Does it extend beyond a glossary to a fuller "codex" (controls, behaviours)?

Status: DOCUMENTED ONLY — not scheduled. Revisit when tutorial/narration work
across the games is mature enough to justify the shared investment.

---

## FW-002 — Graded colour channels for LDR sensors

### The idea
Currently R/G/B LDR channels use a **binary** colour filter: a light contributes
to a channel only if its declared `color` matches the channel exactly. The
fuller target model is **graded**: where lights overlap, the region contains a
mix of colours, and a colour channel should read the partial amount of its
colour present. E.g. a green light + blue light overlap forms cyan; a green
channel in that region should read SOME green (less than a pure green light, but
nonzero), skewed by the relative intensities of the constituents.

### Why it matters
- Truer to the arena's own colour-mixing (overlapping lights already RENDER
  mixed colour + intensity correctly; the sensors don't yet READ the mix).
- Enables subtler challenges built on colour gradients and mixed regions.

### Scope
- In `ldr_reading` (engine/sensor_physics.py), replace the binary
  `ls_color != channel: continue` filter with a per-light colour-component
  weight: decompose each light's colour into R/G/B components and weight its
  contribution to the active channel by the matching component.
- White (W) is unaffected — it already sums all intensity regardless of colour.

### Constraint
Binary filtering (current) UNDER-reports colour in mixes but never OVER-reports,
so it approximates the target without violating it. Pure single-colour lights
are already exact. Graded is an enhancement, not a correctness fix.

Status: DOCUMENTED ONLY.

---

## FW-003 — Directionless ambient light (re-tune orbit/flow without the floor)

### The issue
The target sensor model treats room **ambient** light as DIRECTIONLESS: it
should raise a white sensor's intensity reading but contribute NO force, because
ambient light has no bearing to pull the robot toward. Currently the white
ambient floor (0.3) is applied inside the per-source force term as well as the
sensing readout (engine/sensor_physics.py `ldr_reading`). This injects a small
phantom directional pull and would double-count for an arena with two white
lights.

### Why it's still in place
The Orbit (`ORBIT_INWARD`) and Flow-around tunings were calibrated WITH the
floor present in the force term, and depend on it at larger radii where a single
light's real reading drops below 0.3. Removing the floor from the force term
detunes C3 (Orbit) and C4 (Flow) — verified: they fail without it.

### The faithful fix
Make ambient contribute to the SENSING readout only (applied once to the
aggregate, never per-source), and RE-TUNE orbit/flow constants so those
behaviours are stable without relying on a directional ambient term. Then
re-verify every light challenge.

### Constraint / current safety
Harmless for all present arenas (each uses a single white light or
clearly-separated coloured lights), so neither the double-count nor the phantom
pull is exercised today. It only matters if/when an arena places two or more
white lights.

Status: DOCUMENTED ONLY — deferred because it's a re-tuning project that risks
destabilising hard-won orbit/flow behaviour and should be done deliberately.

---

## FW-004 — PAW-Bot in the in-game narration canvases

### The idea
PAW-Bot now lives on the launch screen (sitting on the narration box) and in the
wiring-tutorial tour strip. The same motif should extend to the **in-game
narration canvases** — the bottom narration/dialogue panels used inside the
games (e.g. Valentino's Vehicles hub narration, the ethology/field-trip dialogue
boxes). PAW-Bot would sit in the bottom portion of those canvases, giving a
consistent narrator presence across the whole suite rather than only on the
launch screen and tour.

### Scope notes
- The launch screen and tour already use `engine/launch_assets.PawBotSprite`
  (bottom-anchored, pose rotation). The in-game canvases use their own dialogue
  drawing (e.g. `games/valentinos/hub.py` `_draw_narrative`, the `DialogueBox`
  in `engine/professor.py`). Adding PAW-Bot means giving those panels room for
  the sprite and drawing it bottom-anchored, like the launch screen.
- Each game's narration panel has different dimensions/positions, so placement
  needs to be checked per game (and must not occlude existing text or buttons,
  cf. the launch-screen and tour text-inset work already done).
- Ties into FW-005 (pose sequencing) — whatever fix lands there should apply
  here too so the in-game PAW-Bot doesn't show the same awkward sequence.

Status: DEFERRED — flagged for a dedicated pass after Phase 5.

---

## FW-005 — PAW-Bot pose sequencing feels awkward / distracting

### The issue
The launch/tour PAW-Bot picks a new pose on each narration advance using a
pseudo-random draw with a single guard: never repeat the *immediately* previous
pose (`PawBotSprite.next_pose` in `engine/launch_assets.py`). In practice this
still produces sequences that read as awkward — e.g. a pose can return after just
one other pose (A → B → A), the same two poses can ping-pong, and some poses
cluster while others are starved. With a small pose set this is noticeable and
distracting.

### Why "pseudo-random, no immediate repeat" isn't enough
The no-immediate-repeat rule only blocks the single previous pose. It does not
prevent near-repeats (A B A), short cycles, or uneven coverage, so the eye still
catches "didn't I just see that?" patterns.

### Candidate fixes (pick during the dedicated pass)
- **Bag/shuffle (recommended):** shuffle all poses into a "bag," draw without
  replacement until the bag is empty, then reshuffle (guaranteeing every pose is
  shown once before any repeats, and no pose returns until the others have). Add
  a guard so a reshuffle doesn't place the same pose across the seam.
- **History window:** forbid the last N poses, not just the last 1.
- **Curated transition rules:** if poses have a "facing"/"posture" relationship,
  prefer transitions that read naturally (e.g. avoid sit→stand→sit flicker).
- **Slower cadence:** change pose less often (e.g. only every other advance) so
  changes are deliberate rather than constant.

### Note
Applies anywhere PAW-Bot rotates poses — launch screen, tour, and (once built)
the in-game canvases in FW-004. A single fix in `PawBotSprite` covers all sites.

Status: DEFERRED — flagged; bag/shuffle is the likely fix.

---

## FW-006 — Instructor authoring suite for Robot Ethology (north star)

### The vision
A real lab-design workflow mirrors the whole game loop, but inverted: the
student plays Robot Ethology to *infer* a robot's hidden behavior hierarchy by
observation; the **instructor/designer** needs to *author* the specimens the
student will study. That authoring is essentially the game's own machinery run
in reverse — and it has four parts:

  1. **Build a robot** — define its morphology (which sensors, where they mount,
     what angle they face), like a lab technician assembling hardware to spec.
  2. **Build an arena** — define the environment (lights, walls, layout).
  3. **Build the hierarchy** — define the behavior priority stack.
  4. **Test robot + hierarchy in the arena** — run the sim to see the resulting
     behavior *before* handing the finished specimen to students.

The student never sees any of this; they only meet the finished robots, with no
blueprint — which is the whole pedagogical point (you infer the deer's eyes are
eyes; no one annotates them for you).

### Why it's a big project (and why it's mostly integration)
The pieces largely EXIST already, scattered:
  - Arena building: `tools/arena_builder.py` (separate instructor tool already).
  - Hierarchy building: `games/ethology/hierarchy_builder.py`.
  - The simulation / test-run: the PyBullet observation sim in
    `games/ethology/hub.py` + `engine/robot/robot_model.py`.
  - Robot morphology: the NEW piece (see FW-007 / the morphology spec +
    inspector being built now). The inspector's specimen rendering is most of a
    read-only robot view, so the robot-builder is "inspector + editing", not a
    from-scratch tool.

So FW-006 is an INTEGRATION + authoring-mode project over largely-existing
parts, unified into one instructor-facing environment — not a greenfield build.
But it is multi-step and should be grown one validated piece at a time.

### Relationship to current work
The morphology JSON spec + Robot Inspector (being built now) are the FRONT of
this arc and its foundation: the spec is the shared contract every authoring
piece reads/writes, and the inspector validates it by displaying it. The full
suite is the destination; we are deliberately building the front first.

Status: DEFERRED — recorded as the north star. Build incrementally after the
morphology spec + inspector are proven.

---

## FW-008 — Classroom tool extraction + standalone executables

### Goal
Extract two focused, classroom-facing tools from the suite as standalone,
installer-delivered desktop apps (Windows .exe first, then macOS .app), each
single-purpose, hardware-upload-centric, no dev CLI:

  1. **RE Hierarchy Builder** — author a behavior hierarchy, upload to a
     physical robot (Clear All / Launch Arduino / Send via BLE). NO simulation,
     NO observation/inference game (in class, robots A and B are physical and
     hypothesis-testing happens in the real world). "Launch Experiment" button
     removed (it's the game action, meaningless without the game).
  2. **BYOV (Valentino's Vehicles builder)** — build a vehicle, SIMULATE it,
     upload. Keeps its simulation. Wiring Tutorial ships with it (BYOV is hard
     without it).

### Key investigation findings (de-risking)
- **Neither tool needs PyBullet.** Verified by importing each with pybullet
  absent from the environment:
  - RE Hierarchy Builder already PyBullet-free; already has a standalone entry
    point `hierarchy_builder.pyw` ("without launching the full game"). Its chain
    is pygame + engine.theme + codegen + arduino_export — all pure Python.
  - VV/BYOV already runs on `engine/adapters/simple_drive.py`
    (`SimpleDriveAdapter`) — 2D vector-math differential drive — NOT the
    PyBullet adapter. No "drift back to vector math" needed; it's already there.
    The codebase has a clean `PhysicsAdapter` abstraction (simple_drive vs
    pybullet_drive) and VV uses the simple one.
- **PyBullet is used ONLY by RE's observation simulation** (engine/simulation,
  robot_model, arena_model, sensor_models, pybullet_drive, ethology/hub) — the
  exact part removed from the classroom build.
- **BLE transport = PySerial over Bluetooth** (HC-05/HC-06 bridges UART↔RFCOMM;
  OS assigns a COM port). So the BLE dependency is just `pyserial` — pure
  Python, no native BLE stack, no special OS Bluetooth permission flow.

### Resulting dependency footprint (both apps)
Python + PyGame + PySerial. (No PyBullet, no bleak/native BLE.) This makes
PyInstaller-style packaging genuinely tractable.

### Sequencing
1. RE Hierarchy Builder → Windows .exe (user's primary platform). [IN PROGRESS]
2. RE Hierarchy Builder → macOS .app (user has Mac access).
3. Then tackle VV/BYOV packaging.

### Remaining real work (not the feared PyBullet nightmare)
- Per-platform builds (Win .exe built on Windows; Mac .app built on a Mac).
- macOS code-signing / notarization (else Gatekeeper warnings).
- Bundling data files (sprites, scripts, robot.json, theme assets) with the exe.
- Verify the Send-via-BLE / Launch-Arduino upload paths end-to-end on real
  hardware from inside a packaged build (hardware-validation; user's domain).
- "Launch Experiment" button removal + ensure the standalone presents only the
  builder (no game shell).
- Shared engine/ code: ensure each app bundles what it imports without the two
  apps drifting (PyInstaller follows imports; keep one shared source tree).

Status: IN PROGRESS — building Windows packaging for RE Hierarchy Builder.

---

## FW-009 — HUD audit (existing-but-displaced mechanics)

Audit of the pre-existing HUD system, recorded for when HUD work resumes
(notably for the Novel Behavior robots, sim + physical, and any game elements
that would benefit). The HUD was BUILT and proven useful for development, then
displaced — not absent. Recovering it later is revival, not greenfield.

### What exists
- `engine/renderer/hud.py` (~242 lines): a complete, modular behavior HUD.
  - `HUDPanel(panel_w, panel_h).draw(surf, info, fps)` renders one robot's panel.
  - Data contract is clean and game-agnostic:
    - `HUDInfo(behavior, trigger, sensors[], robot_label, robot_color)`
    - `SensorBar(label, value, threshold, value_min, value_max, triggered,
      higher_bad)`
  - Renders: current behavior block (color-coded), per-sensor bars with live
    value, a threshold marker, triggered/!triggered styling, translucent IR
    bars vs solid LDR/contact bars, fps. Color-coordinated by sensor/behavior
    type (IR=pink-red, LDR/LIGHT=pale-yellow, contact/front/rear=cyan,
    cruise=green), panel border = robot_color.
- `engine/renderer/pygame_renderer.py`: integrates it, including a `dual_hud`
  mode (two panels, e.g. robots A and B side by side), `show_hud` toggle, and
  `hud_panel_w` left-sidebar layout (arena offset shifts right when HUD shown).
- `main.py`: CLI flags `--hud` (show overlays, hidden by default) and
  `--hud --ir-only` (IR-only panel with ray visualisation). Per-sensor
  `hud_color` is configurable in robot.json.

### Current usage state
- Reachable via `main.py --hud` (the standalone sim entry), NOT surfaced in the
  in-game VV/RE hubs.
- Originally occupied the upper-left (above narration) and was very useful in
  development. Displaced because:
  - In VV, the AnaBBot physical-meter simulation (`_draw_meters`, M1/M2/M3
    LED-segment meters in games/valentinos/hub.py) took over that role/space.
  - In RE, removed deliberately on pedagogical grounds: an ethologist gets no
    heads-up readout of the creature under study.

### Why keep it in mind
- It's a working, well-factored component with a clean data contract — easy to
  revive or repoint at new data sources.
- Strong candidate for the Novel Behavior robots (sim AND physical) once that
  arc arrives; the per-sensor bar + threshold + triggered model maps directly
  onto live telemetry from a physical robot over BLE (the tablet-HUD idea).
- The `SensorBar` value/threshold/triggered model is exactly what a physical
  robot's BLE DATA characteristic could feed for a live tablet HUD.

Status: AUDITED. Not currently wired into the game hubs by design. Revisit when
HUD value re-emerges (Novel Behavior robots; tablet HUD; any game element that
benefits). No action now.

---

## FW-010 — Web BYOV (BugWorks replacement) — ✅ v1 SHIPPED

### STATUS (shipped)
v1 built and deployed live at https://vassar-irrl.github.io/byov (GitHub Pages,
public repo `byov` in the Vassar-IRRL org; deploy-from-branch main/root). Pure
client-side HTML/JS/Canvas, no backend — students open a link, no install.
Source in this repo at `byov_web/` (sim.js physics + DIRECTIONAL sensors,
vehicle.js body+neurons+wiring, arena.js world+render, editor_view.js the
top-down robot/wiring editor, app.js glue). Design spec at docs/BYOV_WEB_SPEC.md.

v1 delivers: two full-screen modes (Build robot / Arena & run) with a toggle;
rectangular AnaBBot top-down deck with sensors at the front (2 LDR outboard,
2 IR inboard), neurons mid-deck, motors at the rear; drag-to-wire header-to-
header (E/I), neuron bias trimpots; the v1 neuron model (N = clamp(bias +
Σ ±1·signal, 0, 1), bias −1..+1, no wire gains, N-only); DIRECTIONAL sensors
(LDR 70° cone inverse-square×cosine, IR narrow beam) — omnidirectional
forbidden; arena authoring (place/erase lights, grid walls, place+drag-aim
robot); Run/Reset, sensor-cone overlay; record→export JSON + import→replay mode
with scrub (pure playback, saves/restores your work on exit); the 5 Braitenberg
presets (Vehicles 1, 2a, 2b, 3a, 3b — the acceptance test, met); and COLOUR
sensors — LDR channels W/R/G/B (click an LDR to cycle) + coloured lights, with
functional filtering (W sees all; R/G/B see only their own colour). Indicator
colours match the parent app (IR pink, LDR·W/R/G/B per robot_builder.py).

User declared v1 "done" (minor visual details may still be tinkered).

### Possible future polish / stretch (post-v1, not committed)
- Multiple/editable body morphologies (deferred deliberately — "the real
  leverage of multiple morphologies is hard; do it carefully once foundations
  are in place"). v1 is one fixed AnaBBot-faithful body.
- Restore the deferred neuron richness: colour-coded wire gains (blue/green/red
  = 1/2/3), T (threshold) outputs with timing, full bias range (−4..+4).
- Flexible/repositionable sensor placement (v1 has fixed sane front mounts).
- Trail-PNG export alongside JSON; graded-spectral colour response (vs the
  current strict channel match).
- Feed the functional colour-filtering model back to the PARENT app (the parent
  has the channel/colour *structure* but its sim physics is currently
  colour-blind; the web version implemented the behaviour).

### ORIGINAL CONTEXT (retained for reference)
BYOV's simulation is the one tool that most wants to be web-accessible: it
replaces **BugWorks** (C. Thornton, Sussex), a Java/jar Braitenberg-vehicle
simulator with a drag-and-drop UI + a Mission Tutor following Braitenberg's
'Vehicles'. BugWorks is unmaintained and behaviorally inconsistent; crucially
it's a **Java application**, a delivery mechanism the modern web has abandoned —
so the right move is NOT a port but a fresh **pure client-side web build**
(HTML/JS/Canvas), the form these tools have migrated to. No backend needed: a
pure simulation has no hardware to talk to, so it's self-contained client-side
(unlike the builder+BLE tools, which stay native and need local serial access).

The Python BYOV serves as the **reference design / spec**, not portable code.
Its SimpleDriveAdapter (vector-math differential drive, no PyBullet) is the
behavior model to re-express in JS. The VV intro→BYOV pathway incl. the Wiring
Tutorial is READY TO SHIP AS-IS for these purposes (may be tinkered later).

### BugWorks parameters to CAPTURE
1. Range of **body plans** where body SHAPE influences world interaction (any
   object can become a robot body). Maps onto existing morphology work
   (polygon chassis / vertices_m, sensor mount+angle) — body geometry must
   participate in interaction, not be a fixed circle/point.
2. Flexible **sensor & motor placement** on the body, placement affecting
   behavior (already modeled in the morphology spec).
3. **Record-and-replay** so students capture behaviors for LAB WRITE-UPS
   (trail drawing / stats / replay). This serves the real classroom workflow.

### BugWorks features to DROP / SIMPLIFY
- The literal **battery-as-constant-voltage** wiring trick (clever but not
  worth replicating; adds fiddliness).
- Pare down object/stimuli selection for **simplicity** (BugWorks'
  anything-is-anything flexibility is part of why it's confusing).

### The TWO core contributions (the reason to build it vs. reuse an existing sim)
- **Simplified, focused palette** matched to the lab (not a generic sandbox).
- **Environment + robot design that mirrors the PHYSICAL arenas and robots**
  used in the lab — a digital twin of the physical PAW lab, consistent with the
  project's sim↔physical through-line. THIS is the differentiator.

### Open scoping questions before building
- Is BYOV's *design* settled enough to re-encode in JS? (Reimplementing a
  moving target across two codebases is the risk.)
- Web build is a real JS/Canvas project, not a wrap of the PyGame app — bounded
  and dependency-free (pure client-side), but new front-end code.

Status: RESEARCHED / SCOPED. No build started. Pending decision on whether to
proceed and confirmation that BYOV design is stable enough to encode.

---

## FW-011 — Cog reward system (FLAGGED, not started)

Generalize "Cogs" as the earned reward/currency across scoring experiences,
in lieu of more typical stars/points.

- Cogs were introduced in **Field Trip** as point-earning.
- **Name That Vehicle** still uses an OLDER points system that predates Cogs;
  it should be migrated to Cogs for consistency.
- Idea: Cogs as a *generalizable* thing earned by successful experiences —
  potentially across scoring games and possibly tutorials, etc. Likely does NOT
  apply to free-play games (e.g. RE discovery, BYOV sandbox), which aren't
  score-based.

Open questions for when this is picked up: which experiences award Cogs (scored
games yes; tutorials maybe; free-play no?), whether Cogs persist/accumulate
across games (a profile-level currency) or are per-game, and what (if anything)
Cogs unlock. 

Status: FLAGGED for later. Do not act yet. Recorded so the cross-game reward
idea and the NTV points-migration aren't lost.


================================================================================
## FW-012 — Unified control-logic abstraction ("any logic, any game, any target")
================================================================================

NORTH STAR / ARCHITECTURAL DIRECTION. Not to be built yet — deliberately parked
until the canonical RE BLE code and the potential-field code exist, because
those two are concrete instances the abstraction must accommodate, and the
potential-field logic (the most structurally different) is real design input.
Designing the common interface before seeing it would be premature.

### The vision (user's, dev8)
Three linked ideas that resolve to ONE abstraction:
  1. DIGITAL VEHICLE CIRCUITRY — a microcontroller runs the BYOV Braitenberg
     neuron model in *code*, so someone with just a microcontroller (no analog
     circuit board) can build/run physical Braitenberg vehicles. The web BYOV
     sim already IS a digital model of that circuitry; this makes the same model
     executable on real hardware.
  2. GAMES DRAW ON ANY LOGIC — Maze and Novel Behavior (and others) become HOST
     environments that can run whichever control logic is chosen: RE ethology
     hierarchies, BYOV Braitenberg networks, potential-field code, maze logic —
     pluggable, not hardcoded per game.
  3. DOWNLOAD ANY LOGIC TO A MICROCONTROLLER — whatever logic runs in sim can be
     flashed to a physical robot and run in the real world.

### The underlying pattern (the real design question)
All these paradigms are, at bottom, FUNCTIONS FROM SENSOR READINGS TO MOTOR
COMMANDS. If they share a common interface ("given these sensor inputs, produce
these motor outputs"), then: any game can run any logic (idea 2, game just feeds
sensors in / reads motors out); any logic can be simulated OR compiled to
firmware (ideas 1 & 3); the digital Vehicle is just "Braitenberg logic targeting
a microcontroller." A common INTERMEDIATE REPRESENTATION for robot control logic
that sits above the specific paradigms.

### The hard tensions (must be resolved BEFORE building — these decide viability)
- T1 — PARADIGMS DIFFER IN SHAPE. Braitenberg = stateless continuous sensor→
  motor map (instant, no memory). RE hierarchy = prioritized behaviors w/
  subsumption-style arbitration (discrete, some state). Potential field = vector
  field computation. Maze solver = may need real STATE/MEMORY (where have I
  been?). A common interface must be loose enough to hold all (risks doing too
  little) or rich enough to be powerful (risks distorting some paradigms). WHERE
  that line sits is the central question.
- T2 — "DOWNLOAD TO MICROCONTROLLER" spans a huge difficulty range:
    (a) hand-written firmware templates per paradigm, configured + flashed
        (closest to what the RE BLE robot already is);
    (b) a config/DATA format the firmware INTERPRETS — download *parameters*
        (the hierarchy, the wiring) to fixed firmware that knows the paradigm.
        The RE BLE robot arguably already works this way (firmware receives a
        hierarchy over BLE). Often the SWEET SPOT.
    (c) genuine CODE GENERATION — sim emits C++ per logic, compiled + flashed.
        Powerful but a rabbit hole.
  Which one is meant changes everything about the build. Leaning (b).
- T3 — INTERACTS WITH BUILT + PARKED WORK. Web BYOV already implements
  Braitenberg logic as portable JS. RE BLE robot already downloads a hierarchy
  to firmware over BLE (an existence proof of approach (b)). But there is a
  PARKED codegen/firmware-drift bug in this project's history — generating
  firmware from higher-level representations HAS bitten us before. Approach (c)
  steps directly onto that landmine. Consult that history before committing.

### Sequencing (agreed, dev8)
Let this sit as north-star while the RE tuning + potential-field code get
finished. Those teach us what the abstraction must hold. THEN design the common
representation with real examples in hand (RE hierarchy, Braitenberg network,
potential field) rather than in the abstract. Potential-field code will REQUIRE
BLE for the physical robot (same transport the RE robot uses) — so the BLE work
just completed is foundational to this too.

Status: NORTH STAR. Do not build yet. Revisit after potential-field code exists.


================================================================================
## FW-013 — Maze game as the BRIDGE to Novel Behavior
================================================================================

STRATEGIC FRAMING (user, dev8). Not to be built yet — downstream of all three
control logics existing (RE hierarchies ✅ soon-canonical, BYOV Braitenberg ✅,
potential fields = in progress). Maze cannot offer a *choice* among logics until
all three work. Recorded now because the framing shapes every later decision.

### What Maze IS (not just "another game")
Maze is deliberately an INTERMEDIATE STEP between the three constrained
behavior-based paradigms and the wide-open Novel Behavior (NB) game. Its
pedagogical job is partly to establish/prove the GAME MECHANICS that NB will
later depend on. So a good Maze level has a DUAL mandate: be a good puzzle AND
exercise a mechanic NB reuses. Maze earns its place by being the bridge.

### Structure ≈ Field Trip challenge-framing + navigational topology + logic choice
Same skeleton as Field Trip: arena + challenge prompt + player configures a
solution. Difference: Maze's arena has a TOPOLOGY that matters (walls to
navigate; target reachable only by solving the structure). Two prompt modes:
  - SPECIFIED: build a robot with a specified logic to solve the maze / reach a
    target (target is across the maze anyway).
  - OPEN-ENDED: solve using whatever logic you want of the three — maybe a
    COMBINATION thereof (flagged tentative; see dependency below).
Reuse Field Trip's challenge/prompt/arena machinery where possible.

### The tricky insight: the logics are NOT equally suited to mazes — and that's the POINT
- Potential fields: NATURAL fit (attractive target + repulsive walls = canonical
  demo) BUT famous LOCAL-MINIMA trap (dead-ends, concave traps). Bug or teaching
  moment depending on framing.
- Braitenberg/BYOV: wall-following + light-seeking solve SOME topologies
  (simply-connected, wall-followable) but can't plan — only react.
- RE hierarchies: "avoid walls / seek target / escape when stuck" as prioritized
  behaviors = a subsumption approach to mazes (real, historically important) but
  still reactive, not planful.
=> The open-ended "any logic" prompt is only HONEST if the maze is solvable by
   >1 paradigm; different mazes favor different ones; some solvable by only one.
   And NONE of these reactive paradigms can solve a maze requiring MEMORY /
   PLANNING (remember which branches you've tried).

### Why this makes Maze the perfect bridge to NB
The level progression can walk students right up to the boundary of what
REACTIVE control can do — and then past it. The final mazes are ones where no
purely-reactive logic suffices (the memory-requiring maze, the local-min trap).
That discovery is the intellectual setup for NB: the thing the three constrained
paradigms CAN'T do is exactly what NB (with state machines — see NB notes) exists
to enable. The traps aren't failures to design around; they're the payload.
"Reactive control visibly runs out of road" = the emotional/intellectual hook.

### The two questions that actually gate Maze design (settle BEFORE building)
Q1 — WHICH NB MECHANIC(S) is Maze meant to prove out? Candidates: logic-selection
     /swapping UI; the "combine multiple logics" machinery; level-progression /
     challenge-authoring; success-detection (did robot reach target?); state /
     memory primitives. Highest-leverage question — determines what Maze must
     contain.
Q2 — Is "COMBINATION of logics" real or optional? If REAL, it forces FW-012's
     unified sensor→motor abstraction to exist first (can't cleanly combine a
     Braitenberg net with an RE hierarchy unless they share the interface) — so
     Maze couldn't ship before FW-012. If OPTIONAL, Maze ships with single-logic
     selection first, adds combination later. This is a real SEQUENCING
     dependency between FW-013, FW-012, and NB.

### Dependencies
Needs: all three logics working (esp. potential fields, in progress). Relates to
FW-012 (unified abstraction — required IF combination is real) and the NB game
(Maze is its onramp; NB's state machines are what the final mazes motivate).

Status: STRATEGIC FRAMING captured. Do not build yet. Revisit once potential-
field logic exists and Q1/Q2 are answered.


================================================================================
## RE CANONICAL SOURCE — established dev8 (hardware-proven behavior logic)
================================================================================

User delivered the tuned, hardware-proven RE firmware (uploaded as
ethology_standalone.zip) as CANONICAL for RE behavior logic + the base for Field
Trip. This is reading (1): canonical BEHAVIOR logic (same Cog*/EthologyRobot
classes the BLE robot uses), not a consolidation onto standalone. The BLE robot
runs this same behavior code; standalone is the "unrolled, always-on" form.

### What canonical looks like (firmware/ethology_standalone/)
- HIERARCHY (.ino, subsumption top-down, run first whose condition holds):
    1. escape_front   (collisionThreshold -> escapeFrontCollision)
    2. avoid_object   (proximityThreshold -> avoidObject)
    3. seek_light     (lightGradientThreshold -> approachLight)
    4. cruise_straight (default -> cruiseStraight)
- BEHAVIOR API (EthologyRobot.h/.cpp — UNCHANGED by tuning, already vetted):
    sensors: rightProx/leftProx (CogProximity A1/A0), rightLight/leftLight
      (CogLight A3/A2), rightFrontBump/leftFrontBump (CogCollision pins 2/4).
    thresholds: PROX_THRESHOLD 35, LIGHT_THRESHOLD 15, COLL_THRESHOLD 1.
    behaviors call driveProportional(L, R, durationSec), proportions [-100,100].
    lightGradient = rightLight - leftLight; approachLight steers by its sign.
- DRIVETRAIN (CogServo): proportions [-100,100] -> Servo angle [0,180] OR PWM
  microseconds [800..2100] w/ deadband [1350..1550]=>1450. begin(leftPin,
  rightPin). Servo channels on the physical robot = LEFT 6, RIGHT 5.

### The two hardware-ground-truth fixes the user tuned (dev8)
  A. SERVO CHANNELS: LEFT=6, RIGHT=5 (standalone .ino previously had 9/10;
     corrected to 6/5). BLE robot .ino ALREADY had 6/5 — matches.
  B. LEFT-MOTOR INVERSION: CogServo.cpp driveProportional now does
     `leftProportion = -leftProportion;` (was `rightProportion = -rightProportion`
     commented out). The left servo is mounted reversed — a physical fact.

### OPEN ITEM — propagate drivetrain fix to the BLE robot (PENDING USER OK)
CogServo.cpp is meant to be IDENTICAL across ethology_standalone and
ethology_ble_robot (same drivetrain class; earlier session de-triplicated these
Cog copies). The BLE robot's CogServo.cpp still has the OLD inversion (left-flip
NOT applied). Since the left-motor inversion is a hardware fact about the same
physical motors, the BLE robot logically needs it too — BUT propagating a
drivetrain inversion could break a robot that's somehow already correct, so this
is HELD pending explicit user confirmation (user watched the hardware; only they
can verify). Do NOT silently sync until confirmed.

### RESOLVED (dev8) — drivetrain fix propagated to the BLE robot
User confirmed: the servo-channel (5/6) and left-servo-inversion changes reflect
how the servos physically plug into the board and what defines correct forward
motion — so they MUST be identical on any firmware driving the robot. Applied
`leftProportion = -leftProportion;` to firmware/ethology_ble_robot/CogServo.cpp.
Verified: ALL shared class files (CogServo, CogProximity, CogLight, CogCollision,
CogAnaDigi, EthologyRobot, Robot — .h and .cpp) are now BYTE-IDENTICAL between
ethology_standalone and ethology_ble_robot. No drift. Only legitimately-differing
files remain: each robot's own .ino, and the BLE robot's CogBluetooth.*. Servo
channels already matched (both 6/5). RE canonical source is now LOCKED.

Status: RE CANONICAL LOCKED (behavior logic + drivetrain, both robots in sync).
Clear to start potential-field work: edit FROM this proven base toward potential-
field logic, with BLE transport for the physical robot.


================================================================================
## FW-014 — Potential Field: CogPotentialField class + standalone (STARTED dev8)
================================================================================

First functional code toward the potential-field control paradigm (the 3rd
logic, needed by FW-012 abstraction + FW-013 Maze). Built FROM canonical RE Cog
foundation. IR-only push/pull proof, at firmware/potential_field_standalone/.

### What was built
- CogPotentialField.h/.cpp — a GENERAL vector-sum potential-field engine.
  Register sensors, each with: reader (CogProximity), mountAngle (deg CCW from
  +Y, PER-SENSOR), gain, policy (Push/Pull). Each tick: read all sensors, build
  contribution vector per sensor (magnitude = strength*gain; direction =
  mountAngle for Pull, +180 for Push), sum into net (Vx,Vy) body frame, convert
  to differential drive. Steering EMERGES from geometry — nothing special-cased.
  Per-sensor angle chosen (over baked-in splay or L/R-difference) specifically so
  it GENERALIZES to arbitrary position AND angle (octagon edges, LDRs, etc.).
- potential_field_standalone.ino — two forward IRs (A0/A1) as PUSH sources,
  slight outward splay (+/-25deg) set IN THE SKETCH (not the class), BASE_SPEED
  bias so field steers a cruising robot. Servos 6/5.
- Copied canonical Cog deps (CogAnaDigi, CogProximity, CogServo) into the folder
  so it's a complete buildable Arduino sketch.

### Design decisions (settled w/ user, consistent w/ earlier VF design threads)
- PHYSICAL model: each sensor reading IS the field measurement at its mount
  angle; no global map. (From the "how can a physical robot work in this
  paradigm" resolution.)
- POINT-MASS model: sensor POSITION affects behavior implicitly via what it
  reads; engine needs each sensor's ANGLE as contribution direction. Explicit
  position = possible later additive extension, not needed now.
- Push = vector away from mount dir; Pull = toward. IR defaults Push.
- proximityStrength: CogProximity::getData() ~[18..60]cm (smaller=closer)
  inverted+normalized to [0..1] so CLOSER => STRONGER push.
- STAY CANONICAL potential fields (speed AND direction from the field vector;
  superposition of all sources).

### VERIFIED (headless C++ harness, mocked IR readings)
Obstacle on right -> turns LEFT; on left -> turns RIGHT; dead-ahead symmetric ->
backs straight up (correct — and a mild local minimum, the pedagogically
meaningful VF trait); clear -> cruises straight on base speed. Turn strength
scales with closeness + asymmetry. Push mechanic proven.

### NEXT (not done)
- Hardware test on the physical robot (user) — tune gains/splay/base speed.
- Add LDR (CogLight) as PULL sources -> attraction; then push+pull together.
- Eventually a BLE version (potential_field_ble_robot) — VF needs BLE for the
  physical robot per the plan; mirror the ethology_ble_robot pattern.
- This class is a prime input to FW-012 (unified sensor->motor abstraction): a
  potential-field logic is fundamentally a vector-sum from readings, quite unlike
  RE subsumption or Braitenberg — exactly the 3rd example that stress-tests the
  abstraction.

### LDR PUSH/PULL INTEGRATED (dev8)
User bench-tested IR push/pull: behaviors "don't do much at a distance but do
materialize" — enough to add LDR light push/pull. DONE. Extended
CogPotentialField to handle TWO sensor kinds via a tagged Source struct
(SrcType::IR|LDR, holding CogProximity* or CogLight*). Added addLight(CogLight*,
mountAngle, gain, policy) + lightStrength() (CogLight::getData()[0..100] ->
[0..1], brighter=stronger). computeNetVector dispatches on type. Chose the
minimal tagged-struct approach over a common sensor interface (that's FW-012,
deliberately deferred). Demo now: 2 IRs PUSH (avoid obstacles, A0/A1, +/-25deg)
+ 2 LDRs PULL (seek light, A2/A3, splayed +/-40deg) — flip LDR policy to Push to
flee light. CogLight copied into the sketch folder. VERIFIED IN SIM: LDR Pull
SEEKS (closest 20 from 198), LDR Push FLEES (never <115, runs to 2600+). Engine
compiles. Bench test + gain tuning = next.

### PROCESSOR DIRECTION (noted, not chased — dev8)
User wants a MORE POWERFUL processor than the R3 for this robot set (the ColorPAL
SoftwareSerial pain is one driver). Candidates floated: ESP32 (some variant), or
even a Nano — must be Arduino-IDE compliant. Explicitly "not the thing to chase
for now." Recorded so it's not lost; revisit when the ColorPAL / multi-sensor /
compute needs make it worth it. (Note: a hardware-UART board also sidesteps the
ColorPAL SoftwareSerial issues from FW-015/016.)


================================================================================
## FW-015 — CogVisLight: ColorPAL ambient + colour-channel sensor (PROTOTYPE)
================================================================================

Prototype colour-aware light sensor, richer than CogLight. Wraps a Parallax
ColorPAL (#28380), which reports BROAD-SPECTRUM AMBIENT light AND per-channel
RGB colour. Intended as the colour-aware light source for potential-field PULL
(colour-tuned attractors) and to mirror the BYOV W/R/G/B colour model on real
hardware. At firmware/colorpal_vislight_demo/ (own sketch folder — a 2nd .ino
can't share a folder). Files: CogVisLight.h, CogVisLight.cpp, demo .ino.

### ColorPAL protocol (from #28380 datasheet — researched, authoritative)
- ONE SIG wire, open-drain, non-inverted serial, 2400-7200 baud (using 4800).
  Sensor has its own pull-up; pin INPUT except when driven LOW. Needs 5V (LEDs).
- SoftwareSerial with RX==TX on the one SIG pin (single-wire).
- Everything TX'd is ECHOED back and must be discarded.
- Reset->Direct: LOW, INPUT, wait-high, LOW 50ms, INPUT, wait 10ms.
- 'm' macro: ambient measure, then R/G/B each (ambient subtracted) -> three
  3-hex-digit values = ambient-corrected R,G,B. (This IS the colour read.)
- "X s": X=LED off, s=sample -> one 3-hex-digit AMBIENT (broad-spectrum) value.
- 10-bit ADC => raw values ~[0..1023].

### API
- begin() (reset + start serial; false if line never released = not connected)
- readColor() -> fills r()/g()/b()   [ambient-corrected RGB]
- readAmbient()/ambient()            [LEDs-off broad-spectrum light]
- getData(channel): 'W'->ambient, 'R'/'G'/'B'->that colour (CogLight-style scalar)

### VERIFIED (headless) vs NOT
VERIFIED: compiles clean vs mocked Arduino/SoftwareSerial; hex-3 parse logic
unit-tested (upper/lowercase, space-skipping, multi-value 'm' reply). NOT yet
verified on hardware — the serial TIMING (echo-drain windows, per-command reset,
read timeouts) is from the datasheet + reference sketches but untested on a real
ColorPAL. Expect timing tuning on the bench.

### NEXT
- Bench bring-up: flash colorpal_vislight_demo.ino, watch AMB + R/G/B on Serial.
- Tune timing if reads are flaky (echo-drain ms, reset pauses, 4800 vs 7200 baud).
- Then integrate as a PULL source in CogPotentialField (colour-tuned light
  attractor) — the colour-aware analogue of using CogLight for attraction.
- Prototype status: blocking reads, per-call reset, no EEPROM-autorun streaming
  (a "= (00 $ m) #00" continuous-stream mode is a later optimisation).

### HARDWARE NOTE (dev8) — UNO R4 + SoftwareSerial
User compiles for Arduino UNO R4 WiFi (Renesas RA4M1, ARM Cortex-M4 — NOT AVR).
- FIXED: removed `_serial.listen()` (AVR-only; the R4 SoftwareSerial has no such
  method; unneeded with a single soft-serial instance anyway). Compiles now.
- BIGGER RISK: R4 SoftwareSerial is a newer, less-proven implementation and is
  known-flaky for demanding timing like the ColorPAL's single-wire open-drain
  4800-7200 baud protocol. May give garbage/no reads at RUNTIME even though it
  compiles. Reference ColorPAL sketches all use classic AVR SoftwareSerial.
- OPTIONS: (A) try on R4 as-is; (B) BETTER for R4 — use a HARDWARE UART (Serial1
  on the R4) instead of SoftwareSerial; ColorPAL is 1-wire but the canonical
  Phil-Pilgrim circuit ties TX+RX together via a resistor to the SIG line, so
  HW-serial works with a small wiring change; (C) test on a classic AVR UNO where
  SoftwareSerial is proven with this sensor. Recommend A first, fall back to B
  (build a Serial1 variant of CogVisLight) if reads are flaky.

### PROTOCOL REWRITE (dev8) — matched to the PROVEN reference driver
Board question RESOLVED: user tested a classic UNO R3. The Parallax REFERENCE
sketch WORKS on R3; the R4 does NOT drive this single-wire protocol (R4
SoftwareSerial unreliable). So: use a classic AVR board (UNO R3 / Mega 2560).
For MULTIPLE ColorPALs later: Mega 2560 (4 hardware UARTs, one sensor each at
4800), or ColorPAL addressing on a shared line; single-UART boards can only
listen to one soft-serial port at a time.

My first CogVisLight FAILED on R3 (printed "read failed") because its protocol
diverged from the working reference. Root causes (NOT .listen()): (1) sent a
single "= m !" instead of the LOOPING, '$'-delimited "=(00 $ m)!"; (2) used one
RX==TX SoftwareSerial instead of the reference's TWO objects (serout TX-only,
serin RX-only, unused=255) with serout.end() + pin flip to INPUT between TX and
RX; (3) didn't SYNC on '$' before reading. REWROTE CogVisLight.cpp to mirror the
proven driver exactly: dual SoftwareSerial, looping program, '$'-sync, read 3x
3-hex. Color streams "=(00 $ m)!"; ambient streams "=(00 $ X s)!". Compiles
clean. Mode tracked via _mode member (switching color<->ambient re-programs the
sensor, ~0.5s reset — so rapid alternation is slow BY DEVICE NATURE; demo reads
color continuously, samples ambient only every 5s).

KNOWN device quirks to expect on the bench (from Parallax forums): ColorPAL is
finicky — may need reset-delay tuning (50/80/100ms) and can "blink blue then go
silent" until timing is right. If it stays uncooperative, a TCS3200-based sensor
is the common modern alternative (would need a different class). 7200 is the
device's ideal baud but AVR SoftwareSerial can't hit it reliably; 4800 is safe.

### HANG FIX (dev8) — "intro prints then nothing"
Symptom: setup() printed the intro line then froze (never reached loop output,
not even the "read failed" line). Cause: begin() did a PRELIMINARY wait-for-HIGH
before calling resetPAL() — the reference does NOT; it goes straight into reset.
That extra wait consumed/disturbed the line state so resetPAL()'s (originally
UNBOUNDED) `while(digitalRead!=HIGH)` never saw the release and hung forever.
Fix: (1) begin() now goes straight to programStream()/resetPAL() like the
reference — no preliminary wait; (2) resetPAL()'s while now has a 1000ms timeout
(insurance so a flaky sensor can never freeze the sketch). All three while-loops
in the class are now bounded. Reset delays kept at the reference's proven
200/80/200 ms (user had tried 10ms; recommend confirming with proven values
first, then experiment).

### REBUILT ON THE REFERENCE (dev8) — after from-scratch driver gave only garbage
All three bauds (4800/7200/9600) gave GARBAGE from the scratch-built driver even
though the raw stream showed bytes arriving (so wiring/reset/handoff were fine).
Could not reconcile why the reference decodes clean at 4800 but the from-scratch
version didn't, despite line-identical begin/reset/read. DECISION (user): stop
chasing it — WRAP THE PROVEN REFERENCE in class form instead, add the two wanted
features. CogVisLight.h/.cpp rewritten to mirror the reference protocol
faithfully (dual SoftwareSerial serin/serout unused=255, reset, "=(00 $ m)!"
loop, read '$' then 9 hex via sscanf %3x%3x%3x, 4800 baud) and ADD:
  * colorName(): red/green/blue/yellow/cyan/magenta/white/dark (from RGB balance)
  * lightLevel(): dark/dim/lit/bright + ambient() brightness proxy (R+G+B sum)
Ambient is DERIVED from the RGB sum (the 'm' macro already ambient-corrects the
channels; a separate LEDs-off ambient mode proved flaky, so brightness-proxy is
the honest simple choice). Qualitative logic unit-tested (all primaries/
secondaries/white/dark correct). Class compiles clean.

IMPORTANT for the bench: demo defaults to SIG_PIN=6 and 4800 baud to MATCH the
reference exactly (the reference used pin 6). Set SIG_PIN to your actual wiring.
RAW_DIAGNOSTIC flag still available. Since this mirrors the working reference, it
should decode where the scratch version didn't.

Status: REBUILT on proven reference + qualitative color/light added; compiles &
unit-tested. Color reads work on hardware (close range).

### HARDWARE FINDINGS (dev8, on UNO R3)
- COLOR works but only at CLOSE range (ColorPAL is REFLECTIVE — fires its own
  LEDs, reads bounce-back; not a distance/color-light sensor). Confirmed it
  CANNOT do BYOV-style distance colored-light seeking. So: CogVisLight = close-
  range SURFACE colour sensor (floor markers, objects) — useful later for
  Maze/NB, not for potential-field push/pull.
- AMBIENT via RGB-sum was misleading (reflective). BUT the LEDs-OFF sample
  ("X s") DOES read INCIDENT light with a "pretty decent gradient" (user bench
  test), AND is DIRECTIONAL (values rise aimed at a light, fall aimed away —
  user rotated it at fixed distance and confirmed). So the ColorPAL CAN do crude
  light-seeking via aiming. Added beginLightMode()/readLight() (LEDs-off stream)
  in the colorpal_light_test + colorpal_seek_light copies of CogVisLight.

### FW-016 — ColorPAL single-sensor light-seek demo (dev8)
firmware/colorpal_seek_light/ — self-contained: one ColorPAL (LEDs-off,
directional) + canonical CogServo (6/5).
FINAL ALGORITHM (user's concept; tadpole-INSPIRED but a normal 2-wheel prop-
drive robot): sensor mounted LEFT, aimed OUT-left. Each cycle delta = current -
previous light; steer by sign+magnitude on top of constant forward drive:
  left = BASE - GAIN*delta ; right = BASE + GAIN*delta
brighter => right faster => turn LEFT (toward the left sensor's light); dimmer
=> turn RIGHT. Always rolls forward ("always swimming"); NO deadband (pure
response, twitches and all). Main knob = GAIN.
(Earlier cast-and-step version was replaced — user wanted the continuous delta-
steering law, not stop-sweep-aim-step.)
SIM: convergence is PARAMETER- and ORIENTATION-sensitive (seeks from some starts,
orbits/weak from others) — inherent to a single-sensor temporal-gradient seeker
(steers on a derivative, tends to ORBIT the light; orbit can be stable-around or
drift-off depending on gain/heading). Sim fidelity to the real sensor's
directionality is itself uncertain, so treat sim as "can seek, needs tuning"
not as a verdict. Compiles. Bench test + tune GAIN/BASE on hardware = next.
NOTE: single sensor hunts, doesn't beeline. Two-sensor directional version
(instant steer toward brighter side, Braitenberg 2a/2b) is the natural follow-on
(needs 2nd ColorPAL or LDRs).

Companion sketch folders: colorpal_vislight_demo (colour + qualitative words),
colorpal_light_test (LEDs-off incident-light bench test), colorpal_seek_light
(this demo).

### OCCLUDED-GOAL DIAGNOSIS COMPLETE (dev10) — model lacks edge-spill gradient
Context: sim-validation toolchain (tools/pf_sim_replay.py = Mode A, math validated;
tools/pf_sim_predict.py = Mode B, predictive + visual, sensor models CALIBRATED to
hardware incl. the non-monotonic LDR ridge, plus collision-stop and binary light
occlusion). Predict-then-confirm against the hand-run trajectory (torch on tower's
FAR face, light fully OCCLUDED, robot 50cm from near face, DIRECTLY opposite light;
real robot hugged near-left edge, ARCED AROUND, drove UNDER the light).

Diagnosis run to closure (each step TESTED, not guessed):
 1. IR cone width does NOT fix it — swept +-12/30/50/70 deg, all stuck at near
    face. A perfectly SYMMETRIC dead-center approach makes both IRs fire
    identically => lateral push cancels to 0 regardless of cone width. (Falsifies
    the earlier 'IR cone too narrow' hypothesis.)
 2. Small ASYMMETRY (dx=1cm off center) DOES break the deadlock — robot rounds the
    near edge (IR_L->18, Vx->+0.97). So real hardware's inevitable imperfection is
    the symmetry-breaker; the idealized sim balances on the knife-edge and drives
    straight in.
 3. Once around the edge with OCCLUSION_LEAK=0.15, LDRs read ~ambient (34) => no
    light signal => robot sails past into empty space (maxY 0.52).
 4. Raising OCCLUSION_LEAK (0.35-0.75) gives a signal, but it points STRAIGHT
    THROUGH the tower => LDR pull (toward light) and IR push (off wall) are
    ANTI-PARALLEL => cancel => robot pinned against the near face (0.48,0.54),
    never rounds.

ROOT CAUSE (genuine model-structure gap, not a tuning miss): the model has NO
TANGENTIAL cue to round an obstacle toward an occluded goal. Binary occlusion
attenuates the STRAIGHT-LINE light value; it does not model light SPILLING /
DIFFRACTING around the tower EDGE, which in reality creates a gradient strongest
NEAR THE EDGE — the exact tangential cue that pulls a real robot around the corner
until the goal comes into view. That edge-gradient is why the real robot arced
around and the idealized sim cannot.

CANDIDATE FIX (future, fit against data; NOT built): model each obstacle EDGE as a
secondary/virtual light source (or compute a light field with edge diffraction) so
occluded goals still present a roundable gradient. Also still open: OFF-AXIS IR
calibration sweep (we only have head-on IR distance data) to pin the true cone.

PEDAGOGICAL PAYLOAD (ties to FW-013 Maze/flow-around): this IS 'goal hidden behind
obstacle, reactive control must round it.' The sim's inability to round it WITHOUT
an edge cue mirrors exactly WHY pure reactive potential-field control 'runs out of
road' and motivates Novel Behavior. The hand-run hardware trajectory (arced around
to the occluded light) is a ready-made teaching example of the reactive-control
limit and what overcomes it.

STATUS: predict-then-confirm instrument VALIDATED as a scientific tool — it
reproduces qualitative behavior for IN-VIEW lights and, crucially, FALSIFIED the
model in a specific localized way for OCCLUDED goals (no edge-spill gradient).
Calibration transferred well on the IR side; LDR ridge modeled; the remaining gap
is a known, named model-structure limitation, not an unknown. Good place to either
add the edge-gradient model OR bank the instrument and return to FW-012/FW-013/game.


### OCCLUDED-GOAL: MORPHOLOGY + DYNAMICS EXPERIMENTS (dev10) — honest status
User reframed correctly: don't tune the model, EXPERIMENT WITH MORPHOLOGY (which is
what the game is about). Also clarified the real robot HUGGED + bumped along the
tower under VALID control (not physics-accident nudging).
Tried, holding model fixed:
 - EDGE-SPILL light model (obstacle corners as secondary emitters when direct light
   occluded). VERIFIED it produces the right ASYMMETRIC gradient statically: an
   off-center robot near the left corner gets LDR_L > LDR_R by +4..+16 -> a real
   tangential cue toward the edge. So the light-cue physics are SOUND.
 - IR MORPHOLOGY sweep (90/75/60/45/30 deg). None reproduced arc-around.
 - SLIDE-ALONG collision (project motion onto wall tangent = hug/bump, replacing
   stop-dead). In pf_sim_predict_slide.py. Did NOT fix it either.
COMMON FAILURE across all: on first IR contact the robot ROTATES ~70 deg in a couple
ticks (heading -> 286) and DRIVES AWAY in a straight line to infinity (once turned
away: IRs=60, LDRs=33 occluded, V=0 -> coasts on base speed forever, never returns).
DIAGNOSIS (tension surfaced, not resolved): the ~70deg snap-pivot comes from
vectorToDifferential turning a large Vx (one +-90 IR at close range -> strength~1 ->
turn=tGain*100 clamped = max-rate pivot). But that math is FIRMWARE-VALIDATED (Mode
A) and the differential-drive kinematics are faithful. So a faithful sim SHOULD
over-rotate -- meaning the gap is elsewhere: likely (a) real firmware wheel response
is smoother/slew-limited vs sim's instantaneous wheel swing, (b) real robot pivots
hard but geometry differs, or (c) the real run's setup differs from the modeled
scenario. NOT yet resolved. Did NOT hand-tune to force a match (would break
predictive value).
KEY OPEN QUESTION for next session: does the real robot's wheel command change
GRADUALLY (firmware smoothing) where the sim applies it instantly? If so, that single
faithfulness fix (slew-limit the wheel commands to match firmware) may explain why
real=hug and sim=flee across ALL morphologies. Worth checking the firmware for any
ramp/smoothing on the motor outputs before more sim changes.
### FIELD TRIP ALIGNED TO HARDWARE PUSH/PULL MODEL (dev10)
Returned to Field Trip and aligned it to three design decisions (user):
 1. PUSH/PULL controls only — RobotBuilder gets radial_only=True; the flow-style
    picker shows just Seek(Pull)/Flee(Push) with header "Push / Pull (tap)".
    Tangential (Orbit, Flow-around) hidden but retained in engine for saved robots
    & the advanced challenges; not deleted.
 2. SENSOR-VECTOR ("puppeteer stick") forces — REWROTE compute_force: each sensor
    contributes ONE vector along ITS OWN MOUNT AIM (world = heading+mount_angle),
    magnitude = its reading, Pull=+1 along aim, Push=-1 opposite. Per-SENSOR now,
    not per-(sensor×source). This fixes the earlier WRONG robot->source bearing
    model (which used knowledge the real robot doesn't have). Matches hardware
    computeNetVector; solutions now transfer to the physical robot.
 3. WALLS AS SOURCE OBJECTS — IR sensors read arena walls/boundary DIRECTLY from
    geometry (ir_reading), independent of the sources list. Removed the dependency
    on a wall-type FieldSource being present. This makes geometry-only challenges
    (e.g. C3 "Touch the Wall") work with an IR sensor.
STEERING: replaced the game's turn-toward-resultant force_to_motors with the
HARDWARE-VALIDATED vectorToDifferential mapping — rotate world force into body
frame (Vy fwd, Vx lateral), forward=base+fGain*Vy, turn=tGain*Vx, left=fwd+turn,
right=fwd-turn. The BASE-SPEED forward bias is the key fix: the robot always creeps
forward, so it never freezes. This resolved the stall where the sensor-aim model +
turn-toward-resultant spun the robot until sensors faced away from sources and
froze (traced live on C6: heading swung 90->177 in 0.5s, force->0, stuck).
VERIFICATION (headless _Sim, shipped solutions): C03 SUCCESS, C06 SUCCESS, C07
SUCCESS. C04/C05 not passing (need per-challenge review — may assume old model or
need tuning); C07/C10 were designed around TANGENTIAL flow-around (deprioritized),
C10 times out. Core Push/Pull mechanics VALIDATED and the stall is gone.
STILL OPEN: review C04 (timeout) + C05 (fails 'too close to red' — a repulsor
challenge, may need push tuning); decide whether C07/C10 get Push/Pull-solvable
redesigns or wait for tangential to return; build a proper headless solution
verifier as a permanent test. Then playtest.

### FIELD TRIP PLAYTEST FIXES + THE TANGENTIAL-CHALLENGE PROBLEM (dev10)
User playtested the Push/Pull build. Findings + fixes:
 - BLANK SCREEN after intro was NOT a crash: the c0 intro dialogue finishes but the
   transition to the first challenge only fired on a click INSIDE the narration box;
   a click on the empty canvas did nothing => looked frozen. FIXED: (a) once the
   intro dialogue is_done, a click ANYWHERE advances to build; (b) the canvas now
   shows "Click anywhere to begin >" instead of blank (and "(read on, then click to
   continue)" while still typing). Robot built + ran + played well once past it.
 - ORBIT CHALLENGE c03 "Circle the Light": unsolvable with Push/Pull (orbit is a
   TANGENTIAL behavior; no sum of radial forces circulates). Per user: DEFERRED —
   removed C3 from ALL_CHALLENGES (definition kept for when tangential returns).
   Sequence now C1,C2,C4,...

BIGGER ISSUE SURFACED (flagged, NOT yet resolved — needs user design decision):
 9 of the 14 remaining active challenges reference tangential/flow-around in their
 hint/solution: c04 Around the Obstacle, c05 Around and Guard, c07 Light and Wall,
 c10 Slalom, c11 Red Herring, c12 Blue Interference, c13 Choose Your Path, c14 Wall
 Magnet, c15 Gauntlet. So deferring only c03 leaves the player hitting c04 (same
 wall) right after C1/C2. The cleanly Push/Pull-solvable set is ~C1,C2,C6,C8,C9.
 CAVEAT: "hint mentions tangential" != "unsolvable with Push/Pull" — some may be
 solvable with clever radial forces and just need reworded hints (C07 passed in an
 earlier headless test). Needs PER-CHALLENGE triage: (a) defer, (b) redesign goal
 for Push/Pull, or (c) confirm already-solvable + reword. This is the shape of the
 whole Push/Pull game and is a USER design call — do not blanket-sweep.
 Pedagogical note: the flow-around cluster is exactly the "reactive Push/Pull runs
 out of road" boundary — a natural home for the bridge to tangential / Novel
 Behavior once that control layer is hardware-ready.

### c04 REFRAMED AS TEACHING WALL + solvability TRIAGE (dev10)
Per user: keep the flow-around challenge but reframe it as the explicit "Push/Pull
runs out of road" teaching moment.
BUILT:
 - Added Challenge.teaching_wall flag. Set on c04 "Around the Obstacle".
 - Rewrote c04 narration: intro invites a genuine try; retry EXPLAINS the limit
   (Push=straight away, Pull=straight toward; when the wall is dead between robot
   and light the two forces fight in a line and CANCEL; rounding needs a SIDEWAYS
   force Push/Pull can't make — a new kind of motion, coming next).
 - RELEASE VALVE: result screen shows "Move on ->" for a teaching_wall challenge
   after >=1 attempt, so the player is never hard-stuck (Next was win-only before).
 - Suppressed "Show Solution" for teaching walls (solution_file cleared — the
   solution would need Flow-around, which isn't available in Push/Pull mode).
 - Verified: c04 fails as intended, Move-on appears, advances.

SOLVABILITY TRIAGE (empirical — sampled Push/Pull configs through headless _Sim;
"YES"=a sample solved it, "no"=samples didn't => likely-hard, NOT a proof):
 SOLVABLE: c01,c02,c05,c06,c07,c08,c09,c12  (several MENTION flow-around in hints
   but are solvable with radial forces — hints just need rewording).
 NOT (sampled): c04(=teaching wall), c10 Slalom, c11 Red Herring, c13 Choose Your
   Path, c14 Wall Magnet, c15 Gauntlet.
 => Correcting an earlier WRONG assumption ("mentions tangential"=="unsolvable").
   Real picture: one teaching wall (c04) + a hard cluster at the END (c10,c11,
   c13-c15). c12 solvable sits oddly among them.

STILL OPEN (user design calls, not swept unilaterally):
 - Reword hints for the solvable-but-flow-around-worded ones (c05,c07 etc.) so they
   don't tell the player to use a hidden Flow-around style.
 - Decide the end cluster (c10,c11,c13-c15): defer like the orbit challenge, mark as
   more teaching walls, or redesign for Push/Pull. Natural arc = C1..C9 (minus c04
   teaching wall) as the playable Push/Pull unit, c04 as its concept-boundary
   climax, end cluster deferred until tangential returns.
 - Re-verify "solvable" ones are solvable by a PLAYER (sampled != easily findable).

### c04 WIDER GAPS + RELAXED CONSTRAINT + SENSOR-UPGRADE ATTEMPT (dev10)
Per user (who got the robot INTO the gap on a real screenshot; disproved "impossible"):
 - WIDER GAPS: narrowed c04 inner wall from ±0.12 to ±0.08 (each end gap 18cm->22cm)
   to reflect the open tabletop. Gap is 22cm vs 9.4cm robot = passable with room.
 - RELAXED CONSTRAINT (user's rule: touching a wall is fine; being STUCK in one
   spot for a couple seconds is the real failure): walls are now EXEMPT from the
   repulsor-contact fail; added a STUCK-IN-PLACE check (fail if within
   STUCK_RADIUS_M=0.03 for STUCK_FAIL_S=4.0s, only when the arena has walls, and
   never while at a legitimate goal). Original light-avoidance contact rule KEPT for
   non-wall avoid targets (e.g. C5/C6 forbidden lights).
   TUNING NOTE: first tried 0.05m/2.5s — too twitchy, regressed C05/C07 (punished
   legit slow maneuvering). 0.03m/4.0s fires only on genuine dead-stops. Verified.
 - SENSOR UPGRADE ATTEMPT (calibrated LDR directionality, floor 0.2 + cos^4):
   TRIED then REVERTED. Applying the bench-calibrated SHARPER directional cone
   globally REGRESSED the game (C6 timed out — narrower cone loses the light during
   maneuvering). The calibration geometry (elevated torch, out-of-plane) differs
   from the in-plane game arenas, and challenges are balanced around the gentler
   cosine. Calibration stays ground-truth for the VALIDATION TOOL (its purpose); the
   game keeps its tuned cosine. HONEST: not a drop-in upgrade.
REGRESSION STATUS (final): C03 OK, C06 OK, C07 OK. C04 + C10 fail "Stuck against
the wall" (the genuine flow-around traps). C05 fails "too close to light_red" — a
PRE-EXISTING issue in its shipped solution (fails identically with all my changes
reverted), needs separate review.
NET on c04: it is still a hard flow-around trap in idealized symmetric physics
(centered robot vs centered obstacle, light behind = no symmetry-break). Wider gaps
+ relaxed constraint make it FAIRER and fail HONESTLY, but do not make it trivially
Push/Pull-solvable — consistent with the whole sim-vs-hardware finding.

### BUILDER SENSOR/MOTOR LEFT-RIGHT FLIP BUG — FIXED (dev10)
Symptom (user): place an IR on the RIGHT, relaunch the robot builder, it's on the
LEFT. Root cause: a save/load SIGN MISMATCH in robot_builder.py. _export_sensor
saves y_m = -canvas_x (lateral is LEFT-positive by convention; canvas x is
right-positive). But the LOAD path read canvas_x = y_m WITHOUT re-negating, so every
round-trip mirrored x: right->left. Motors had the identical bug (save negates, load
didn't). FIX: load now negates y_m back into canvas x for both sensors and motors,
undoing the export negation. Verified: sensor placed at canvas x=+0.05 exports
y_m=-0.05 and reloads to canvas x=+0.05 (right stays right); motor same. This was a
PRE-EXISTING bug (convention baked in), not from recent work. Export convention
unchanged, so robots saved before/after both round-trip correctly now.

### C4 WALL-PASSTHROUGH FIX + GAP-TIGHTENING FINDING (dev10)
User: robot could pass "over" the wall at the edge; C4 succeeds with LDR-pull alone,
IR-push makes it richer but isn't needed; wanted a TIGHTER gap to make it more
interesting (else move on). Chose: fix pass-over AND tighten.
 - PASS-OVER BUG FIXED: hub _blocked() used block_d = BODY_RADIUS-0.004 = 0.043m,
   ignoring wall THICKNESS (0.025). True solid boundary is BODY_RADIUS+half_t =
   0.0595m, so there was a ~1.5cm skin where the body overlapped the wall but wasn't
   stopped — worst near the ends/faces, letting the robot slip OVER. FIX: block_d =
   BODY_RADIUS + wall_half_thickness - 0.004 (per-wall, reads each wall's thickness).
   Also updated check_reach_wall (field_physics) to dist <= body_radius+half_t so
   'reach the wall' still registers at the (correct) surface. Verified: overlap-
   unblocked points dropped from many -> ~1; C3 reach still OK; C4 still solvable
   (LDR-only OK, LDR+IR OK) and now genuinely goes AROUND, not over.
 - GAP-TIGHTENING FINDING (tested, not guessed): tightening the gap does NOT work
   while keeping Push/Pull solvable. Swept wall left-end x0 from +0.06 down through
   0.0 to -0.093. ONLY x0=+0.06 (current) solves; x0<=+0.04 all FAIL 'stuck', even
   though the corridor is still >20cm (wider than the 9.4cm robot!). Reason: the
   binding constraint is NOT corridor width — it's the wall END intruding on the
   straight-line path from robot (x=0) to the centered light. As soon as the wall
   reaches toward center, radial light-seek drives INTO it instead of around, and
   past center it's the full go-around/symmetry problem again. So +0.06 is the
   SWEET SPOT — the tightest solvable position. Per user's 'else move on': tightening
   isn't available without breaking solvability => MOVE ON. C4 is done: solid wall,
   solvable with LDR-pull, richer with IR-push, cannot be cheesed.

### FIELD TRIP SCRIPT-EDITING METHOD + SCRIPT-INDEX BUG FIXED (dev10)
User asked to recall the method for editing arenas/challenges via SCRIPTS.
METHOD: per-challenge plain-text files in games/field_trip/scripts/field_trip/,
named ft_c<N>.txt. Format: @slot headers (@intro, @build_hint, @on_run, @success,
@retry) with PAW-BOT: lines under each. Markup: <Term>(n) = highlighted term +
glossary footnote; *term*(n) = highlight only. Footnotes defined in ft_glossary.txt.
The hub reads these .txt files LIVE (engine.professor.load_script) — they are the
source of narration the player sees.
BUG FOUND + FIXED (introduced by deferring c03): _load_narration mapped
script_name = f"ft_c{idx+1}" using SEQUENCE POSITION. After c03 was removed from
ALL_CHALLENGES, every challenge from position 2 on loaded the PREVIOUS challenge's
script (off by one) — e.g. "Around the Obstacle" (c04) was showing the orbit
"Circle the Light" (ft_c3) narration. FIX: map by the challenge's OWN id
(c04 -> ft_c4) via the numeric part of challenge.id. Verified across all 14 active
challenges.
IMPORTANT CONSEQUENCE: the game reads the .TXT files, NOT the in-code
narration={...} dicts in challenges.py. So the c04 teaching-wall reframe written
into challenges.py earlier was NEVER displayed — ft_c4.txt (old "Flow-around the
wall" text) is what actually plays. To reframe c04 (now that it's SOLVABLE with
Push/Pull, the teaching-wall framing may no longer even be wanted), edit ft_c4.txt.
SCRIPTS STATUS: exist = ft_c1, ft_c2, ft_c4 (+ ft_c0, ft_welcome, ft_glossary,
ft_tut_complete). MISSING (challenges show no narration): ft_c5..ft_c15. ft_c3
(orbit) exists but its challenge is deferred.

### CHALLENGE-EDITING WORKFLOW HARDENED (dev10)
Answering "how do I edit arenas/challenges" (vs scripts): challenges/arenas are
defined IN PYTHON in engine/field_trip/challenges.py — each is a Challenge(...) block
with arena=_arena(lights=[_arena_light(...)], walls=[_arena_wall(...)]),
required_reach/avoid (by source id), dwell_zone, duration_s, hint, etc. Add a new
challenge by defining CN = Challenge(...) and adding it to ALL_CHALLENGES (which sets
sequence + order). No JSON/data file or live editor for challenges (unlike the .txt
scripts, and unlike the standalone tools/arena_builder.py which serves the OTHER
robosim project).
TWO CLEANUPS (user-approved) to de-risk editing:
 1. SINGLE SOURCE OF TRUTH (safety-check variant): lights/walls were written TWICE
    (arena=... AND sources=...) and could silently drift (nearly happened moving the
    C4 wall). Added _sources_from_arena() + Challenge.__post_init__ that either
    AUTO-DERIVES sources from the arena when sources= is omitted, or VALIDATES an
    explicit sources= against the arena geometry and raises a clear OUT-OF-SYNC error
    naming the mismatch. _arena_light/_arena_wall now take optional sid=. Verified:
    all 14 load in-sync; a deliberately-moved wall fails loudly.
 2. Removed the 4 DEAD narration={...} dicts (c01-c04) from challenges.py — the game
    reads the .txt scripts (ft_c<N>.txt), so those dicts were never displayed and
    were misleading. narration field defaults None. Regression unchanged
    (C03/04/06/07 OK; C05 pre-existing 'too close to light_red').
NOTE for future: to reframe c04 narration (now that it's Push/Pull-SOLVABLE, the
teaching-wall framing may be unwanted), edit ft_c4.txt — NOT the code.

### KEY FINDING — EMERGENT CIRCULATION FROM PUSH/PULL (dev10) [CORRECTS EARLIER CLAIM]
USER DISCOVERED (by playing C5): asymmetric Push/Pull sensor configs produce real,
SUSTAINED orbit / flow-around motion — circulation EMERGES from morphology, with no
explicit tangential term. Verified in sim: an asymmetric config (LDR flee-red at
+15..60° offset + IR seek-wall at -15..-60° offset, sensors offset in POSITION too)
traced -986° (2.74 revolutions) of continuous rotation around the target.

=> This CORRECTS a claim I made repeatedly this session ("no combination of radial
Push/Pull can produce circulation / flow-around; it's structurally impossible").
That claim was WRONG as stated. The correct, narrower statement:
  - A SINGLE radial sensor cannot circulate (Pull=straight toward, Push=straight
    away). TRUE.
  - SYMMETRIC configs tend to stall on the centerline (the occluded-goal/centered-
    wall traps). TRUE — and that's what the earlier tests kept hitting.
  - But an ASYMMETRIC MULTI-SENSOR config (sensors offset in position AND mount
    angle) yields a resultant force that ROTATES as the robot turns; that feedback
    loop produces sustained orbit/flow-around. The circulation is EMERGENT from the
    sensor arrangement, not built into any one sensor.
PEDAGOGICAL UPSHOT (richer than the old framing): flow-around/orbit is not a separate
"mode" you must switch on via the tangential term — it can EMERGE from how you arrange
simple radial Push/Pull sensors. Morphology (placement + angle) is the real design
space, and clever morphology reaches behaviors that "shouldn't" be possible from
radial parts. This also likely explains the HARDWARE flow-around (the physical robot's
real asymmetry was doing exactly this). Revisit the earlier "occluded-goal impossible"
and "c04/teaching-wall" conclusions in this light — they were about SYMMETRIC configs;
asymmetric morphology may reach them. (The idealized-sim occluded case still has the
separate edge-spill gradient gap.)

### C5 hold_s 6.0 -> 4.0 (user tweak, verified)
User lowered C5 dwell hold_s from 6.0 to 4.0s. Rationale: emergent patrolling orbits
near the wall held ~4.4-4.5s (the far side of each orbit drifts just past the 10cm
band, resetting the CONTINUOUS timer at 6s). At 4.0s the "guard by patrolling orbit"
behavior — which genuinely emerges from asymmetric Push/Pull — now satisfies the
challenge. Verified: asymmetric flee-red+seek-wall configs SUCCEED at 4.0s. This makes
"Around and Guard" solvable by the emergent behavior its name implies, in Push/Pull.

### THE MAZE (c16) ADDED + CORRIDOR (c10) KEPT (dev10)
User reframed slalom -> "The Corridor" (c10, vertical walls, light upper-right) and
then wanted a SEPARATE mini-maze after it. Built C16 "The Maze" (stage 3, added to
end of ALL_CHALLENGES; Corridor stays c10).
MAZE GEOMETRY (user spec + correction): three lanes (x thirds, dividers at -0.10,
+0.10). Left wall hangs from NORTH (y=+0.40) down to -0.20 => gap at BOTTOM. Right
wall rises from SOUTH (y=-0.40) up to +0.20 => gap at TOP. Robot starts NW corner
(-0.25,+0.35) facing DOWN (heading 270). Light in lower-right corner (+0.20,-0.30).
Forced path = full S-curve: DOWN left lane, UNDER left wall, UP middle lane, OVER
right wall, DOWN right lane to light. The NW-down start (user's key correction) makes
the first leg natural — seek pulls the robot down the left lane immediately.
SOLVABILITY (sampled, honest): HARD. No sampled Push/Pull config solves it. "Seek
only" correctly descends the left lane (NW->bottom-left) but JAMS in the bottom-left
corner instead of slipping right under the left wall — i.e. it can't make the LANE-
CHANGE turn (radial seek keeps pulling straight at the wall-blocked light). This is
the "reactive control runs out of road" phenomenon in pure form: at each gap the robot
must route AWAY from the goal to get around, which radial Push/Pull resists. May be
solvable by a clever asymmetric config (emergent circulation — see C5 finding); NOT
confirmed either way, and NOT declared impossible (C5 taught that lesson). Positioned
as a stage-3 capstone / bridge toward the maze + Novel Behavior game, a hard "edge of
Push/Pull" challenge may be exactly right. PLAYTEST to decide: threadable with clever
morphology, or the intended teaching wall for where reactive control ends.

### THE MAZE (c16) — COLORED WAYPOINT LIGHTS (dev10, user idea)
User idea to make the serpentine maze tractable: replace the single distant goal with
THREE COLORED breadcrumb lights (red, green, blue), dimmer/smaller early -> brighter/
larger late, each just past a bend. Colour channels avoid the white-light SUMMING
problem (a red-seek LDR ignores green/blue, so the near waypoint isn't overpowered by
the far goal). Committed C16: RED (0.0,-0.30, r0.10 i0.6) just under the left wall;
GREEN (0.0,+0.30, r0.15 i0.9) up top; BLUE goal (0.20,-0.30, r0.22 i1.4) lower-right.
Win = reach BLUE; avoid both walls. Robot chases R->G->B with colour-matched seeks.
PROGRESS (real, incremental — best maze result yet): with R+G+B colour seeks + both-
side IR repel, the robot cleanly descends the left lane (leg 1) AND ROUNDS BEND 1
(slips under the left wall's bottom end into the middle lane) — which NO earlier
config or the white-waypoint version could do. Confirmed by trace (heading rotates
277->304 while crossing below the wall end).
REMAINING JAM: it stalls entering/climbing the MIDDLE lane (~-0.09,-0.25), because the
PASSED red light keeps pulling it back down — the breadcrumb doesn't "release" once
passed (summing model: red still tugs). Nudging red's position/intensity moved the jam
a little past the wall end but didn't thread leg 2. FUNDAMENTAL: a single fixed sensor
config can't "forget" a waypoint once past it, so chained breadcrumbs need either
(a) waypoint lights whose pull is very local (tiny radius, high peak) so they vanish
quickly once passed, (b) per-leg color hand-off that a fixed config can't fully do, or
(c) the emergent-circulation morphology to carry momentum through each bend.
STATUS: the colored-waypoint design is a genuine improvement (first config to clear a
bend) and worth keeping. Full 3-leg solve not yet found; may be at the edge of fixed-
config Push/Pull. PLAYTEST target: can a hand-tuned morphology thread all three, or is
this the 'reactive control runs out of road' capstone.

### SPIRAL MAZES (c17 Spiral Out, c18 Spiral In) — NEGATIVE RESULT (dev10, user idea)
User idea: a uniform-corridor SQUARE SPIRAL, centre<->corner, SAME arena, two
challenges (out then in). "No lights, just walls" first (then maybe one light per end).
BUILT: C17 (centre->corner) + C18 (corner->centre) sharing _SPIRAL_WALLS (nested
square rings + a corridor-floor wall forcing the coil; corridors ~0.13m, robot 9.4cm).
Added POSITIONAL dwell goals ("pos": (x,y)) to hub win-logic so a walls-only maze can
win by reaching a LOCATION (corner / centre) with no light — a small general addition.
FINDING (tested, important): the spiral is NOT traversable by this reactive control:
 - NO lights: wall-repulsion alone gives NO directional drive — "stay off walls" isn't
   "go this way." Robot's forward creep just stalls against a wall near centre. All IR
   configs stuck (best reached the inner-ring exit, then jammed).
 - WITH a goal light at the corner: STILL not traversed — the light pulls STRAIGHT
   toward the corner (through walls), but a spiral requires travelling AWAY from the
   goal for long stretches. Best config worked out of the inner ring and part way up,
   then stuck.
ROOT (fundamental, not tuning): reactive potential-field control follows gradients
toward/away from sources; it has NO representation of "follow this corridor around
even though it leads away from the goal." A spiral's sustained away-from-goal travel is
exactly what reactive control cannot do. This is arguably the PUREST "reactive control
runs out of road" demonstration in the game — cleaner than the serpentine, because the
away-from-goal requirement is unavoidable and sustained.
=> PEDAGOGICAL GOLD for the Maze->Novel-Behavior bridge (FW-013): the spiral is a
crisp, visual proof that reactive control has a ceiling, motivating non-reactive
(planning / wall-following-with-memory / novel) control. Keep as a capstone /
demonstration, NOT as a Push/Pull-solvable challenge. If a solvable version is wanted
later, it needs the new control paradigm, not tuning. Connects to the emergent-
circulation finding: even that (asymmetric orbit) can't sustain a multi-turn inward/
outward spiral.

### SPIRAL PORTED TO ROBOT ETHOLOGY (dev10, user request)
Ported the spiral maze to RE as an OBSERVATION environment for the target behavior
(RE is a behavior-ID game — players watch the target subsumption hierarchy act in an
arena and hypothesize its rules; the arena is the environment, not a puzzle to solve).
BUILT:
 - games/ethology/arenas/arena_spiral.json: square spiral scaled to RE's 1.5x2.5
   arena and larger robot (body_radius 0.0775, diam 0.155). Corridor ~0.24m, inner
   cell 0.26m. Robots START AT CENTRE (0,0); LIGHT in the top-right CORNER (0.55,1.05,
   intensity 1.4). Same 7-wall coil design as Field Trip's (nested square rings +
   corridor-floor forcing the coil), rescaled. Validated: ArenaConfig.from_file parses
   it; walls/light/start all load.
 - replays.json: added bundle "CB: Spiral (centre start, corner light)" referencing
   arena_spiral.json with existing morphologies (wide_splayed / forward_close) and the
   default target hierarchy, so there's a real target behavior to observe winding
   through the spiral. All bundle references validated to exist + parse.
WHY THIS FITS RE (vs Field Trip): RE doesn't need the spiral "solved" — it's about
OBSERVING how the target behavior navigates it. The spiral is a rich observation
environment: the subsumption target (Escape Front/Rear -> Avoid Object -> Cruise) will
wall-follow / get stuck / cruise in visually interesting ways as it winds out toward
the corner light. Connects to the Field Trip finding that reactive control can't cleanly
solve a spiral — here that same limitation becomes something to WATCH and reason about.
NOTE: bundle uses the default target hierarchy for both A/B; could later pair contrasting
hierarchies (e.g. moth vs roach) to compare how different behaviors handle the spiral.

### BYOV WEB — NEURONS MADE OPTIONAL, DIRECT SENSOR->MOTOR IS THE DEFAULT (dev12)
User feedback on the shipped web BYOV: neurons should NOT be there by default; they
should be ADDABLE like sensors, and the default should be wiring sensors DIRECTLY to
motors. Agreed (Braitenberg's Vehicles 1-2 are literally sensors wired to motors, so
neurons-by-default put an abstraction in front of the simplest, clearest case).
Chose the FULL rewire (Option 1) over a minimal parallel path, because the general
model is actually LESS code than maintaining two wiring systems, and the minimal
version would have been a detour rather than a stepping stone.
MODEL (byov_web/vehicle.js, rewritten):
 - this.neurons = [] by DEFAULT. addNeuron() / removeNeuron() create and delete them;
   removal prunes wires both into and out of the neuron.
 - MOTORS are now first-class wire TARGETS: each { id, bias, inputs:[{srcId,sign}] },
   exactly like a neuron. srcId may be a SENSOR id (direct wiring) or a NEURON id.
 - evaluate() is a two-stage feed-forward pass: sensors -> neurons
   (N = clamp(bias + Σ sign*sensor, 0,1)) -> motors (M = clamp(bias + Σ sign*src, 0,1)).
   Neurons accept sensor inputs only, so the graph can never loop.
 - MOTOR BIAS added = a RESTING speed (defaults 0). This is what makes Vehicle 3
   (inhibitory) work without a neuron: the light inhibits a motor that would otherwise
   run. Faithful to Braitenberg and keeps neurons genuinely optional.
 - connect(srcId, targetId, sign) / disconnect / clearWiring; toJSON/loadJSON updated
   to persist motors as well as neurons.
EDITOR (byov_web/editor_view.js, rewritten): motors drawn at the rear each with their
own E/I input headers (drop targets) and a draggable bias needle; neurons laid out in
a row in the middle, however many exist (possibly none); "+ neuron" button bottom-left;
each neuron has a × delete hotspot. Wires are built from TARGET-owned input lists, so
sensor->motor, sensor->neuron and neuron->motor all render and are all clickable to
remove. _tryConnect generalised to (sensor-out | neuron-out) -> (neuron-in | motor-in).
PRESETS (app.js): all five rewritten as DIRECT sensor->motor wiring, zero neurons.
Verified behaviour with light on the left: V1 straight, V2a turns AWAY (coward),
V2b turns TOWARD (aggressor), V3a TOWARD and settles (love), V3b AWAY (explorer) —
all matching Braitenberg. 3a/3b use motor bias .6 inhibited by the LDRs.
TESTED (node): 0 neurons by default; direct same-side/crossed excite; motor bias +
inhibition; add neuron -> sensor->neuron->motor; neuron bias; removeNeuron prunes both
directions; neuron->neuron blocked; save/load round-trip. Editor layout+draw smoke-
tested with 0, 2 and 1 neurons via a stub canvas. index.html hints and README updated
to describe the new default.
NOT YET DONE: no browser run-through (headless only) — worth a manual click-test of
drag-to-wire onto the new motor E/I targets and the +neuron / × buttons before
re-deploying to the GitHub Pages site.

### BYOV WEB v3 — WEIGHTED WIRES, METERS, NEURON GRID (dev12, user spec)
Seven changes requested after the neurons-optional rework:
 1. NEURON CAP 6 (MAX_NEURONS). addNeuron() returns null when full.
 2/7. ADD/REMOVE via +/- buttons placed OUTSIDE the robot, left of the deck's
    outer edge (verified: button right edge 82 <= deck.x 90). Removal is LIFO
    (removeLastNeuron()); the per-neuron × was dropped. Button shows n/6.
 3. WIRE COLOUR = WEIGHT, not excite/inhibit — blue 1x, green 2x, red 3x, matching
    WIRE_WEIGHT in engine/signals.py so web and Python agree. Excite/inhibit still
    comes from WHICH INPUT the wire lands on (E or I), as on the physical board.
    NOTE (interaction I had to choose, not specified): LEFT-CLICK a wire cycles its
    colour blue->green->red; RIGHT-CLICK removes it. Say if you'd rather it were
    the other way round, or a modifier key.
 4. METERS M1/M2/M3 permanently installed between the sensor headers and the neuron
    rows. Exactly ONE wire each (a new wire replaces the old), source may be a sensor
    OR a neuron. DISPLAY ONLY — verified they never affect motor output, matching
    engine/vehicle.py where meters are display-only. Each draws its live value.
 5. NEURONS laid out 3 ROWS OF 2 (verified: 3 distinct rows, 2 distinct columns),
    mirroring the board and reading as network layers.
 6. NO per-motor pots. ONE shared bias pot between the motors = a resting speed
    applied to BOTH, so a vehicle can idle forward with no neurons. setBias(x) is
    now a single-argument, vehicle-level call.
MODEL: inputs are {srcId, sign, color}; contribution = sign * WIRE_WEIGHT[color] *
source. neuron N = clamp(bias + Σ, 0,1); meter = clamp(weight*src, 0,1); motor =
clamp(sharedBias + Σ, 0,1). Feed-forward only (neurons take sensor inputs), so no loops.
TESTED (node): cap at 6; LIFO removal; blue/green/red = 0.30/0.60/0.90 from a 0.3
signal; colour cycling wraps; shared bias applies to both motors and is inhibitable;
meter keeps one wire and leaves motors at zero; meter fed by a neuron; deleting a
neuron prunes meter + motor wires that fed from it; save/load round-trip. Editor
smoke-tested via stub canvas: draw at 0 and 6 neurons, 3x2 grid, buttons outside deck,
meters between sensors and neurons, mixed-colour wires. Presets re-verified (V1
straight, 2a away, 2b toward, 3a toward-and-settle, 3b away) with ZERO neurons.
STILL NOT DONE: no real-browser click-through. Test locally with
`cd byov_web && python3 -m http.server 8000` -> http://localhost:8000 (ES modules
need a server; file:// will not work). Nothing is deployed by doing this.

### BYOV WEB — HINT SPACING + LIVE METER HUD (dev12)
 - Instructions were scrolling: .hint now has margin 0.4em 0 / line-height 1.32
   (about 2/3 the previous vertical space). Last hint reworded to the user's text:
   "Single-click LDR to cycle color channels: R, G, B, W (any color ambient)",
   with each letter tinted its channel colour.
 - METER HUD added to the Arena & run canvas, replicating the Python game's wiring
   inspector (engine/builder/wiring_inspector.py::_draw_meter_bar): 10-segment
   vertical LED bars in a 52px gutter down the LEFT of the canvas, ordered M3 top,
   M2 middle, M1 bottom (matching the game's node layout). Colours taken from the
   game: M1/M3 lit #dc3232 red, M2 lit #f0f0f0 white, with dim #3c0a0a / #3c3c3c;
   when NOT running everything drops to #1e1e1e/#0f0f0f, exactly like the game's
   inactive state. Lit segments get a canvas shadow glow while running. Segment
   count uses Math.floor(val*10) to match the Python int() truncation (verified
   0.24->2, 0.55->5, 0.99->9, 1.00->10). Each bar is labelled with its meter id and
   the id of whatever is wired to it (or a dash).
   Renderer._resize now reserves the gutter so the arena never overlaps the HUD
   (verified arena origin x=68 > hud width 52).
   app.js passes `running` into renderer.draw; the replay path now also calls
   evaluate() so scrubbing a recording drives the meters too.
TESTED (stub canvas): 30 segments drawn, correct lit counts per meter and colour,
bars left of the arena, all-dark when stopped.

### BYOV WEB — METER HUD VISIBILITY FIX + BULLETED HINTS (dev12)
 - BUG: the meter HUD was drawing but INVISIBLE. The idle colours I used
   (#1e1e1e lit / #0f0f0f dim) sit at the same luminance as the canvas background
   (--panel #11151c), so the bars vanished until Run was pressed. FIX: each meter
   now has an always-visible HOUSING (dark fill + stroked bezel) and unlit LEDs are
   #262b33, clearly lighter than the panel. While running the game's colours take
   over (M1/M3 #dc3232 red, M2 #f0f0f0 white) with a shadow glow on lit segments;
   unlit segments drop to the game's dim values. So the meters read as hardware when
   idle and light up when running. Verified: 3 housings + 30 visible off-LEDs idle;
   M1 at 0.70 -> 7 lit while running.
   Also factored the rounded-rect into Renderer._rr (canvas roundRect isn't
   universally available, and the old code fell back to square corners).
 - INSTRUCTIONS still scrolled. Converted the <p class="hint"> stack into a
   <ul class="hints"> with disc bullets (blue ::marker) so lines stay visually
   distinct while sitting tighter: list margin 4px, li margin-bottom 3px,
   line-height 1.28, and .side h3 margins reduced. Also TRIMMED the wording of the
   five non-user-authored hints (the "Single-click LDR..." line is left exactly as
   written). Estimated list height ~210px, down from ~294px.

### BYOV WEB — METERS SIDE-BY-SIDE + MODULE CACHE-BUSTING (dev12)
User reported still seeing NO meters in Arena & run, and asked for them arranged
LEFT-TO-RIGHT as on the physical robot / in the Build Robot view.
 - LAYOUT: the HUD is now three 10-segment bars SIDE BY SIDE, ordered M1 M2 M3
   left-to-right (matching editor_view's meter row), in a 118px gutter left of the
   arena, with a "METERS" header, each bar labelled and showing its wired source.
   Verified label x-order M1(41) < M2(75) < M3(109) on a common baseline, arena
   origin x=134 so nothing overlaps.
 - LIKELY CAUSE OF "no meters": stale ES modules. index.html loaded app.js with no
   version, and app.js imported ./arena.js etc. unversioned, so a browser could keep
   serving the OLD arena.js (which had no HUD at all) even after a reload — each
   module is cached independently. All module specifiers now carry ?v=4
   (index.html script tag + every import). Bump this version on future JS edits, or
   hard-reload (Ctrl/Cmd+Shift+R), when a change doesn't appear.
 - Code path re-verified as correct before changing anything: _drawMeterHUD is
   called first thing in Renderer.draw, nothing repaints the gutter afterwards, and
   the stub-canvas test draws 3 housings + 30 unlit LEDs when idle and the right lit
   counts when running (M1 0.80 -> 8, M3 0.35 -> 3).

### BYOV WEB — PRESETS NO LONGER DELETE NEURONS (dev12, user request)
Rationale (user): you may want to start from a quick preset, ADD neurons to see how
they modify the behaviour, then switch to another preset — the neurons you built
shouldn't be thrown away. Presets now SEVER CONNECTIONS but leave the neurons
themselves, with their biases, on the board.
 - Vehicle.clearWiring() takes options: { removeNeurons=false, resetNeuronBias=false,
   clearMeters=false, resetBias=true }. Defaults keep neurons AND their biases;
   neuron/motor input lists are emptied; _pruneDeadInputs() runs afterwards.
 - app.js clearWiring() no longer does `v.neurons = []`.
TWO JUDGEMENT CALLS worth confirming:
 1. METER wiring SURVIVES a preset switch. Meters are display-only instrumentation
    and don't affect behaviour, so wiping them would just destroy the observation
    setup the user built. Say the word if presets should clear meters too.
 2. The SHARED MOTOR POT is still reset by a preset (resetBias default true),
    because each preset sets it deliberately (2a/2b .15, 3a/3b .6, V1 none) — if it
    persisted, switching to Vehicle 1 after Vehicle 3 would leave a phantom .6
    resting speed and the vehicle would behave wrongly.
TESTED: start on 2b, add N1/N2 with biases .35/-.20, wire N1 and a meter; switch to
3a -> both neurons survive with biases intact, their wires severed, motor wiring is
the new preset's only, shared bias .60, meter wiring kept; 3a still turns toward the
light with idle neurons on board; switching to V1 resets the pot to 0.
Module cache version bumped to v=5.

### BYOV WEB — MOTORS GET FORWARD/REVERSE BANKS, NOT E/I (dev12, user request)
User: motors having E/I made no sense — it could awkwardly reverse something already
decided by a neuron. The physical robot has 4 FORWARD headers and 4 REVERSE headers
per motor; you specify direction, and inhibition belongs to neurons.
 - MODEL: motor is now { id, fwd:[{srcId,color}], rev:[...] }, four slots per bank
   (MOTOR_SLOTS = 4, extra wires ignored). Motor value = clamp(sharedBias + Σ fwd
   weights - Σ rev weights, -1, 1) — matching engine/vehicle.py's (FL - BL) and
   (FR - BR). connect()'s third argument is now the PORT: a sign for neurons,
   'fwd'/'rev' for motors (a bare -1 maps to 'rev' for safety); a source occupies
   one slot per motor, so re-dropping it on the other bank MOVES it rather than
   duplicating. disconnect/cycleWireColor/clearWiring/toJSON/loadJSON all updated.
 - EDITOR: each motor draws two rows of four grey sockets (same grey as the meter
   inputs), FWD above REV, labelled in green/amber. Motor headers no longer carry a
   sign and never render E/I. Wire k in a bank draws to socket k, so the four
   sockets fill in order like the real board.
 - PRESETS now name a direction: V1/2a/2b wire FWD; 3a/3b keep the shared pot at .6
   and wire the LDRs to REV.
BEHAVIOUR CHANGE WORTH KNOWING: with a real reverse bank, Vehicle 3a/3b can now drive
a wheel NEGATIVE (light on the left gives L=-0.20, R=0.40) where the old E/I version
clamped it at 0. That is faithful to the engine's (FL - BL) and makes 3a pivot harder
toward the light rather than just stalling that wheel. If you'd rather 3a only ever
slowed to a stop, the alternative is to build it with a NEURON (bias 1.0, LDR on the
I input, N -> FWD), which is arguably the more Braitenberg-faithful construction and
a nice motivation for neurons — say the word and I'll switch the preset.
TESTED: 16 motor headers (2 motors x 2 banks x 4), FWD row above REV, no sign on any
motor header; bank capped at 4 wires; re-dropping a source on the other bank moves it;
reverse wire yields a negative command; save/load round-trip; all five presets still
give the right turn direction. Cache version bumped to v=6.

### BYOV WEB — INSTRUCTION BLOCK NUDGED UP ONE LINE (dev12)
Last hint line ("...ambient)") was sitting just below the canvas bottom edge. Pulled
the whole side-panel block up by ~17px: .side h3 margin 14px->8px top / 4px->3px
bottom, ul.hints margin-top 4px->0, li gaps 3px->2px, line-height 1.28->1.26.
Also added ?v= to the stylesheet link (CSS was not cache-busted before, only the JS
modules) and bumped everything to v=7.

### PYTHON WIRING EDITOR — CHASSIS OUTLINE BEHIND THE BOARD (dev12, ported from web)
User liked the web BYOV's "circuit board overlaying the chassis" and wanted the Python
side to outline the board the same way, with the board itself unchanged across chassis.
FINDING FIRST: the Python board layout was ALREADY fixed and chassis-independent —
wiring_editor.py states "All layout is computed as fractions of the given rect", and its
row order already matches the web front-to-rear (sensors .10, meters .18, neuron E/I .29,
neuron bodies .50, neuron N/T .70, motor FWD .83, motor REV .93). The only thing missing
was the chassis outline; the module had ZERO references to chassis.
IMPLEMENTED:
 - WiringEditor(..., chassis_polygon=None) + set_chassis_polygon(). The POLYGON is
   passed in (robot-local metre vertices) rather than importing robot_builder, which
   would be circular — robot_builder imports WiringEditor.
 - _draw_chassis_outline(): draws the deck polygon + two wheels behind the board,
   immediately after the panel background fill. Purely decorative; no hit-testing
   depends on it, and callers that pass no chassis (Valentino's hub x2, ntv_game, the
   standalone demo) are unaffected.
 - robot_builder passes chassis_polygon_m(self._chassis) at construction and calls
   set_chassis_polygon() from _set_chassis(), so the outline follows the selection.
DESIGN NOTE: the deck is stretched to FILL the panel rather than kept at the robot's
true aspect. First attempt preserved aspect and looked wrong — the chassis is roughly
square, the panel is portrait, so the sensor row and motor banks fell OUTSIDE the
outline. Filling matches the web deck (which also fills its panel) and keeps the
silhouettes tellable apart: square corners (rectangle) vs bevelled (octagon) vs
tapered (triangle). Verified by rendering all three.
NOT DONE YET: the user's follow-on point that this "should reduce the number of panels"
— actually removing/merging the builder's separate chassis panel is a further change to
robot_builder's layout, not attempted here.

### PYTHON BUILDER — BOARD SKETCH ON THE ROBOT, RIGHT PANEL BACK TO WIRING-ONLY (dev12)
Superseded the previous approach (chassis outline behind the right wiring panel), which
distorted the octagon/triangle (stretch-to-fill) and put a rival robot silhouette next
to the left canvas's true-scale one. User's cleaner reframe: keep the right panel as
pure wiring, and draw a FAINT board SKETCH on the LEFT robot drawing, so the right panel
reads as a "blow-up" of that board region.
CHANGES:
 - REVERTED the right-panel outline: removed _draw_chassis_outline + set_chassis_polygon
   from wiring_editor.py and the draw call; removed the builder's set_chassis_polygon()
   call and the chassis_polygon= constructor arg. (The constructor still accepts a
   chassis_polygon kwarg as a harmless no-op store, in case any caller passes it.)
   Right panel is wiring-only again.
 - ADDED robot_builder._draw_board_sketch(): a translucent (SRCALPHA) schematic of the
   board on the left canvas, drawn right after the chassis polygon and BEFORE peg holes/
   parts so the placement dots stay readable over it. Shapes echo the wiring panel's row
   order front-to-rear: sensor headers, meters, neuron E/I, neuron bodies (triangles),
   neuron outputs, two motor banks (FL/BL, FR/BR) of 4x2 pins, plus a rounded board
   border. Positioned in metric space via _w2s and centred on the chassis, so it scales
   correctly and is never distorted; it fits within each chassis (incl. the narrower
   triangle). It's schematic, not a metric PCB.
VERIFIED: all three chassis draw the sketch; full builder draws canvas+panel together;
right panel has no outline method left; a placed sensor renders over the sketch.
This is the design to keep. The "merge the panels" idea is intentionally NOT pursued —
overlaying metric peg-holes with dense circuitry would be a busy, competing screen; the
faint-sketch + blow-up relationship gives the association without the clutter.

### PYTHON — BOARD SKETCH REVERTED + TOUR OFFER SHOWN ONCE (dev12)
 - BOARD SKETCH BACKED OUT: the translucent board schematic on the left canvas read
   as too busy. Removed _draw_board_sketch and its call; builder is back to the two
   distinct views (true-scale robot left, wiring panel right). Nothing else depended
   on it.
 - TOUR OFFER ONCE: in the Wiring Tutorial, PAW-Bot's full Yes/No tour offer popped up
   on EVERY editor visit, hogging the screen and delaying the next guided edit. Now it
   pops up only the FIRST time; subsequent visits open collapsed with just the
   "Play Tour" link (tour stays enabled, link live). Implemented via a new
   WiringEditor(tour_already_offered=False) kwarg — when True (and the tour is enabled)
   the editor starts in state "done" (the existing collapsed state) instead of "offer".
   Valentino's Hub passes tour_already_offered=getattr(self,'_tour_offered',False) and
   sets self._tour_offered=True after the first open. Verified: first visit -> "offer",
   later visits -> "done" with tour still enabled; non-tutorial editors unaffected
   ("off"); Play Tour re-entry still works.

### PF BOUNDARY PROBE — WHERE POTENTIAL FIELDS SUCCEED / FAIL (dev12)
First systematic pass mapping the reactive boundary for the Maze progression (FW-013),
using FT's field_physics (the real PF solver) with a config search over radial +
tangential, symmetric + asymmetric sensor placements.
RESULT (corrected after a DEEPER search — the shallow 40-config pass gave false fails,
same lesson as the emergent-circulation finding: don't call it impossible on a thin
search):
 SOLVABLE by potential fields (with the right ASYMMETRIC / tangential config):
   - open field, offset barrier (C4), doorway/gap, L-corner, one-bend serpentine
   - CENTERED barrier (symmetric) — flow-around at IR ang60,t2.0 breaks the cancellation
   - U-TRAP (concave local-minimum) — same flow-around climbs out
   - DOUBLE-BACK (offset weave) — asymmetric config threads it (121 cfgs)
   - SHALLOW SPIRAL with goal OUTSIDE — light pulls the robot out the opening
 NOT solvable (robust across 1350 configs):
   - DEAD-END requiring BACK-OUT — robot pulled into a pocket, must reverse out and
     go around; no gradient says "leave the goal direction". Pure memory/state case.
   - (from earlier this session) DEEP multi-turn spiral, goal at CENTRE — sustained
     travel away from goal.
KEY TAKEAWAYS for the progression:
 1. There IS a rich SINGLE-SCHEMA (early-tier) band — doorways, L-corners, offset
    barriers, single bends, shallow spirals are maze-like AND PF-solvable. Early tier
    is not empty (my earlier worry was wrong).
 2. Potential fields are MORE capable than first thought: with asymmetric/tangential
    morphology they clear centered barriers, U-traps, and double-backs — cases the
    literature calls PF failure modes. The emergent-circulation finding generalises.
 3. The genuine reactive wall has ONE signature: the robot must travel SUSTAINEDLY
    AWAY from the goal with no gradient to guide it (dead-end back-out; deep centre
    spiral). THAT is what needs memory/state — the capstone/NB boundary.
 4. IMPLICATION for the middle tier (combination): the set of "single-schema fails
    but reactive-combination solves" may be SMALL, because most former "fails" are
    already single-schema-solvable with better morphology. The middle tier's honest
    content is now in question — worth the dedicated combination probe next.
PLAYTEST ARENAS ADDED (end of ALL_CHALLENGES, ids cp1..cp5): Centered Barrier, U-Trap,
Double-Back, Shallow Spiral (all sim-solvable — confirm human-findable), and Dead-End
(expected unsolvable — feel the wall). Reach by advancing to the end of the list.

### PF BOUNDARY PROBES — REBUILT AFTER DESIGN-VALIDATION FAILURE (dev12)
USER CAUGHT A REAL METHODOLOGY ERROR: the first probe set had (a) openings too narrow
to pass and (b) start poses that let the robot reach the goal WITHOUT encountering the
feature under test. Worst case: "Double-Back" started mid-arena and the robot simply
rounded one wall end — traced and confirmed ZERO y-direction reversals. The earlier
"SOLVED" result was therefore measuring a much easier task than the probe's name claimed.
PROCESS LESSON: I validated with a SOLVER instead of validating the EXPERIMENT. A probe
is only meaningful if its geometry FORCES the behaviour under test. New rule followed
here: before any solvability search, run a NAIVE SEEK and confirm the feature actually
traps it (entered the pocket? pinned at the cap? stalled on the centreline?).
REBUILT (user constraints: custom start pose per probe — whatever forces the feature;
all corridors >= 0.16 m, since the robot needs > 0.119 m to fit = body radius 0.047 +
wall half-thickness 0.0125 per side):
 cp1 Centered Barrier — symmetric wall dead ahead; naive seek stalls at x~0.00.
 cp2 U-Trap — concave pocket, mouth facing start, goal beyond; seek enters and pins.
 cp3 Double-Back — robot starts BOXED IN at the closed top of a corridor, goal up-and-
     right; the only exit is DOWN, away from the goal. Naive seek: 0 y-reversals,
     never descends — trapped exactly as intended.
 cp4 Shallow Spiral (goal OUTSIDE, corridors widened to 0.16).
 cp5 Dead-End lure — starts OUTSIDE, goal directly beyond the pocket's cap; naive seek
     ENTERS the pocket (confirmed) and jams.
SOLVABILITY (now meaningful): cp1 SOLVABLE (12 cfgs), cp2 SOLVABLE (14), cp4 SOLVABLE
(2), cp5 SOLVABLE (38 — surprising: circulation carries the robot back OUT of a dead-end
pocket, so a lure alone does NOT defeat reactive control), cp3 NOT SOLVED (1350 cfgs,
closest 0.23).
=> THE REACTIVE WALL, ISOLATED: being BOXED IN such that the only exit runs SUSTAINEDLY
AWAY from the goal. Circulation can slide AROUND an obstacle but cannot drive the length
of a corridor in the anti-goal direction — no gradient points there and no memory says
"I came from there." cp3 is the cleanest single artefact demonstrating the need for
memory/state, and the best capstone candidate found so far.
PLAYTEST: python games/field_trip/hub.py --challenge 18..22 (cp1..cp5), from repo root.

### PREFAB SOLUTIONS FOR THE PF PROBES (dev12) + TWO REAL BUGS IN MY OWN SEARCH
User asked for default robot builds for each solvable probe, so playtesting can start
from a known-good build and diverge from there. Wrote FT_CP1/CP2/CP4/CP5_solution.json
and attached them via solution_file (reachable in-game via "Show Solution", which loads
the config into the builder). cp3 gets a solution_desc explaining it is unsolvable BY
DESIGN (the capstone memory case) and no file.
TWO BUGS THIS EXERCISE EXPOSED IN MY EARLIER "SOLVABLE" CLAIMS — both meant I had been
searching a space the GAME CANNOT BUILD:
 1. TANGENTIAL MAGNITUDE. My search swept arbitrary tangential values (±1.5, ±2.0), but
    the builder only offers ±SWIRL (3.0) via its fixed FLOW_STYLES. Prefabs written with
    ±1.5/±2.0 solved as-written but FAILED after a builder round-trip, because the
    builder snaps tangential to its preset. Caught by testing round-trip, not just load.
 2. ORBIT POLICY. For policy "none" WITH a tangential, hub._build_sensors_from_cfg
    applies ORBIT_INWARD (0.3), a deliberate slight inward pull so orbits don't spiral
    out. My search passed policy=0.0 directly, bypassing that — so "orbit" solutions the
    search found did not reproduce through the game's own loader.
=> RE-SEARCHED using the game's exact semantics (FLOW_STYLES tangentials + ORBIT_INWARD).
   Plenty of genuinely buildable solutions exist: cp1 59, cp2 34, cp4 423, cp5 41.
FINAL PREFABS (verified BOTH as-written and after a builder round-trip):
   cp1  LDR Seek +30 | IR Flow-around-right, aim +90, y-0.04   ~8.3s
   cp2  LDR Seek +30 | IR Orbit-left,        aim +90, y+0.04   ~22.7s
   cp4  LDR Seek -30 | IR Flow-around-left,  aim -90, y+0.04   ~1.6s
   cp5  LDR Seek +30 | IR Orbit-left,        aim +90, y+0.04   ~21.4s
NOTE: all four rely on a TANGENTIAL (Orbit / Flow-around) style. Those styles are
currently HIDDEN in Field Trip's builder (radial_only=True) pending hardware validation,
so the prefabs load and run but a player cannot presently dial them in by hand. If the
probes are meant to be player-solvable, radial_only must be relaxed for these challenges
— worth deciding. cp2/cp5 at ~21-23s also sit at about half the 45s limit; fine, but
less margin than cp1/cp4.

### CORRECTION — PROBES RE-SOLVED UNDER THE PLAYER'S ACTUAL CONSTRAINTS (dev12)
USER CAUGHT IT: they playtest with IR + LDR, PUSH/PULL ONLY. Every prefab and every
"solvable" verdict I had produced relied on a TANGENTIAL term (Orbit / Flow-around) —
styles hidden behind radial_only=True and therefore NOT in the player's vocabulary. I
had been searching a space the player cannot build in.
RE-SEARCHED with tangential forced to 0 (2 sensors: LDR attract + IR repel, free angle
and lateral offset, 729 configs each). RESULT — the boundary SURVIVES the correction and
is now stronger, because it holds under the real constraints:
   cp1 Centered Barrier   33/729 solve, best 6.5s
   cp2 U-Trap             12/729 solve, best 6.5s
   cp4 Shallow Spiral    127/729 solve, best 2.7s
   cp5 Dead-End           17/729 solve, best 12.5s
   cp3 Double-Back         0/729  — STILL UNSOLVABLE
The winning morphology is exactly the EMERGENT CIRCULATION the user discovered earlier
this session: LDR Seek angled ~45 off-axis plus an IR Flee aimed ~90 to one side, both
offset laterally. Asymmetry alone makes the resultant force rotate as the robot turns —
no explicit circulation term required. The tangential styles were never necessary.
PREFABS REWRITTEN as pure Push/Pull (tangential 0.0 everywhere), verified as-written AND
after a builder round-trip, so they are inspectable and editable in the builder as it is
currently configured. The earlier note about needing to relax radial_only is MOOT.
STANDING CONCLUSION: with plain Push/Pull, the ONLY probe that resists is cp3 — boxed in
with the sole exit running sustainedly away from the goal. That remains the cleanest
demonstration of the need for memory/state.

### PROBE GEOMETRY CORRECTED AGAIN — AND A REACHABILITY CHECK ADDED (dev12)
USER CAUGHT THREE MORE GEOMETRY ERRORS, one severe:
 1. cp3 Double-Back was a FULLY SEALED CHAMBER. Side walls ran from y=-0.40 (the arena
    floor) up to the cap, so there was no exit at all. Flood fill: only 420 free cells
    reachable, goal NOT among them. My "0/729 solve — the reactive wall" verdict was
    therefore MEANINGLESS; it measured a box with no door, not a control limit. My
    naive-seek validation had reported "trapped as intended" — the symptom, which I
    misread as confirmation.
 2. cp4 Spiral started at (0,0), the central dead end, one wall around from the light,
    so the coil was barely traversed.
 3. cp5 Dead-End started BELOW the inverted horseshoe, so the robot could go round the
    outside without ever committing to the pocket.
PROCESS FIX (now standard, run FIRST): flood-fill REACHABILITY — is the goal reachable
from the start, and is the start itself unblocked? Checking "does the robot get stuck"
is not sufficient; a sealed arena passes that test for the wrong reason.
REBUILT to the user's specs: cp3 side walls now stop at y=-0.14 leaving a real exit at
the bottom (robot still boxed at the top, must run the corridor DOWN and out); cp4
starts in the long outer arm at (0.18,-0.18) facing left with the light moved to the
CENTRE (0,0) so the coil must actually be wound inward; cp5 starts INSIDE at the top of
the pocket (0,+0.14) facing away (hdg 270) with the light just beyond the cap.
All five now pass reachability (cp3: 420 -> 2210 free cells) and a naive seek is still
trapped by the intended feature in each.
SOLVABILITY, PUSH/PULL ONLY (the player's real constraints), re-measured:
   cp1  33/729   6.5s      cp2  12/729   6.5s
   cp3   2/729  34.0s      cp4   1/729  13.2s      cp5  15/729  16.3s
=> REVISED CONCLUSION: with a genuine exit, cp3 IS solvable — but only 2 of 729 configs
find it and both need ~34-41s of the 45s budget. cp4 is narrower still (1/729). So the
honest picture is NOT "reactive control hits a hard wall here" but "the solution band
becomes vanishingly narrow" as the away-from-goal stretch lengthens. That is a weaker
claim than the earlier sealed-chamber result implied, and it materially changes the
Maze/NB argument: the case for memory rests on SEARCH DIFFICULTY and robustness, not on
strict impossibility. Worth re-examining the deep-spiral result from earlier this
session for the same defect before relying on it.
PREFABS updated for cp3/cp4/cp5 with the working push/pull configs; all five verified
as-written and after a builder round-trip.

### BUG — PROCEDURAL CHALLENGES REGENERATED EVERY FRAME (dev12)
User: "Challenge 23 cycles through goals in real time, making gameplay impossible."
CAUSE: challenge 23 is the first PROCEDURAL (stage-4) challenge — one past the 22
hand-authored ones. Hub._current_challenge() called generate_challenge(idx+1) with no
seed and no cache, and generate_challenge defaults to rng=random.Random() (fresh source
per call). The method is called from 11 sites INCLUDING the draw loop, so the arena was
re-rolled every frame: lights changing count, position and colour continuously.
FIX: generate once per index from a seed derived from that index (random.Random(idx+1))
and cache in Hub._generated. Verified: 1 distinct arena across 200 draw-loop calls,
identical across a fresh Hub (so deterministic between runs), and different challenge
numbers still produce different arenas.
WHAT THE BUG UNCOVERS (user asked — worth recording):
 1. LATENT CONTRACT. _current_challenge() is treated as a cheap PURE accessor by all 11
    callers. True for a list index, false for generation. Anything that later makes
    lookup non-trivial (disk loads, modifiers) breaks identically. The contract "same
    index -> same object" is now enforced by the cache instead of by luck.
 2. THE WHOLE STAGE-4 TIER HAS NEVER WORKED. Not specific to 23 — every procedural
    challenge was unplayable, unnoticed because playtesting stayed in the authored list.
 3. CONSEQUENCE FOR FW-013 (the important one). Maze plans lean on procedural generation
    for later levels, and "level-progression / challenge-authoring" is a candidate NB
    mechanic. This shows procedural generation here is UNPROVEN — never run end to end.
    It also exposed a design gap beyond the crash: no caller-supplied SEED, so generated
    challenges could not be referenced, replayed or shared. For a maze game where "level
    47" must mean the same arena for teacher and student, seeded determinism is a
    REQUIREMENT, not a nicety. Now seeded by challenge number.
 4. generate_challenge does NOT verify its arenas are reachable or solvable — the exact
    defect found in the hand-built probes this session. If procedural mazes proceed, the
    flood-fill reachability check belongs INSIDE the generator.

### HANDOFF PREPARED (end of dev13)
Wrote HANDOFF_dev13.md at the repo root for continuing in a new chat: environment /
restore steps, how to reach challenges via the Field Trip CLI, everything changed this
segment (FT builder + collision + script-index + single-source-of-truth fixes; BYOV web
v3 with optional neurons, weighted wires, meters, motor FWD/REV banks, meter HUD; RE
spiral arena), what was deliberately REVERTED (chassis outline, board sketch — keep the
two distinct views), the PF boundary investigation with its results table, the six
methodology rules learned the hard way, and the open questions. Verified its factual
claims against the code before packaging (22 challenges, probes at N=18-22 with prefabs
attached, BYOV at ?v=7).
KEY THING FOR THE NEXT SESSION TO NOT MISS: the dev12 deep-spiral "not traversable"
conclusion (c17/c18) predates the reachability check and was built the same way as the
sealed cp3 — it is UNVERIFIED and should be re-checked before anything relies on it.

---

## dev14 — IR fold-back, the sweep harness, and maze generation

### The sweep harness now exists (`tools/pf_sweep.py`)

Every "N of 729" figure in this document came from an uncommitted heredoc. None
could be re-run or audited. That is fixed: `pf_sweep.py` reproduces `Hub.tick()`
exactly (same `MOTOR_SPEED`, `PHYS_DT`, `force_to_motors`, sliding collision).

The 729 config grid was **reconstructed from the shipped `FT_CP*_solution.json`
prefabs**, which between them use lateral offsets {-0.04, 0, +0.04} and angles
from {-90,-70,-45,-20,0,+20,+45,+70,+90} — 27 mountings per sensor, 27² = 729.
Acceptance test: all five shipped prefabs solve, at 6.5 / 6.5 / 33.7 / 13.1 /
17.0 s against the recorded 6.5 / 6.5 / 34 / 13.2 / 16.3.

**Caveat, stated plainly.** The reconstruction reproduces cp1 (32 vs 33) and cp2
(12 vs 12) almost exactly, cp3 closely (3 vs 2), but diverges on cp4 (6 vs 1) and
cp5 (18 vs 15). The original grid is unrecoverable, so which is correct cannot be
settled. **Treat the dev14 OFF column as the new baseline** — it is the one that
can be re-run.

### IR fold-back is now modelled, opt-in (`set_ir_foldback`)

User correction: the GP2Y0A21's "18–60 cm" figure is the *practical* monotonic
band, not a sensing limit. Below the peak the output **folds back** — a wall at
4 cm returns roughly the voltage of a wall at 35–40 cm. The sensor does not
saturate up close, it **lies**.

Both simulators clamped to 1.0 below the near threshold (Python at 10 cm, BYOV
web at 18 cm). `_ir_response()` now takes an opt-in `foldback` flag; at contact
it reads 0.145, the same as a wall at 50 cm. **Default is off, and the curve with
the flag off is bit-identical to the previous one** (verified across 0–1 m), so
no existing challenge or recorded result changes silently.

### Re-measurement: fold-back does not make things harder, it makes them DIFFERENT

| probe | dev12 (unverifiable) | dev14 OFF | dev14 ON |
|---|---|---|---|
| cp1 centered barrier | 33 | 32 | 25 |
| cp2 U-trap | 12 | 12 | 6 |
| cp3 double-back | 2 | 3 | **31** |
| cp4 shallow spiral | 1 | 6 | **1** |
| cp5 dead-end | 15 | 18 | **44** |

cp1/cp2/cp4 get harder. **cp3 gets 10× easier and cp5 nearly 2.5× easier.**

The mechanism: clamping to 1.0 makes a wall *maximally repulsive at contact*, so
an IR·Flee blasts the robot away from any surface it touches. Fold-back weakens
near-wall repulsion, letting the robot **hug and slide along a wall** instead.
cp3 and cp5 both require travelling away from the goal along a wall or out of a
pocket — exactly what wall-hugging enables. cp1/cp2/cp4 need strong repulsion to
steer around obstacles, and lose it.

The winning cp3 config under fold-back is **LDR +90 / IR +90** — both aimed hard
sideways at the wall. That is a wall-follower morphology, and the optimistic
model was suppressing it.

**Consequence for FW-013:** the honest sensor model is not merely more realistic,
it is what makes wall-following reachable at all. Since mazes are solved by
wall-following (below), fold-back should probably be ON for maze challenges.

### Maze generation (`engine/maze/`)

Ported from the user's Amazing Kingdoms web game (`maze.html`). The xorshift PRNG
and `carve()` are bit-identical to the JS — verified against Node; note JS `>>`
is a *signed* shift and a naive port diverges at the 4th value. **A seed produces
the same maze in the browser and in PAW.**

- `carve()` is a randomised depth-first backtracker → **perfect maze** (spanning
  tree, no loops). The JS validator asserts this directly (`edges/2 == w*h-1`).
- `to_arena()` emits PAW arena geometry, merging collinear wall runs.
- **A memoryless wall-follower solves 80/80 generated mazes** across 40 seeds and
  both handednesses, at 1.2–1.7× the optimal path. Loop-freeness is not what
  makes mazes hard for a reactive robot — it is what makes them **solvable**.

This relocates the FW-013 tiers: tier 1 = gradient seek (fails on long
away-from-goal runs); tier 2 = consistent-handedness circulation (**any** perfect
maze); tier 3 = memory, which requires **braided** mazes with loops. To reach
tier 3 the generator must *add* loops after carving.

### Geometry constraints found (`tools/arena_check.py`)

Reachability + connected components + **maximin corridor clearance**. That last
one was missing and it matters:

- **c17/c18 spiral corridors are 10.5 cm clear for a 9.4 cm robot — 5.5 mm per
  side.** Below the project's own ≥0.16 m comfort rule. The dev12 "not traversable
  by reactive control" verdict is *confounded*: too-narrow-to-fit and
  too-hard-to-control both predict the observed failure. Still unverified, for a
  different reason than dev13 expected. (Reachability itself passes — the sealed
  chamber defect does **not** apply here.)
- c17/c18 also have a sealed 8115-cell strip below the outer ring, ~32% of free
  space, permanently unreachable.

Three constraints converge on maze sizing at RE scale (1.5 × 2.5 m, robot 15.5 cm):

| corridor | grid | optimal | wall-follower | side IR |
|---|---|---|---|---|
| 20 cm | 6×10 | 61 s | 92 s | **inside fold-back zone — lies** |
| 28 cm | 4×7 | 41 s | 62 s | marginal |
| **35 cm** | **3×6** | **34 s** | **51 s** | **honest** |

At 0.175 m/s a 45 s budget buys 7.9 m; a 6×10 maze needs 16 m. Fold-back and the
time budget push the same way: fewer, wider cells. Wall-following still solves
80/80 at 3×6.

### The goal light is already a recogniser, not a beacon

Measured a green-channel LDR from every cell of a generated maze's solution path:
zero on 27 of 38 cells, and completely non-monotonic in distance — 0.14 at a
metre down a clear corridor, 0.00 at 25 cm through a wall. Wall shadowing gives
"only visible in line of sight" for free.

Recommendation adopted: **success = positional dwell** (ground truth), with a
coloured light marking the goal that the robot needs its own recogniser to stop
on. `color_reading()` and `contact_reading()` already exist in
`sensor_physics.py`.

### BYOV web cannot host mazes as built

Geometry imports trivially (it already has internal walls, wall collision, IR
raycasting, LDR occlusion — only a corner-origin vs centre-origin shift and a key
rename). But `IR.MIN_RANGE = 0.18` returns a flat 1 below 18 cm: side-IR is
**completely blind** below a 28 cm corridor, which in its 1.2 m arena permits a
maze 3 cells wide. Either BYOV's IR adopts the Python model, or BYOV does not get
mazes.

### Still open

- Wall-following in *continuous* space through 3- and 4-way junctions is
  untested; the 80/80 result is on the discrete cell grid. **This is the next
  experiment** and the one thing that decides whether tier 2 is real.
- Field Trip still cannot load arena JSON (RE can; `arena_builder` writes it).
  Agreed direction: generator writes JSON, challenge reads it, provenance
  invisible — the same contract Amazing Kingdoms uses.
- Migrate the robot to RE scale while letting each challenge declare its own
  arena size, so early challenges stay quick.

---

## dev14b — scale migration, and what it did to every prior conclusion

### What changed

`BODY_RADIUS` 0.047 → **0.0775** (`games/ethology/robot.json`), and every legacy
arena scaled by `WORLD_SCALE = 1.6489` in `Challenge.__post_init__`. Arenas go
from 0.6 × 0.8 to **0.99 × 1.32 m**, inside RE's 1.5 × 2.5 floor with room left
for mazes. `MOTOR_SPEED` 0.25 → 0.35 (hardware max), durations × 1.178 so time
budgets are unchanged in travel-distance terms. New challenges set
`prescaled=True` to opt out.

**The old radius was a bug, not a choice.** The chassis is *drawn* as a 169 mm
octagon (`robot_builder`'s `bsquare_m`), so the robot collided as a circle barely
half the size of the body on screen and slid through gaps it visibly could not
fit. 0.0775 brings collision into line with what the player sees.

Relative geometry is preserved exactly — clearances scale with the robot, so
c17/c18 remain razor-thin (6 mm/side) and everything else is unchanged in
proportion. Sensor mount offsets and the IR/LDR response curves are deliberately
NOT scaled: a peg hole is where it is, and a sensor's 10 cm is 10 cm.

### The result: the probe difficulties were largely an artifact of arena size

| probe | dev12 | dev14 pre-migration | **dev14b OFF** | dev14b ON |
|---|---|---|---|---|
| cp1 centered barrier | 33 | 32 | **18** | 15 |
| cp2 U-trap | 12 | 12 | **57** | 51 |
| cp3 double-back | **2** | 3 | **45** | 39 |
| cp4 shallow spiral | 1 | 6 | **9** | 10 |
| cp5 dead-end | 15 | 18 | **94** | 99 |

cp3 — the probe the whole PF-boundary argument rested on, at "2 of 729, a very
narrow needle" — is **45 of 729** at the corrected scale. cp5 goes 15 → 94.

The cause is that the sensor curves have absolute length scales while the arena
did not. In a 0.6 × 0.8 m arena the robot was almost always inside 10 cm of a
wall, where IR is pinned at 1.0 and carries no gradient. Scaled up, walls sit in
the graded part of the curve and the same morphologies steer far better.

**The dev12/dev13 PF-boundary conclusions were measured in an arena too small for
the robot's own sensors.** They should be treated as void rather than merely
unverified. Only cp1 got harder.

### Fold-back mostly dissolved too

Pre-migration, fold-back flipped cp3 from 3 to 31 and cp5 from 18 to 44. Post-
migration the ON and OFF columns differ by a handful of configs (18/15, 57/51,
45/39, 9/10, 94/99). Same reason: fewer readings now land in the sub-10 cm zone
at all.

So the dev14 claim that "the honest sensor model is what makes wall-following
reachable" was itself an artifact of the too-small arena — it is **withdrawn**.
Fold-back still matters for maze corridors, where the robot is deliberately close
to walls, and it still sets the ~30 cm minimum honest corridor. But it is not the
tier-2 enabler dev14 claimed.

### Open

- Every "N of 729" figure predating dev14b is void. `tools/pf_sweep.py` is the
  only re-runnable source; regenerate anything that matters.
- c16/c17/c18 have not been re-swept at the new scale.
- The maze work is unaffected — it was always authored at RE scale.

---

## dev14c — PyBulletAdapter made to work

### Environment: PyBullet builds, but budget for it

No prebuilt wheel exists on PyPI for any platform — pybullet is source-only, and
it took **~13 minutes to compile on this sandbox's single core**. Two earlier
attempts died silently because a bash command timeout kills its whole process
group; `setsid nohup ... &` survives.

A built wheel is saved to `outputs/wheels/pybullet-3.2.7-cp312-cp312-linux_x86_64.whl`.
Since the filesystem resets between sessions, **re-upload that wheel rather than
rebuilding**:

    pip install <path>/pybullet-3.2.7-cp312-cp312-linux_x86_64.whl --break-system-packages

### PyBulletAdapter had never been executed — four bugs, all on the hot path

Not "an abstraction to adopt". 390 lines of never-run code:

1. `reset_robot()` passed `physicsClientId` to `RobotModel.reset_pose()`, which
   does not accept it (the client is bound at construction).
2. `RobotModel.apply_drive()` **did not exist**. The adapter's `step()` called it.
3. `load_world()` constructed `ArenaModel` but never called `build()`.
4. `load_world()` constructed `RobotModel` but never called `create_body()`, so
   `_body_id` stayed -1 and every PyBullet call failed with
   `GetBasePositionAndOrientation failed`.

All fixed. `tools/test_pybullet_adapter.py` now exists — 11 assertions, all
passing. **Its absence is precisely why this sat broken**: RE talks to
`simulation.py` directly, so nothing ever touched the adapter.

### apply_drive: the sign convention, resolved

Firmware `CogServo::driveProportional` negates **left**, then maps with
`map(prop, -100, 100, 180, 0)` — an **inverted** map.
`engine/hal/sketch_bridge.py` negates **right** and uses a **non-inverted** map,
with a comment claiming it mirrors CogServo. The two inversions cancel; both
yield `left_angle = 90 + L*0.9`, `right_angle = 90 - R*0.9`. Correct, but the
comment misdescribes why. `RobotModel.apply_drive()` documents the derivation.

Turn rate worth knowing: at `wheel_base = 0.08`, a full differential command
gives **omega = 8.75 rad/s — about 1.4 rev/s**. The first version of the smoke
test failed its own sign check because 0.5 s of turning wraps past 180 degrees.
The adapter was right; the test was wrong.

### `dt` is a primitive duration, not a physics timestep

Corrected from dev14b, where this was wrongly listed as an interface mismatch.
`PhysicsAdapter.step(left, right, dt)` mirrors
`driveProportional(leftProp, rightProp, durationInSeconds)`: hold this command
for this long, no sensing, no re-decision. The adapter now applies the command
once and sub-steps the engine at its own fixed timestep until `dt` is consumed.
Verified: doubling `dt` doubles distance travelled (ratio 2.00).

**Throughput: ~110x realtime** (200 primitives of 0.05 s in 0.09 s), physics
only, no sensor computation. The earlier worry that PyBullet would be too slow
for the 729-config sweep was unfounded, though the sweep's real cost is sensor
ray casting, not integration.

### RE handles primitive durations correctly — it is the reference

`ArduinoHAL` emulates Arduino's blocking `delay()` without blocking the sim:
`driveProportional` writes servo angles, `_delay(ms)` records a resume timestamp
in a `TimedAction`, and `call_loop()` returns early while it is active — skipping
`loop()` entirely until the duration expires, with the written angles still in
force. `SketchBridge.install()` wires it up. So a 0.5 s primitive commits the
robot for 0.5 s of un-re-evaluated motion, exactly as on hardware, and behaviours
built from primitives of mixed duration (0.1 / 0.2 / 0.5 / 1.0 s in
`EthologyRobot.cpp`) keep their ratios.

Two stale comments in `engine/hal/ethology_robot.py` claimed the opposite — that
"the simulation tick rate determines effective duration". **That doc error caused
a wrong architectural conclusion earlier in this session** (that the pin-level
interface was an impedance mismatch to bridge around). Both corrected.

### Field Trip does NOT honour the contract — next task

`Hub.tick()` recomputes `compute_force` -> `force_to_motors` every physics tick:
60 Hz, against firmware that decides at `TICK_MS = 50` (20 Hz) and commits for
50 ms. `CYCLE_S = 0.5` exists in `hub.py` but gates only repulsor grace
bookkeeping, not control.

Measured on cp1: **18/729 at 60 Hz, 24/729 at the hardware 20 Hz.** A fifth
independent source of number-invalidation, after the sealed arena, corridor
width, world scale, and control rate.

Field Trip needs a `TimedAction`-equivalent gate modelled on `ArduinoHAL`.

### Remaining, in order

1. Field Trip control loop gated on primitive duration.
2. Field Trip acquires a `RobotConfig`; drop `_blocked()` and the inline loop;
   move onto `PyBulletAdapter`.
3. `pf_sweep` onto the same adapter; re-run the probes.
4. Regenerate all five solution prefabs — **four of five currently fail**
   (cp2, cp3, cp4, cp5), broken by the dev14b scale migration. Criteria agreed:
   legibility first, robustness as tiebreaker, speed only as a floor (reject
   anything near the time limit).

---

## dev14d — playtest findings (user, all three games)

### RE: behaviours read as physically correct

User confirms the hierarchy's behaviours look like what the physical robots do.
That validates `ArduinoHAL`'s `TimedAction` gate as the reference implementation
Field Trip should copy.

### RE: avoidObject CANNOT traverse any corridor that fits in its own arena

User: the robot "just sits at the heart of the spiral and oscillates."

Diagnosed and quantified. `PROX_THRESHOLD = 33` fires at **~35 cm** from a wall.
Measured corridor of `arena_spiral.json` via `tools/arena_check.py`: **19.0 cm**
(17 mm clear per side) — note the arena's own docstring claims ~0.24 m, which is
wrong.

In a 19 cm corridor **both** proximity sensors are permanently under threshold,
so `avoidObject` never leaves this branch:

    if rp <= PROX_THRESHOLD and lp <= PROX_THRESHOLD:
        if rp <= lp: driveProportional(-40, 40, 0.3)    # turn left
        else:        driveProportional( 40,-40, 0.3)    # turn right

Turn left -> left wall closer -> next decision turns right -> oscillation. It is
structural, not a tuning nuance. For either sensor to read clear you need
`corridor/2 > 35 cm`, i.e. **corridor > ~70 cm** — two corridors across RE's
1.5 m arena.

**Consequence for the maze question.** A fixed hierarchy cannot solve mazes
*as currently written*, and the reason is not the hierarchy: `avoidObject` was
tuned for open-arena obstacle avoidance and has no corridor case. It needs
either a corridor mode (both-triggered -> drive straight, centre between walls)
or a much shorter threshold. **This is a bigger constraint than the ~30 cm
fold-back minimum**: hierarchy robots need 70 cm corridors, PF robots need 30 cm.
Any maze arena has to state which it is for.

### Field Trip: scale better, aspect ratio still wrong

User: robot scale looks better, builder scale fine, pacing good for the first
handful of challenges. But **arena dimensions still differ from RE's**.

FT is now 0.99 x 1.32 (aspect 0.75); RE is 1.5 x 2.5 (aspect 0.60). dev14b
scaled the legacy arena rather than re-shaping it, so the proportions are
inherited from the old 0.6 x 0.8. Options, undecided:
  (a) fixed render scale (metres-per-pixel pinned to RE) so FT visibly occupies
      a *portion* of the same world — matches the stated intent that early
      challenges use part of the arena, and needs no re-authoring;
  (b) re-author FT arenas at RE's aspect ratio — changes every challenge layout;
  (c) accept the difference and document it.
(a) looks right and is the one that also fixes the 1.9x on-screen robot size
jump between arenas noted in dev14.

### Valentino's: point-robot collision FIXED

User: "Overlap with walls is pretty bad" — confirmed by screenshot showing the
robot's centre stopped at the wall face with its whole front half buried inside.

`SimpleDriveAdapter.__init__` took no `body_radius` and `_inside_wall()` used
only half the wall thickness as its margin, i.e. it treated the robot as a
dimensionless point. Fixed:
  - `body_radius` parameter added (default 0.0775, from RE's robot.json)
  - boundary margin is now the body radius
  - internal walls use `body_radius + wall_half_thickness`
  - wall thickness now read from the **arena** (per-wall `thickness`, falling
    back to the arena's `wall_thickness`) instead of the module constant
    `_WALL_T = 0.012`, so arenas at different scales collide correctly

Verified: overlap into the boundary goes from ~77.5 mm to 0.0 mm; the body edge
now stops at the wall face for both boundary and internal walls.

VV's arena is 0.5 x 1.0 — still a third aspect ratio, unaddressed.

---

## dev14e — PROX_THRESHOLD 20 cm (one variable, under test)

### The threshold was diverging three ways

| location | was | now |
|---|---|---|
| `engine/hal/ethology_robot.py` (simulator) | 33 | **20** |
| `firmware/ethology_ble_robot/EthologyRobot.h` | 35 | **20** |
| `firmware/ethology_standalone/EthologyRobot.h` | 35 | **20** |
| `materials/arduino_classes/EthologyRobot.h` | 35 | **20** |
| `engine/bluetooth/mock_bt_server.py` | 15 | **20** |

`tools/calibration/calibration_receiver.py` still uses 35 — an analysis constant
in a measurement tool, not robot behaviour. Left pending review.

### Units, settled

`CogProximity::analyzeData` maps raw [120,720] -> **[60,18] CENTIMETRES** — the
sensor's PRACTICAL band. The firmware's own comment on that line says
"map to [10, 80]" and is **wrong**; the code is right. The Python HAL had a
matching wrong comment ("18=10cm, 60=80cm"). Both corrected.

`getData()` **SATURATES at 18**: a wall at 18 cm and a wall at 2 cm both read 18.

### The hard floor this implies

A robot centred in a corridor of clear width C has each 45-degree sensor seeing
`(C/2 - 0.0548) * sqrt(2)`. For that to be a live reading rather than the clamp,
**C > ~36 cm** (41 cm centre-to-centre with 5 cm walls). Below it both sensors are
pinned and there is no gradient to steer on, whatever the threshold.

So the threshold change does NOT rescue `arena_spiral.json` (19 cm corridors,
sensors at 5.7 cm, both pinned at 18). Testing there will show no improvement,
for reasons that are not about the threshold.

### Test fixture: games/ethology/arenas/arena_corridor_test.json

Serpentine, **44 cm clear corridors** (25 cm builder grid x2), 1.45 x 2.45 m.
Validated: start clear, goal reachable, 0.0% stranded space.

Falsifiable prediction, so the experiment can fail honestly:

| arena | position | L | R | expected |
|---|---|---|---|---|
| spiral (19 cm) | centred | 18.0 | 18.0 | both trigger -> oscillate |
| spiral (19 cm) | drifted 10 cm | 19.8 | 18.0 | both trigger -> oscillate |
| **corridor test (44 cm)** | centred | 23.4 | 23.4 | **clear -> cruise straight** |
| **corridor test (44 cm)** | drifted 10 cm | 37.5 | 18.0 | **R triggers -> steer left** |

If the corridor test still oscillates while centred, the saturation model is
wrong and the diagnosis needs revisiting.

### Expected regression, watch for it

Open-arena avoidance now triggers at 20 cm instead of 33. At 0.35 m/s with 0.3 s
primitives the robot covers ~10.5 cm per decision, so it will pass much closer to
obstacles and will sometimes reach the bump sensors before avoiding.
`escapeFrontCollision` handles that, so it is recoverable rather than broken — but
it is a visible behaviour change to a game that previously read correctly.

### Grid: NOT changed, deliberately

One variable at a time. For the record, the 36 cm floor forces **3 x 5** cells in
a 1.5 x 2.5 arena at every viable grid, so the grid choice affects placement
granularity, not maze size. **The existing 25 cm grid already works** (x2 = 45 cm
corridor, tiles 1.5 and 2.5 exactly). A finer grid (12.5 cm x4, same 45 cm
corridor) would only buy placement resolution for non-maze features. If 3 x 5 is
too small the lever is arena width, not grid.

---

## dev14f — Arena Editor: Open did not put the arena into play (FIXED)

User: opening `arena_corridor_test.json` in RE's Arena Editor, then Save / Launch
/ Done, returned an arena with no interior walls.

### Cause: one variable doing two jobs

`ArenaBuilder._arena_path` was both "the file being edited" and "the slot the
game reads back". RE launches the builder with

    --arena games/ethology/arenas/session_current.json

and after the editor exits reads `_working_arena()`, whose precedence is
session -> bundle -> default. So `--arena` is an **output slot**, not a document.

`_load_dialog()` repointed `_arena_path` to the browsed file and set
`_dirty = False`. Consequences:

- **Done** -> `_request_done` saw `_dirty == False` and exited without saving.
  `session_current.json` never written; RE fell through to the default arena.
- **Save** -> wrote to the browsed file (`arena_corridor_test.json` onto itself).
  The session slot was still never written.
- **Launch** -> `_save()` likewise hit the wrong path.

### Fix

`_session_path` now records the `--arena` slot separately from `_loaded_from`
(caption only). Opening an arena loads its CONTENT into the slot and does not
redirect where the slot writes, and marks the session dirty so Done/Save
actually write it. `_request_done` always writes the slot when one exists, even
if the user opened an arena and edited nothing — exiting the editor should leave
the game running whatever is on screen.

Standalone use (no `--arena`) is unchanged: Open still repoints the save target,
which is correct for a document editor.

Verified: session slot 0 internal walls -> Open corridor test -> Done -> session
slot has 4 internal walls, source file untouched.

### Related, NOT fixed — flagging only

The builder's **Launch** button starts `main.py --arena <path>`, a standalone
runner, not the RE hub. Separately, `Hub.__init__` calls
`_clear_session_arena()`, so a freshly launched RE deletes
`session_current.json` on startup. Launch-from-builder therefore takes a
different route from Done, and now that Done works the two may disagree. Worth
deciding whether Launch should exist in the hub-launched context at all.

---

## dev14g — VV regression fixed, serpentine ported to FT

### VV scale DID backslid — my error

dev14d gave `SimpleDriveAdapter` a `body_radius` defaulting to **0.0775** (the
octagon inradius). **VV's robot is the rectangle chassis, 94 x 167 mm** — half
width 4.7 cm. So the default was 1.6x too large and the robot stopped ~3 cm clear
of side walls: floating instead of overlapping. Over-corrected from one visible
error into its mirror image.

Fixed properly: `engine/builder/robot_builder.chassis_collision_radius(spec)`
returns the INSCRIBED radius of the actual chassis —
rectangle 4.70 cm, octagon 8.45 cm, triangle 5.97 cm — and VV passes it.

This is the chassis-loading argument in miniature: **a hardcoded collision radius
is wrong for any chassis but one.** The rectangle's 1.78 aspect also means a
circle is a poor model at all — the nose can still overlap a head-on wall by up
to 3.6 cm. Real polygon collision (PyBulletAdapter) is the actual fix.

### Field Trip can now load arena JSON

`challenges.load_arena_json(path)` — the format is byte-identical to what RE
loads and `tools/arena_builder.py` writes, so an arena is portable and a
challenge cannot tell whether its arena was authored or generated. Arenas loaded
this way are already at the correct robot scale, so those challenges set
`prescaled=True`.

### cp6 "Probe: Serpentine Corridor" — sequence position 23

    python games/field_trip/hub.py --challenge 23

The SAME arena JSON that RE's hierarchy traverses. 1.45 x 2.45 m, 44 cm
corridors, 90 s budget.

### PREDICTION WRONG: push/pull DOES solve the serpentine

dev14f predicted PF would fail for lack of a forward-drive term when the side
walls cancel and the light is occluded. A coarse sweep (225 configs, every 2nd
angle) finds **6 that solve**, best 58.3 s of the 90 s budget.

Every winner has **IR at -90 degrees with a +0.04 lateral offset** — a
side-facing repulsor mounted off-centre. That is the user's own
emergent-circulation morphology, and it evidently supplies handedness AND enough
forward component. So PF needs no explicit cruise term; the morphology carries
it.

Narrow (6/225 = 2.7%) and slow (65% of budget), consistent with the cp3/cp5
pattern: reactive control solves these, but from a thin band of configurations.

Braitenberg remains untested.

### Arena sizes still do NOT match — decision needed

| game | arena | wall_t |
|---|---|---|
| Robot Ethology | 1.5 x 2.5 | 0.05 |
| Valentino's | 1.2 x 1.6 | 0.025 |
| Field Trip | 0.989 x 1.319 | 0.041 |
| NTV `arena_gen` | 0.5 x 1.0 | - |
| (cp6, ported) | 1.45 x 2.45 | 0.05 |

Aspect ratios differ too: FT 0.75, RE 0.60. So matching RE is **not** a uniform
scale — FT's 22 legacy challenges would either be re-authored, or their content
centred in a larger canvas (leaving margins the robot can wander into, which
changes avoid-light challenges). Builder grid is 0.25 m and applies to all.

---

## dev14h — one shared arena canvas (engine/arena/world.py)

### The module

`engine/arena/world.py` is now THE place arena dimensions are defined. No game
declares its own floor.

    CANVAS_W, CANVAS_H = 1.5, 2.5     # the physical lab floor (RE's figures)
    WALL_THICKNESS     = 0.05         # the physical wall block
    GRID_M             = 0.25
    SENSOR_HONEST_MIN_CORRIDOR = 0.30 # below this the IR folds back and lies
    PROX_GRADIENT_MIN_CORRIDOR = 0.36 # below this RE's prox saturates, no gradient

    fit_to_canvas(arena) -> (arena, k)   uniform scale, boundary becomes canvas
    conforms(arena)      -> [problems]   empty means conforming

**Scaled:** wall endpoints, light positions and radii, robot start position —
layout, i.e. where things sit relative to each other.
**Not scaled:** wall THICKNESS (a physical block is 5 cm in any game), the robot
(a chassis property), and sensor response curves (10 cm is 10 cm anywhere). That
last one is why a bigger arena is a genuinely different problem rather than the
same one drawn larger.

The fit is UNIFORM. A non-uniform stretch would distort angles and make
horizontal corridors a different width from vertical ones.

### Applied

| | was | now |
|---|---|---|
| Robot Ethology | 1.5 x 2.5, wall 0.05 | unchanged (factor 1.0) |
| Field Trip | 0.99 x 1.32, wall 0.041 | **1.5 x 2.5, wall 0.05** (x2.5 from raw) |
| Valentino's | 1.2 x 1.6, wall 0.025 | **1.5 x 2.5, wall 0.05** (x1.25) |

FT applies it in `Challenge.__post_init__`; VV and RE get it in
`engine/arena/__init__.load_arena()`, so any arena JSON any game loads is fitted
on the way in. All 23 FT challenges and all 3 RE arenas conform.

### Corridors moved into the sensor-honest range

| | before | after |
|---|---|---|
| c10 | 31.0 | 64.8 |
| c16 The Maze | 27.9 | **43.8** |
| cp1 | 20.2 | **31.4** |
| cp3 | 24.6 | **38.8** |
| cp5 | 24.6 | **38.8** |
| c17/c18 Spiral | 16.8 | 26.6 — **still below the 30 cm floor** |

Six of nine cross the floor. Their walls move OUT of the IR fold-back zone,
where readings had been reporting a distant surface while touching a near one.
The spirals remain a known exception.

### engine/arena.py IS DEAD CODE

`engine/arena.py` (12 KB) is permanently SHADOWED by the `engine/arena/`
PACKAGE — Python resolves `import engine.arena` to `engine/arena/__init__.py`.
Nothing has ever imported the module. Discovered by editing it and having the
change do nothing.

Marked with a header; NOT deleted, so removal is deliberate. Someone should diff
it against the package and delete it.

### Durations are a placeholder

Distances grew x2.5 while `MOTOR_SPEED` is already at the 0.35 m/s hardware
ceiling, so budgets stretch by x1.79 (a 30 s challenge becomes 53.6 s). The
intended fix is **deliberate robot placement** — a bigger arena does not require
starting the robot in the far corner — not a larger multiplier. Starts are
carried through unchanged, scaled with the layout, pending review.

Per user: the boundary is the wrong lever for avoid challenges anyway. A robot
parked far from the light satisfies "avoid" by doing nothing and teaches nothing;
starting it INSIDE the light's field of influence forces a real push.

### Next

- Review the 23 robot starts and headings (position + orientation, per challenge).
- Re-run `pf_sweep` — the numbers move a sixth time, this time describing a robot
  whose sensors actually work.
- Regenerate the five solution prefabs afterwards.

---

## dev14i — ACTION unified: polygon physics in all three games

### The root register bug: the octagon was 9% too big

`robots/ethology_v2.json` (CAD source) gives `chassis.bounding_square_mm = 155`.
`robot_builder.CHASSIS["octagon"]` said **0.1690** ("70 mm edges") while the same
file's header comment said 155 mm. The header was right.

0.155 / 2 = **0.0775** exactly — RE's `body_radius` IS the octagon inradius. So
the builder had been drawing a chassis 9% larger than the robot every other part
of the system assumed. Corrected, along with the triangle whose circumradius is
derived from the octagon's bounding circle.

### What each game did BEFORE

| game | shape | radius |
|---|---|---|
| Robot Ethology | cylinder | 0.0775 |
| Field Trip | circle, hand-rolled `_blocked()` | 0.0775 for EVERY chassis |
| Valentino's | circle, `SimpleDriveAdapter` | chassis-derived, 0.047 for the rectangle |

The same rectangle robot was a 4.7 cm circle in VV and a 7.75 cm circle in FT — a
65% difference in one physical body, introduced in dev14g while fixing VV's
floating robot. Every chassis was DRAWN as a polygon in all three games and
COLLIDED as a circle in all three.

### What they do now

All three collide as the polygon they are drawn as, from one implementation.

- `RobotConfig` carries `chassis_spec`, derived from `geometry` +
  `bounding_square` when a robot.json describes itself the CAD way — which is
  why RE's polygon path was dormant despite the data being present.
- `RobotModel.create_body()` builds a convex hull from `chassis_polygon_m()`
  instead of a cylinder, falling back to a cylinder when no spec is given.
  (`createVisualShape` needs indices as well as vertices for a mesh, so polygon
  bodies use `vis_id = -1`; nothing renders from PyBullet, the games draw from
  the pose.)
- **Field Trip** `_Sim.tick()` now calls `PyBulletAdapter.step(left, right, dt)`.
  Deleted: the per-axis sliding fallback and the differential-drive integration.
- **Valentino's** moved from `SimpleDriveAdapter` to `PyBulletAdapter`.

### Two bugs died as side effects

- **Wheelbase.** FT computed `omega = (right-left) * MOTOR_SPEED / (BODY_RADIUS*2)`
  — 0.155 where `robots/ethology_v2.json` gives 0.080. Field Trip had been
  simulating a robot turning at about half the real rate. `WHEEL_BASE = 0.080`
  is now named separately and passed to the adapter.
- **Primitive duration.** `step(left, right, dt)` treats `dt` as how long the
  command is HELD, mirroring `driveProportional(l, r, durationInSeconds)`.

### Measured: polygon contact differs from circle contact

Driving into a wall for 10 s (boundary y = +1.25):

| shape | heading | stop y | slid x | final heading |
|---|---|---|---|---|
| cylinder 7.75 cm | 90 | +1.1725 | +0.001 | 89.3 |
| cylinder 7.75 cm | 60 | +1.1725 | +0.673 | 64.1 |
| octagon polygon | 90 | +1.1645 | +0.003 | 90.0 |
| **triangle polygon** | 90 | +1.1899 | **-0.368** | **120.2** |
| **rectangle polygon** | 60 | +1.2020 | +0.664 | **90.0** |

The triangle catches on its nose and pivots 30 degrees. The rectangle driven in
at 60 degrees **torques itself square against the wall** and then slides — the
"catch a corner, slip in, bump around, come free" behaviour a circle cannot
produce, because a circle has no corner and no orientation.

### Consequences to expect

- **All sweep numbers are void again** — seventh time, and this one is
  substantive: rigid-body contact with a real chassis outline is a different
  problem from a sliding circle, and FT's turn rate roughly doubles.
- Solvability is now genuinely per-chassis. The same challenge is a different
  problem for the octagon, triangle and rectangle. That is the intended lever,
  not a defect.
- `SimpleDriveAdapter` now has no callers. Keep as the documented fast
  approximation or delete after the conformance comparison.

### Still open

- Re-run `pf_sweep` on the adapter, then regenerate the five prefabs.
- Robot start placement review (23 challenges, position and heading).
- Start screens: PAW-Bot in the narrative panel, a stylistic scene per game.

---

## dev14j — canvas fit gap fixed; render clipping NOT yet diagnosed

### Fixed: load_arena's early return bypassed the canvas fit

`engine/arena/__init__.load_arena()` returns `dict(DEFAULT_ARENA)` early when the
file is missing — **before** the dev14h fit. So any caller hitting a missing path
got a 1.0 x 2.0 arena while every real arena was 1.5 x 2.5. Now fitted on that
path too.

### Verified, so these are NOT the cause of the clipping

- VV's arena loads as **1.5 x 2.5, conforming, 0 internal walls** — the green
  bars in the screenshot are the boundary, not content.
- `arena_scale()` and `world_to_screen()` in `games/valentinos/arena/arena.py`
  are **byte-identical** to `engine/arena/__init__.py`, same `MARGIN = 28`. The
  duplicate-module hypothesis is wrong.
- FT's `_canvas_rect` = `Rect(PANEL_W, 0, ww-PANEL_W, wh-2)`; VV/RE use
  `Layout.arena` = `Rect(pw, 0, ww-pw, wh)`. Near-identical.

**I could not reproduce the clipping headlessly and have not found the cause.**
Not asserting one.

### Third duplicated module found

`games/valentinos/arena/arena.py` duplicates `engine/arena/__init__.py`. After
`engine/arena.py` (dead, shadowed) that is two redundant copies of the arena
renderer. Consolidating is the right fix regardless of the clipping cause.

### User's proposal (agreed, not yet done)

FT renders the arena fully visible with letterboxing and looks cleanest. RE and
VV should render through the SAME path: one shared canvas rect and one
`draw_arena`, with the VV local copy deleted.

### Open, blocking playtest

- **VV vehicle demo does not play.** Not diagnosed. The adapter works in
  isolation (steps, poses, ray_casts, contacts) so it is not a bare adapter
  failure.
- Render clipping in RE and VV.
- FT arena resize effects on challenges — deliberately deferred by the user until
  the above are fixed.

---

## dev14k — render clipping: ruled out the fit math, added a runtime probe

### What the three full-screen comparisons establish

All three games call `Layout.compute_window_size(0.90)`, so the window is
identical. Computing the canvas rect and scale for each:

| | canvas rect | scale |
|---|---|---|
| Field Trip (`PANEL_W = 440`) | `(440, 0, w-440, h-2)` | 176.8 px/m |
| VV / RE (`Layout.arena`, panel_w 256) | `(256, 0, w-256, h)` | 177.6 px/m |

(at the headless 800x500 dummy size; the ratio is what matters)

**Near-identical.** Different panel widths do NOT change the arena size, because
for a 0.6-aspect arena in these rects the HEIGHT is the binding constraint in all
three. So the clipping is not the canvas rect and not `arena_scale()`.

Also already ruled out: VV's arena loads conforming at 1.5 x 2.5;
`arena_scale()` and `world_to_screen()` in `games/valentinos/arena/arena.py` are
byte-identical to the engine's with the same `MARGIN = 28`.

From the screenshots, FT renders at aspect 0.606 and RE at 0.613 (both correct,
1.5/2.5 = 0.60) while **VV measures ~0.537 — off-aspect**, suggesting VV and RE
may be two DIFFERENT bugs rather than one.

### Runtime probe added

`draw_arena()` now honours `PAW_RENDER_PROBE=1`, printing once per distinct
(rect, arena) pair:

    [RENDER-PROBE] surf=(W,H) rect=(x,y,w,h) arena=1.5x2.5 wall_t=0.05
                   scale=NNN.Npx/m box=WWWxHHH top=.. bottom=.. left=.. right=..

Off by default, at most a few lines. Run each game once with it set and compare
`box`/`top`/`bottom` against the actual window height — that identifies whether
the arena is being drawn oversized, offset, or with a stale arena dict, without
further inference.

This is deliberately a diagnostic rather than a fix: the fit math is provably the
same across games, so guessing further would only produce another wrong theory.

---

## dev14l — VV intro arena off-aspect: FOUND and FIXED

### Cause

VV's `vv_intro_*` states do NOT draw `self._arena`. They draw
`self._intro_arenas[idx]`, built by
`games/valentinos/games/ntv/arena_gen.generate_arena()` — which authors at
**0.5 x 1.0** and never passes through `load_arena()`, so it never received the
dev14h canvas fit.

0.5 / 1.0 = **0.50**, matching the ~0.537 aspect measured off the user's
screenshot, against 0.60 everywhere else. `arena_gen.py` was the last remaining
producer of a non-conforming arena in the suite — the inventory in dev14h listed
it and it was the one path not wired up.

### Fix

`generate_arena()` now fits its output to the shared canvas before returning.
Verified: all three motives return 1.5 x 2.5, wall_t 0.05, conforming.

**CAVEAT:** the fit is x2.5, so `arena_gen.py`'s stated design principle —
"features placed so sensors are active within the first 2-3 seconds" — needs
re-checking. Placement scales; sensor RANGES do not. This is the same class of
issue as everywhere else in dev14, and it now applies to the generator's core
guarantee.

### The probe printed nothing — two possible reasons

1. The user may have unzipped `...az.zip` (documentation) rather than
   `...ba.zip` (the first package containing the probe).
2. Independently: **Robot Ethology does not call `engine.arena.draw_arena` at
   all.** It renders through `engine/renderer/pygame_renderer.PyGameRenderer`
   via `engine/simulation.py` — a SECOND renderer with its own scale and
   centring logic. So the probe would never fire for RE, and RE's clipping is
   almost certainly a property of that renderer rather than of `arena_scale()`.

That makes three renderers in the tree:
`engine/arena/__init__.py` (FT, VV), `engine/renderer/pygame_renderer.py` (RE),
and the dead/duplicate `games/valentinos/arena/arena.py`.

### Still open

- **RE clipping** — inspect `PyGameRenderer`'s own scale/centre computation. It
  is a different code path from everything examined so far.
- **VV demo not playing** — still undiagnosed, though it shares the intro-state
  code path that was just found to use a separate arena source, so worth
  re-testing now.

---

## dev14m — renderer inventory; RE clipping still open, now instrumented

### Three renderers, and RE uses its own

| game | draws via | scale computed in |
|---|---|---|
| Field Trip | `engine.arena.draw_arena` | `engine.arena.arena_scale` |
| Valentino's | `engine.arena.draw_arena` | `engine.arena.arena_scale` |
| **Robot Ethology** | **its own `_draw_canvas` / `_to_screen`** | **`Hub._scale()`** |

Plus `engine/renderer/pygame_renderer.PyGameRenderer` (used by
`engine/simulation.py`) — a FOURTH drawing path, whose `__init__` sizes itself
from the **full desktop resolution** (`pygame.display.Info()` minus 80px chrome)
rather than from the window the games actually create at
`Layout.compute_window_size(0.90)`. Not currently implicated in the hub clipping,
but it is a real divergence and would clip if it ever drew into a hub window.

### What has been RULED OUT for the RE clipping

`Hub._to_screen()` and `Hub._scale()` are **formula-identical** to
`engine.arena.world_to_screen()` and `arena_scale()`:

    scl = min((rect.w - MARGIN*2)/aw, (rect.h - MARGIN*2)/ah)
    cx, cy = rect.left + rect.w//2, rect.top + rect.h//2

Same `MARGIN = 28` in both. Both games build their window from
`Layout.compute_window_size(0.90)`; RE reassigns `WW, WH` from it before
`set_mode`, so the window IS the computed size. For a 0.6-aspect arena in either
canvas rect the HEIGHT is the binding constraint, so the differing panel widths
(FT's fixed `PANEL_W = 440` vs `Layout.panel_w`) do not change the result. FT and
RE compute 176.8 vs 177.6 px/m — a 0.5% difference.

**The arena math is provably the same. The difference must be in the rect or the
arena config actually passed at draw time**, which cannot be established from
compressed screenshots.

### Instrumented

`Hub._draw_canvas` in RE now emits the same `[RENDER-PROBE]` line as
`engine.arena.draw_arena`, gated on the same `PAW_RENDER_PROBE=1`, tagged with
its source. This is required because the original probe lives in `draw_arena`,
which **RE never calls** — the earlier silent run was correct behaviour, not a
missing probe.

Running all three with the flag now yields one comparable line each.

### Remaining Perception work (the last unintegrated leg)

RE's sensors do not go through `engine/sensor_physics.py` at all — they run
through `engine/hal/ethology_robot.py` (`CogProximity` emulation) on the
`ArduinoHAL` path. FT and VV share `sensor_physics`. So "the same sensor" is two
implementations with separately-maintained constants, which is how
`PROX_THRESHOLD` came to hold three different values.

Unifying Perception means deciding whether the HAL's `Cog*` classes should be
thin wrappers over `sensor_physics`, or whether `sensor_physics` should be
expressed in terms of the firmware classes. The HAL is the more faithful model
(it emulates the Arduino), so the second direction is likely right.

---

## dev14n — World rendering unified (the probe paid off)

### The cause, from the user's render_probe.txt

    FT  rect=(685, 36, 493, 822)  scale=291.3px/m  box=437x728  top=83  bottom=811
    RE  rect=(455,  0, 969, 896)  scale=336.0px/m  box=504x840  top=28  bottom=868

Same 1424x896 window, same arena data (1.5 x 2.5, wall 0.05), same scale
formula, same MARGIN=28 — and a 15% difference in rendered size.

**Field Trip had a private `Hub._arena_rect()` that no other game had.** It
pre-shrinks the canvas to the arena's aspect ratio with a **0.92 fit factor**
and centres it; `draw_arena` then applies MARGIN *inside* that. Two insets
compose. RE and VV passed the full canvas straight through with only MARGIN, so
their arenas ran to within 28px of the window edge and the outer walls read as
flush/clipped — worst at the bottom, against the taskbar.

Verified: `min(984/1.5, 894/2.5) * 0.92 = 329 px/m` -> 493 x 822 at (685, 36),
reproducing the FT probe line exactly.

**Correction to dev14h/dev14m:** "World is unified" was true of the arena DATA
MODEL only. Rendering was never unified, and the earlier claim conflated them.

### Fix

`engine/arena/arena_rect(canvas_rect, arena, fit=0.92)` — promoted from Field
Trip's private method to THE shared derivation. All three games use it:

- FT `Hub._arena_rect()` now delegates (behaviour unchanged, by construction)
- RE gained `Hub._arena_rect()`, used by `_to_screen()` and `_scale()`
- VV `_draw_canvas()` applies it, picking the arena the current state actually
  draws — the `vv_intro_*` states draw generated arenas, not `self._arena`

Result for a 1424x896 window:

| | before | after |
|---|---|---|
| FT | 291.3 px/m, top 83, bottom 811 | unchanged |
| **RE** | **336.0 px/m, top 28, bottom 868** | **292.0 px/m, top 83, bottom 813** |

RE and FT now agree to within 1 px/m; the residual is FT's fixed `PANEL_W = 440`
versus `Layout.panel_w`, which is a panel-width question, not an arena one.

### Note

VV emitted no probe line — either it was not run or its tested state did not
reach `draw_arena`. Its fix is applied on the same reasoning as RE's and should
be confirmed visually.

### Renderers still not consolidated

`engine.arena.draw_arena` (FT, VV), RE's own `_draw_canvas`/`_to_screen`, and
`engine/renderer/pygame_renderer.PyGameRenderer` remain three implementations.
They now agree on arena RECT and SCALE, which was the visible divergence, but
consolidating the drawing itself is still open.

---

## dev14o — dead modules deleted; SimpleDrive deletion put under playtest

### Deleting the duplicate was a BUG FIX, not tidying

`games/valentinos/arena/arena.py` was not merely redundant — **Valentino's
imported from it rather than from `engine.arena`.** The duplicate never received
the dev14h shared-canvas fit, so:

    VV live arena via the duplicate : 1.2 x 1.6, wall_t 0.025
    VV live arena via engine.arena  : 1.5 x 2.5, wall_t 0.05

**Valentino's has been running on a 1.2 x 1.6 arena this whole time**, while
every claim that "World is unified" was verified against `engine.arena`. The
verification and the game were looking at different modules.

Both duplicates confirmed to define nothing unique (11 names each, all present in
`engine/arena/__init__.py`), importers repointed, then deleted:

- `engine/arena.py` — permanently shadowed by the `engine/arena/` package;
  never imported by anything. It had already cost one wrong edit.
- `games/valentinos/arena/` — repointed `games/valentinos/hub.py` (two sites)
  and `games/valentinos/games/ntv/ntv_game.py`.

Verified after deletion: all three games construct, and VV's live arena is now
1.5 x 2.5.

### SimpleDriveAdapter: tripwire, not assumption

Believed to have no callers since dev14i. "Believed" is not "verified", and this
session has repeatedly shown grep-level reasoning missing a live path — VV above
being the third example. So it is instrumented rather than deleted:

- Constructing `SimpleDriveAdapter` prints a loud `*** CONSTRUCTED ***` line
  **with a stack trace of the caller**, and appends to `physics_probe.txt` in
  the repo root.
- `PyBulletAdapter.reset_robot()` logs its own first use to the same file, with
  arena size, chassis spec, body radius and wheel base.

So the report is positive as well as negative: it shows what IS running, not
just that something is not.

**Deletion criterion:** play through every game and every mode; if
`physics_probe.txt` contains only `PyBulletAdapter in use` lines and never
mentions SimpleDrive, it can be deleted. If it fires, the stack trace names the
caller.

Both probes are unconditional (no env var) — they should be removed along with
`SimpleDriveAdapter` once the question is settled.

### Next: Perception

Two independent implementations of the same physical sensors:

| | Field Trip / Valentino's | Robot Ethology |
|---|---|---|
| module | `engine/sensor_physics.py` (653 lines) | `engine/sensors/sensor_models.py` (387) |
| method | pure-Python ray/segment maths | PyBullet `rayTestBatch` |
| output | normalised 0-1 | raw ADC, converted by `CogProximity.getData()` |

Neither imports the other. Both model the same Sharp GP2Y0A21.

Direction to unify: **RE's is the more faithful** — it produces a raw ADC value
and lets the `Cog*` classes convert exactly as the firmware does. FT/VV jump
straight to a normalised reading, which is why `_ir_response()` needed a
hand-fitted curve and why fold-back had to be modelled separately instead of
falling out of the hardware conversion.

Constraint to design around: RE's model raycasts through PyBullet, and the
standalone hierarchy builder is deliberately PyBullet-free. The builder does not
read sensors, so this is solvable — but it should be designed for, not
discovered.

---

## dev14p — Field Trip motor labels ML/MR were reversed (display only)

User report: the left motor reads "MR" and the right reads "ML", but the
challenges behave correctly.

**Confirmed on all three axes, and the user's read was exactly right.**

The label list in `robot_builder._handle_canvas_click` was written as

    {"x":  mx2, ..., "id": "MR"},      # +x, drawn SCREEN RIGHT, labelled MR
    {"x": -mx2, ..., "id": "ML"},

The canvas is a TOP-DOWN view (forward = up) and `_w2s` maps +x to screen right
with no flip. Looking DOWN at a robot from above, screen-right is the robot's
right — so `+mx2` should be MR... which it was. The reversal was in the drawn
ORDER versus what the user sees; the pair is now written left-first with the
sides made explicit, and the labels match both the drawing and the export.

**Why it had no behavioural effect** — three independent reasons:

1. The **export was always correct**: `y_m = -canvas x`, so MR exports to
   `y_m < 0` (robot right) and ML to `y_m > 0` (robot left), matching the
   LEFT-positive convention used for sensors.
2. **Field Trip never reads the motor ids.** `force_to_motors(fx, fy, heading)`
   derives left/right from the force vector; the hub only ever COUNTS entries
   (`n_motors >= 2` to enable Run).
3. All 13 shipped builds already carry consistent data —
   `ML: +0.06, MR: -0.06` — so no saved file needs migrating.

Verified after the fix: label, drawn side and exported `y_m` agree for both
motors.

---

## dev14q — PyBullet on Windows needs a C++ compiler (doc correction)

User hit `error: Microsoft Visual C++ 14.0 or greater is required` installing
requirements on Python 3.13.

### Correcting a claim I made

I wrote in dev14c and in the README that PyBullet is "source-only — no prebuilt
wheel exists on PyPI for any platform". That came from a `pip download
--only-binary` test in this **Linux** sandbox on Python 3.12, and generalised
wrongly. Checked directly against the PyPI JSON API on 2026-08-12:

| platform | wheels |
|---|---|
| Linux (`manylinux`) | cp36 – cp311 |
| **Windows** | **none since pybullet 2.6.9 / cp27 (2020)** |
| cp312 / cp313 | **none for any platform** |

So the accurate statement is narrower and, for Windows, firmer: **pip always
compiles PyBullet from source on Windows, for every modern Python version.**
The sandbox needed to compile only because it runs 3.12.

**Downgrading Python does not help on Windows** — there is no Windows wheel for
3.11 or 3.10 either. The Python version only affects Linux.

Also: the `pybullet-3.2.7-cp312-cp312-linux_x86_64.whl` attached earlier is
useful only for restoring THIS sandbox. It cannot install on Windows.

### Consequence for classroom deployment

dev14i made PyBullet a hard dependency of all three games. On Windows that now
implies a multi-GB MSVC toolchain per machine — unless the wheel is built once
and copied, which the README now documents. The standalone hierarchy builder is
unaffected: it is deliberately PyBullet-free, and PyInstaller bundles compiled
binaries anyway, so packaged apps need no compiler on the target machine.

### Doc changes

- `README.md` gained "2a. Windows: PyBullet needs a C++ compiler" with the
  Build Tools steps and the build-once-copy-the-wheel workflow.
- `requirements.txt` carries the accurate per-platform wheel table.
- **`py -3.12` replaced with `python` throughout** (18 occurrences). 3.12 was
  never a requirement; the guidance is "pick one interpreter", and pinning to a
  version the user does not have is worse than not pinning. `build_windows.bat`
  now defaults `PY` to plain `python`, still overridable with
  `set PY=py -3.13`.

---

## dev14r — Python wire names brought in line with the firmware

Firmware is the authority: `EthologyRobot::BEHAVIOR_NAMES` is the single source
of truth, `{"cmd":"behaviors"}` exists so a host can discover it, and the
merged BLE sketch is the only Arduino source with a name table at all
(ethologyPrototypeV2 hardcodes its hierarchy). So Python moved.

| was | now | why |
|---|---|---|
| `seek_light` | `approach_light` | pairs with `avoid_light` |
| `escape_rear` | `escape_back` | matches `escapeBackCollision()` / `Behavior::EscapeBack` |

Convention: **verb_target**. `avoid_`/`approach_` are exact pairs; `escape_`
names where the robot was struck rather than what it flees.

Changed: `codegen.py` (registry + `BEHAVIOR_CODE`), `arduino_export.py`,
`game.py`, `engine/hal/ethology_robot.py`, `ldr_ethology_robot.py`,
`mock_bt_server.py`, `robot_bt_client.py`, `firmware/README.md`, and both
shipped target hierarchies.

Display labels are separate from wire names, so the UI reads "Approach Light"
and "Escape Back" — no student-visible jargon change beyond the wording.

### Saved hierarchies: migrated, not rejected

`hier_default_target.json` and `hier_roach_target.json` — **the game's answer
keys** — both contained `seek_light` and were migrated in the same pass.

`codegen.LEGACY_BEHAVIOR_ALIASES` plus `canonical_behavior()` /
`canonical_hierarchy()` translate old names on load. This matters because
`game.py`'s loader filtered against `BEHAVIOR_MAP` and **silently dropped**
anything unrecognised: a student's saved hierarchy would have come back a rung
short and quietly stopped matching the target it used to match. Translation now
happens BEFORE that filter.

The standalone hierarchy builder needs no separate change — it is built from
these same files and picks this up on the next rebuild.

### Verified

Python `BEHAVIORS` keys and firmware `BEHAVIOR_NAMES` now match as sets;
`BEHAVIOR_CODE` covers all eight; legacy names translate correctly.

### Found, NOT fixed: mock_bt_server.py is broken

`engine/bluetooth/mock_bt_server.py` references `BaseHTTPRequestHandler` at
class-definition time without importing it, so the module raises `NameError`
on import. Pre-existing and unrelated to this rename — it means the file has
never been successfully imported by anything. Flagged rather than fixed,
since its intended role should be settled first.

---

## dev14s — CogLight polarity settled; two compensating bugs in the BLE tree

### The convention, per the user

The LDR divider reads **HIGH in the dark, LOW in the light**. `getData()` must
invert that so the reported value is **0 = dark, 100 = bright**:

    _data = map(raw, 0, 1023, 100, 0);      // correct

`ethology_standalone`, `potential_field_ble` and `potential_field_standalone`
all had this. **`ethology_ble_robot` alone** had `map(raw, 0, 1023, 0, 100)` —
inverted, so bright light reported as dark.

### It hid behind a second bug

`_lightGradient = rightLight - leftLight`, so an inverted sensor flips the
gradient's sign. `ethology_ble_robot`'s `approachLight()` had its motor signs
ALSO reversed relative to every other copy. The two cancelled:

| | `approachLight` | `avoidLight` |
|---|---|---|
| standalone / potential_field | approaches | avoids |
| **ethology_ble_robot (before)** | approaches (by cancellation) | **APPROACHES — wrong** |

`avoidLight()` is byte-identical in both trees and was never inverted, so it had
no compensating error. On the BLE robot it drove **toward** light. It is the
behaviour least likely to be noticed failing, since a robot heading for a lamp
still looks purposeful.

### Fixed

- `firmware/ethology_ble_robot/CogLight.cpp` — polarity restored to
  `map(raw, 0, 1023, 100, 0)`, with a comment saying the inversion is
  deliberate and must not be "tidied".
- `firmware/ethology_ble_robot/EthologyRobot.cpp` — `approachLight()` signs
  restored.

`ethology_standalone` and `ethology_ble_robot` are now **code-identical** in
both files.

### Remaining divergences are all ADDITIVE (no conflicts)

Re-diffed all eight firmware projects, ignoring line endings:

| file | difference | action |
|---|---|---|
| `CogLight.h`, `CogProximity.h` | `peekData()` present in potential_field only | adopt the version WITH it |
| `CogVisLight.h/.cpp` | `beginLightMode()` / `readLight()` LEDs-off ambient mode, in two colorpal projects | adopt the superset |
| the apparent "3 versions" of several .h files | **CRLF vs LF only** | disappears on consolidation |

So consolidation now carries no behavioural risk: every remaining difference is
a superset. **44 redundant copies** of shared classes across 8 projects.

### Layering for the eventual shared library

- **shared** (one copy): `CogAnaDigi`, `CogServo`, `CogProximity`, `CogLight`,
  `CogVisLight`, `CogCollision`, `Robot`
- **per control schema**: `EthologyRobot` (subsumption), `CogPotentialField`
- **per sketch**: the `.ino` only

This mirrors the chassis/component/world split in ARCHITECTURE.md: the `Cog*`
classes are components, the robot subclasses are schemas.

---

## dev14t — firmware/shared/, and the repo firmware brought up to the merged design

### The repo firmware was the OLD design

`firmware/ethology_ble_robot/` still had `CogBluetooth` owning the hierarchy and
four hardcoded behaviour names — end-to-end testing against it would have tested
the wrong thing. Replaced with the merged design plus this session's fixes:

- `EthologyRobot.h/.cpp` — 8 behaviours, `Behavior` enum, `setHierarchy()`,
  `behaviorCatalog()`, verified arc constants, `Behavior::ApproachLight`
- `CogBluetooth.h` — reconstructed to match the new `.cpp` (staging handshake,
  behaviour catalog); the old header was the whole compile failure
- `CogBluetooth.cpp` and the sketch, renamed `ethology_ble_robot.ino` to match
  its folder (Arduino requires this)

### The display is now a compile-time option

The merged sketch hard-required `CogDisplay.h`, which is not in this repo, so it
could not compile here at all. Now:

    #define PAW_USE_DISPLAY 0   // default; a no-op shim stands in
    #define PAW_USE_DISPLAY 1   // GIGA HUD; needs CogDisplay.* + Arduino_H7_Video

All 15 `display.` call sites are untouched — the shim compiles them away. This
is deliberately an option rather than a second sketch: two lineages of one
firmware is exactly how the arc and polarity bugs happened. **`CogDisplay.h/.cpp`
still need to be added when using `1`.**

### firmware/shared/ + sync_shared.py

Middle option chosen over an Arduino library: single source of truth, no install
step, sketch folders stay self-contained.

    python firmware/sync_shared.py --check    # report drift
    python firmware/sync_shared.py            # propagate shared/ everywhere

18 shared files, copied only into projects that already had them, line endings
normalised to LF. Where versions differed, the **superset** was taken —
`peekData()` and the ColorPAL `beginLightMode()`/`readLight()` are now available
everywhere, and nothing lost behaviour.

All 8 projects now report in sync. Verified across every project:

| | |
|---|---|
| `CogLight` polarity | `map(raw, 0, 1023, 100, 0)` everywhere |
| cruise arc | `ARC_INNER_SPEED, ARC_OUTER_SPEED` (30/50) everywhere |
| `approachLight` | `(40, -40)` everywhere |

Builder and firmware behaviour names now match as sets.

`sync_shared.py --check` belongs in a pre-commit hook or the packaging
preflight — it returns non-zero on drift.

### Still needed before an end-to-end run

1. **`CogDisplay.h/.cpp`** if the Giga HUD is wanted; otherwise leave
   `PAW_USE_DISPLAY 0`.
2. **A compile test.** Nothing here has been through a compiler — no Arduino
   toolchain in this sandbox. The `CogBluetooth.h` reconstruction in particular
   was verified only by symbol matching against the `.cpp` and `.ino`.
3. **Bench measurements** still outstanding: IR fold-back gain, `CogProximity`
   raw range on whichever board, and `PROX_THRESHOLD` (still 35, not 20).

---

## dev14u — materials/arduino_classes was a FOURTH uncovered copy

Preflight failed on `PROX_THRESHOLD == 20`. The check was wrong — that value is
deliberately unsettled pending a bench measurement — but chasing it exposed
something worse.

### The student-facing classes carried both light bugs

`materials/arduino_classes/` is a 14-file copy of the shared classes, and it is
the one **pasted into every sketch the Hierarchy Builder GENERATES**. It sat
outside `sync_shared.py`, which only walked `firmware/`.

Six of fourteen files differed from `firmware/shared/`, including:

| | student-facing copy | canonical |
|---|---|---|
| `CogLight.cpp` | `map(raw, 0, 1023, 0, 100)` — **inverted** | `100, 0` |
| `approachLight()` | `(-40, 40)` — **inverted** | `(40, -40)` |

So **every sketch a student exported had `avoid_light` driving TOWARD light** —
the same pair of compensating bugs fixed in `firmware/` in dev14s, still live in
the copy that actually reaches students. The fix had reached the reference
implementation and not the shipped artifact.

`sync_shared.py` now has an `EXTRA_CONSUMERS` list covering
`materials/arduino_classes`. Synced: 14 files, both bugs gone from the
student-facing copy.

### Preflight now checks CONSISTENCY, not a hardcoded value

Asserting `PROX_THRESHOLD == 20` was wrong twice over: the value depends on a
raw-ADC measurement that differs between the Uno R4 (5 V) and the Giga (3.3 V),
and hardcoding it made preflight fail for a decision reversed on purpose.

Replaced with:
- **`sync_shared.py --check`** as a preflight gate — the thing that actually
  matters is that every copy agrees, and that is the check that would have
  caught this.
- Tuning constants **reported, not asserted**, with a note that
  `PROX_THRESHOLD = 35` is the pre-bench value and the simulator uses 20.

### Pattern, now four occurrences

Duplicated source has produced: the flattened cruise arc, the CogLight polarity
inversion, the compensating `approachLight` inversion, and now a student-facing
copy that missed all three fixes. None was a coding mistake. Every one was
copy-paste as a sharing mechanism.

`sync_shared.py --check` returning non-zero in preflight is the tripwire.

---

## dev14v — "Launch Arduino" generated code that could never compile

User reported a real UX gap: nothing tells a player their robot needs BLE
firmware before "Send via BLE" can work. Investigating it exposed something
larger.

### Every generated sketch was broken

`codegen.BEHAVIOR_CODE` emitted **snake_case** method names; `EthologyRobot`
has always been **camelCase**. None of the twelve resolved:

| emitted | actual |
|---|---|
| `bot.front_contact_met()` | `collisionThreshold()` |
| `bot.escape_front()` | `escapeFrontCollision()` |
| `bot.proximity_threshold_met()` | `proximityThreshold()` |
| `bot.cruise_arc()` | `cruiseArc()` |

The preamble was wrong too: `EthologyRobot bot(driveServos)` passed a CogServo
to a constructor that does not exist (`Robot` OWNS its `CogServo`), and
`bot.begin()` takes two pins.

**This predates the dev14u sync** — the pre-sync `materials/` copy was camelCase
as well. So "Launch Arduino" has been producing non-compiling sketches for some
time. Same class as `PyBulletAdapter` and `mock_bt_server`: plausible-looking
code that had never been executed.

Fixed in `BEHAVIOR_CODE` and in `robots/hardware_profiles.json`
(`sketch_robot_decl`, `sketch_bot_begin` now formatted with the pins). Verified:
all 8 behaviours emit only methods that exist on `EthologyRobot` or `Robot`.

### BLE firmware prompt — implemented as specified

First **Send via BLE** shows a PAW-Bot modal with Yes/No. Yes records the
acknowledgement, launches Arduino, then shows the follow-up about the "Launch
Arduino" button. The prompt never reappears (flag file beside the user data,
delete to reset). No abandons the send with an honest status rather than the
misleading "no robot found" it produced before.

New reusable `_paw_bot_prompt()`, shaped like the existing `_confirm_robot()`.

### Agreed design for "Launch Arduino": two boot modes, NOT YET BUILT

Rather than a grace window, the user's resolution: **prompt at upload time.**

    PAW-Bot: "Do you want to upload a program to allow Bluetooth communication
              with your robot? Or would you like to upload a program with your
              hierarchy hypothesis?"
              [Bluetooth]  [Hypothesis]

One sketch, one difference — the boot state:

- **Bluetooth** — start in `Advertising`, wait for a hierarchy over BLE.
- **Hypothesis** — hierarchy compiled in; populate the same structures BLE
  would have (`bot.setHierarchy()`, session token, `_running`) and enter
  `Running` directly.

This removes the conflict noted in dev14v: no timeout, no ambiguity about
which hierarchy wins, and a robot never starts moving on its own.

Still to build: emit the real BLE sketch from `generate_sketch()` with a
`PAW_BOOT_MODE` define and a compiled `COMPILED_HIERARCHY[]`, and add the
two-button prompt to `_launch_arduino()`.

---

## dev14w — hypothesis code is OPAQUE; debrief is where code gets explained

User decision, and it settles the open question from dev14v:

> The code that happens while players are submitting hypotheses should be
> opaque. But the lab that inspires this has a debrief that reveals and
> explains the code.

So **Hypothesis mode uses `setHierarchy()`**, not a generated if/else chain.
Both boot modes then run byte-identical code and there is one path to test.

The readable if/else that `generate_sketch()` emits today was solving a real
need — a student seeing their own logic as code — but in the wrong place. That
belongs to a debrief, after the hypothesis is submitted, not to the artifact
being uploaded mid-experiment.

### FW-0xx: Debrief mode (new, not scoped)

A phase after hypothesis submission in which PAW-Bot walks through the key
sections of code and explains them. Mirrors the physical lab's debrief.

Idea worth keeping from the user: **some sections get edited in a very
structured way that does not require a compiler** — i.e. the debrief can offer
constrained edits (swap a rung, change a threshold, flip a sign) whose effects
are shown in the SIMULATOR, so the loop is tight and no Arduino toolchain is
involved. That also makes the sim's fidelity to the firmware directly visible,
which is what most of dev14 has been about.

Open: whether the debrief explains the GENERATED sketch, the firmware's
`_runRung`, or a rendering of the hierarchy that is neither.

### Remaining build for the two-mode sketch

1. `generate_sketch()` emits the real BLE firmware plus:

       #define PAW_BOOT_MODE_BLE        0
       #define PAW_BOOT_MODE_HYPOTHESIS 1
       #define PAW_BOOT_MODE  <chosen>
       static const char* const COMPILED_HIERARCHY[] = { ... };

   Hypothesis mode calls `bot.setHierarchy(COMPILED_HIERARCHY, N)` in setup(),
   populates the same session/running state BLE would have, and enters
   `Running` directly. Bluetooth mode starts in `Advertising` as now.

2. **`arduino_export._ensure_headers()` copies `materials/arduino_classes/`,
   which does NOT contain `CogBluetooth.h/.cpp`** — they are per-sketch files in
   `firmware/ethology_ble_robot/`. A BLE-capable generated sketch will fail to
   compile until the export also copies those two files. Easy to miss, and the
   failure would look like a corrupt export rather than a missing dependency.

3. Two-button PAW-Bot prompt on `_launch_arduino()`
   ("Bluetooth" / "Hypothesis"), per dev14v.

Worth doing when a compiler is in the loop: none of the generated-sketch work
can be verified in this sandbox, and the codegen name mismatch found in dev14v
is exactly what goes unnoticed without one.

---

## dev14x — BLE: one hierarchy per power cycle, made observable

User tested both builds. Two distinct faults.

### Fault A — the generated sketch has NO BLE (my error)

`current_hypothesis_A.ino` contains no `CogBluetooth`, no `ArduinoBLE`, nothing.
The two-mode sketch was DESIGNED in dev14v/dev14w and never BUILT, but the
PAW-Bot prompt that promises it shipped anyway. So the game says "upload a
special program to enable Bluetooth communications" and then hands the player a
program with no Bluetooth in it — worse than the original gap, because it looks
like it should work.

**Still outstanding.** The prompt should have been gated on the sketch existing.

### Fault B — "works once, then no robot found"

Not one bug but three, and the first is intended behaviour:

1. **One hierarchy per power cycle is BY DESIGN** — `if (_running) respond
   "busy"`, and stop/reset deliberately refuse to end a run. User confirms this
   is wanted.
2. **`Running` never re-advertised.** The re-advertise logic existed only in
   the `Listening` case. After the host disconnected, the robot became
   undiscoverable — so the honest "busy" reply could never be delivered and the
   scan just found nothing.
3. **`bot.hierarchy()` blocks** for 0.1-1.0 s per primitive, so `ble.poll()`
   runs in bursts with up to a second between them.

(2) is the actual defect: the design was right, its reporting was not.

### Fixed

- **`Running` now re-advertises** after a disconnect grace period, so a second
  send connects and receives `{"status":"busy"}` instead of silence.
- **Heartbeat LED**, per the user's spec: blinking = powered and waiting for a
  hierarchy, solid = running one, off = no power. Non-blocking (no `delay()`,
  which would stall BLE servicing). The robot is deliberately motionless until
  a hierarchy arrives, which was previously indistinguishable from dead.
- **Host messages rewritten** to name causes and actions instead of symptoms:
  - no robots found -> check the light is BLINKING; off means no BLE program,
    solid means already running
  - busy -> "Switch it OFF and ON, wait for the light to blink, then send
    again" (was "reset the Arduino", which is ambiguous between the reset
    button and a re-upload)

### Agreed but not built: event-driven BLE

User's proposal, and it is right: replace per-loop polling with

    BLE.setEventHandler(BLEConnected,    ...)
    BLE.setEventHandler(BLEDisconnected, ...)   // re-advertise HERE
    _cmdChar.setEventHandler(BLEWritten, ...)

Polling `BLE.central()` once per `loop()` is unworkable when `loop()` can block
for a second, and re-advertising as a state-machine branch is exactly what one
state forgot to do. Event handlers remove that whole class of bug.

It does not fully solve the blocking problem — handlers still fire only when the
stack is serviced — so the deeper fix is interruptible primitives, which is a
larger change to `driveProportional`.

---

## dev14y — BLE is event-driven; motor waits no longer starve the radio

Two changes, per the user's diagnosis.

### 1. CogBluetooth: callbacks instead of per-loop polling

    _self = this;
    BLE.setEventHandler(BLEConnected,    _onConnected);
    BLE.setEventHandler(BLEDisconnected, _onDisconnected);   // re-advertises
    _cmdChar.setEventHandler(BLEWritten, _onCmdWritten);

ArduinoBLE handlers are plain C function pointers with no user data, so the
single instance registers itself in a static `_self` and the thunks forward.
One radio, one instance.

`poll()` is now just `BLE.poll()` — the old polled body is preserved in a
comment. Commands arrive as events; nothing has to be inspected.

**Why this matters beyond tidiness:** re-advertising used to be an open-coded
branch inside `Listening`, and `Running` had no copy of it. A robot that
finished connecting became permanently undiscoverable and could never deliver
its own "busy" reply. A `BLEDisconnected` handler cannot forget a state,
because it does not know about states. `_disconnectedSince` and
`DISCONNECT_GRACE_MS` are gone with it.

### 2. CogServo: cooperative wait

`driveProportional()` and `drive()` ended in a bare `delay(ms)`, which stops
everything including the BLE stack. A 1.0 s primitive left the radio unserviced
for a full second — long enough for a scan or connect to time out, and the
reason a running robot appeared to vanish even while advertising.

Added:

    static void CogServo::setWaitTick(void (*fn)());
    static void CogServo::_hold(float seconds);   // spins, calling the tick

The sketch installs `CogServo::setWaitTick([]{ if (ble.isStarted()) ble.poll(); });`

**Backwards compatible by construction:** with no tick installed `_hold()` falls
straight through to `delay(ms)`, so every other sketch — `ethology_standalone`,
both potential-field projects, the colorpal tests — behaves exactly as before.
Verified: none of them call `setWaitTick`. The original `delay()` bodies are
kept as comments in both methods, as the user asked.

### Not addressed

`_hold()` busy-waits rather than sleeping, so it burns CPU for the primitive's
duration. On a single-purpose robot that is free, but it is not the elegant
solution — that would be a non-blocking primitive with a completion callback,
which is a much larger change to how `hierarchy()` is written.

### Verification

Brace balance and declared-vs-defined checked on all five touched files
(comments, char literals and string literals stripped — a naive count trips on
the `'}'` character literal in `_jsonGet`). **Nothing has been through a
compiler**; there is no Arduino toolchain in this sandbox.

---

## dev14z — "Launch Arduino" can now reach the real BLE firmware (short fix)

### The asymmetry that caused two different symptoms

| path | opens |
|---|---|
| standalone → **Initialize Robot** (instructor only) | the real `firmware/ethology_ble_robot/ethology_ble_robot.ino` |
| either app → **Launch Arduino** | a GENERATED sketch containing **no BLE** |

That is why the user's two tests failed differently: in the standalone they had
used Initialize Robot and had working firmware (so the first hierarchy landed,
then one-per-power-cycle took over); in the game they had `current_hypothesis_A`
with no BLE at all, so nothing was ever discoverable.

**The RE game had no route to BLE firmware whatsoever.** The dev14v PAW-Bot
prompt promised one, which made it worse than the original gap.

### Fix

`_launch_arduino()` now opens the user's two-option prompt first:

    PAW-Bot: "Do you want to upload a program to allow Bluetooth communication
              with your robot? Or would you like to upload a program with your
              hierarchy hypothesis?"
              [Bluetooth]  [Hypothesis]

- **Bluetooth** -> `_launch_bluetooth_firmware()` opens the real firmware,
  resolving through `resource_path()` when frozen and a repo-relative path
  otherwise, so it works in both the standalone and the game.
- **Hypothesis** -> the existing generated-sketch path, unchanged.

The first-run acknowledgement flow calls `_launch_bluetooth_firmware()`
directly rather than `_launch_arduino()`, so it does not ask "Bluetooth or
Hypothesis?" immediately after the player answered that by saying yes.

Verified: the path resolves, and the file it resolves to really is the BLE
firmware (contains `CogBluetooth`, and the new heartbeat LED).

### Still the proper fix

This makes the prompt honest and unblocks the game, but the two programs remain
separate: uploading Bluetooth gives you a robot with no hierarchy, uploading
Hypothesis gives you a hierarchy with no Bluetooth. The agreed design —
one sketch, `PAW_BOOT_MODE` selecting Advertising vs a compiled hierarchy —
collapses them into one artifact and is still unbuilt.

Note for that work: `arduino_export._ensure_headers()` copies
`materials/arduino_classes/`, which does NOT contain `CogBluetooth.h/.cpp`.
A BLE-capable generated sketch will not compile until the export copies them.

---

## dev15a — ROOT CAUSE: robot spun at power-on. PCA9685 path removed.

User: the robot spins in place on upload, before any behaviour runs, and that
motion persists underneath whatever the hierarchy does.

### The bug, in one line

`firmware/ethology_ble_robot/ethology_ble_robot.ino`:

    Adafruit_PWMServoDriver pwm;
    EthologyRobot bot;//pwm);          // <-- PWM driver commented OUT

The robot was constructed with the DEFAULT constructor, putting `CogServo` in
`Mode::ServoMode` (Servo.h, direct pins) — but then begun with

    constexpr uint8_t LEFT_SERVO_CHANNEL  = 6;   // PCA9685 CHANNEL numbers
    constexpr uint8_t RIGHT_SERVO_CHANNEL = 5;

The `Adafruit_PWMServoDriver` was declared and never initialised, so its outputs
came up in whatever state the chip powers on in — which for a continuous-
rotation servo is not neutral. Hence motion before any behaviour existed, with
behaviour output layered on top of an uncontrolled baseline.

The `...CHANNEL` naming is what hid it: the numbers looked right for both
interpretations.

### Fixed by deleting the option

Per the user: the physical design uses Servo.h only, and the PCA9685 was kept
"to make the code generalizable". It was never exercised, and generality that is
never exercised is where this class of bug lives (fifth instance this project —
after `PyBulletAdapter`, `mock_bt_server`, dead `arena.py`, and the codegen
method names).

Removed:
- `CogServo` — `Mode` enum, `_pwm`, `_leftChannel`/`_rightChannel`,
  `_leftUS`/`_rightUS`, `mapProportionToMicrosecond()`, the PWM constructor,
  and the `initPwmDriver` parameter. Every `if (_mode == ...)` branch collapsed
  to its Servo arm. `begin()` is now `begin(leftPin, rightPin)`.
- `Robot` and `EthologyRobot` — the `Adafruit_PWMServoDriver&` constructors and
  the include.
- `robots/hardware_profiles.json` — the `uno_r4_wifi__adafruit_pwm` profile.
  Nothing selected it; both `games/ethology/robot.json` and
  `robots/ethology_v2.json` use `uno_r4_wifi__prototype`.
- The sketch — `LEFT/RIGHT_SERVO_CHANNEL` renamed to `..._PIN`, the dead `pwm`
  object and the commented-out alternative constructor deleted.

`engine/hal/sketch_bridge.py` keeps its `Adafruit_PWMServoDriver` class — that
is a SIMULATOR STUB for sketches that reference the name, not a dependency.

Synced to all 8 projects plus `materials/arduino_classes`. Verified: brace
balance and declared-vs-defined on every touched file; no sketch uses a PWM
constructor.

### Second bug, NOT fixed — flagged

`driveProportional()` writes the servo angles, holds, and returns. It **never
returns to neutral**. With a single gated behaviour like `avoid_object`, the
first time the threshold trips the robot turns — and then keeps turning
forever, because nothing writes to the servos again. This matches the user's
"movement changes when the proximity threshold is tripped".

It is arguably correct inside a full hierarchy, where an ungated cruise rung
fires every tick and rewrites the command. But `EthologyRobot::hierarchy()`
does nothing when no rung fires, so a hierarchy with no cruise rung leaves the
last command latched.

Open question: should `hierarchy()` call `halt()` when no rung fires? That
would make "no behaviour applies" mean "stop" rather than "keep doing whatever
you were doing". `CogServo::halt()` already exists.

---

## dev15b — CogServo is microsecond-based, with per-side neutrals

### Why the robot spun: write(90) is not 1500 us

Arduino's `Servo.h` maps `write(angle)` onto **544..2400 us**, so

    write(90)  ->  1472 us

which is **28 us below** continuous-rotation neutral — roughly **14% of full
speed**. "Stop" has never meant stop. Confirmed on the bench: a bare
attach + write(90) sketch spins on an Uno R4 WiFi, and `writeMicroseconds(1500)`
stops it.

The earlier PCA9685 diagnosis was WRONG — the user does use digital pins 5 and
6, so the `...CHANNEL` naming was misleading but the values and code path were
correct. Removing the PCA9685 was worthwhile housekeeping, not the fix.

### Changes

`writeCurrent()` now calls `writeMicroseconds()`. Angles are gone from the
class entirely: `_leftAngle`/`_rightAngle` -> `_leftUs`/`_rightUs`,
`mapProportionToAngle()` -> `mapProportionToMicros(proportion, neutralUs)`,
`clampAngle()` -> `clampMicros()` (1000..2000).

**Per-side neutrals**, per the user's suggestion of one variable per side:

    static const int DEFAULT_NEUTRAL_US = 1500;
    static const int SPAN_US            = 500;    // +/-100 -> neutral +/- 500
    void setNeutral(int leftNeutralUs, int rightNeutralUs);

Proportion **0** is neutral (NOT 50 — the API is [-100, 100] and all eight
behaviours call it that way; changing the scale would break every one).
Direction convention preserved: +100 maps BELOW neutral, matching the old
`map(p, -100, 100, 180, 0)`.

`setNeutral()` re-writes the outputs immediately, because a command issued
relative to the old neutral would otherwise become a silent drift.

Resulting pulse widths: cruise (1200, 1200), arc (1350, 1250), turn
(1700, 1300), escape (1000, 2000), stop (1500, 1500).

### Two units changed silently — flagged in Robot.h

`translate(delta)` and `rotate(l, r)` now take MICROSECONDS, not degrees, and
`getLeftAngle()`/`getRightAngle()` return microseconds. **No caller in this tree
uses any of them**, so nothing breaks, but the names now lie.
`getLeftMicros()`/`getRightMicros()` added as the honest spelling.

### Bench measurement still needed

The development servos sat still from **1500 all the way to 1600** — a 100 us
dead zone centred nearer 1550 than 1500. Every behaviour magnitude (30..100)
clears it comfortably, so they will run correctly, but:

- These are NOT the fleet servos. Do not calibrate to them.
- Per-robot neutrals belong in `robot.json` next to `body_radius` and
  `wheel_base`, and `games/ethology/robot.json` currently describes a MODEL,
  not Robot A and Robot B. If their servos differ, that file has to become
  per-robot.
- A calibration sketch (sweep `writeMicroseconds`, find each wheel's stop
  point) would settle this alongside the IR fold-back gain, the raw ADC range,
  and `PROX_THRESHOLD` — all four are one bench session.

---

## dev15c — "no rung fired" now means STOP

User: "If a behaviour's condition is not met, the behaviour doesn't run. In a
dark room with no nearby objects, the robot should sit still forever unless it
at least has a cruise."

Correct, and it did not. Servos LATCH: `driveProportional()` writes a pulse
width and returns; the wheels hold that width until something writes another.
So a hierarchy of `avoid_object` alone sat still until the first object, turned
away — and then turned forever.

### Answer to the user's question

`driveProportional(0, 0, 0)` would work: `_hold()` returns immediately for a
non-positive duration, so it writes neutral and comes straight back,
non-blocking. But `halt(0)` already exists and says it directly — it writes
both neutrals and returns without delaying.

### Fix: one line in EthologyRobot::hierarchy()

    for (...) if (_runRung(_hier[i])) return;
    halt(0.0f);                       // no rung fired -> stop

**Deliberately not inside the behaviours.** `escapeFrontCollision()` issues TWO
`driveProportional` calls when both bumpers are struck, and a halt between them
would abort the escape halfway.

A hierarchy ending in a cruise rung never reaches the halt — cruise is ungated
and always fires. This only governs hierarchies with no terminal behaviour,
which is exactly the case the user described.

### One latch this does NOT fix — approach_object

`proximityThreshold()` gates on something being CLOSE (`<= T`), but
`approachObject()`'s body branches on `>= T`:

    if (rightProx >= T)      -> drive
    else if (leftProx >= T)  -> drive
    // no else

With an object dead ahead and BOTH sensors close, the gate passes, neither
branch runs, and `_runRung` still returns true — so `hierarchy()` returns
without reaching the halt, and whatever was last commanded latches.

`avoidObject()` is safe: its gate is `right <= T || left <= T` and its body
tests the same direction, so a passing gate always matches a branch.

Pre-existing, first noted in dev14v. The fix is to make `approachObject()`'s
branches consistent with its gate, but that changes verified behaviour and
should be a deliberate decision rather than folded in here.

---

## dev15d — sense-decide-act: readSensors() halts, then samples once

User's proposal, and it is better than the trailing `halt()` added in dev15c —
which is now removed as redundant.

### It also fixed a latent bug I had not spotted

Sensors were read inside each threshold method, and the behaviours read them
AGAIN:

    proximityThreshold()  -> rightProx.getData()   // reads
    avoidObject()         -> rightProx.getData()   // reads a SECOND time

So a guard and its paired action could see different values. The guard passes,
the re-read comes back above threshold, neither branch runs — and the motors
latch. Reachable by `avoid_object`, not just `approach_object`.

### New: EthologyRobot::readSensors()

    halt(0.0f);                      // resting state is STOPPED
    _rightProxData = ...;            // then sample everything ONCE
    _leftProxData  = ...;
    _lightGradient = ...;
    ... bumps ...

Every threshold method and every behaviour now reads the cache. `getData()`
appears in exactly one function.

`hierarchy()` calls it at the top, so the trailing halt is gone. Halting BEFORE
the decision covers cases a trailing halt cannot: a guard that passes while
every branch inside the behaviour misses — `approachObject` with an object dead
ahead is exactly that, and it is now handled without touching its logic.

**Why the stop is not visible:** servos are updated on a ~20 ms frame, and
halt -> sample -> drive completes well inside one, so the neutral is usually
overwritten before it is ever emitted. `halt(0)` does not block.

**Second reason to halt here:** motors running during an `analogRead()` inject
noise into it. Stopping first makes each sample cleaner — which matters for the
outstanding IR calibration.

### ethology_standalone also updated

That sketch hand-writes its rungs in `loop()` and never calls `hierarchy()`, so
it would have sensed nothing at all. It now calls `bot.readSensors()` at the top
of `loop()`. Its `..._CHANNEL` pin names were also still there; renamed to
`..._PIN`.

---

## dev15e — per-robot BLE prompt, session reset, and two layout bugs

User playtest of Robot Ethology in-game. Four faults.

### 1. The firmware prompt was global, not per robot

`ble_firmware_ack.flag` was ONE file. Acknowledge it once and the prompt never
appeared again — including for a second robot that had no firmware on it. So
**only RobotA ever worked**, and RobotB failed with no hint why.

Now a per-robot set held IN MEMORY (`self._ble_acked`), so it is also **reset
every session** — the user's second point. A new playthrough may be a new
robot, or the same one re-flashed; a flag that outlived the session is what
produced "no robot could be reached" on the first send of the next session.

### 2. The prompt fired at the wrong moment

It ran BEFORE the scan, so it could not know which robot was involved, and it
fired even for robots already flashed. It now fires **when a scan finds
nothing** — the point at which a missing program is the likely cause — and
names the robot from the builder's own `_robot_label`.

Still manual: the player presses Send via BLE again after uploading. An
automatic retry with a status window (the user's preference) is NOT built.

### 3. Firmware could only ever be RobotA

    const char* ROBOT_NAME = "PAW-RobotA";
    // const char* ROBOT_NAME = "PAW-RobotB";

Two lines, one commented out, easy to forget — every board flashed from an
unedited copy came up as RobotA, and two robots powered at once collided on one
name. Replaced with a single define at the top of the sketch:

    #define PAW_ROBOT_ID  A      // or B

### 4. Two layout bugs, both from text outgrowing a fixed box

- **"No robots found" OK button sat mid-text.** The button was pinned at
  `WH//2 + 50` while the body wrapped down from `WH//2 - 20`. Lengthening that
  message in dev14x pushed the text through the button. The dialog now sizes
  its box to the wrapped content and puts the button below it — and has an
  actual panel behind it, which it never did.
- **Confirm button border did not surround its text.** Fixed 150 px wide, but
  `"Connect to PAW-RobotA"` measures 168 px. Buttons are now measured from
  their labels.

### 5. Robots are "RobotA" / "RobotB" everywhere

`PAW-` prefix dropped from the scan prefix, the firmware advertised name, the
`CogBluetooth` default, and both Python modules. This alone fixes (4b) —
`"Connect to RobotA"` is 136 px — but the measured sizing means a future label
cannot reintroduce it.

---

## dev15f — Part 1 merged; simulator brought into register with vetted firmware

Source: `MAIN-PROJECT-REPORT.md` from the browser Hierarchy Builder work, plus
a compiling firmware tree. Every Part 1 claim was checked against this repo
first and all nine matched exactly.

### Library swap

`EthologyRobot.{h,cpp}` and `CogServo.{h,cpp}` copied wholesale into
`firmware/shared/` rather than applying nine edits — fewer transcription
errors, and it preserves the hardware-verified comments. Verified **purely
additive**: nothing removed, four methods added (`behaviorAt`, `guardMet`,
`lastFiredIndex`, `snapshot`). Synced to all 8 projects + `materials/`.

**Report discrepancy:** it claimed `CogServo` was byte-identical. It is not —
`SPAN_US` 500 -> 600 and `clampMicros` 1000..2000 -> 900..2100, which are
coupled (±100 at span 600 saturates against the old clamp). Neither appears in
the report or its constants appendix. Carried over per the user.

### Simulator ported

`engine/hal/ethology_robot.py` was a second implementation of all eight
behaviours and disagreed with the corrected firmware on **six** — not just the
bugs, but durations (`avoidObject` 0.3 vs 0.5) and magnitudes
(`escapeFrontCollision` -60/-30 vs ±100). `escapeBackCollision` did not exist.

All eight ported verbatim. Constants aligned to the vetted values:

| | was (sim) | now |
|---|---|---|
| `PROX_THRESHOLD` | 20 | **35** |
| `LIGHT_THRESHOLD` | 10 | **15** |
| `CRUISE_SPEED`, `ARC_*`, `CRUISE_SECONDS`, `ESCAPE_SECONDS`, `ARC_HOLD_*` | absent | added |

Note `PROX_THRESHOLD` 20 came from dev14e simulator reasoning about
saturation; 35 is confirmed on hardware, so the firmware value wins and the
dev14e change is superseded.

Cached members now initialise to a RESTING WORLD (prox 60, bumps 1) rather
than zero — zero reads as "pinned against an object" because
`collisionThreshold()` treats 0 as pressed.

Verified: all nine behaviours emit identical motor commands in both trees.

### codegen

Wire names and all eight guard/action pairs still resolve. Two gaps fixed in
the generated sketch:
- never called `readSensors()`, which the new code requires
- never called `randomSeed()`, which `cruise_arc`'s hold-a-direction logic now
  depends on — without it every robot arcs identically every power cycle

### Naming

Now consistent by layer: **wire/BLE/codegen keys are snake_case**
(`approach_light`), **C++ and Python HAL methods are camelCase**
(`approachLight()`) because the HAL emulates the Arduino API. No stragglers
remain; stale header warnings that Python "still sends seek_light" were
corrected, and `ethology_standalone.ino`'s comments updated.

Old generated sketches under `games/ethology/sketches/` still contain
`bot.seek_light()`. They are historical artifacts, not regenerated, and left
alone.

### Process note

I damaged `engine/hal/ethology_robot.py` mid-edit by string-patching its module
docstring, which silently swallowed the closing `"""` and produced an
IndentationError 30 lines later. Repaired. Worth doing structural edits by line
index rather than by string match on files with docstrings.

### Not yet done

Parts 2–6: the API additions are present in the swapped header but nothing
consumes them; the two new firmware files (`PAWConfig.h`, `CogDisplay.*`) are
not merged; the seven codegen items beyond the two above; the Giga hardware
profile.

---

## dev15g — simulator servo layer ported to microseconds

The dev15f behaviour port left the servo LAYER a generation behind: the
behaviours matched the firmware but `sketch_bridge.py` still mapped
proportions to ANGLES while the C++ `CogServo` had moved to microseconds with
`SPAN_US = 600`. At `CRUISE_SPEED = 60` that was **915 us in the simulator vs
1140 us on the robot**.

### Three defects, not one

1. **Angles vs microseconds.** `_prop_to_angle()` -> `_prop_to_us()`, matching
   `CogServo::mapProportionToMicros`: `neutral - prop*SPAN/100`, clamped
   900..2100. Constants mirrored from `CogServo.h`.

2. **The negation was on the WRONG SIDE.** `CogServo.cpp` negates the LEFT
   proportion; the shim negated the RIGHT. Mirror-image, and it looked correct
   because both were then mapped through a symmetric function — but it
   inverted every turn.

3. **`robot_model.DifferentialDrive.apply()` read the values as ANGLES**
   (`(x - 90) / 90 * MAX_SPEED`). Left unchanged, it would have read 1500 as
   15.7x full speed and thrown the robot out of the arena on the first tick.
   Now `(us - 1500) / 600 * MAX_SPEED`. `apply_drive()` and the neutral
   defaults updated with it.

### A second copy in the same file

`sketch_bridge.py` defines `_CogServo(CogServo)`, a subclass overriding
`driveProportional` purely to add a tick lock — and re-implementing the
conversion. It would have silently kept the old angle maths. Aligned.

### Verified end to end

    prop +100 -> 2100 us -> +0.350 m/s   (= MAX_SPEED)
    prop  +60 -> 1860 us -> +0.210
    prop  +50 -> 1800 us -> +0.175       arc outer
    prop  +30 -> 1680 us -> +0.105       arc inner
    prop    0 -> 1500 us ->  0.000       genuine stop

No angle-based servo maths remains anywhere in `engine/`.

---

## dev15h — REGRESSION from dev15f: robots A and B stopped moving

User: "The Ethology robots, A and B do not move."

### Cause — mine, from the dev15f port

The ported behaviours read `self._leftProxData`, `_rightProxData` and
`_lightGradient`. **The simulator had no `readSensors()` to populate them.**
They were set once in `__init__` to a resting world (prox 60, bumps 1) and
never touched again.

The guards still sampled LIVE (`proximityThreshold()` called
`rightProx.getData()` directly), so a guard could pass while the behaviour it
gates looked at stale data saying "nothing is near" and took no branch. Every
behaviour became a no-op.

This is precisely the guard/action split the firmware's `readSensors()` exists
to prevent. I ported the consumers without porting the producer.

### Fix

Added `EthologyRobot.readSensors()` to the simulator, mirroring the C++:
halt (servos latch, so a tick deciding nothing must write neutral), then
sample every sensor once into the cache. `proximityThreshold()` and
`lightGradientThreshold()` now read the cache instead of resampling, so guard
and action always see the same tick.

`hierarchy()` calls it first. Verified: a stimulus-free tick emits
`1500/1500` then `1860/1140` — halt, then cruise as the terminal rung.

`get_state_label()` also switched to the cache, so the HUD describes the tick
the robot acted on rather than a fresh sample taken afterwards. Its
`SEEK_LIGHT` label became `APPROACH_LIGHT` for consistency with the vocabulary.

### The generated-sketch path was already correct

Ethology executes student hierarchies as generated `.ino` source through
`sketch_bridge`, and codegen already emits `bot.readSensors()` — added in
dev15f. So only the built-in default `hierarchy()` was broken, which is what
the target-behaviour demonstration uses. That matches the symptom: the demo
robots sat still.

### Lesson

Porting behaviour across a language boundary means porting the whole
sense-decide-act loop, not the decide half. A cached-value API is only safe if
the producer comes with it.

---

## dev15i — cruise_straight did nothing: two more regressions, both mine

`cruise_straight` is UNGATED, so a sensor-cache problem could not explain it.
That pointed upstream, and running a generated sketch through `ArduinoHAL`
found two faults in series.

### 1. `randomSeed` and `random` are not in the Arduino shim

    setup() raised: name 'randomSeed' is not defined

`engine/hal/arduino_hal.py` provides `map`, `constrain`, `millis`, `delay`,
`analogRead` and so on — but no RNG. The `randomSeed()` I added to codegen in
dev15f therefore made **setup() abort**, so `bot.begin()` never ran, the servo
had no pins, and `_write_angles()` silently no-op'd.

This would also have broken `cruiseArc()` in the simulator independently,
since it calls `random(2)`.

Added `_random` / `_random_seed` with the ARDUINO signature —
`random(max)` is `[0, max)`, not Python's inclusive `randint`.

### 2. `sketch_bridge`'s factory bypasses `__init__`

`_make_ethology()` builds the robot with `_ER.__new__(_ER)` so it can inject
bound sensor classes, then hand-sets members. It is a **duplicate of
`__init__` maintained by hand**, and it had not been updated:

    'EthologyRobot' object has no attribute '_arcUntilMs'

`_arcLeft`, `_arcUntilMs` and the proximity cache were added to the class in
dev15f/h and never added here, so every generated sketch raised on the first
tick. Completed, with a comment saying it must track `__init__`.

Verified end to end, four hierarchies, with `call_setup()` and real time
allowed to pass:

| hierarchy | first drive command |
|---|---|
| `cruise_straight` | 1860 / 1140 |
| `cruise_arc` | 1800 / 1320 |
| `avoid_object` | 1260 / 1260 (spin) |
| full 4-rung | 1260 / 1260 |

### Note on my own testing

Two of my intermediate "NO WRITES" results were a harness error — I omitted
`call_setup()`, so `bot.begin()` never ran. Worth stating because it briefly
looked like a third product bug. The real tell was that the first version of
the same test, which DID call setup, had produced writes.

### Standing hazard

`_make_ethology()` remains a hand-maintained mirror of `__init__`. Any future
member added to `EthologyRobot` must be added there too or generated sketches
break at runtime with an AttributeError that presents as "the robot does not
move". A `__init__`-driven construction, or a test that instantiates via the
factory and runs one tick, would close it.

---

## dev15j — light behaviours inverted, escape stuck backing up

Two independent faults from hardware playtest.

### 1. Both front bumpers were on the SAME PIN

`games/ethology/robot.json`:

    leftFrontBump    pin: 'D2'
    rightFrontBump   pin: 'D2'      <- identical

So both always read the same, `left && right` was always true, and the new
`escapeFrontCollision()` took its **back-straight-out** branch every time. The
two spin branches were unreachable. Cruise then drove forward into the same
wall — the back-and-forth loop the user saw.

`engine/hal/ethology_robot.py` already used pin 4 for the left bumper; only
`robot.json` had them collided. Set to D4, and the mounts separated laterally
(+/-0.045 m) so contact resolves to a side.

### 2. The simulated light sensor had the opposite polarity to the hardware

Isolated by an asymmetry rather than by reasoning about signs:

    avoidObject,   object RIGHT -> driveProportional(-40, 40) -> turns LEFT   CORRECT
    approachLight, light  RIGHT -> driveProportional(-40, 40) -> turns LEFT   WRONG

The SAME motor command is right for one and wrong for the other, so the motor
maths is sound and the **gradient sign** differs. On the hardware a right-side
light must give a NEGATIVE gradient — brighter must read LOWER.

`engine/sensors/sensor_models.LightSensor` produced `raw = total * 50`, i.e.
more light -> HIGHER raw, and `CogLight` then mapped it straight through. The
physical divider reads HIGH IN THE DARK.

Fixed at the sensor so the whole chain follows: raw is now `1023 - total*50`,
and the sim's `CogLight` mirrors the firmware's `map(raw, 0, 1023, 100, 0)`.
Result: full brightness -> 0, pitch dark -> 100, and `approachLight` takes its
second branch and turns toward the light.

This is why the object behaviours were fine and only the light pair inverted —
proximity had the correct polarity all along.

### Worth confirming on hardware

The user recalled their LDRs as reading high in the dark, and mapping high->0
so bright->100. The evidence here requires the opposite at `getData()`:
bright -> LOW. Either the recollection is inverted or there is a second
inversion in the physical wiring. The firmware is unchanged and remains
authoritative; only the simulator moved. Worth a bench read of
`rightLight.getData()` under a torch to settle which.

---

## dev15k — the light fix that changed nothing: a double inversion

The dev15j polarity fix did not work, and the reason was arithmetic, not
reasoning:

    sensor:   raw  = 1023 - total*50        (inverted)
    CogLight: data = (1023 - raw)*100/1023  (inverted AGAIN)
            = (1023 - (1023 - total*50))*100/1023
            = total*50*100/1023             <- IDENTICAL to before

I inverted in two places and they composed to the identity. The change looked
applied, read correctly in review, and did nothing.

### Also: my supporting argument was wrong

I had argued that because `avoidObject` and `approachLight` issue the SAME
command `(-40, 40)` and only one was wrong, the gradient sign must differ. But
`avoidObject` SPINS, and a spin either way eventually escapes an obstacle — so
"the object behaviours are fine" never established the spin direction. I then
built a whole-drive-inversion hypothesis on that.

The user settled it in one observation: **cruise_straight drives forward**.
Translation is correct, so rotation is too, and only the light polarity was
ever at fault.

### The actual fix — invert ONCE, at the sensor

`LightSensor` now returns `raw = 1023 - total*50`; both `CogLight` maps stay
`raw * 100 / 1023`. Composed: dark -> 100, saturated -> 0.

Consistency check, which is the real test rather than wheel arithmetic — all
three must hold under one polarity:

    light LEFT     -> rightLight higher -> gradient POSITIVE
    approachLight  -> (-40, 40) -> LEFT  -> toward.  correct
    avoidLight     -> ( 40,-40) -> RIGHT -> away.    correct
    avoidObject, obstacle RIGHT -> (-40, 40) -> LEFT -> away. correct

### Standing hazard, now documented in CogLight.h

Inverting polarity in two places is undetectable by inspection of either place
alone. The contract says: invert exactly once, at the sensor, and never in the
map as well.
