"""
valentinos/games/ntv/vehicles.py
---------------------------------
Canonical vehicle definitions for Name That Vehicle.
"""
from __future__ import annotations
from dataclasses import dataclass
from valentinos.engine.signals import Connection
from valentinos.engine.vehicle import VehicleConfig


@dataclass(frozen=True)
class VehicleDef:
    key:    str
    label:  str
    names:  tuple
    config: VehicleConfig
    motive: str   # "light" | "obstacle"

    @property
    def full_name(self) -> str:
        return ", or ".join([self.label] + list(self.names))

    @property
    def short_name(self) -> str:
        return self.names[0]

    @property
    def choice_label(self) -> str:
        if len(self.names) == 1:
            return self.names[0]
        return f"{self.names[0]}  ({', '.join(self.names[1:])})"


V1 = VehicleDef(
    key="v1", label="Vehicle 1",
    names=("Obstacle Avoidance",),
    motive="obstacle",
    config=VehicleConfig(
        connections=[Connection("RL","FL","blue"), Connection("RR","FR","blue")],
        name="Vehicle 1 — Obstacle Avoidance",
    ),
)

V2A = VehicleDef(
    key="v2a", label="Vehicle 2a",
    names=("Cowardice", "Fear"),
    motive="light",
    config=VehicleConfig(
        connections=[Connection("PL","FL","blue"), Connection("PR","FR","blue")],
        name="Vehicle 2a — Cowardice",
    ),
)

V2B = VehicleDef(
    key="v2b", label="Vehicle 2b",
    names=("Aggression",),
    motive="light",
    config=VehicleConfig(
        connections=[Connection("PL","FR","blue"), Connection("PR","FL","blue")],
        name="Vehicle 2b — Aggression",
    ),
)

V3A = VehicleDef(
    key="v3a", label="Vehicle 3a",
    names=("Love",),
    motive="light",
    config=VehicleConfig(
        connections=[
            Connection("N1","FL","blue"), Connection("N2","FR","blue"),
            Connection("PL","I1","blue"), Connection("PR","I2","blue"),
        ],
        neuron_biases={"N1": 1.0, "N2": 1.0},
        name="Vehicle 3a — Love",
    ),
)

V3B = VehicleDef(
    key="v3b", label="Vehicle 3b",
    names=("Explorer",),
    motive="light",
    config=VehicleConfig(
        connections=[
            Connection("N1","FL","blue"), Connection("N2","FR","blue"),
            Connection("PL","I2","blue"), Connection("PR","I1","blue"),
        ],
        neuron_biases={"N1": 1.0, "N2": 1.0},
        name="Vehicle 3b — Explorer",
    ),
)

INTRO_ORDER: list[VehicleDef] = [V1, V2A, V2B, V3A, V3B]
ALL_VEHICLES: dict[str, VehicleDef] = {v.key: v for v in INTRO_ORDER}
# For compound generation — all five can combine
COMBINABLE: list[VehicleDef] = INTRO_ORDER


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
