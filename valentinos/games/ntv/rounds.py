"""
valentinos/games/ntv/rounds.py
--------------------------------
Round generation and scoring for Name That Vehicle.

Round structure (1-based round number):
  1–5   : 1 behavior,  3 choices
  6–10  : 1 behavior,  5 choices
  11–25 : 2 behaviors, 5 choices
  26–40 : 3 behaviors, 5 choices
  41+   : 1–3 behaviors randomly, 5 choices

A Round holds:
  - the correct component list (the vehicle(s) being shown)
  - a list of Choice objects (what the player sees)
  - the scoring state for this round

Scoring per round:
  correct_score : 0.0–1.0, updated incrementally per correct component found
  incorrect_score : 0.0 or 1.0, set only at round end (= fraction never found)
  Each component is worth 1/N where N = number of behaviors.
  A component can only be credited once.
"""

from __future__ import annotations
import random
from dataclasses import dataclass, field
from itertools import combinations

from valentinos.games.ntv.vehicles import (
    VehicleDef, VehicleConfig,
    COMBINABLE, INTRO_ORDER, ALL_VEHICLES,
    make_compound, compound_label, component_keys,
)


# ── Round spec ────────────────────────────────────────────────────────────────

@dataclass
class Choice:
    """One entry in the player's choice list."""
    components: list[VehicleDef]   # what this choice represents
    label:      str                 # display text
    keys:       frozenset          # frozenset of .key for comparison

    @classmethod
    def from_components(cls, components: list[VehicleDef]) -> "Choice":
        return cls(
            components=list(components),
            label=compound_label(components),
            keys=component_keys(components),
        )


@dataclass
class Round:
    number:     int                 # 1-based
    correct:    list[VehicleDef]   # the actual vehicle(s) being shown
    choices:    list[Choice]        # what the player sees (includes correct)
    config:     VehicleConfig      # merged wiring for the sim

    # Scoring state
    found_keys:     set = field(default_factory=set)  # component keys credited
    guesses_made:   int = 0
    round_over:     bool = False

    @property
    def n_behaviors(self) -> int:
        return len(self.correct)

    @property
    def value_per_behavior(self) -> float:
        return 1.0 / self.n_behaviors

    @property
    def correct_keys(self) -> frozenset:
        return component_keys(self.correct)

    def evaluate_guess(self, choice: Choice) -> dict:
        """
        Process one guess. Returns a result dict:
          newly_correct : list[str]  — short_names of newly credited behaviors
          already_had   : list[str]  — correct but already credited
          wrong         : list[str]  — components in guess that are not correct
          correct_delta : float      — how much correct_score increased
          round_over    : bool
          reveal        : bool       — True if answer should be shown
        """
        self.guesses_made += 1

        newly_correct = []
        already_had   = []
        wrong         = []

        for key in choice.keys:
            if key in self.correct_keys:
                if key not in self.found_keys:
                    self.found_keys.add(key)
                    newly_correct.append(ALL_VEHICLES[key].short_name)
                else:
                    already_had.append(ALL_VEHICLES[key].short_name)
            else:
                wrong.append(ALL_VEHICLES[key].short_name)

        correct_delta = len(newly_correct) * self.value_per_behavior

        # Round ends when all behaviors found OR 3 guesses made
        all_found = self.found_keys >= self.correct_keys
        out_of_guesses = self.guesses_made >= 3

        if all_found or out_of_guesses:
            self.round_over = True

        return {
            "newly_correct":  newly_correct,
            "already_had":    already_had,
            "wrong":          wrong,
            "correct_delta":  correct_delta,
            "all_found":      all_found,
            "round_over":     self.round_over,
            "reveal":         self.round_over and not all_found,
            "guesses_made":   self.guesses_made,
        }

    def incorrect_fraction(self) -> float:
        """Call at round end. Returns fraction of behaviors never found."""
        unfound = self.correct_keys - self.found_keys
        return len(unfound) * self.value_per_behavior

    def feedback_for_guess(self, result: dict) -> str:
        """Human-readable feedback string for this guess result."""
        nc = result["newly_correct"]
        wr = result["wrong"]
        n  = self.guesses_made

        if result["all_found"]:
            if self.n_behaviors == 1:
                return "Well done!"
            if len(nc) == self.n_behaviors:
                return "Well done!"
            found_all = sorted(self.found_keys)
            names = ", ".join(ALL_VEHICLES[k].short_name for k in found_all)
            return f"Well done! You identified: {names}"

        if result["reveal"]:
            correct_names = compound_label(self.correct)
            return f"The answer was: {correct_names}"

        # Partial feedback
        lines = []
        if nc:
            lines.append(f"Correct: {', '.join(nc)}")
        if wr:
            lines.append(f"Not quite: {', '.join(wr)}")

        if n == 1:
            lines.append("Try again.")
        elif n == 2:
            lines.append("Sorry. One last guess...")

        return "  ".join(lines) if lines else "Try again."


# ── Round complexity spec ─────────────────────────────────────────────────────

def _complexity_for_round(round_num: int) -> tuple[int, int]:
    """Returns (n_behaviors, n_choices) for a given round number."""
    if round_num <= 5:
        return 1, 3
    elif round_num <= 10:
        return 1, 5
    elif round_num <= 25:
        return 2, 5
    elif round_num <= 40:
        return 3, 5
    else:
        return random.choice([1, 2, 3]), 5


# ── Choice pool builders ──────────────────────────────────────────────────────

def _all_combos_of_size(n: int) -> list[list[VehicleDef]]:
    """All combinations of n vehicles from COMBINABLE."""
    return [list(c) for c in combinations(COMBINABLE, n)]


def _build_choices(correct: list[VehicleDef],
                   n_choices: int,
                   n_behaviors: int) -> list[Choice]:
    """
    Build a choice list containing the correct answer plus distractors.
    All choices have the same number of components as the correct answer.
    """
    correct_keys = component_keys(correct)
    pool = _all_combos_of_size(n_behaviors)

    # Remove the correct one from pool (we'll add it back)
    pool = [c for c in pool if component_keys(c) != correct_keys]

    # Sample distractors
    n_distractors = n_choices - 1
    if len(pool) <= n_distractors:
        distractors = pool
    else:
        distractors = random.sample(pool, n_distractors)

    choices = [Choice.from_components(correct)]
    for d in distractors:
        choices.append(Choice.from_components(d))

    random.shuffle(choices)
    return choices


# ── Round factory ─────────────────────────────────────────────────────────────

def generate_round(round_num: int,
                   rng: random.Random | None = None) -> Round:
    """Generate one NTV round for the given round number."""
    if rng is None:
        rng = random.Random()

    n_behaviors, n_choices = _complexity_for_round(round_num)

    # Pick correct vehicle(s)
    correct = rng.sample(COMBINABLE, n_behaviors)
    config  = make_compound(correct) if n_behaviors > 1 else correct[0].config
    choices = _build_choices(correct, n_choices, n_behaviors)

    return Round(
        number=round_num,
        correct=correct,
        choices=choices,
        config=config,
    )


# ── Session score tracker ─────────────────────────────────────────────────────

@dataclass
class SessionScore:
    correct:   float = 0.0
    incorrect: float = 0.0
    rounds:    int   = 0

    def apply_round(self, round_obj: Round, extra_correct: float = 0.0):
        """
        Call at round end.
        extra_correct: any correct_delta not yet applied (from final guess).
        """
        self.correct   += extra_correct
        self.incorrect += round_obj.incorrect_fraction()
        self.rounds    += 1

    @property
    def display(self) -> str:
        return (f"Correct: {self.correct:.1f}   "
                f"Incorrect: {self.incorrect:.1f}   "
                f"Rounds: {self.rounds}")
