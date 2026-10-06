"""
valentinos/games/ntv/vehicles.py
---------------------------------
Canonical vehicle definitions for Name That Vehicle.

Each vehicle exists in two sensor modalities:
  LDR variant — responds to light  (uses LDR·C1, LDR·C2)
  IR  variant — responds to objects (uses IR·L,  IR·R)

The behavioral name (Cowardice, Love, etc.) is stimulus-independent:
it describes the wiring topology, not what the robot responds to.
"""
from __future__ import annotations
from dataclasses import dataclass
from engine.signals import Connection
from engine.vehicle import VehicleConfig


@dataclass(frozen=True)
class VehicleDef:
    key:      str           # unique key e.g. "ldr_v2a", "ir_v3b"
    label:    str           # display e.g. "Vehicle 2a"
    names:    tuple         # ("Cowardice", "Fear")
    config:   VehicleConfig
    motive:   str           # "light" | "obstacle"
    sensor:   str           # "LDR" | "IR"

    @property
    def full_name(self) -> str:
        short = self.label.replace("Vehicle ", "").strip()
        return f"{short} — {self.names[0]}"

    @property
    def short_name(self) -> str:
        return self.names[0]

    @property
    def choice_label(self) -> str:
        if len(self.names) == 1:
            return self.names[0]
        return f"{self.names[0]}  ({', '.join(self.names[1:])})"


# ── LDR vehicles (respond to light) ──────────────────────────────────────────

LDR_V1 = VehicleDef(
    key="ldr_v1", label="Vehicle 1",
    names=("Target Avoidance",),
    motive="light", sensor="LDR",
    config=VehicleConfig(
        connections=[
            Connection("LDR·C1", "FL", "blue"),
            Connection("LDR·C1", "FR", "blue"),
        ],
        name="V1 — Target Avoidance (LDR)",
    ),
)

LDR_V2A = VehicleDef(
    key="ldr_v2a", label="Vehicle 2a",
    names=("Cowardice", "Fear"),
    motive="light", sensor="LDR",
    config=VehicleConfig(
        connections=[
            Connection("LDR·C1", "FL", "blue"),
            Connection("LDR·C2", "FR", "blue"),
        ],
        name="V2a — Cowardice (LDR)",
    ),
)

LDR_V2B = VehicleDef(
    key="ldr_v2b", label="Vehicle 2b",
    names=("Aggression",),
    motive="light", sensor="LDR",
    config=VehicleConfig(
        connections=[
            Connection("LDR·C1", "FR", "blue"),
            Connection("LDR·C2", "FL", "blue"),
        ],
        name="V2b — Aggression (LDR)",
    ),
)

LDR_V3A = VehicleDef(
    key="ldr_v3a", label="Vehicle 3a",
    names=("Love",),
    motive="light", sensor="LDR",
    config=VehicleConfig(
        connections=[
            Connection("N1", "FL", "blue"),
            Connection("N2", "FR", "blue"),
            Connection("LDR·C1", "I1", "green"),
            Connection("LDR·C2", "I2", "green"),
        ],
        neuron_biases={"N1": 1.0, "N2": 1.0},
        name="V3a — Love (LDR)",
    ),
)

LDR_V3B = VehicleDef(
    key="ldr_v3b", label="Vehicle 3b",
    names=("Explorer",),
    motive="light", sensor="LDR",
    config=VehicleConfig(
        connections=[
            Connection("N1", "FL", "blue"),
            Connection("N2", "FR", "blue"),
            Connection("LDR·C1", "I2", "green"),
            Connection("LDR·C2", "I1", "green"),
        ],
        neuron_biases={"N1": 1.0, "N2": 1.0},
        name="V3b — Explorer (LDR)",
    ),
)

# ── IR vehicles (respond to obstacles) ───────────────────────────────────────

IR_V1 = VehicleDef(
    key="ir_v1", label="Vehicle 1",
    names=("Target Avoidance",),
    motive="obstacle", sensor="IR",
    config=VehicleConfig(
        connections=[
            Connection("IR·L", "FL", "blue"),
            Connection("IR·L", "FR", "blue"),
        ],
        name="V1 — Target Avoidance (IR)",
    ),
)

IR_V2A = VehicleDef(
    key="ir_v2a", label="Vehicle 2a",
    names=("Cowardice", "Fear"),
    motive="obstacle", sensor="IR",
    config=VehicleConfig(
        connections=[
            Connection("IR·L", "FL", "blue"),
            Connection("IR·R", "FR", "blue"),
        ],
        name="V2a — Cowardice (IR)",
    ),
)

IR_V2B = VehicleDef(
    key="ir_v2b", label="Vehicle 2b",
    names=("Aggression",),
    motive="obstacle", sensor="IR",
    config=VehicleConfig(
        connections=[
            Connection("IR·L", "FR", "blue"),
            Connection("IR·R", "FL", "blue"),
        ],
        name="V2b — Aggression (IR)",
    ),
)

IR_V3A = VehicleDef(
    key="ir_v3a", label="Vehicle 3a",
    names=("Love",),
    motive="obstacle", sensor="IR",
    config=VehicleConfig(
        connections=[
            Connection("N1", "FL", "blue"),
            Connection("N2", "FR", "blue"),
            Connection("IR·L", "I1", "green"),
            Connection("IR·R", "I2", "green"),
        ],
        neuron_biases={"N1": 1.0, "N2": 1.0},
        name="V3a — Love (IR)",
    ),
)

IR_V3B = VehicleDef(
    key="ir_v3b", label="Vehicle 3b",
    names=("Explorer",),
    motive="obstacle", sensor="IR",
    config=VehicleConfig(
        connections=[
            Connection("N1", "FL", "blue"),
            Connection("N2", "FR", "blue"),
            Connection("IR·L", "I2", "green"),
            Connection("IR·R", "I1", "green"),
        ],
        neuron_biases={"N1": 1.0, "N2": 1.0},
        name="V3b — Explorer (IR)",
    ),
)

# ── Canonical lists ───────────────────────────────────────────────────────────

# Ordered for intro sequence (LDR only, original 5)
INTRO_ORDER: list[VehicleDef] = [LDR_V1, LDR_V2A, LDR_V2B, LDR_V3A, LDR_V3B]

# All 10 single-sensor vehicles for NTV rounds 1-20
LDR_VEHICLES: list[VehicleDef] = [LDR_V1, LDR_V2A, LDR_V2B, LDR_V3A, LDR_V3B]
IR_VEHICLES:  list[VehicleDef] = [IR_V1,  IR_V2A,  IR_V2B,  IR_V3A,  IR_V3B]
ALL_NTV:      list[VehicleDef] = LDR_VEHICLES + IR_VEHICLES

# Behavior names (stimulus-independent) for answer columns
BEHAVIOR_NAMES: list[str] = [
    "Target Avoidance",
    "Cowardice",
    "Aggression",
    "Love",
    "Explorer",
]

# Legacy aliases for code that still uses old names
V1, V2A, V2B, V3A, V3B = LDR_V1, LDR_V2A, LDR_V2B, LDR_V3A, LDR_V3B
ALL_VEHICLES: dict[str, VehicleDef] = {v.key: v for v in ALL_NTV}
COMBINABLE:   list[VehicleDef]       = INTRO_ORDER


def make_compound(components: list[VehicleDef]) -> VehicleConfig:
    """Merge multiple vehicle configs into one compound wiring."""
    all_conns, seen, biases = [], set(), {}
    for vdef in components:
        for c in vdef.config.connections:
            sig = (c.source, c.dest, c.color)
            if sig not in seen:
                seen.add(sig)
                all_conns.append(c)
        for k, v in vdef.config.neuron_biases.items():
            biases[k] = min(4.0, biases.get(k, 0.0) + v)
    return VehicleConfig(
        connections=all_conns, neuron_biases=biases,
        name=" + ".join(v.short_name for v in components),
    )


def compound_label(components: list[VehicleDef]) -> str:
    return " + ".join(v.short_name for v in components)


def component_keys(components: list[VehicleDef]) -> frozenset:
    return frozenset(v.key for v in components)
