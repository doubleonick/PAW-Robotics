"""
valentinos/engine/recorder.py
------------------------------
Records robot pose + signal snapshot each frame.
Saves to .vvrec (Valentino's Vehicles Recording) files — JSON lines format
so they are human-readable and trivially parsed offline.

Each line is a JSON object:
  {"t": 1.23, "x": 0.1, "y": 0.05, "h": 0.7,
   "signals": {"RL": 0.8, "N1": 0.4, ...},
   "motors": {"left": 0.6, "right": -0.2}}

"Offline replay" means loading a .vvrec file in a standalone viewer
without needing the simulation running — the file is self-contained.
"""

from __future__ import annotations
import json
import time
from dataclasses import dataclass
from pathlib import Path

from engine.robot_body import RobotState
from engine.vehicle import MotorCommand


@dataclass
class Frame:
    t:       float          # recording time (seconds from run start)
    x:       float
    y:       float
    hdg:     float          # heading radians
    signals: dict           # signal snapshot from evaluator
    motors:  tuple[float, float]  # (left, right)


class Recorder:
    def __init__(self):
        self._frames: list[Frame] = []
        self._start: float = 0.0
        self._active: bool = False

    def start(self) -> None:
        self._frames = []
        self._start  = time.monotonic()
        self._active = True

    def stop(self) -> None:
        self._active = False

    @property
    def is_active(self) -> bool:
        return self._active

    def record(self, state: RobotState, signals: dict,
               motors: MotorCommand) -> None:
        if not self._active:
            return
        t = time.monotonic() - self._start
        self._frames.append(Frame(
            t=t, x=state.x, y=state.y, hdg=state.heading,
            signals=dict(signals),
            motors=(motors.left, motors.right)))

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            for fr in self._frames:
                f.write(json.dumps({
                    "t": round(fr.t, 4),
                    "x": round(fr.x, 5),
                    "y": round(fr.y, 5),
                    "h": round(fr.hdg, 5),
                    "signals": {k: round(v, 4)
                                for k, v in fr.signals.items()},
                    "motors": [round(fr.motors[0], 4),
                               round(fr.motors[1], 4)],
                }) + "\n")

    @property
    def frames(self) -> list[Frame]:
        return list(self._frames)

    @property
    def duration(self) -> float:
        return self._frames[-1].t if self._frames else 0.0


def load_recording(path: str | Path) -> list[Frame]:
    """Load a .vvrec file. Works offline — no simulation needed."""
    frames = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            frames.append(Frame(
                t=d["t"], x=d["x"], y=d["y"], hdg=d["h"],
                signals=d.get("signals", {}),
                motors=tuple(d.get("motors", [0, 0]))))
    return frames
