"""
valentinos/engine/vehicle.py
-----------------------------
The Ana BBot analog computer model.

A Vehicle is defined by:
  - A list of Connection objects (the jumper wires)
  - Per-neuron bias values (the trimpots R1–R6)
  - Per-LDR sensitivity values (the LDR trimpots)
  - A GAIN value for the motor responsiveness trimpot

evaluate(sensor_readings, dt) computes one tick and returns MotorCommand.

The evaluator:
  1. Populates a signal table from sensor readings
  2. Evaluates neurons in topological order (handles neuron→neuron chains)
  3. Evaluates motor inputs (FL, BL, FR, BR)
  4. Returns net left/right motor drive in [-1.0, 1.0]
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import NamedTuple
import math

from engine.signals import Connection, Neuron, WIRE_WEIGHT

# ── Valid signal node names ────────────────────────────────────────────────────

# Sensor source nodes the wiring editor will accept. Three groups:
#   LIVE     — emitted by the current readers (hub._read_sensors, ntv_game):
#              IR·L, IR·R, LDR·C1, LDR·C2
#   LEGACY   — old AnaBBot names (RL/RR = IR; PL/PR = photo). No live reader
#              emits these anymore, but they remain valid so older saved
#              vehicles and the engine unit tests still load. Wiring a fresh
#              vehicle to these yields 0.0 — prefer the LIVE names.
#   RESERVED — LDR·C3/C4: extra placements planned for BYOV expansion; no
#              reader emits them yet, so they currently read 0.0.
SENSOR_NODES  = {"RL", "RR", "PL", "PR",          # LEGACY
                 "IR·L", "IR·R",                  # LIVE
                 "LDR·C1", "LDR·C2",              # LIVE
                 "LDR·C3", "LDR·C4"}              # RESERVED (future)
NEURON_N_NODES = {f"N{i}" for i in range(1, 7)}
NEURON_T_NODES = {f"T{i}" for i in range(1, 5)}   # only neurons 1-4 have T
MOTOR_NODES   = {"FL", "BL", "FR", "BR"}
METER_NODES   = {"M1", "M2", "M3"}

EXCITATORY_NODES  = {f"E{i}" for i in range(1, 7)}
INHIBITORY_NODES  = {f"I{i}" for i in range(1, 7)}

VALID_SOURCES = SENSOR_NODES | NEURON_N_NODES | NEURON_T_NODES
VALID_DESTS   = EXCITATORY_NODES | INHIBITORY_NODES | MOTOR_NODES | METER_NODES


# ── Sensor readings input ─────────────────────────────────────────────────────

# SensorReadings is now a plain dict {sensor_id: float}.
# Kept as an alias so existing imports still work.
SensorReadings = dict


# ── Motor output ──────────────────────────────────────────────────────────────

class MotorCommand(NamedTuple):
    """Net wheel drive values, each in [-1.0, 1.0]."""
    left:  float   # positive = forward
    right: float   # positive = forward


# ── Vehicle definition ────────────────────────────────────────────────────────

@dataclass
class VehicleConfig:
    """
    Complete description of one Ana BBot wiring configuration.

    connections    : list of Connection (the jumper wires)
    neuron_biases  : dict  e.g. {"N1": 0.5, "N3": -1.0}  (default 0.0)
    ldr_gains      : dict  e.g. {"LDR·C1": 1.2, "LDR·C2": 0.9}  (default 1.0)
    gain           : float  overall motor responsiveness   (default 1.0)
    name           : optional human-readable label
    """
    connections:   list[Connection]      = field(default_factory=list)
    neuron_biases: dict[str, float]      = field(default_factory=dict)
    ldr_gains:     dict[str, float]      = field(default_factory=dict)
    gain:          float                  = 1.0
    name:          str                    = ""

    def validate(self) -> list[str]:
        """Return list of error strings, empty if valid."""
        errors = []
        for c in self.connections:
            if c.source not in VALID_SOURCES:
                errors.append(f"Invalid source: {c.source!r}")
            if c.dest not in VALID_DESTS:
                errors.append(f"Invalid dest: {c.dest!r}")
            if c.color not in WIRE_WEIGHT:
                errors.append(f"Invalid wire color: {c.color!r}")
        return errors


# ── Evaluator ─────────────────────────────────────────────────────────────────

class VehicleEvaluator:
    """
    Stateful evaluator for a VehicleConfig.

    Maintains neuron state across ticks (needed for threshold timing).
    Call reset() to clear state when starting a new run.
    Call tick(sensors, dt) each simulation step.
    """

    def __init__(self, config: VehicleConfig):
        self._config  = config
        self._neurons = {
            i: Neuron(index=i, has_threshold=(i <= 4))
            for i in range(1, 7)
        }
        self._signals: dict[str, float] = {}

    def reset(self) -> None:
        for n in self._neurons.values():
            n.reset()
        self._signals = {}

    def update_config(self, config: VehicleConfig) -> None:
        """Hot-swap config without resetting neuron state."""
        self._config = config

    # ── Main tick ──────────────────────────────────────────────────────────

    def tick(self, sensors: dict, dt: float) -> MotorCommand:
        """
        Evaluate one simulation step.

        Returns net motor drive (left, right) each in [-1.0, 1.0].
        """
        cfg = self._config
        sig = self._signals

        # 1. Load sensor signals from dict {sensor_id: float}
        for _sid, _val in sensors.items():
            gain      = cfg.ldr_gains.get(_sid, 1.0)
            sig[_sid] = max(0.0, min(1.0, float(_val) * gain))

        # 2. Build connection index keyed by dest node
        dest_map: dict[str, list[Connection]] = {}
        for c in cfg.connections:
            dest_map.setdefault(c.dest, []).append(c)

        # 3. Evaluate neurons in topological order
        #    Neurons may feed other neurons (N1 → E2, etc.)
        #    We do up to 6 passes to resolve chains; cycles are supported
        #    (they just stabilize over multiple ticks rather than one)
        for _pass in range(6):
            changed = False
            for idx in range(1, 7):
                neuron = self._neurons[idx]
                neuron.bias = cfg.neuron_biases.get(f"N{idx}", 0.0)

                exc = self._sum_inputs(dest_map, f"E{idx}", sig)
                inh = self._sum_inputs(dest_map, f"I{idx}", sig)

                old_N = neuron.N
                # On pass 0 we do the full stateful update (advances timers)
                # On subsequent passes within same tick we recompute without
                # advancing timers further
                if _pass == 0:
                    neuron.evaluate(exc, inh, dt)
                else:
                    # Recompute N only (T stays as computed in pass 0)
                    s      = neuron.bias + exc - inh
                    neuron._sum = s
                    neuron.N    = max(0.0, min(1.0, s))

                sig[f"N{idx}"] = neuron.N
                if neuron.has_threshold:
                    sig[f"T{idx}"] = neuron.T

                if abs(neuron.N - old_N) > 1e-6:
                    changed = True

            if not changed:
                break   # converged

        # 4. Evaluate meter inputs (for display)
        for _m in ("M1", "M2", "M3", "M4"):
            sig[_m] = max(0.0, min(1.0,
                          self._sum_inputs(dest_map, _m, sig)))

        # 5. Evaluate motor inputs
        fl = self._sum_inputs(dest_map, "FL", sig)
        bl = self._sum_inputs(dest_map, "BL", sig)
        fr = self._sum_inputs(dest_map, "FR", sig)
        br = self._sum_inputs(dest_map, "BR", sig)

        raw_left  = max(-1.0, min(1.0, (fl - bl) * cfg.gain))
        raw_right = max(-1.0, min(1.0, (fr - br) * cfg.gain))

        return MotorCommand(left=raw_left, right=raw_right)

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _sum_inputs(dest_map: dict, dest: str,
                    signals: dict[str, float]) -> float:
        """Sum all weighted signal inputs arriving at dest."""
        total = 0.0
        for c in dest_map.get(dest, []):
            total += signals.get(c.source, 0.0) * c.weight
        return total

    # ── Introspection ──────────────────────────────────────────────────────

    def signal_snapshot(self) -> dict[str, float]:
        """Return a copy of the current signal table (for HUD / telemetry)."""
        return dict(self._signals)

    def neuron_states(self) -> list[dict]:
        """Return per-neuron state dicts for display."""
        out = []
        for idx in range(1, 7):
            n = self._neurons[idx]
            out.append({
                "index": idx,
                "bias":  n.bias,
                "sum":   n._sum,
                "N":     n.N,
                "T":     n.T if n.has_threshold else None,
                "T_state": n._t_state if n.has_threshold else None,
                "T_timer": n._t_timer if n.has_threshold else None,
            })
        return out
