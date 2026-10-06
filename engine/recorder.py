"""
engine/recorder.py
--------------------
Lightweight run recorder for RoboSim.

Captures robot pose (x, y, heading_deg) at each render frame.
Saved as newline-delimited JSON to a .robrec file.

File format (one JSON object per line):
  {"t": 1.23, "x": 0.12, "y": -0.34, "hdg": 90.0}
"""

from __future__ import annotations
import json
import math
import os
import time
from dataclasses import dataclass


@dataclass
class Frame:
    t:   float   # seconds since recording start
    x:   float
    y:   float
    hdg: float   # degrees


class Recorder:
    """Collects frames during a simulation run and writes to file."""

    def __init__(self, path: str):
        self._path   = path
        self._start  = None
        self._frames: list[Frame] = []
        self._active = False

    def start(self) -> None:
        self._start  = time.monotonic()
        self._frames = []
        self._active = True

    def stop(self) -> None:
        self._active = False

    @property
    def is_active(self) -> bool:
        return self._active

    def record(self, x: float, y: float, hdg_rad: float) -> None:
        if not self._active or self._start is None:
            return
        self._frames.append(Frame(
            t   = round(time.monotonic() - self._start, 3),
            x   = round(x, 4),
            y   = round(y, 4),
            hdg = round(math.degrees(hdg_rad), 2),
        ))

    def save(self) -> int:
        """Write recording to file. Returns number of frames saved."""
        os.makedirs(os.path.dirname(os.path.abspath(self._path)), exist_ok=True)
        with open(self._path, "w") as f:
            for fr in self._frames:
                f.write(json.dumps(
                    {"t": fr.t, "x": fr.x, "y": fr.y, "hdg": fr.hdg}
                ) + "\n")
        return len(self._frames)


def load_recording(path: str) -> list[Frame]:
    """Load a .robrec file and return list of Frames."""
    frames = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            frames.append(Frame(
                t=d["t"], x=d["x"], y=d["y"], hdg=d["hdg"]))
    return frames
