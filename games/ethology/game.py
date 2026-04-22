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
    return ["escape_front", "avoid_object", "seek_light", "cruise_straight"]


@dataclass
class RobotTarget:
    label:     str              # "A" or "B"
    hierarchy: list[str]        # the secret target hierarchy
    color:     tuple            # render color
    solved:    bool   = False   # player guessed correctly


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

    @property
    def experiments_remaining(self) -> int:
        return max(0, MAX_EXPERIMENTS - len(self.experiments))

    @property
    def is_over(self) -> bool:
        all_solved = all(t.solved for t in self.targets.values())
        return all_solved or self.experiments_remaining == 0

    def new_game(self) -> None:
        """Generate fresh targets and reset experiment log."""
        self.targets = {
            "A": RobotTarget(
                label="A",
                hierarchy=generate_hierarchy(),
                color=(200, 50, 50),    # red
            ),
            "B": RobotTarget(
                label="B",
                hierarchy=generate_hierarchy(),
                color=(50, 80, 200),    # blue
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
