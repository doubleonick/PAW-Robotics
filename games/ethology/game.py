"""
games/ethology/game.py
-----------------------
Robot Ethology game state manager.

Handles:
  - Semi-random target hierarchy generation for robots A and B
  - Experiment counter (20 total, tracked per robot)
  - Correctness checking (exact ordered match)
  - Game state persistence between hub sessions

Target hierarchies are stored in memory only — never written to
disk in a player-accessible location. The targets/ folder contains
the robot.json and sketch files used for the observation phase,
but the actual hierarchy ordering is held in this object.
"""

from __future__ import annotations
import json
import os
import datetime
from dataclasses import dataclass, field

GAME_DIR = os.path.dirname(os.path.abspath(__file__))

MAX_EXPERIMENTS = 20


# DEV MODE — fixed hierarchy
def generate_hierarchy() -> list[str]:
    return ["escape_front", "avoid_object", "approach_light", "cruise_straight"]


def _load_hierarchy(filename: str) -> list[str] | None:
    """Load a hierarchy spec (a priority-ordered list of behavior names) from
    the hierarchies/ folder. Returns the behavior list, or None if missing /
    invalid so callers can fall back. Any hierarchy file may be loaded and
    assigned to one or both robots — the file is the unit; how it's assigned is
    the caller's choice.

    Designed toward FW-006: the instructor tool's hierarchy builder will WRITE
    these same files, so the game/tool contract is one folder of JSON specs.
    """
    from games.ethology.codegen import BEHAVIOR_MAP, canonical_hierarchy
    path = os.path.join(GAME_DIR, "hierarchies", filename)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        behaviors = data.get("behaviors", [])
        # Translate pre-convention wire names ("seek_light", "escape_rear")
        # BEFORE filtering. Without this they fail the BEHAVIOR_MAP test below
        # and are silently DROPPED — a saved hierarchy would quietly come back
        # a rung short and stop matching the target it used to match.
        behaviors = canonical_hierarchy(behaviors)
        # keep only recognized behavior keys, preserving order
        valid = [b for b in behaviors if b in BEHAVIOR_MAP]
        return valid or None
    except Exception:
        return None


def list_hierarchies() -> list[str]:
    """Return the available hierarchy filenames (for pools / selection later)."""
    d = os.path.join(GAME_DIR, "hierarchies")
    try:
        return sorted(f for f in os.listdir(d) if f.endswith(".json"))
    except Exception:
        return []


def load_replay_manifest() -> list[dict]:
    """Read the replay manifest (replays.json) — the single registry of valid
    replay bundles. Each bundle names an arena, two morphologies (A/B) and a
    shared hierarchy. Origin is tagged per entry ('CB' curated, 'AG' auto-
    generated) so hand-authored and generated replays coexist in one registry.

    Returns the list of bundle dicts (empty if the manifest is missing). The
    FW-006 instructor tool will read/write this file; constrained generation
    will APPEND 'AG'-tagged entries here rather than maintain a parallel system.
    """
    path = os.path.join(GAME_DIR, "replays.json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh).get("replays", [])
    except Exception:
        return []


def _load_morphology(filename: str) -> dict | None:
    """Load a robot morphology spec (body + sensor layout) from the
    morphologies/ folder. Returns None if missing so the game still runs
    (the inspector simply won't be offered for that robot)."""
    path = os.path.join(GAME_DIR, "morphologies", filename)
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


@dataclass
class RobotTarget:
    label:     str              # "A" or "B"
    hierarchy: list[str]        # the secret target hierarchy
    color:     tuple            # render color
    solved:    bool   = False   # player guessed correctly
    morphology: dict | None = None   # body/sensor spec (robot_X.json), or None


@dataclass
class Experiment:
    robot_label:  str
    hypothesis:   list[str]
    correct:      bool
    timestamp:    str = field(default_factory=lambda:
                              datetime.datetime.now().isoformat())


class GameState:

    def __init__(self):
        self.targets: dict[str, RobotTarget] = {}
        self.experiments: list[Experiment]   = []
        self._started = False
        # Arena filename a loaded replay bundle wants (the hub reads this from
        # arenas/); None means "use the hub's normal arena resolution".
        self.arena_ref: str | None = None
        # Sequential replay-selection cursor: which manifest bundle to try next.
        # Advances on each new_game() so "Play Again" cycles through the pool.
        self._bundle_cursor: int = 0

    @property
    def experiments_remaining(self) -> int:
        return max(0, MAX_EXPERIMENTS - len(self.experiments))

    @property
    def is_over(self) -> bool:
        all_solved = all(t.solved for t in self.targets.values())
        return all_solved or self.experiments_remaining == 0

    def load_replay(self, bundle: dict) -> bool:
        """Load a replay bundle (one manifest entry) into the game: each robot's
        morphology and hierarchy, plus the arena reference for the hub. Returns
        True if the core pieces loaded.

        Hierarchies are PER ROBOT (hierarchy_a, hierarchy_b) — symmetric with
        morph_a / morph_b. The embodiment-lesson case points both at the SAME
        file (same logic, different bodies), but the format permits different
        hierarchies per robot, which the FW-006 instructor tool will want.
        (A bundle may also use a single legacy 'hierarchy' key, applied to both.)

        WHICH bundle to load (selection policy) is intentionally the caller's /
        future tool's job; this method faithfully loads the one it is handed.
        """
        morph_a = _load_morphology(bundle.get("morph_a", ""))
        morph_b = _load_morphology(bundle.get("morph_b", ""))
        shared  = bundle.get("hierarchy")          # optional convenience key
        hier_a  = _load_hierarchy(bundle.get("hierarchy_a", shared or ""))
        hier_b  = _load_hierarchy(bundle.get("hierarchy_b", shared or ""))
        if not (morph_a and morph_b and hier_a and hier_b):
            return False
        self.targets = {
            "A": RobotTarget("A", list(hier_a), (200, 50, 50),
                             morphology=morph_a),
            "B": RobotTarget("B", list(hier_b), (50, 80, 200),
                             morphology=morph_b),
        }
        # the arena filename for the hub to load (arena lives in arenas/)
        self.arena_ref = bundle.get("arena")
        self.experiments = []
        self._started    = False
        return True

    def assign_hierarchy(self, filename: str,
                         robots: tuple[str, ...] = ("A", "B")) -> bool:
        """Load a hierarchy file and assign it to one or both robots.

        This is the general capability behind the embodiment setup: any
        hierarchy in existence can be loaded into either robot, or both. The
        default new_game() path loads one shared hierarchy into both; the
        instructor tool (FW-006) will use this same mechanism to assign
        hierarchies freely. Returns True on success.
        """
        h = _load_hierarchy(filename)
        if not h:
            return False
        for label in robots:
            t = self.targets.get(label)
            if t is not None:
                t.hierarchy = list(h)
        return True

    def _pick_morphology_pair(self) -> tuple[dict | None, dict | None]:
        """Return the (A, B) morphology specs for this game.

        Designed toward FW-006: the instructor authoring tool will ultimately
        OWN the morphologies/ folder and decide hierarchy + morphology variance.
        So the game's job is simply to LOAD whatever specs live there — today
        the two hand-authored example files, tomorrow whatever the tool writes.
        This keeps the game/tool contract a single folder of JSON specs, so the
        tool slots in later with no change here. Variation/selection policy is
        deliberately NOT baked in now; that is the tool's responsibility.
        """
        morph_A = _load_morphology("morph_wide_splayed.json")
        morph_B = _load_morphology("morph_forward_close.json")
        return morph_A, morph_B

    def new_game(self) -> None:
        """Generate fresh targets and reset experiment log.

        The pedagogical core of Robot Ethology: robots A and B run the SAME
        behaviour hierarchy but have DIFFERENT morphologies (sensor placement /
        angle). Identical logic + different embodiment ⇒ visibly different
        behaviour — so the player must NOT conclude "different behaviour means
        different logic". Hence both robots share one hierarchy here; only their
        morphology differs.

        Content comes from the replay manifest (replays.json) when present — the
        single registry of valid bundles. Selection is SEQUENTIAL: each
        new_game() (i.e. each "Play Again") advances to the next bundle, wrapping
        around at the end, so the player cycles through the authored pool. A
        bundle that fails to load (a referenced file is missing/typo'd) is
        SKIPPED with a logged warning rather than masking the rest — only if NO
        bundle in the manifest loads do we fall back to the direct example files.
        (Sequential is a simple, predictable policy; the FW-006 instructor tool
        may later govern selection more richly.)
        """
        manifest = load_replay_manifest()
        n = len(manifest)
        if n:
            # try each bundle once, starting at the cursor, skipping broken ones
            for step in range(n):
                idx = (self._bundle_cursor + step) % n
                if self.load_replay(manifest[idx]):
                    # next call resumes AFTER the one we just loaded
                    self._bundle_cursor = (idx + 1) % n
                    return
                else:
                    import sys
                    print(f"[ethology] replay bundle skipped (missing/invalid "
                          f"file): {manifest[idx].get('name', idx)}",
                          file=sys.stderr)
            # no bundle loaded — fall through to defaults
            print("[ethology] no replay bundle loaded; using default files",
                  file=sys.stderr)
        # ── Fallback: direct example files (no manifest / none loaded) ──
        shared_hierarchy = (_load_hierarchy("hier_default_target.json")
                            or generate_hierarchy())
        morph_A, morph_B = self._pick_morphology_pair()
        self.targets = {
            "A": RobotTarget(
                label="A",
                hierarchy=list(shared_hierarchy),
                color=(200, 50, 50),    # red
                morphology=morph_A,
            ),
            "B": RobotTarget(
                label="B",
                hierarchy=list(shared_hierarchy),
                color=(50, 80, 200),    # blue
                morphology=morph_B,
            ),
        }
        self.experiments = []
        self._started    = False

    def record_experiment(self, robot_label: str,
                          hypothesis: list[str]) -> bool:
        """
        Test hypothesis against target. Records result.
        Returns True if correct.
        Raises ValueError if robot already solved or no experiments left.
        """
        if self.experiments_remaining <= 0:
            raise ValueError("No experiments remaining")
        target = self.targets.get(robot_label)
        if target is None:
            raise ValueError(f"Unknown robot: {robot_label}")
        if target.solved:
            raise ValueError(f"Robot {robot_label} already solved")

        correct = (hypothesis == target.hierarchy)
        if correct:
            target.solved = True

        self.experiments.append(Experiment(
            robot_label=robot_label,
            hypothesis=hypothesis,
            correct=correct,
        ))
        return correct

    def experiments_for(self, robot_label: str) -> list[Experiment]:
        return [e for e in self.experiments if e.robot_label == robot_label]

    def can_experiment_on(self, robot_label: str) -> bool:
        target = self.targets.get(robot_label)
        if target is None or target.solved:
            return False
        return self.experiments_remaining > 0

    def target_sketch_source(self, robot_label: str) -> str:
        """
        Return the target sketch as an in-memory string — never written to disk.
        The player cannot access this.
        """
        if not self.targets:
            raise RuntimeError("new_game() must be called first")
        from games.ethology.codegen import generate_sketch
        target = self.targets[robot_label]
        return generate_sketch(target.hierarchy,
                               f"target_{robot_label}.ino")
