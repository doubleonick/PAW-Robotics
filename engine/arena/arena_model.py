"""
engine/arena/arena_model.py
-----------------------------
ArenaModel: creates the PyBullet static environment.

Wall physics:
  - High lateral friction so the robot slides along walls rather than
    passing through or bouncing wildly
  - Low restitution (not bouncy)
  - Walls are box shapes, not planes — PyBullet resolves contacts correctly
"""

from __future__ import annotations

import logging
import math
from typing import Any

import pybullet as p

from engine.config import ArenaConfig, LightSource


logger = logging.getLogger(__name__)

_INSTANCE: "ArenaModel | None" = None


class ArenaModel:

    def __init__(self, config: ArenaConfig, physics_client: int):
        global _INSTANCE
        self._config   = config
        self._client   = physics_client
        self._body_ids: list[int] = []
        _INSTANCE = self

    @staticmethod
    def get_instance() -> "ArenaModel | None":
        return _INSTANCE

    def build(self) -> None:
        self._body_ids.clear()
        self._create_floor()
        self._create_walls()
        self._create_internal_walls()
        logger.info("Arena built: %.2fm × %.2fm  (%d internal walls)",
                    self._config.width, self._config.height,
                    len(self._config.internal_walls))

    def _make_static_box(self, hx: float, hy: float, hz: float,
                         cx: float, cy: float, cz: float,
                         color: list[float]) -> int:
        col = p.createCollisionShape(
            p.GEOM_BOX, halfExtents=[hx, hy, hz],
            physicsClientId=self._client)
        vis = p.createVisualShape(
            p.GEOM_BOX, halfExtents=[hx, hy, hz],
            rgbaColor=color, physicsClientId=self._client)
        bid = p.createMultiBody(
            baseMass=0,
            baseCollisionShapeIndex=col,
            baseVisualShapeIndex=vis,
            basePosition=[cx, cy, cz],
            physicsClientId=self._client)
        # High friction walls so robot slides cleanly rather than sticking
        p.changeDynamics(
            bid, -1,
            lateralFriction=0.5,
            spinningFriction=0.0,
            rollingFriction=0.0,
            restitution=0.05,
            physicsClientId=self._client)
        # Walls and floor are in group 1; robot (group 2) collides with them
        # IR raycasts use collisionFilterMask=1 to hit only this group
        p.setCollisionFilterGroupMask(
            bid, -1,
            collisionFilterGroup=1,
            collisionFilterMask=3,   # collides with groups 1 and 2
            physicsClientId=self._client)
        return bid

    def _create_floor(self) -> None:
        w, h = self._config.width / 2, self._config.height / 2
        bid = self._make_static_box(
            w, h, 0.005,
            0, 0, -0.005,
            [0.15, 0.15, 0.18, 1.0])
        self._body_ids.append(bid)

    def _create_walls(self) -> None:
        w  = self._config.width  / 2
        h  = self._config.height / 2
        t  = self._config.wall_thickness / 2
        wh = 0.10   # wall half-height

        # (half_x, half_y, cx, cy)
        wall_specs = [
            (w + t, t,     0,      h + t),   # north
            (w + t, t,     0,     -h - t),   # south
            (t,     h,     w + t,  0    ),   # east
            (t,     h,    -w - t,  0    ),   # west
        ]
        for hx, hy, cx, cy in wall_specs:
            bid = self._make_static_box(
                hx, hy, wh,
                cx, cy, wh,
                [0.4, 0.42, 0.45, 1.0])
            self._body_ids.append(bid)

    def _create_internal_walls(self) -> None:
        """Create PyBullet bodies for internal walls drawn in the arena builder.

        Each wall is a line segment (x0,y0)→(x1,y1) with a given thickness.
        We create a box oriented along the segment.
        """
        wh = 0.10   # same height as boundary walls

        for iw in self._config.internal_walls:
            dx   = iw.x1 - iw.x0
            dy   = iw.y1 - iw.y0
            length = math.sqrt(dx*dx + dy*dy)
            if length < 0.01:
                continue

            # Centre of the segment
            cx = (iw.x0 + iw.x1) / 2
            cy = (iw.y0 + iw.y1) / 2

            # Angle of the segment in the XY plane
            angle = math.atan2(dy, dx)

            # Half-extents: along segment = length/2, across = thickness/2
            hl = length / 2
            ht = iw.thickness / 2

            col = p.createCollisionShape(
                p.GEOM_BOX,
                halfExtents=[hl, ht, wh],
                physicsClientId=self._client)
            vis = p.createVisualShape(
                p.GEOM_BOX,
                halfExtents=[hl, ht, wh],
                rgbaColor=[0.5, 0.55, 0.65, 1.0],
                physicsClientId=self._client)

            orn = p.getQuaternionFromEuler(
                [0, 0, angle], physicsClientId=self._client)

            bid = p.createMultiBody(
                baseMass=0,
                baseCollisionShapeIndex=col,
                baseVisualShapeIndex=vis,
                basePosition=[cx, cy, wh],
                baseOrientation=orn,
                physicsClientId=self._client)

            p.changeDynamics(
                bid, -1,
                lateralFriction=0.5,
                spinningFriction=0.0,
                rollingFriction=0.0,
                restitution=0.05,
                physicsClientId=self._client)
            p.setCollisionFilterGroupMask(
                bid, -1,
                collisionFilterGroup=1,
                collisionFilterMask=3,
                physicsClientId=self._client)

            self._body_ids.append(bid)
            logger.debug("Internal wall: (%.2f,%.2f)→(%.2f,%.2f) len=%.2fm",
                         iw.x0, iw.y0, iw.x1, iw.y1, length)

    @property
    def body_ids(self) -> list[int]:
        return self._body_ids

    @property
    def light_sources(self) -> list[LightSource]:
        return self._config.light_sources

    @property
    def width(self) -> float:
        return self._config.width

    @property
    def height(self) -> float:
        return self._config.height
