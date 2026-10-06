/* sim.js — BYOV core physics
 *
 * The HEART of the simulator: a faithful digital twin of the physical AnaBBot.
 * Two things distinguish this from BugWorks:
 *   1. DIRECTIONAL sensors with a real cone of operation (NOT omnidirectional).
 *      A sensor's reading depends on its mounted angle/position AND its
 *      orientation to / distance from the stimulus.
 *   2. Real physical constants from engine/adapters/simple_drive.py.
 *
 * Units are metres / radians / seconds, matching the physical robot, so the
 * sim↔physical correspondence (C2) is exact.
 */

// ── Physical constants (from the real AnaBBot) ───────────────────────────────
export const PHYS = {
  WHEELBASE:  0.080,   // m  — distance between wheels
  MAX_SPEED:  0.175,   // m/s at motor command 1.0
  WALL_T:     0.012,   // m  — wall thickness
  BODY_R:     0.045,   // m  — robot body radius (~AnaBBot footprint)
};

// ── Sensor specs (real analogues) ────────────────────────────────────────────
// LDR light sensor: wide cone, inverse-square × cosine falloff.
export const LDR = {
  FOV_HALF:   Math.PI * 70 / 180,  // 70° half-angle (≈140° cone)
  REF_DIST:   0.30,                // m — distance at which a unit light reads ~1
};
// IR proximity (Sharp GP2Y0A21): narrow beam, 18–60 cm useful range.
export const IR = {
  FOV_HALF:   Math.PI * 5 / 180,   // ~5° half-angle (very narrow)
  MIN_RANGE:  0.18,                // m
  MAX_RANGE:  0.60,                // m
};

const TAU = Math.PI * 2;
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const norm = (a) => { while (a > Math.PI) a -= TAU; while (a < -Math.PI) a += TAU; return a; };

/* World-space pose of a sensor mounted on the robot.
 * mount = {x, y, angle}  — x/y are body-frame offsets (m), angle is degrees
 *                          CCW from body +Y (forward), matching the Python model.
 * Body frame: +Y = forward, +X = right.
 * Returns { x, y, dir } where dir is the world-space facing angle (radians).
 */
export function sensorPose(robot, mount) {
  const h = robot.heading;
  const sin = Math.sin(h), cos = Math.cos(h);
  // body +Y(forward) -> world (cos h, sin h); body +X(right) -> (sin h, -cos h)
  const wx = robot.x + mount.x * sin + mount.y * cos;
  const wy = robot.y - mount.x * cos + mount.y * sin;
  const dir = h + (mount.angle * Math.PI / 180);
  return { x: wx, y: wy, dir };
}

/* Does an LDR of the given channel respond to a light of the given color?
 * White (W) channel responds to ANY light. Colored channels (R/G/B) respond
 * ONLY to lights of their own color. (White light is seen only by the W
 * channel — colored channels are strict.)
 */
export function channelSeesColor(channel, lightColor) {
  const ch = (channel || 'W').toUpperCase();
  const col = (lightColor || 'white').toLowerCase();
  if (ch === 'W') return true;               // white channel: sees everything
  if (ch === 'R') return col === 'red';
  if (ch === 'G') return col === 'green';
  if (ch === 'B') return col === 'blue';
  return true;
}

/* LDR reading: sum over light sources of (inverse-square distance ×
 * cosine off-axis), gated by the FOV cone, occlusion by walls, AND the
 * sensor's colour channel vs the light's colour. Returns [0, 1].
 * `channel` is one of 'W','R','G','B' (default 'W').
 */
export function readLDR(pose, lights, walls, channel = 'W') {
  let total = 0;
  for (const L of lights) {
    if (!channelSeesColor(channel, L.color)) continue;   // colour mismatch -> blind
    const dx = L.x - pose.x, dy = L.y - pose.y;
    const dist = Math.hypot(dx, dy);
    if (dist < 1e-4) { total += (L.intensity || 1); continue; }
    const bearing = Math.atan2(dy, dx);
    const off = Math.abs(norm(bearing - pose.dir));   // off-axis angle
    if (off > LDR.FOV_HALF) continue;                 // outside the cone
    if (occluded(pose, L, walls)) continue;           // wall blocks the light
    const cosFactor = Math.cos(off * (Math.PI / 2) / LDR.FOV_HALF); // 1 at axis -> 0 at edge
    const distFactor = (LDR.REF_DIST * LDR.REF_DIST) / (dist * dist); // inverse-square
    total += (L.intensity || 1) * cosFactor * distFactor;
  }
  return clamp(total, 0, 1);
}

/* IR reading: nearest obstacle/wall within the narrow beam, mapped so
 * closer = stronger, within the sensor's useful range. Returns [0, 1].
 */
export function readIR(pose, walls) {
  // cast a short ray along the sensor direction; find nearest wall hit.
  const maxD = IR.MAX_RANGE;
  let nearest = Infinity;
  const rayX = Math.cos(pose.dir), rayY = Math.sin(pose.dir);
  for (const w of walls) {
    const t = raySegment(pose.x, pose.y, rayX, rayY, w.x1, w.y1, w.x2, w.y2);
    if (t !== null && t < nearest) nearest = t;
  }
  if (nearest === Infinity || nearest > maxD) return 0;
  if (nearest < IR.MIN_RANGE) return 1;          // saturated up close
  // map [MIN..MAX] -> [1..0]
  return clamp(1 - (nearest - IR.MIN_RANGE) / (IR.MAX_RANGE - IR.MIN_RANGE), 0, 1);
}

/* Differential-drive update. left/right are motor commands in [-1, 1].
 * Mutates robot {x, y, heading}. dt in seconds. Stops at walls (no slide).
 */
export function driveStep(robot, left, right, dt, walls) {
  const vL = clamp(left, -1, 1) * PHYS.MAX_SPEED;
  const vR = clamp(right, -1, 1) * PHYS.MAX_SPEED;
  const v = (vL + vR) / 2;
  const omega = (vR - vL) / PHYS.WHEELBASE;
  const nx = robot.x + v * Math.cos(robot.heading) * dt;
  const ny = robot.y + v * Math.sin(robot.heading) * dt;
  // wall collision: if the new body circle would cross a wall, don't translate
  if (!bodyHitsWall(nx, ny, walls)) { robot.x = nx; robot.y = ny; }
  robot.heading = norm(robot.heading + omega * dt);
}

// ── geometry helpers ─────────────────────────────────────────────────────────
function raySegment(px, py, dx, dy, x1, y1, x2, y2) {
  // ray (px,py)+t(dx,dy), t>=0  vs segment (x1,y1)-(x2,y2). returns t or null.
  const ex = x2 - x1, ey = y2 - y1;
  const denom = dx * ey - dy * ex;
  if (Math.abs(denom) < 1e-9) return null;
  const t = ((x1 - px) * ey - (y1 - py) * ex) / denom;
  const u = ((x1 - px) * dy - (y1 - py) * dx) / denom;
  if (t >= 0 && u >= 0 && u <= 1) return t;
  return null;
}

function occluded(pose, light, walls) {
  const dx = light.x - pose.x, dy = light.y - pose.y;
  const dist = Math.hypot(dx, dy);
  const rx = dx / dist, ry = dy / dist;
  for (const w of walls) {
    const t = raySegment(pose.x, pose.y, rx, ry, w.x1, w.y1, w.x2, w.y2);
    if (t !== null && t < dist - 1e-3) return true;
  }
  return false;
}

function bodyHitsWall(x, y, walls) {
  for (const w of walls) {
    if (pointSegDist(x, y, w.x1, w.y1, w.x2, w.y2) < PHYS.BODY_R + PHYS.WALL_T / 2)
      return true;
  }
  return false;
}

function pointSegDist(px, py, x1, y1, x2, y2) {
  const ex = x2 - x1, ey = y2 - y1;
  const len2 = ex * ex + ey * ey;
  let t = len2 ? ((px - x1) * ex + (py - y1) * ey) / len2 : 0;
  t = clamp(t, 0, 1);
  const cx = x1 + t * ex, cy = y1 + t * ey;
  return Math.hypot(px - cx, py - cy);
}

export { clamp, norm };
