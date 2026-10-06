# Valentino's Vehicles — Consistency Audit

> **STATUS (updated this session).** Findings #1, #2, #3, #4, #5 are now
> **resolved**; #8 is **deferred** by request; #6 and #7 remain as noted.
> A new behavioral defect found during the cleanup sweep — the default
> "Cowardice" vehicle being inert — was also fixed. See the "Resolution"
> note under each finding. Changes made:
> - Deleted `games/valentinos/main.py` and `games/valentinos/simulator.py`
>   (pre-adapter scaffolding; bypassed the `PhysicsAdapter` contract).
> - Fixed the default Cowardice vehicle to use live `LDR·C1/C2` names
>   (`hub.py` ~621) — it was wired to `PL/PR`, which no live reader emits,
>   so it produced zero motor output.
> - Updated stale comments/docstrings to current names: `SENSOR_NODES`
>   grouping comment and `ldr_gains` example (`engine/vehicle.py`), the
>   wiring-tutorial phase block (`hub.py`), and the shared wiring-editor
>   fallback defaults + docstring + standalone demo (`engine/builder/wiring_editor.py`).
> - Verified: legacy `RL/RR/PL/PR` kept VALID so existing engine tests and
>   older saved vehicles still load; Field Trip (which shares the wiring
>   editor) still imports and passes C6/C7.
>
> Still open: #6 (duplicate sensor readers in hub vs ntv_game — now two, not
> three), #7 (note only), #8 (the `ldr_reading`/`main.py` name collisions —
> deferred), and a separately-noted pre-existing test-harness circular import
> via the `games/valentinos/engine/*` compatibility stubs (unrelated to naming).

---

Scope: mismatches between documentation and implementation, stale code, and
contradictory code within `games/valentinos/` and the shared `engine/` modules
it depends on. Triggered by the V1 "drift along the north wall" observation,
which turned out to be correct behavior surfaced by a deeper structural split.

Severity legend: **[A]** active bug a player can hit · **[S]** stale/dead code ·
**[D]** doc/comment out of sync · **[R]** risk / latent inconsistency.

---

## The headline finding: two parallel runtimes with different sensors AND different physics

VV has **two independent run paths that do not agree**, and which one you hit
depends on how you launch the game:

| Concern        | `hub.py` (main game: tutorial, BYOV, NTV via its own loop) | `simulator.py` (the `main.py` dev launcher) |
|----------------|------------------------------------------------------------|---------------------------------------------|
| Sensor names   | `IR·L, IR·R, LDR·C1, LDR·C2`                                | `RL, RR, PL, PR`                            |
| Sensor reader  | `Hub._read_sensors` (hub.py ~662)                          | `Simulator._read_sensors` (simulator.py 151)|
| Drive+collision| `SimpleDriveAdapter.step` — **axis-separated wall sliding**| inline **full-rollback** — stop dead        |

These are not two views of one engine; they are two engines. A wiring authored
for one names sensors the other never produces, and the wall behavior differs
because the collision code differs. This is the root cause of the confusion in
this session — including my own incorrect mid-investigation conclusions.

---

## Findings

### 1. [A] `simulator.py` is stale — old sensor names, reachable from `main.py`
`Simulator._read_sensors` (simulator.py:151) emits only `RL, RR, PL, PR`. The
rest of VV was renamed to `IR·L/IR·R/LDR·C1/LDR·C2`. `simulator.py` is **not**
dead — `main.py` imports and constructs it (main.py:33, 132). So a vehicle
wired with the current `LDR·C1` names is **inert** if run through `main.py`'s
Simulator (the wire resolves to `0.0`), but **live** if run through `hub.py`
(BYOV / tutorial). Same wiring, opposite result, depending on entry point.

This is exactly the trap from this session: `LDR·C1 → FL/FR` was inert in
`simulator.py` (what I first read) but drove the robot in BYOV (the hub path).

→ Decide whether `main.py`/`Simulator` is still a supported entry point. If yes,
   port its `_read_sensors` (and default config) to the new names. If no, delete
   `simulator.py` and the `main.py` launch path, or make `main.py` route through
   the same Hub sim loop.

### 2. [A] The "drift along the wall" is correct hub behavior, not a bug
`SimpleDriveAdapter.step` (simple_drive.py:90-120) implements **deliberate wall
sliding**: on collision it retries `(new_x, old_y)` then `(old_x, new_y)`, and
updates `self._heading` unconditionally every tick. Docstring line 17 says
"Accurate wall sliding". So a light-seeking V1 that reaches the north wall keeps
its heading, slides along the wall, and creeps — expected.

The earlier mental model of "stop dead on contact" matches `simulator.py`'s
full-rollback collision (simulator.py:194-206, comment: "stop on contact, no
sliding"), NOT the hub path. So the two paths **document opposite collision
intentions** and both are in the tree. Pick one definition of wall contact for
VV and make both paths obey it (or collapse to one path per finding 1).

### 3. [S/R] `SENSOR_NODES` advertises sensors no reader emits
`engine/vehicle.py:31-34` defines:
```
SENSOR_NODES = {"RL","RR","PL","PR", "IR·L","IR·R", "LDR·C1","LDR·C2", "LDR·C3","LDR·C4"}
```
This is the union of: old names (`RL/RR/PL/PR`), current names
(`IR·L/IR·R/LDR·C1/LDR·C2`), and **never-implemented** names (`LDR·C3/LDR·C4`).
Because `VALID_SOURCES = SENSOR_NODES | …`, the wiring editor treats **all** of
these as wireable. Any wire from `RL/RR/PL/PR/LDR·C3/LDR·C4` is silently `0.0`
in the hub path. The editor lets players build dead wires with no feedback.

→ Reduce `SENSOR_NODES` to exactly what the active reader emits
   (`IR·L, IR·R, LDR·C1, LDR·C2`). Add `C3/C4` only when `_read_sensors`
   actually produces them. Until then they are aspirational nodes that present
   as functional.

### 4. [D] `VehicleConfig.ldr_gains` docstring uses retired names
`engine/vehicle.py:71` — `ldr_gains : dict e.g. {"PL": 1.2, "PR": 0.9}`.
`PL/PR` are the old names. A player following this example keys gains to sensors
the hub reader never emits, so the gains do nothing. Update the example to
`{"LDR·C1": 1.2, "LDR·C2": 0.9}`.

### 5. [D] `hub.py` wiring-tutorial phase comments contradict the tutorial's own code
The phase comment block (hub.py:381-392) describes V1 as `RL→FR, RR→FL` (crossed
IR wiring). The actual tutorial prompts and target wiring a few lines below
(hub.py:428, 454-470) use `LDR·C1 → FL and FR` (symmetric light wiring). The
comment is from an earlier design and is now actively misleading — it cost real
time in this session.

→ Rewrite the phase comments to match the implemented `LDR·C1/LDR·C2` tutorial.

### 6. [R] Three separate sensor-reading implementations, only two consistent
- `hub.py:_read_sensors` (~662): `IR·L, IR·R, LDR·C1, LDR·C2` via adapter. ✔ current
- `ntv_game.py` (~138-142): `IR·L, IR·R, LDR·C1, LDR·C2`. ✔ current, but a
  *third copy* of the same logic
- `simulator.py:_read_sensors` (151): `RL, RR, PL, PR`. �’ stale (finding 1)

Even setting aside the stale one, the hub and NTV readers are duplicated logic
that must be kept in lockstep by hand. They already differ in detail (NTV builds
`SensorReadings(**{...})`; hub builds a plain dict via an adapter helper). One
shared `read_sensors(robot, arena, adapter)` would remove the drift risk.

### 7. [S] Compatibility stubs are fine — noted so they're not mistaken for dupes
`games/valentinos/engine/robot_body.py` (5 lines) and
`games/valentinos/engine/vehicle.py` (stub) both just `from engine.X import *`.
These are intentional shims after the modules moved up to `engine/`. Not a
problem — but they mean there is exactly **one** real `robot_body`/`vehicle`,
which is good. (Note: `engine/robot_body.py` also defines its own
`ir_reading`/`ldr_reading` that are NOT the `engine/sensor_physics.py` versions;
that duplication is real but currently consistent — see finding 8.)

### 8. [R] Two `ldr_reading` / `ir_reading` implementations, different signatures
- `engine/sensor_physics.py`: `ldr_reading(wx, wy, angle_world, arena, …)` —
  spatial field sampler (Field Trip's path; also the one this session's
  `intensity` change touched).
- `engine/robot_body.py`: `ldr_reading(illuminance, gain)` — scalar mapper
  (Valentino's path). Its own docstring calls `sensor_physics` "the
  authoritative implementation" yet does not delegate to it.

Today these don't conflict because VV calls the scalar one and FT calls the
spatial one. But the naming collision is a latent trap: an edit to "the"
`ldr_reading` can silently hit the wrong game. Recommend renaming one
(e.g. `robot_body.ldr_normalize`) so the two are never confused.

---

## What is NOT wrong (verified, to bound the audit)
- The compatibility stubs (finding 7) are correct and intentional.
- The Field Trip force model is fully isolated; nothing in VV imports
  `field_physics`, `compute_force`, `force_to_motors`, or `FieldSensor`.
- The session's `intensity` change to `sensor_physics.ldr_reading` does not
  reach VV (VV uses `robot_body.ldr_reading`). VV's behavior this session was
  pre-existing.

---

## Suggested order of operations
1. **Decide the entry-point question** (finding 1): is `main.py`/`Simulator`
   still supported? This gates everything else.
2. If retiring it: delete `simulator.py` + its `main.py` path. If keeping it:
   route it through the hub sim loop so there is one reader and one collision.
3. **Unify the sensor reader** (finding 6) into one shared function.
4. **Trim `SENSOR_NODES`** to the real, emitted set (finding 3); decide
   `C3/C4`'s fate.
5. **Pick one wall-contact semantics** (finding 2) — slide vs stop — and make it
   the only one.
6. Sweep the **doc/comment fixes** (findings 4, 5, 8 rename).

None of these are urgent in the "game is broken" sense — the hub path (what
players use) is internally consistent and behaves as designed. They are
correctness-of-the-codebase issues that will keep generating confusion (as they
did this session) until reconciled.
