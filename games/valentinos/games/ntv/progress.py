"""
valentinos/games/ntv/progress.py
----------------------------------
Persistent progress for Name That Vehicle.

Stored in valentinos/games/ntv/progress.json:
  intro_seen   : bool   — whether the player has seen the full intro
  lifetime_correct   : float
  lifetime_incorrect : float
  lifetime_rounds    : int
"""

from __future__ import annotations
import json
import os

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "progress.json")

_DEFAULTS = {
    "intro_seen":          False,
    "lifetime_correct":    0.0,
    "lifetime_incorrect":  0.0,
    "lifetime_rounds":     0,
}


def load() -> dict:
    if os.path.exists(_PATH):
        try:
            with open(_PATH) as f:
                data = json.load(f)
            out = dict(_DEFAULTS)
            out.update(data)
            return out
        except Exception:
            pass
    return dict(_DEFAULTS)


def save(progress: dict) -> None:
    try:
        with open(_PATH, "w") as f:
            json.dump(progress, f, indent=2)
    except Exception as e:
        print(f"[ntv] Could not save progress: {e}")


def mark_intro_seen() -> None:
    p = load()
    p["intro_seen"] = True
    save(p)


def record_session(correct: float, incorrect: float, rounds: int) -> None:
    p = load()
    p["lifetime_correct"]   = round(p["lifetime_correct"]   + correct,   2)
    p["lifetime_incorrect"] = round(p["lifetime_incorrect"] + incorrect, 2)
    p["lifetime_rounds"]    += rounds
    save(p)
