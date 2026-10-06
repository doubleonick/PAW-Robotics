# PAW-Robotics — Continuation Handoff (end of dev14)

Hand this file to a new chat with the latest zip. Written to be read cold.
Supersedes `HANDOFF_dev13.md`, which is retained for the PF-boundary history.

---

## 1. Environment / restore

```
cd /home/claude/PAW && unzip -q /mnt/user-data/uploads/<latest>.zip
```

Latest package: **`PAW-Robotics-refactor_05082026ay.zip`** (or later).

**PyBullet is now required and takes ~13 minutes to build.** There is no
prebuilt wheel on PyPI for any platform — it is source-only. A built wheel is in
the outputs:

```
pip install <path>/pybullet-3.2.7-cp312-cp312-linux_x86_64.whl --break-system-packages
```

**Re-upload that wheel rather than rebuilding.** If you must rebuild, note that a
bash command timeout kills its whole process group — use
`setsid nohup pip wheel pybullet --no-deps -w ~/pbwheel &` and poll.

Also each session:
- `pip install pygame --break-system-packages -q`
- Headless: `os.environ["SDL_VIDEODRIVER"]="dummy"; pygame.init();
  pygame.display.set_mode((100,100))` — `set_mode` is required.
- Run from the repo root so `engine.*` resolves. Heredocs work; `/tmp/foo.py`
  does not.
- Repackage: `cd /home/claude/PAW && zip -rq
  /mnt/user-data/outputs/PAW-Robotics-refactor_<date><letter>.zip
  PAW-Robotics-refactor -x "*.pyc" -x "*__pycache__*"`

User ("doubleonick") is on Windows, playtests the real games, and **catches real
errors repeatedly**. Several of this session's most important corrections came
from them, not from me.

---

## 2. What dev14 was about

Not the maze investigation it started as. It became: bring **Perception, Action
and World** into register across Field Trip, Robot Ethology and Valentino's.

See `CHANGELOG.md` v2.6 for the full list, `ARCHITECTURE.md` for the layer model,
`REGRESSION_LOG.md` for what broke and why, `FUTURE_WORK.md` (dev14a–dev14j) for
the investigation trail including the corrections.

**The one-line summary:** almost every finding was geometry or units, not
control. Arena sizes, a 9%-wrong chassis, a wheelbase standing in for a body
width, three different sensor thresholds, a sensor model that clamped where the
hardware folds back.

---

## 3. BROKEN — fix before anything else

1. **VV vehicle demo does not play.** Appeared after the `PyBulletAdapter` port.
   The adapter works in isolation (verified: steps, poses, ray casts, contacts).
   Undiagnosed. `REGRESSION_LOG` R-14i.
2. **RE and VV arenas render with partially occluded walls.** FT renders
   correctly. Ruled out: arena conformance, `arena_scale`/`world_to_screen`
   (byte-identical between VV's local copy and the engine's), canvas rects.
   Not reproduced headlessly. R-14j. **User's call: make RE and VV render through
   FT's exact path**, and delete `games/valentinos/arena/arena.py`.
3. **Four of five FT solution prefabs fail** (cp2–cp5). "Show Solution" loads a
   build that does not solve. R-14a.

The user has explicitly deferred looking at what the FT arena resize did to the
challenges until 1 and 2 are fixed.

---

## 4. Numbers you must not trust

**Every "N of 729" figure predating dev14 is void.** They have now been
invalidated seven times over the project's history, by: a sealed arena, corridor
width, world scale, control rate, fold-back, the chassis correction, and polygon
physics.

`tools/pf_sweep.py` is the only re-runnable source. Regenerate anything that
matters. The config grid (27 mountings per sensor: 9 angles x 3 offsets) is
reconstructed from the shipped prefabs and reproduces cp1/cp2 closely but
diverges on cp4/cp5 — the original grid is unrecoverable.

**Solvability is now per-chassis.** "Is cp3 solvable" has no answer without
naming the robot. That is the intended lever, not a defect.

---

## 5. Live findings worth keeping

- **A memoryless wall-follower solves 80/80 generated perfect mazes** (40 seeds,
  both handednesses). Loop-freeness is not what makes mazes hard for a reactive
  robot — it is what makes them **solvable**. Tier 3 (memory) needs **braided**
  mazes, so the generator must *add* loops.
- **RE's hierarchy traverses a 44 cm serpentine** with Escape_Front +
  Avoid_Object + **Cruise_ARC**. Cruise_Straight fails: a symmetric avoid plus a
  symmetric cruise has no handedness to break the tie at a reversal.
- **Push/pull also solves it** — 6 of 225 coarse configs, best 58 s of 90. Every
  winner has IR at −90° with a +0.04 lateral offset: the user's own
  emergent-circulation morphology. I predicted PF would fail; I was wrong.
- **Corridor floors are absolute, not relative to the robot**: 30 cm for honest
  IR, 36 cm for RE's proximity gradient. A smaller chassis does not help.
- **c17/c18 spirals remain unverified**, now for a third reason: 26.6 cm
  corridors, still below the 30 cm floor.
- The **goal light is a recogniser, not a beacon**, inside a maze — zero on 27 of
  38 path cells, non-monotonic in distance. Wall shadowing gives that for free.

---

## 6. Queued

1. Re-run `pf_sweep` on the adapter; regenerate all five prefabs (legibility
   first, robustness tiebreaker, speed as a floor).
2. **Robot start placement review, 23 challenges, position and heading.** Budgets
   stretched x1.79 with the canvas fit; the fix is placement, not a bigger
   multiplier. The user's point: a robot parked far from the light satisfies
   "avoid" by doing nothing — start it INSIDE the light's field of influence.
3. Delete `engine/arena.py` (dead, shadowed) and
   `games/valentinos/arena/arena.py` (duplicate) after diffing.
4. Conformance harness: SimpleDrive vs PyBullet on identical arenas.
5. Start screens — PAW-Bot in the narrative panel, a stylistic scene per game
   keyed to the banner. Design direction only, nothing built.
6. Hardware: **measure the real IR curve.** `_FOLD_GAIN = 4.0` is a guess from
   the datasheet shape, and it sets the 30 cm corridor floor.

---

## 7. Working relationship notes

What works: investigate before building; verify with code rather than asserting;
state plainly what is tested vs assumed; push back on scope sprawl; keep
`FUTURE_WORK.md` appended **including the corrections**.

Errors I made this session, all caught by measurement or by the user:
- Called the spiral arena's "0.24 m corridor" wrong; it was centre-to-centre and
  correct, and I was measuring face-to-face.
- Predicted potential fields would fail the serpentine. They solve it.
- Claimed fold-back was what made wall-following reachable. That was an artifact
  of the too-small arena and does not survive the scale fix. Withdrawn.
- Over-corrected VV's collision radius from "buried in the wall" to "floating
  3 cm clear" — the mirror-image error.
- Edited `engine/arena.py` and wondered why nothing changed. It is dead code.
- Wrote a smoke test whose sign check failed because the robot turned past 180°.
  The adapter was right; the test was wrong.

Three separate conclusions in this project's history have been overturned by
arena geometry rather than control. Check the geometry first.
