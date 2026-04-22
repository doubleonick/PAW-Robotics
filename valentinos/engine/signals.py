"""
valentinos/engine/signals.py
-----------------------------
Analog signal model for the Johuco Ana BBot.

All signals are normalized floats in [0.0, 1.0] except internal neuron
sums which can range from roughly -4 to +7 (bias -4..+4 plus weighted
inputs).

Named signal nodes match the physical board labels exactly:
  Sources : RL, RR, PL, PR          (sensors)
             N1..N6                  (neuron continuous outputs)
             T1..T4                  (neuron threshold outputs, 4 of 6)
  Sinks   : E1..E6, I1..I6          (neuron excitatory / inhibitory inputs)
             FL, BL, FR, BR          (motor forward/back inputs)
             M1, M2, M3              (meters — display only, no effect)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

# ── Wire weights ───────────────────────────────────────────────────────────────

WIRE_WEIGHT = {"blue": 1, "green": 2, "red": 3}

WireColor = Literal["blue", "green", "red"]

# ── Connection ────────────────────────────────────────────────────────────────

@dataclass
class Connection:
    """
    A single jumper wire from one signal node to another.

    source : signal name  e.g. "RL", "N1", "T2"
    dest   : signal name  e.g. "E1", "FL", "M2"
    color  : wire color   "blue" | "green" | "red"  (weight 1 / 2 / 3)
    """
    source: str
    dest:   str
    color:  WireColor = "blue"

    @property
    def weight(self) -> int:
        return WIRE_WEIGHT[self.color]

    def __repr__(self):
        return f"Connection({self.source!r} →{self.color[0].upper()}→ {self.dest!r})"


# ── Neuron ────────────────────────────────────────────────────────────────────

# Threshold timing constants (seconds)
_T_ON_BASE  = 0.2   # turn-on  time when internal sum == 1.0
_T_OFF_BASE = 0.2   # turn-off time when internal sum == 0.0 (max off time)


@dataclass
class Neuron:
    """
    One of the six neurons on the Ana BBot board.

    Parameters
    ----------
    index    : 1-based neuron number (1–6)
    bias     : trimpot value, range -4.0 to +4.0, default 0.0
    has_threshold : True for neurons 1–4 (have T output), False for 5–6

    State (updated each tick)
    -------------------------
    N        : continuous output, clamp(internal_sum, 0, 1)
    T        : threshold binary output (0.0 or 1.0), only valid if has_threshold
    _sum     : last computed internal sum
    _t_state : current threshold state (False=off, True=on)
    _t_timer : remaining time until threshold transitions (seconds)
    """
    index:         int
    bias:          float = 0.0
    has_threshold: bool  = True

    # Runtime state — not constructor params
    N:        float = field(default=0.0, init=False)
    T:        float = field(default=0.0, init=False)
    _sum:     float = field(default=0.0, init=False, repr=False)
    _t_state: bool  = field(default=False, init=False, repr=False)
    _t_timer: float = field(default=0.0,  init=False, repr=False)

    def reset(self) -> None:
        self.N = self.T = self._sum = 0.0
        self._t_state = False
        self._t_timer = 0.0

    def evaluate(self, excitatory: float, inhibitory: float, dt: float) -> None:
        """
        Compute one tick.

        Parameters
        ----------
        excitatory : sum of all weighted excitatory inputs to this neuron
        inhibitory : sum of all weighted inhibitory inputs to this neuron
        dt         : elapsed time since last tick (seconds)
        """
        s         = self.bias + excitatory - inhibitory
        self._sum = s
        self.N    = max(0.0, min(1.0, s))

        if self.has_threshold:
            self._update_threshold(s, dt)

    def _update_threshold(self, s: float, dt: float) -> None:
        """
        Time-delayed binary threshold output.

        Turn-on  delay = _T_ON_BASE  / max(s, 1e-6)   when s > 0
        Turn-off delay = _T_OFF_BASE / max(-s, 1e-6)  when s <= 0
                         BUT cannot be SLOWER than _T_OFF_BASE
        """
        if not self._t_state:
            # Currently OFF — count toward turn-on
            if s > 0.0:
                delay = _T_ON_BASE / s
                self._t_timer += dt
                if self._t_timer >= delay:
                    self._t_state = True
                    self._t_timer = 0.0
            else:
                self._t_timer = 0.0   # reset if sum not positive
        else:
            # Currently ON — count toward turn-off
            if s <= 0.0:
                # turn-off delay = T_OFF_BASE / (1 + |s|)
                # sum=0  → 0.2s, sum=-1 → 0.1s, sum=-2 → 0.067s
                # "cannot be slower than 0.2s" is naturally satisfied
                delay = _T_OFF_BASE / (1.0 + abs(s))
                self._t_timer += dt
                if self._t_timer >= delay:
                    self._t_state = False
                    self._t_timer = 0.0
            else:
                self._t_timer = 0.0   # reset if sum still positive

        self.T = 1.0 if self._t_state else 0.0

    @property
    def name_N(self) -> str:
        return f"N{self.index}"

    @property
    def name_T(self) -> str:
        return f"T{self.index}"
