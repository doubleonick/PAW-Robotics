"""
robosim/simulation.py
----------------------
Simulation — supports N robots running simultaneously in one PyBullet world.

Usage (single robot — backward compatible with main.py):
    sim = Simulation(arena_config)
    sim.add_robot(robot_config, sketch_path="sketches/ethology.ino")
    sim.setup()
    sim.run()

Usage (N robots):
    sim = Simulation(arena_config)
    sim.add_robot(robot_config, sketch_path="sketches/a.ino",
                  color=(220, 50, 50), label="A",
                  start_x=-0.3, start_y=0.0, start_heading=math.pi/2)
    sim.add_robot(robot_config, sketch_path="sketches/b.ino",
                  color=(50, 100, 220), label="B",
                  start_x= 0.3, start_y=0.0, start_heading=math.pi/2)
    sim.setup()
    sim.run()
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any

import pybullet as p
import pybullet_data

from robosim.config import ArenaConfig, RobotConfig
from robosim.arena.arena_model import ArenaModel
from robosim.robot.robot_model import RobotModel
from robosim.hal.arduino_hal import ArduinoHAL
from robosim.renderer.pygame_renderer import PyGameRenderer
from robosim.recorder import Recorder

logger = logging.getLogger(__name__)

PHYSICS_DT = 1.0 / 120.0


@dataclass
class _RobotEntry:
    """Internal record for one robot in the simulation."""
    config:        RobotConfig
    sketch_path:   str | None
    color:         tuple              = (60, 160, 230)
    label:         str                = ""
    start_x:       float              = 0.0
    start_y:       float              = 0.0
    start_heading: float              = math.pi / 2
    # Populated during setup():
    model:         RobotModel | None  = None
    hal:           ArduinoHAL | None  = None
    recorder:      Recorder | None    = None


class Simulation:

    def __init__(self,
                 arena_config: ArenaConfig,
                 # Legacy single-robot params kept for backward compat
                 robot_config:   RobotConfig | None  = None,
                 sketch_path:    str | None           = None,
                 start_x:        float                = 0.0,
                 start_y:        float                = 0.0,
                 start_heading:  float                = math.pi / 2,
                 show_hud:       bool                 = False,
                 dual_hud:       bool                 = False,
                 scale_px_per_m: float | None         = None,
                 ir_only:        bool                 = False,
                 arena_name:     str                  = "",
                 robot_name:     str                  = ""):

        self._arena_cfg      = arena_config
        self._show_hud       = show_hud
        self._dual_hud       = dual_hud
        self._scale_px_per_m = scale_px_per_m
        self._ir_only        = ir_only
        self._arena_name     = arena_name
        self._robot_name     = robot_name

        self._client:   int            = -1
        self._arena:    ArenaModel | None  = None
        self._renderer: PyGameRenderer | None = None
        self._running:  bool           = False
        self._robots:   list[_RobotEntry] = []

        # Duration limit in seconds (None = run until window closed)
        self.duration: float | None    = None
        # Callback invoked when simulation ends normally (duration elapsed)
        self.on_complete = None

        # Legacy single-robot shortcut
        if robot_config is not None:
            self.add_robot(robot_config, sketch_path,
                           start_x=start_x, start_y=start_y,
                           start_heading=start_heading)

    # ------------------------------------------------------------------
    # Robot registration (call before setup())
    # ------------------------------------------------------------------

    def add_robot(self,
                  config:        RobotConfig,
                  sketch_path:   str | None = None,
                  color:         tuple      = (60, 160, 230),
                  label:         str        = "",
                  start_x:       float      = 0.0,
                  start_y:       float      = 0.0,
                  start_heading: float      = math.pi / 2) -> int:
        """Register a robot. Returns its index (0-based)."""
        idx = len(self._robots)
        self._robots.append(_RobotEntry(
            config=config, sketch_path=sketch_path,
            color=color, label=label,
            start_x=start_x, start_y=start_y,
            start_heading=start_heading,
        ))
        return idx

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def setup(self) -> None:
        self._client = p.connect(p.DIRECT)
        p.setAdditionalSearchPath(pybullet_data.getDataPath(),
                                   physicsClientId=self._client)
        p.setGravity(0, 0, -9.81, physicsClientId=self._client)
        p.setTimeStep(PHYSICS_DT, physicsClientId=self._client)
        p.setPhysicsEngineParameter(numSolverIterations=50,
                                     physicsClientId=self._client)

        self._arena = ArenaModel(self._arena_cfg, self._client)
        self._arena.build()

        for entry in self._robots:
            entry.model = RobotModel(entry.config, self._client,
                                     color=entry.color)
            entry.model.create_body(entry.start_x, entry.start_y,
                                    entry.start_heading)

            entry.hal = ArduinoHAL(
                read_callback=entry.model.read_pin,
                write_callback=entry.model.write_pin,
            )
            if entry.sketch_path:
                entry.hal.load_sketch(entry.sketch_path)
                entry.hal.call_setup()
                bot = entry.hal._namespace.get("bot")
                if bot:
                    if hasattr(bot, "set_reset_callback"):
                        idx = self._robots.index(entry)
                        bot.set_reset_callback(
                            lambda x, y, h, _i=idx: self.reset_pose(_i, x, y, h))
                    # Pass robot identity to bot for HUD display
                    bot._robot_label = entry.label
                    bot._robot_color = entry.color
                logger.info("Robot %s sketch loaded: %s",
                            entry.label or str(self._robots.index(entry)),
                            entry.sketch_path)
            else:
                logger.warning("Robot %s has no sketch — will sit idle.",
                               entry.label or str(self._robots.index(entry)))

        # Renderer — single robot uses legacy robot_cfg for HUD
        primary_cfg = self._robots[0].config if self._robots else None
        self._renderer = PyGameRenderer(
            self._arena_cfg,
            primary_cfg,
            show_hud=self._show_hud,
            dual_hud=self._dual_hud,
            scale_px_per_m=self._scale_px_per_m,
            ir_only=self._ir_only,
            arena_name=self._arena_name,
            robot_name=self._robot_name,
        )
        self._renderer.init()
        logger.info("Simulation ready (%d robot(s)).", len(self._robots))

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset_pose(self, robot_idx: int = 0,
                   x: float = 0.0, y: float = 0.0,
                   heading: float = 0.0) -> None:
        if 0 <= robot_idx < len(self._robots):
            m = self._robots[robot_idx].model
            if m:
                m.reset_pose(x, y, heading)

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def start_recording(self, path: str, robot_idx: int = 0) -> None:
        if 0 <= robot_idx < len(self._robots):
            entry = self._robots[robot_idx]
            entry.recorder = Recorder(path)
            entry.recorder.start()
            logger.info("Recording robot %d → %s", robot_idx, path)

    def stop_recording(self, robot_idx: int = 0) -> str | None:
        if 0 <= robot_idx < len(self._robots):
            entry = self._robots[robot_idx]
            if entry.recorder and entry.recorder.is_active:
                entry.recorder.stop()
                n = entry.recorder.save()
                logger.info("Recording saved: %d frames", n)
                return entry.recorder._path
        return None

    def stop_all_recordings(self) -> list[str]:
        paths = []
        for i in range(len(self._robots)):
            p_ = self.stop_recording(i)
            if p_:
                paths.append(p_)
        return paths

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        self._running = True
        accumulator   = 0.0
        render_accum  = 0.0
        last_time     = time.monotonic()
        start_time    = last_time
        RENDER_DT     = 1.0 / 30.0

        try:
            while self._running:
                now = time.monotonic()
                dt  = min(now - last_time, 0.05)
                last_time    = now
                accumulator  += dt
                render_accum += dt

                if not self._renderer.poll_events():
                    break

                # Duration limit
                if self.duration and (now - start_time) >= self.duration:
                    self._running = False
                    if self.on_complete:
                        self.on_complete()
                    break

                while accumulator >= PHYSICS_DT:
                    self._physics_step()
                    accumulator -= PHYSICS_DT

                if render_accum >= RENDER_DT:
                    self._render()
                    render_accum -= RENDER_DT

                self._renderer.tick(fps=30)

        except KeyboardInterrupt:
            logger.info("Interrupted.")
        finally:
            self.teardown()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _physics_step(self) -> None:
        for entry in self._robots:
            if entry.hal:
                entry.hal.call_loop()
            if entry.model:
                entry.model.step(self._arena.body_ids)

        p.stepSimulation(physicsClientId=self._client)

        for entry in self._robots:
            self._check_contacts(entry)

    def _check_contacts(self, entry: _RobotEntry) -> None:
        if not entry.model or not entry.hal:
            return
        try:
            bot = entry.hal._namespace.get("bot")
            if not (bot and hasattr(bot, "notify_contact")):
                return
            for wall_id in self._arena.body_ids[1:]:
                contacts = p.getContactPoints(
                    bodyA=entry.model.body_id,
                    bodyB=wall_id,
                    physicsClientId=self._client)
                if contacts:
                    bot.notify_contact()
                    return
        except Exception:
            pass

    def _render(self) -> None:
        # Build list of robot draw data
        robots_draw = []
        for entry in self._robots:
            if not entry.model:
                continue
            hud_info = None
            state_label = ""
            if entry.hal:
                try:
                    bot = entry.hal._namespace.get("bot")
                    if bot:
                        if hasattr(bot, "get_hud_info"):
                            hud_info = bot.get_hud_info()
                        if hasattr(bot, "get_state_label"):
                            state_label = bot.get_state_label()
                except Exception:
                    pass
            robots_draw.append({
                "x":       entry.model.pos_x,
                "y":       entry.model.pos_y,
                "heading": entry.model.heading,
                "sensors": entry.model.sensors,
                "color":   entry.color,
                "label":   entry.label,
                "hud_info":    hud_info,
                "state_label": state_label,
            })

        # Use first robot's data for legacy HUD
        primary = robots_draw[0] if robots_draw else {}
        self._renderer.draw(
            robot_x=primary.get("x", 0),
            robot_y=primary.get("y", 0),
            robot_heading=primary.get("heading", 0),
            robot_color=primary.get("color"),
            robot_label=primary.get("label", ""),
            sensors=primary.get("sensors", {}),
            light_sources=self._arena.light_sources,
            state_label=primary.get("state_label", ""),
            hud_info=primary.get("hud_info"),
            extra_robots=robots_draw[1:],
        )

        # Record
        for entry in self._robots:
            if entry.recorder and entry.recorder.is_active and entry.model:
                entry.recorder.record(
                    entry.model.pos_x,
                    entry.model.pos_y,
                    entry.model.heading)

    def teardown(self) -> None:
        if self._renderer:
            self._renderer.shutdown()
        if self._client >= 0:
            try:
                p.disconnect(physicsClientId=self._client)
            except Exception:
                pass
        logger.info("Simulation shut down.")
