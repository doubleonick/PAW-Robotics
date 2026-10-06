"""
engine/sensor_physics.py
------------------------
Universal sensor physics for PAW games.

Every sensor type that requires both robot geometry AND arena context
is implemented here.  This is the single authoritative location for
all sensor physics calculations.

Architecture
------------
Each public function takes:
    wx, wy          -- sensor world position (metres)
    angle_world     -- sensor facing angle in world frame (radians)
                       = robot_heading + sensor.angle_deg (converted)
    arena           -- arena dict (walls, lights, field sources, etc.)
    **kwargs        -- type-specific parameters (channel, max_range, etc.)

Response curves (raw distance/illuminance → 0..1 output) stay in
robot_body.py — they are properties of the sensor hardware, not the
arena.  sensor_physics.py calls those curves after computing the raw
physical quantity.

Adding a new sensor type
------------------------
1. Write a function with signature:
       def mysensor_reading(wx, wy, angle_world, arena, **kwargs) -> float
2. Add it to SENSOR_DISPATCH.
3. Done — hub._read_sensors() picks it up automatically via read_sensor().
"""

from __future__ import annotations

import math
from typing import Any

# --- CALIBRATED LDR directional response (dev10 hardware bench) ---
# Measured: 0deg->100%, 45deg->~60%, 90deg->~57% of head-on reading.
# Modeled as floor + (1-floor)*max(0,cos(theta))**pow.
LDR_DIR_FLOOR = 0.20   # residual response at 90deg off-axis
LDR_DIR_POW   = 4.0    # sharpness of the directional dropoff



# ── Geometry helpers ──────────────────────────────────────────────────────────

def _angle_diff(a: float, b: float) -> float:
    """Signed difference a − b, wrapped to (−π, π]."""
    d = (a - b) % (2 * math.pi)
    if d > math.pi:
        d -= 2 * math.pi
    return d


def _ray_segment_intersect(
        ox: float, oy: float,
        dx: float, dy: float,
        ax: float, ay: float,
        bx: float, by: float) -> float | None:
    """
    Intersect ray (origin ox,oy; direction dx,dy) with segment (ax,ay)–(bx,by).
    Returns the ray parameter t > 0 at intersection, or None.
    """
    rdx = bx - ax
    rdy = by - ay
    denom = dx * rdy - dy * rdx
    if abs(denom) < 1e-10:
        return None
    t_ray  = ((ax - ox) * rdy - (ay - oy) * rdx) / denom
    t_seg  = ((ax - ox) * dy  - (ay - oy) * dx)  / denom
    if 0.0 <= t_seg <= 1.0 and t_ray > 1e-6:
        return t_ray
    return None


def _wall_segments(arena: dict) -> list[tuple]:
    """
    Return all wall segments as ((x0,y0),(x1,y1)) pairs.
    Includes boundary walls and internal walls.
    Cached on the arena dict to avoid recomputation.
    """
    if "_wall_segments_cache" in arena:
        return arena["_wall_segments_cache"]
    aw = arena["width"]
    ah = arena["height"]
    t  = arena.get("wall_thickness", 0.012)
    segs = [
        ((-aw/2 - t,  ah/2 + t), ( aw/2 + t,  ah/2 + t)),
        ((-aw/2 - t, -ah/2 - t), ( aw/2 + t, -ah/2 - t)),
        (( aw/2,     -ah/2    ), ( aw/2,       ah/2    )),
        ((-aw/2 - t, -ah/2    ), (-aw/2 - t,   ah/2    )),
    ]
    for iw in arena.get("internal_walls", []):
        segs.append(((iw["x0"], iw["y0"]), (iw["x1"], iw["y1"])))
    arena["_wall_segments_cache"] = segs
    return segs


def invalidate_arena_cache(arena: dict) -> None:
    """
    Call this whenever arena walls change (e.g. after arena builder closes).
    Clears cached wall segments and shadow grid so they recompute on next use.
    """
    arena.pop("_wall_segments_cache", None)
    arena.pop("_shadow_grid_cache",   None)


# ── Shadow / occlusion ────────────────────────────────────────────────────────

def _shadow_factor(sx: float, sy: float,
                   lx: float, ly: float,
                   light_radius: float,
                   arena: dict) -> float:
    """
    Return 1.0 (fully lit) … 0.0 (full shadow) for point (sx,sy)
    relative to light at (lx,ly).

    Casts a ray from the point toward the light.  If any wall segment
    intersects the ray before reaching the light, the point is in shadow.

    Penumbra: shadow fades smoothly from 1 (full shadow, right behind wall)
    to 0 (lit) over a distance proportional to the light radius.
    """
    dx   = lx - sx
    dy   = ly - sy
    dist = math.hypot(dx, dy)
    if dist < 1e-6:
        return 1.0

    # Ray direction from point toward light (normalised)
    ndx, ndy = dx / dist, dy / dist

    # Penumbra width — larger lights cast softer shadow edges
    penumbra = max(0.05, light_radius * 0.5)

    for (ax, ay), (bx, by) in _wall_segments(arena):
        t = _ray_segment_intersect(sx, sy, ndx, ndy, ax, ay, bx, by)
        if t is None or t >= dist - 0.001:
            continue   # no hit, or wall is at/beyond the light

        # Wall is between point and light — point is in shadow.
        # Shadow fades with distance from the wall (penumbra):
        # close to wall = full shadow, far from wall = back to lit.
        point_to_wall = t   # distance from point to occluding wall
        fade_start    = penumbra        # full shadow within this dist
        fade_end      = penumbra * 6.0  # fully lit beyond this dist
        if point_to_wall <= fade_start:
            return 0.0   # full shadow
        if point_to_wall >= fade_end:
            return 1.0   # shadow has faded — back to lit
        # Smooth transition
        t_fade = (point_to_wall - fade_start) / (fade_end - fade_start)
        return t_fade   # 0.0 = shadow, 1.0 = lit

    return 1.0   # clear line of sight — fully lit


# ── IR proximity ──────────────────────────────────────────────────────────────

def _min_dist_to_walls(wx: float, wy: float, arena: dict) -> float:
    """
    Minimum distance from point (wx, wy) to any wall segment
    (boundary walls and internal walls).
    Used to detect when a sensor origin has passed through a wall.
    """
    min_d = float("inf")
    for (ax, ay), (bx, by) in _wall_segments(arena):
        seg_dx = bx - ax
        seg_dy = by - ay
        seg_len_sq = seg_dx**2 + seg_dy**2
        if seg_len_sq < 1e-12:
            continue
        t = max(0.0, min(1.0,
                ((wx - ax) * seg_dx + (wy - ay) * seg_dy) / seg_len_sq))
        cx = ax + t * seg_dx
        cy = ay + t * seg_dy
        d  = math.hypot(wx - cx, wy - cy)
        if d < min_d:
            min_d = d
    return min_d


def ir_reading(wx: float, wy: float, angle_world: float,
               arena: dict,
               max_range: float = 0.80,
               adapter=None,
               foldback: bool | None = None) -> float:
    """
    Cast a ray from the sensor world position (wx, wy) in direction
    angle_world.  Return normalised proximity reading [0, 1].

    If adapter is provided and supports ray casting (PyBulletAdapter),
    uses it for physically accurate ray casts that include robot bodies.
    Otherwise falls back to 2D wall-segment ray cast.

    Uses the Sharp IR response curve (10cm–80cm):
      1.0  at ≤ 10cm
      ~0.1 at   70cm
      0.0  beyond 80cm

    foldback: None = use the module default (see set_ir_foldback), True/False
    to override per call. When on, sub-10cm readings fold back to look like a
    distant surface instead of clamping to 1.0.
    """
    # Check if sensor origin is past any wall (boundary or internal).
    # Do this by finding the minimum distance from the sensor to any
    # wall segment.  If closer than the sensor's physical size (~5mm),
    # it is pressed against or through the wall — return 1.0.
    # This handles both boundary walls and internal walls.
    _SENSOR_RADIUS = 0.005   # 5mm — sensor body half-size
    _min_wall_dist = _min_dist_to_walls(wx, wy, arena)
    if _min_wall_dist < _SENSOR_RADIUS:
        # Pressed against the wall. Optimistically that reads full scale; with
        # fold-back it reads like a distant surface, which is the real failure.
        return _ir_response(0.0, foldback=foldback)

    if adapter is not None:
        dist = adapter.ray_cast(wx, wy, angle_world, max_range)
    else:
        dx   = math.cos(angle_world)
        dy   = math.sin(angle_world)
        dist = max_range
        for (ax, ay), (bx, by) in _wall_segments(arena):
            t = _ray_segment_intersect(wx, wy, dx, dy, ax, ay, bx, by)
            if t is not None and t < dist:
                dist = t

    return _ir_response(dist, foldback=foldback)


def _ir_response(distance_m: float, foldback: bool | None = None) -> float:
    """Sharp IR response curve (10cm–80cm range).
    Kept internal — use ir_reading().
    1.0 at <= 10cm, 0.0 at >= 80cm, inverse-power falloff between.

    FOLD-BACK (opt-in, off by default)
    ----------------------------------
    The real GP2Y0A21 is NOT monotonic. Its output rises to a peak around
    8-10 cm and then FALLS again as the target gets closer, so a wall at 4 cm
    returns roughly the same voltage as a wall at 35-40 cm. The nominal
    "10-80 cm" figure is the usable monotonic band, not the sensing limit —
    below it the sensor does not saturate, it LIES, reporting a distant
    surface while touching a near one.

    Clamping to 1.0 up close (the default here) is the optimistic model: it
    makes a close wall maximally visible. Enabling fold-back makes narrow
    corridors genuinely hostile to a side-mounted IR, which is what the
    hardware does.

    Off by default so existing challenges and their recorded solve rates are
    unaffected. Enable per-call, or globally via set_ir_foldback(True).
    """
    if distance_m <= 0.0:
        return _foldback_response(0.0) if _resolve_foldback(foldback) else 1.0
    NEAR_M = 0.10   # 10cm — full scale (saturation)
    FAR_M  = 0.80   # 80cm — minimum detectable
    if distance_m < NEAR_M and _resolve_foldback(foldback):
        return _foldback_response(distance_m)
    if distance_m > FAR_M:
        return 0.0
    if distance_m <= NEAR_M:
        return 1.0
    # Inverse-power curve fitted to Sharp GP2Y0A21 characteristic
    _K = 1.2
    return max(0.0, min(1.0, (NEAR_M / distance_m) ** _K))


# ── IR fold-back (opt-in) ─────────────────────────────────────────────────────

IR_FOLDBACK = False          # global default; see set_ir_foldback()
_FOLD_GAIN  = 4.0            # how fast apparent distance grows below the peak


def set_ir_foldback(enabled: bool) -> None:
    """Globally enable/disable close-range fold-back for the IR model."""
    global IR_FOLDBACK
    IR_FOLDBACK = bool(enabled)


def _resolve_foldback(override: bool | None) -> bool:
    return IR_FOLDBACK if override is None else bool(override)


def _foldback_response(distance_m: float) -> float:
    """Below the peak, report the reading of a MUCH FARTHER surface.

    apparent = NEAR + (NEAR - d) * GAIN, so contact (d=0) reads like 0.50 m.
    That is the hardware failure this models: the sensor cannot distinguish
    'touching' from 'half a metre away'.
    """
    NEAR_M, _K = 0.10, 1.2
    apparent = NEAR_M + (NEAR_M - max(0.0, distance_m)) * _FOLD_GAIN
    if apparent > 0.80:
        return 0.0
    return max(0.0, min(1.0, (NEAR_M / apparent) ** _K))


# ── LDR photometric (upgraded) ────────────────────────────────────────────────

def ldr_reading(wx: float, wy: float, angle_world: float,
                arena: dict,
                channel: str = "white",
                gain: float = 1.0,
                only_source: tuple | None = None) -> float:
    """
    Compute LDR reading with:
      • Lambertian directional response  — cosine falloff by facing angle
      • Shadow occlusion with penumbra   — walls cast soft shadows
      • Distance falloff                 — same curve as before
      • Channel filtering                — W reads all, R/G/B read matching

    Target sensor model (see FUTURE_WORK FW-002):
      • W (white): an ambient, colour-blind intensity sensor. It sums the
        intensity of ALL lights regardless of colour, so overlapping lights
        read BRIGHTER. A room-ambient floor models background light.
      • R/G/B: read only the matching-colour component. Currently this is a
        BINARY filter — a light contributes iff its declared colour matches
        the channel exactly. The fuller model is GRADED: a mixed region (e.g.
        cyan from green+blue) contains SOME of each constituent colour, so a
        green channel in a cyan region should read partial green. Graded
        colour is deferred (FW-002); binary under-reports mixes but never
        over-reports, so it approximates without violating the target model.

    angle_world: sensor facing in world frame (radians).
                 = robot_heading + radians(sensor.angle_deg)

    only_source: if given as (x, y), restrict the LIGHT contribution to the
                 single light at that position. The force model uses this so
                 each light's signal is attributed to ITS OWN bearing (without
                 it, a sensor's total-channel reading was smeared across every
                 source's direction — a bug that let one light pull toward
                 another). NOTE: the white ambient floor is currently applied in
                 this mode too (see FW-003 divergence note below) because the
                 orbit/flow tunings depend on it.
    """
    total = 0.0

    for ls in arena.get("light_sources", []):
        ls_color = ls.get("color", "white")

        # Channel filter. W reads all colours (colour-blind intensity).
        # R/G/B: BINARY match for now (graded colour = FW-002).
        if channel != "white" and ls_color != channel:
            continue

        lx, ly = ls["x"], ls["y"]

        # Single-source restriction for the per-source force model.
        if only_source is not None:
            if abs(lx - only_source[0]) > 1e-6 or abs(ly - only_source[1]) > 1e-6:
                continue
        lr     = max(0.01, ls.get("radius", 0.15))
        emit   = max(0.0, ls.get("intensity", 1.0))

        # 1. Distance falloff
        dist = math.hypot(wx - lx, wy - ly)
        if dist >= lr * 3:
            continue
        falloff = max(0.0, 1.0 - dist / (lr * 3))

        # 2. Lambertian directional response (cosine).
        # NOTE (dev10): tried swapping in the hardware-CALIBRATED sharper response
        # (floor + (1-floor)*cos^4, from bench data 0/45/90deg -> 100/60/57%). It
        # REGRESSED game challenges (e.g. C6 timed out) because the narrower cone
        # makes LDRs lose the light during maneuvering — the bench geometry differs
        # from the in-plane game arenas, and existing challenges are balanced around
        # the gentler cosine. The calibration remains the ground truth for the
        # sim-VALIDATION tool (its actual purpose); the game keeps the tuned cosine.
        dir_to_light  = math.atan2(ly - wy, lx - wx)
        theta         = _angle_diff(dir_to_light, angle_world)
        directional   = max(0.0, math.cos(theta))

        # 3. Shadow occlusion with penumbra
        shadow = _shadow_factor(wx, wy, lx, ly, lr, arena)

        # Each light adds its own intensity; overlapping lights read brighter.
        total += emit * falloff * directional * shadow

    # Ambient floor for the white channel.
    #
    # KNOWN MODEL DIVERGENCE (see FUTURE_WORK FW-003): the target sensor model
    # treats room ambient as DIRECTIONLESS — it should not contribute to any
    # force term, because ambient light has no bearing to pull the robot toward.
    # However, the existing Orbit (ORBIT_INWARD) and Flow-around tunings were
    # calibrated WITH this floor present in the per-source force term, and rely
    # on it at the larger radii where a single light's real reading falls below
    # 0.3. Removing it here detunes C3 (Orbit) and C4 (Flow). So for now the
    # floor is applied in BOTH modes (sensing and per-source force). This is a
    # pragmatic divergence, harmless for every current arena (all use a single
    # white light or clearly-separated coloured lights); it would, however,
    # double-count for an arena with TWO white lights and injects a small
    # phantom directional pull. The faithful fix is to make ambient
    # directionless and RE-TUNE orbit/flow without it (FW-003).
    if channel == "white" and not arena.get("light_sources"):
        total = 0.3
    elif channel == "white" and total < 0.3:
        total = max(total, 0.3)

    return max(0.0, min(1.0, total * gain))


# ── Color / RGB channel ───────────────────────────────────────────────────────

def color_reading(wx: float, wy: float, angle_world: float,
                  arena: dict,
                  channel: str = "red",
                  gain: float = 1.0) -> float:
    """
    Directional photometric reading for a specific color channel (R/G/B).
    Identical to ldr_reading with channel filtering — no ambient floor.
    A named alias for clarity when used with explicit color sensors.
    """
    return ldr_reading(wx, wy, angle_world, arena,
                       channel=channel, gain=gain)


# ── Ultrasonic (future) ───────────────────────────────────────────────────────

def ultrasonic_reading(wx: float, wy: float, angle_world: float,
                       arena: dict,
                       max_range: float = 2.0,
                       cone_half_angle: float = 0.26,
                       adapter=None) -> float:
    """
    Multi-ray cone cast simulating an ultrasonic sensor.
    Casts 5 rays across the beam cone, returns the closest hit.
    Longer range and wider beam than IR.
    Output is normalised distance [0, 1]:  1.0 = touching, 0.0 = at max_range.

    If adapter is provided, uses it for physically accurate batch ray casts.
    cone_half_angle: half-width of the beam cone in radians (~15° default).
    """
    N_RAYS = 5
    if adapter is not None:
        best = adapter.ray_cast_cone(wx, wy, angle_world,
                                     cone_half_angle, N_RAYS, max_range)
    else:
        best    = max_range
        offsets = [cone_half_angle * (i / (N_RAYS - 1) - 0.5) * 2
                   for i in range(N_RAYS)]
        for off in offsets:
            angle = angle_world + off
            dx, dy = math.cos(angle), math.sin(angle)
            for (ax, ay), (bx, by) in _wall_segments(arena):
                t = _ray_segment_intersect(wx, wy, dx, dy, ax, ay, bx, by)
                if t is not None and t < best:
                    best = t

    return max(0.0, 1.0 - best / max_range)


# ── Contact / bump sensor (future) ───────────────────────────────────────────

def contact_reading(wx: float, wy: float, angle_world: float,
                    arena: dict,
                    robot_corners: list[tuple] | None = None,
                    threshold_m: float = 0.005,
                    adapter=None) -> float:
    """
    Returns 1.0 if the sensor position is within threshold_m of any wall,
    0.0 otherwise.  For accurate collision use robot_corners (body polygon).

    This is a proximity trigger, not a continuous reading — output is binary
    (0 or 1) in normal use.  The threshold models sensor mechanical travel.
    """
    # Use adapter contacts if available for accurate body-part detection
    if adapter is not None:
        contacts = adapter.contacts()
        for c in contacts:
            if math.hypot(c.position_w[0] - wx,
                          c.position_w[1] - wy) <= threshold_m * 10:
                return 1.0
        return 0.0

    segs = _wall_segments(arena)

    # Simple check: distance from sensor world position to nearest wall
    for (ax, ay), (bx, by) in segs:
        # Distance from point (wx,wy) to segment (ax,ay)-(bx,by)
        seg_dx = bx - ax
        seg_dy = by - ay
        seg_len_sq = seg_dx**2 + seg_dy**2
        if seg_len_sq < 1e-12:
            continue
        t = max(0.0, min(1.0,
                         ((wx - ax) * seg_dx + (wy - ay) * seg_dy)
                         / seg_len_sq))
        closest_x = ax + t * seg_dx
        closest_y = ay + t * seg_dy
        dist = math.hypot(wx - closest_x, wy - closest_y)
        if dist <= threshold_m:
            return 1.0

    return 0.0


# ── Hall effect / magnetic (future) ───────────────────────────────────────────

def hall_reading(wx: float, wy: float, angle_world: float,
                 arena: dict,
                 max_range: float = 0.3) -> float:
    """
    Omnidirectional magnetic field sensor.
    Reads 'magnetic_sources' from the arena dict (not yet in arena builder).
    Returns normalised field strength [0, 1] with distance falloff.
    angle_world is ignored — hall sensors are omnidirectional.
    """
    total = 0.0
    for ms in arena.get("magnetic_sources", []):
        dist   = math.hypot(wx - ms["x"], wy - ms["y"])
        radius = max(0.01, ms.get("radius", max_range))
        if dist < radius:
            total += max(0.0, 1.0 - dist / radius) * ms.get("strength", 1.0)
    return max(0.0, min(1.0, total))


# ── Acoustic (future) ─────────────────────────────────────────────────────────

def acoustic_reading(wx: float, wy: float, angle_world: float,
                     arena: dict,
                     frequency_band: str = "all") -> float:
    """
    Sound pressure level sensor.
    Reads 'sound_sources' from the arena dict (not yet in arena builder).
    Basic model: distance falloff, no reflections yet.
    Future upgrade: add wall reflections for echo/reverb effects.
    """
    total = 0.0
    for ss in arena.get("sound_sources", []):
        if frequency_band != "all" and \
                ss.get("band", "all") != frequency_band:
            continue
        dist   = math.hypot(wx - ss["x"], wy - ss["y"])
        radius = max(0.01, ss.get("radius", 1.0))
        if dist < radius * 3:
            total += max(0.0, 1.0 - dist / (radius * 2))
    return max(0.0, min(1.0, total))


# ── Universal dispatch ────────────────────────────────────────────────────────

SENSOR_DISPATCH: dict[str, Any] = {
    "IR":       ir_reading,
    "LDR":      ldr_reading,
    "COLOR":    color_reading,
    "BUMP":     contact_reading,
    "SONIC":    ultrasonic_reading,
    "HALL":     hall_reading,
    "ACOUSTIC": acoustic_reading,
}


def read_sensor(sensor_type: str,
                wx: float, wy: float,
                angle_world: float,
                arena: dict,
                adapter=None,
                **kwargs) -> float:
    """
    Universal sensor reading entry point.

    Parameters
    ----------
    sensor_type : str
        One of the keys in SENSOR_DISPATCH ("IR", "LDR", "COLOR", etc.)
    wx, wy : float
        Sensor world position in metres.
    angle_world : float
        Sensor facing direction in world frame (radians).
        Compute as: robot_heading + math.radians(sensor_angle_deg)
    arena : dict
        Arena definition dict with walls, lights, etc.
    **kwargs
        Type-specific parameters forwarded to the sensor function:
          LDR / COLOR : channel="white"/"red"/"green"/"blue", gain=1.0
          IR          : max_range=0.5
          SONIC       : max_range=2.0, cone_half_angle=0.26
          BUMP        : robot_corners=None, threshold_m=0.005

    Returns
    -------
    float
        Normalised sensor reading in [0.0, 1.0].

    Raises
    ------
    ValueError
        If sensor_type is not in SENSOR_DISPATCH.
    """
    fn = SENSOR_DISPATCH.get(sensor_type)
    if fn is None:
        raise ValueError(
            f"Unknown sensor type: {sensor_type!r}. "
            f"Known types: {list(SENSOR_DISPATCH)}")
    # Pass adapter to functions that can use it (IR, SONIC, BUMP)
    # LDR/COLOR/HALL/ACOUSTIC ignore it — PyBullet has no coverage there
    if adapter is not None and sensor_type in ("IR", "SONIC", "BUMP"):
        kwargs["adapter"] = adapter
    return fn(wx, wy, angle_world, arena, **kwargs)


# ── Shadow grid (for rendering overlay) ──────────────────────────────────────

def compute_shadow_grid(arena: dict,
                        resolution: int = 24) -> list[list[float]]:
    """
    Compute a grid of shadow values across the arena for rendering.

    Returns a 2D list [row][col] of floats in [0, 1]:
      1.0 = fully lit, 0.0 = fully shadowed.

    The grid covers the arena bounds at the given resolution (cells per
    metre).  Cached on the arena dict — call invalidate_arena_cache() when
    walls or lights change.

    Used by draw_arena() to render the shadow overlay.
    """
    cache_key = f"_shadow_grid_cache_{resolution}"
    if cache_key in arena:
        return arena[cache_key]

    aw = arena["width"]
    ah = arena["height"]
    nx = max(4, int(aw * resolution))
    ny = max(4, int(ah * resolution))

    grid = []
    for row in range(ny):
        wy = -ah/2 + (row + 0.5) * ah / ny
        grid_row = []
        for col in range(nx):
            wx = -aw/2 + (col + 0.5) * aw / nx
            # Shadow = min shadow factor across all light sources
            if not arena.get("light_sources"):
                grid_row.append(1.0)
                continue
            # A cell is lit if ANY light illuminates it (max, not min)
            cell_lit = 0.0
            for ls in arena["light_sources"]:
                lx, ly = ls["x"], ls["y"]
                lr     = max(0.01, ls.get("radius", 0.15))
                dist   = math.hypot(wx - lx, wy - ly)
                if dist >= lr * 3:
                    continue   # outside light range
                # Combine shadow factor with distance falloff
                intensity = max(0.0, 1.0 - dist / (lr * 2))
                sf        = _shadow_factor(wx, wy, lx, ly, lr, arena)
                cell_lit  = max(cell_lit, sf * intensity)
            grid_row.append(cell_lit)
        grid.append(grid_row)

    arena[cache_key] = grid
    return grid
