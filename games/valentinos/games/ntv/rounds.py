"""
valentinos/games/ntv/rounds.py
--------------------------------
Round generation and scoring for Name That Vehicle.

Round structure:
  1–10  : single sensor, single source, no repeats until all 10 seen
  11–20 : single sensor, multiple sources (2 sources of the same type)
  21–30 : mixed sensors — one LDR vehicle + one IR vehicle, both active,
           arena has both light and obstacle. Extended demo timer.

Answer structure:
  Two independent columns — LDR behavior and IR behavior.
  Each column: one of 5 behavior names + "N/A".
  Both columns must be set before Verify activates.
"""

from __future__ import annotations
import random
from dataclasses import dataclass, field

from valentinos.games.ntv.vehicles import (
    VehicleDef, VehicleConfig,
    LDR_VEHICLES, IR_VEHICLES, ALL_NTV,
    BEHAVIOR_NAMES, make_compound,
)
from valentinos.games.ntv.arena_gen import generate_arena, _place_light, _place_obstacle

# Sentinel value for "not applicable"
NA = "N/A"

# All choices per column (5 behaviors + N/A)
COLUMN_CHOICES: list[str] = BEHAVIOR_NAMES + [NA]

# Demo timer durations
TIMER_SINGLE = 10.0
TIMER_MULTI  = 10.0
TIMER_MIXED  = 10.0


class SessionScore:
    """Running tally for the session."""
    def __init__(self):
        self.rounds    = 0
        self.correct   = 0.0
        self.incorrect = 0.0

    @property
    def accuracy(self) -> float:
        if self.rounds == 0:
            return 0.0
        return self.correct / self.rounds


@dataclass
class NTVAnswer:
    """Player's dual-column answer."""
    ldr: str = ""
    ir:  str = ""

    @property
    def is_complete(self) -> bool:
        return bool(self.ldr) and bool(self.ir)


@dataclass
class Round:
    number:       int
    vehicle:      VehicleDef | None  # None for compound rounds
    config:       VehicleConfig
    arena:        dict
    correct_ldr:  str
    correct_ir:   str
    demo_timer:   float = TIMER_SINGLE

    guesses_made:  int   = 0
    round_over:    bool  = False
    player_answer: NTVAnswer = field(default_factory=NTVAnswer)

    def evaluate(self, answer: NTVAnswer) -> dict:
        self.guesses_made += 1
        ldr_ok = (answer.ldr == self.correct_ldr)
        ir_ok  = (answer.ir  == self.correct_ir)
        both   = ldr_ok and ir_ok
        self.round_over = both or self.guesses_made >= 3
        return {
            "ldr_correct":  ldr_ok,
            "ir_correct":   ir_ok,
            "both_correct": both,
            "round_over":   self.round_over,
        }


class RoundSequence:
    """
    Generates rounds in the correct stage order.
    Stages determined by round number:
      1-10:   single sensor, single source
      11-20:  single sensor, two sources
      21-30:  mixed sensors (LDR + IR), both source types
      31+:    cycles back to stage 2 then 3 (no stage 1 repeat)
    """

    def __init__(self, rng: random.Random | None = None):
        self._rng     = rng or random.Random()
        self._number  = 0
        # Stage 1 pool: all 10 single-sensor vehicles, shuffled
        self._s1_pool:  list[VehicleDef] = []
        # Stage 2 pool: same 10 vehicles
        self._s2_pool:  list[VehicleDef] = []
        # Stage 3 pool: pairs of (ldr_veh, ir_veh)
        self._s3_pool:  list[tuple] = []

    def next_round(self) -> Round:
        self._number += 1
        n = self._number

        if n <= 10:
            return self._make_stage1()
        elif n <= 20:
            return self._make_stage2()
        else:
            # Stage 3 from round 21 onward, cycling
            return self._make_stage3()

    # ── Stage 1: single sensor, single source ────────────────────────────────

    def _make_stage1(self) -> Round:
        if not self._s1_pool:
            self._s1_pool = list(ALL_NTV)
            self._rng.shuffle(self._s1_pool)
        vehicle = self._s1_pool.pop()
        arena   = generate_arena(vehicle.motive, self._rng)

        ldr, ir = self._single_answers(vehicle)
        return Round(
            number      = self._number,
            vehicle     = vehicle,
            config      = vehicle.config,
            arena       = arena,
            correct_ldr = ldr,
            correct_ir  = ir,
            demo_timer  = TIMER_SINGLE,
        )

    # ── Stage 2: single sensor, two sources ──────────────────────────────────

    def _make_stage2(self) -> Round:
        if not self._s2_pool:
            self._s2_pool = list(ALL_NTV)
            self._rng.shuffle(self._s2_pool)
        vehicle = self._s2_pool.pop()

        import copy
        from valentinos.games.ntv.arena_gen import _BASE
        arena = copy.deepcopy(_BASE)

        # Place two sources of the vehicle's type
        if vehicle.motive == "light":
            _place_light(arena, self._rng)
            _place_light(arena, self._rng)
        else:
            _place_obstacle(arena, self._rng)
            _place_obstacle(arena, self._rng)

        ldr, ir = self._single_answers(vehicle)
        return Round(
            number      = self._number,
            vehicle     = vehicle,
            config      = vehicle.config,
            arena       = arena,
            correct_ldr = ldr,
            correct_ir  = ir,
            demo_timer  = TIMER_MULTI,
        )

    # ── Stage 3: mixed sensors, both source types ─────────────────────────────

    def _make_stage3(self) -> Round:
        if not self._s3_pool:
            # Build all LDR×IR pairs, shuffle
            pairs = [(l, r) for l in LDR_VEHICLES for r in IR_VEHICLES]
            self._rng.shuffle(pairs)
            self._s3_pool = pairs
        ldr_veh, ir_veh = self._s3_pool.pop()

        config = make_compound([ldr_veh, ir_veh])
        arena  = generate_arena("both", self._rng)

        return Round(
            number      = self._number,
            vehicle     = None,  # compound
            config      = config,
            arena       = arena,
            correct_ldr = ldr_veh.short_name,
            correct_ir  = ir_veh.short_name,
            demo_timer  = TIMER_MIXED,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _single_answers(self, vehicle: VehicleDef) -> tuple[str, str]:
        behavior = vehicle.short_name
        if vehicle.sensor == "LDR":
            return behavior, NA
        else:
            return NA, behavior
