# PAW-Robotics — Continuation Handoff (end of dev13)

Hand this file to a new chat along with the latest zip. It is written to be read
cold: environment first, then what changed, then what is unresolved.

---

## 1. Environment / restore

Working copy lives at `/home/claude/PAW/PAW-Robotics-refactor/`.
**The filesystem resets between sessions.** To restore:

```
cd /home/claude/PAW && unzip -q /mnt/user-data/outputs/<latest>.zip
```

Latest package: **`PAW-Robotics-refactor_25062026al.zip`**

Notes that bite every session:
- `pip install pygame --break-system-packages -q` (also `matplotlib` if plotting).
  pygame must be reinstalled each session before any `hub.py` import.
- Headless pygame: `os.environ["SDL_VIDEODRIVER"]="dummy"; pygame.init();
  pygame.display.set_mode((100,100))` — the `set_mode` call is required, not optional.
- Run scripts **from the repo root** so `engine.*` imports resolve. Heredoc
  (`python3 << 'EOF'`) works; `/tmp/foo.py` does not (no `games` on path).
- Repackage: `cd /home/claude/PAW && zip -rq /mnt/user-data/outputs/PAW-Robotics-refactor_<date><letter>.zip PAW-Robotics-refactor -x "*.pyc" -x "*__pycache__*"`

Layout: games under `games/` (`field_trip/`, `valentinos/`, `ethology/`), shared
code in `engine/`, web sim in `byov_web/`, firmware in `firmware/`.
User ("doubleonick") is on Windows and playtests the real games; Claude edits,
runs headless tests, packages zips, previews with `present_files`.

Prior transcripts: `paw-robotics-dev.txt` … `dev12.txt`, catalogued in
`/mnt/transcripts/journal.txt`. This segment is **dev13**.

---

## 2. How to reach things

Field Trip has its own CLI (`paw.py --game` only picks the *game*, not the challenge):

```
python games/field_trip/hub.py --challenge N     # N is 1-based sequence position
```

Current sequence (22 authored challenges, then procedural):

| N | id | label |
|---|----|-------|
| 1–14 | c01,c02,c04…c15 | main curriculum (c03 "Circle the Light" is deferred) |
| 15 | c16 | The Maze (serpentine, colored waypoints) |
| 16–17 | c17,c18 | Spiral Out / Spiral In |
| 18–22 | cp1–cp5 | **PF boundary probes** (see §4) |
| 23+ | — | procedurally generated |

BYOV web: `cd byov_web && python3 -m http.server 8000` → `http://localhost:8000`.
ES modules need a server; `file://` will not work. Nothing is deployed by this.
Deploying is just commit+push (Pages is already configured); module specifiers
carry `?v=N` for cache-busting — **bump it on every JS/CSS edit**.

---

## 3. What changed in dev13

### Field Trip / builder
- **Builder sensor+motor left-right flip FIXED** (pre-existing): `_export_sensor`
  saved `y_m = -canvas_x` but load read `canvas_x = y_m` without re-negating, so
  every round-trip mirrored. Both sensors and motors now negate on load.
- **Wall pass-through FIXED**: `_blocked()` used `BODY_RADIUS-0.004`, ignoring wall
  thickness. Now `BODY_RADIUS + half_thickness - 0.004` per wall; `check_reach_wall`
  updated to match (`dist <= body_radius + half_t`).
- **Script index bug FIXED**: `_load_narration` mapped `ft_c{idx+1}` by *sequence
  position*, so deferring c03 made every later challenge load the previous one's
  script. Now maps by the challenge's own id (`c04 → ft_c4`).
- **Single source of truth for challenge geometry**: `Challenge.__post_init__` either
  auto-derives `sources` from `arena`, or validates an explicit `sources` list against
  arena geometry and raises a clear OUT-OF-SYNC error. Dead in-code `narration={...}`
  dicts removed (the game reads `.txt` scripts).
- **Tour offer shown once**: `WiringEditor(tour_already_offered=...)`; Valentino's Hub
  sets it after the first guided edit, so PAW-Bot's full offer no longer interrupts
  every subsequent visit (collapsed "Play Tour" link instead).
- **Procedural challenges FIXED** — see §5, item 3.

### BYOV web (shipped simulator)
Rewritten to v3 after user feedback. All changes are web-only; no Python touched.
- **Neurons are optional.** Default is direct sensor→motor wiring. `addNeuron()` /
  `removeLastNeuron()` (LIFO), capped at **6**, laid out **3 rows of 2**.
- **Wire colour = weight**, not excite/inhibit: blue 1×, green 2×, red 3× — matching
  `engine/signals.py`, so web and Python agree. Left-click a wire cycles colour,
  right-click removes.
- **Meters M1–M3** permanently installed between sensor headers and neuron rows; one
  wire each; **display only**, never affect motors.
- **Motors have FORWARD/REVERSE banks of 4 sockets** (like the board's FL/BL, FR/BR),
  no excite/inhibit. Motor value = `clamp(sharedBias + Σfwd − Σrev, −1, 1)`.
- **One shared bias pot** between the motors (a resting speed); no per-motor pots.
- **Meter HUD in the arena canvas**: three 10-segment LED bars, side by side, M1 M2 M3
  left-to-right, in a 118px left gutter. M1/M3 red, M2 white. Glow while running.
- Presets rewritten as direct sensor→motor; **presets no longer delete neurons** —
  they sever wires but keep neurons and their biases (meter wiring survives too;
  the shared pot resets because each preset sets it deliberately).

### Robot Ethology
- `games/ethology/arenas/arena_spiral.json` — spiral arena scaled to RE's 1.5×2.5
  arena and larger robot (body radius 0.0775), corridors ~0.24 m, robots start centre,
  light in the top-right corner. User wants it for a **control-schema comparison via
  the hypothesis-testing path**, not to play the game as intended. A "CB: Spiral"
  bundle exists in `replays.json` but is optional.

### Reverted deliberately (do not re-add without asking)
- Chassis outline behind the wiring panel — distorted the octagon/triangle and put a
  rival silhouette next to the true-scale robot.
- Translucent board sketch on the robot canvas — read as too busy.
- **Decision: the builder keeps two distinct views.** Full merge was considered and
  rejected: metric peg-holes plus dense circuitry compete for the same space.

---

## 4. The PF boundary investigation (the live thread)

**Goal:** map where potential fields / Push-Pull succeed and fail, to decide whether
FW-013's Maze can be a three-tier progression (choose a schema → combine schemas →
new capability) or collapses to two tiers.

**Constraints that matter:** the user playtests with **IR + LDR, Push/Pull only**.
Tangential styles (Orbit, Flow-around) are hidden behind `radial_only=True`. Any
solvability claim must be made inside that space or it is not about their game.

**Probes** `cp1`–`cp5` are in `ALL_CHALLENGES` (challenges 18–22), each with a
push/pull prefab in `games/field_trip/solutions/FT_CP*_solution.json`, wired via
`solution_file` so "Show Solution" loads the build.

| probe | feature | push/pull configs solving (of 729) | best time |
|-------|---------|-----------------------------------|-----------|
| cp1 | centered barrier (symmetric cancellation) | 33 | 6.5 s |
| cp2 | U-trap (concave local minimum) | 12 | 6.5 s |
| cp3 | double-back (long away-from-goal exit) | **2** | 34 s |
| cp4 | shallow spiral, wind inward | **1** | 13.2 s |
| cp5 | dead-end, back out of a pocket | 15 | 16.3 s |

**Current conclusion (weaker than earlier in the session, and that matters):**
there is **no hard reactive wall** among these. As the away-from-goal stretch
lengthens, the solution band becomes *vanishingly narrow* (2/729, 1/729) and slow
(34 s of a 45 s budget). So the argument for memory/state rests on **search
difficulty and robustness**, not on strict impossibility.

**Winning morphology throughout** is the user's own earlier discovery: asymmetric
Push/Pull produces **emergent circulation** — LDR Seek angled off-axis plus an IR Flee
aimed to one side, both laterally offset. No explicit tangential term is needed.

### Methodology rules learned the hard way (follow these)
1. **Flood-fill reachability FIRST.** Is the goal reachable from the start, and is the
   start unblocked? cp3 was once a *fully sealed chamber* (420 reachable cells, goal
   not among them) and its "0/729 — the reactive wall" verdict was meaningless.
2. **"Robot gets stuck" is not validation.** A sealed arena passes that test for the
   wrong reason.
3. **Validate the experiment, not just the solver.** An early "Double-Back" probe was
   solved by rounding one wall end — traced, zero y-reversals. The arena did not test
   its own name.
4. **Search inside the player's real constraints and the game's real semantics.** Two
   separate bugs came from not doing this: searching arbitrary tangential magnitudes
   the builder cannot produce (it only offers ±3.0), and passing `policy=0` directly
   when the hub applies `ORBIT_INWARD=0.3` for orbit styles.
5. **Corridors need > 0.119 m** centre-to-centre (body radius 0.047 + wall half
   thickness 0.0125 per side); use ≥ 0.16 m for comfort.
6. **Prefabs must survive a builder round-trip**, not just load.

---

## 5. Open questions / next steps

1. **Re-check the deep-spiral result from dev12.** c17/c18 were declared "not
   traversable by reactive control" *before* the reachability check existed, and were
   built the same way as the sealed cp3. **Treat that conclusion as unverified.**
2. **The middle tier of the Maze progression is in doubt.** If most single-schema
   failures are actually solvable with better morphology, the set of "one schema fails
   but a *memoryless combination* solves" may be small or empty. The dedicated
   combination probe has **not** been run. This is the highest-value next
   investigation, and it gates FW-013's shape (and whether FW-012 must come first).
3. **Procedural generation is unproven.** Challenge 23+ regenerated every frame
   (`_current_challenge()` called `generate_challenge()` with no seed/cache from the
   draw loop). Fixed by seeding from the index and caching in `Hub._generated`. But:
   the whole stage-4 tier had never been exercised, and `generate_challenge` does
   **not** check that its arenas are reachable or solvable. If procedural mazes
   proceed, put the flood-fill check *inside* the generator.
4. **FW-013 Q1 and Q2 remain unanswered** (from `FUTURE_WORK.md`): which NB mechanic
   is Maze meant to prove out, and is "combination of logics" real or optional? Q2
   determines whether FW-012 (unified sensor→motor abstraction) must land first.
5. Smaller, still open: rewrite `ft_c4.txt` (still has the old flow-around framing —
   c04 is now solvable, so the teaching-wall text may be unwanted); write
   `ft_c5.txt`–`ft_c15.txt` (those challenges show no narration); review C05's shipped
   solution (fails its own avoid-light rule); c16 waypoint hand-off refinement
   (a passed waypoint keeps pulling — needs tiny-radius/high-peak locals); strip
   `[BLE-DEBUG]` prints from `games/ethology/hierarchy_builder.py` before a classroom
   build; browser click-test of the BYOV motor FWD/REV banks and `+`/`−` buttons.

---

## 6. Working relationship notes

The user is a domain expert who playtests and **catches real errors repeatedly** —
several of this session's most important corrections came from them, not from me:
that asymmetric Push/Pull yields emergent circulation (correcting my "impossible"
claim); that the probe arenas did not test their own features; that cp3 was a sealed
chamber; that I had been searching outside their Push/Pull constraints.

What works: investigate before building; verify claims with code rather than
asserting; state plainly what is tested vs assumed; push back on scope sprawl;
preview before committing; keep `FUTURE_WORK.md` appended with findings **including
the corrections**. Do not over-claim impossibility from a thin search — that error
recurred twice this session and both times the user was right.
