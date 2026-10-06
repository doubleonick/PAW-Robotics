/* arena.js — the world: boundary, internal walls, light sources, and all
 * canvas rendering (arena, vehicle body, directional sensor cones, trail).
 * Mirrors the physical PAW arena proportions (1.2 m × 1.6 m).
 */
import { PHYS, LDR, sensorPose } from './sim.js?v=7';

export class Arena {
  constructor(width = 1.2, height = 1.6) {
    this.W = width; this.H = height;
    this.grid = 0.10;                 // 10 cm grid for wall/light placement
    this.walls = this._boundary();
    this.lights = [{ x: width * 0.5, y: height * 0.85, intensity: 1, color: 'white' }];
    this.robotStart = { x: width * 0.5, y: height * 0.18, heading: Math.PI / 2 };
  }
  _boundary() {
    const { W, H } = this;
    return [
      { x1: 0, y1: 0, x2: W, y2: 0 },
      { x1: W, y1: 0, x2: W, y2: H },
      { x1: W, y1: H, x2: 0, y2: H },
      { x1: 0, y1: H, x2: 0, y2: 0 },
    ];
  }
  snap(v) { return Math.round(v / this.grid) * this.grid; }
  addWallCell(gx, gy) {
    // add the four edges of a grid cell at (gx,gy) as walls (dedup-ish)
    const x = gx * this.grid, y = gy * this.grid, g = this.grid;
    this.addWall(x, y, x + g, y); this.addWall(x + g, y, x + g, y + g);
    this.addWall(x + g, y + g, x, y + g); this.addWall(x, y + g, x, y);
  }
  addWall(x1, y1, x2, y2) { this.walls.push({ x1, y1, x2, y2 }); }
  addLight(x, y, intensity = 1, color = 'white') { this.lights.push({ x, y, intensity, color }); }
  clearLights() { this.lights = []; }
  clearWalls() { this.walls = this._boundary(); }
  reset() { this.walls = this._boundary(); }
}

/* Renderer maps world metres -> canvas pixels and draws everything. */
export class Renderer {
  constructor(canvas, arena) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.arena = arena;
    this.trail = [];
    this._resize();
  }
  _resize() {
    // Fit arena into the canvas, leaving a gutter on the LEFT for the meter HUD.
    const c = this.canvas;
    const pad = 16;
    this.hudW = 118;                      // left gutter: M1 M2 M3 LED bars, side by side
    const availW = c.width - pad * 2 - this.hudW, availH = c.height - pad * 2;
    this.scale = Math.min(availW / this.arena.W, availH / this.arena.H);
    this.ox = pad + this.hudW + (availW - this.arena.W * this.scale) / 2;
    this.oy = pad + (availH - this.arena.H * this.scale) / 2;
  }

  /* Meter HUD — three 10-segment LED bars standing SIDE BY SIDE in the gutter
   * to the left of the arena, ordered M1 M2 M3 left-to-right, matching the
   * physical robot and the Build Robot view. M1/M3 red, M2 white (the game's
   * colours). Housing and unlit LEDs are always visible; lit segments glow
   * while running. */
  _drawMeterHUD(vehicle, running) {
    if (!vehicle || !vehicle.meters) return;
    const ctx = this.ctx;
    const SEGMENTS = 10, segW = 18, segH = 9, segGap = 2;
    const barH = SEGMENTS * (segH + segGap) - segGap;     // 108
    const LIT  = { M1: '#dc3232', M2: '#f0f0f0', M3: '#dc3232' };
    const DIM  = { M1: '#4a1414', M2: '#4a4a4a', M3: '#4a1414' };
    const OFF  = '#262b33';                    // unlit LED, visible on the panel
    const order = ['M1', 'M2', 'M3'];          // left -> right, as on the robot
    const pitch = 34;                          // centre-to-centre spacing
    const groupW = (order.length - 1) * pitch;
    const cx0 = 16 + this.hudW / 2 - groupW / 2;
    const by = Math.max(24, (this.canvas.height - barH) / 2 - 30);

    // header for the whole HUD
    ctx.fillStyle = running ? '#c9d1d9' : '#6b7280';
    ctx.font = 'bold 10px monospace'; ctx.textAlign = 'center';
    ctx.fillText('METERS', 16 + this.hudW / 2, by - 14);

    order.forEach((id, i) => {
      const mt  = vehicle.meters.find(m => m.id === id);
      const val = (vehicle._meterVals && vehicle._meterVals[id]) || 0;
      const lit = Math.floor(val * SEGMENTS);   // int() truncation, as in the game
      const cxBar = cx0 + i * pitch;
      const bx = cxBar - segW / 2;

      // housing — always visible so the meters read as hardware when idle
      ctx.fillStyle = '#0b0e13';
      ctx.strokeStyle = running ? '#3a4250' : '#232a33';
      ctx.lineWidth = 1.5;
      this._rr(bx - 5, by - 5, segW + 10, barH + 10, 4);
      ctx.fill(); ctx.stroke();

      for (let seg = 0; seg < SEGMENTS; seg++) {
        const sy = by + barH - seg * (segH + segGap) - segH;
        const on = running && seg < lit;
        ctx.fillStyle = on ? LIT[id] : (running ? DIM[id] : OFF);
        if (on) { ctx.shadowColor = LIT[id]; ctx.shadowBlur = 10; }
        this._rr(bx, sy, segW, segH, 2); ctx.fill();
        ctx.shadowBlur = 0;
      }

      // label + whatever is wired to it
      ctx.fillStyle = running ? '#c9d1d9' : '#8b949e';
      ctx.font = 'bold 11px monospace'; ctx.textAlign = 'center';
      ctx.fillText(id, cxBar, by + barH + 18);
      ctx.fillStyle = '#6b7280'; ctx.font = '9px monospace';
      ctx.fillText(mt && mt.input ? mt.input.srcId.replace('LDR_', 'L').replace('IR_', 'I') : '—',
                   cxBar, by + barH + 29);
    });
  }

  /* rounded-rect path helper (canvas roundRect isn't everywhere) */
  _rr(x, y, w, h, r) {
    const ctx = this.ctx;
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  // world (m) -> canvas (px). World y is up; canvas y is down -> flip.
  tx(x) { return this.ox + x * this.scale; }
  ty(y) { return this.oy + (this.arena.H - y) * this.scale; }
  m(v) { return v * this.scale; }

  pushTrail(x, y) { this.trail.push({ x, y }); if (this.trail.length > 4000) this.trail.shift(); }
  clearTrail() { this.trail = []; }

  draw(vehicle, opts = {}) {
    const ctx = this.ctx, A = this.arena;
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    this._drawMeterHUD(vehicle, !!opts.running);

    // arena floor
    ctx.fillStyle = '#0d1117';
    ctx.fillRect(this.tx(0), this.ty(A.H), this.m(A.W), this.m(A.H));

    // grid (edit mode)
    if (opts.showGrid) {
      ctx.strokeStyle = '#1c2230'; ctx.lineWidth = 1;
      for (let gx = 0; gx <= A.W + 1e-6; gx += A.grid) {
        ctx.beginPath(); ctx.moveTo(this.tx(gx), this.ty(0)); ctx.lineTo(this.tx(gx), this.ty(A.H)); ctx.stroke();
      }
      for (let gy = 0; gy <= A.H + 1e-6; gy += A.grid) {
        ctx.beginPath(); ctx.moveTo(this.tx(0), this.ty(gy)); ctx.lineTo(this.tx(A.W), this.ty(gy)); ctx.stroke();
      }
    }

    ctx.strokeStyle = '#30363d'; ctx.lineWidth = 1;
    ctx.strokeRect(this.tx(0), this.ty(A.H), this.m(A.W), this.m(A.H));

    // light sources (glow), tinted by colour
    const LIGHT_RGB = { white: '255,200,60', red: '220,60,60', green: '60,200,60', blue: '80,140,255' };
    for (const L of A.lights) {
      const rgb = LIGHT_RGB[L.color] || LIGHT_RGB.white;
      const r = this.m(0.08) * (L.intensity || 1);
      const g = ctx.createRadialGradient(this.tx(L.x), this.ty(L.y), 0,
                                         this.tx(L.x), this.ty(L.y), r * 3);
      g.addColorStop(0, `rgba(${rgb},0.9)`);
      g.addColorStop(0.4, `rgba(${rgb},0.25)`);
      g.addColorStop(1, `rgba(${rgb},0)`);
      ctx.fillStyle = g;
      ctx.beginPath(); ctx.arc(this.tx(L.x), this.ty(L.y), r * 3, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = `rgb(${rgb})`;
      ctx.beginPath(); ctx.arc(this.tx(L.x), this.ty(L.y), r * 0.5, 0, Math.PI * 2); ctx.fill();
    }

    // walls
    ctx.strokeStyle = '#8b949e'; ctx.lineWidth = Math.max(2, this.m(PHYS.WALL_T));
    for (const w of A.walls) {
      ctx.beginPath(); ctx.moveTo(this.tx(w.x1), this.ty(w.y1));
      ctx.lineTo(this.tx(w.x2), this.ty(w.y2)); ctx.stroke();
    }

    // trail
    if (this.trail.length > 1) {
      ctx.strokeStyle = 'rgba(88,166,255,0.6)'; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(this.tx(this.trail[0].x), this.ty(this.trail[0].y));
      for (const p of this.trail) ctx.lineTo(this.tx(p.x), this.ty(p.y));
      ctx.stroke();
    }

    if (vehicle) this._drawVehicle(vehicle, opts);
  }

  _drawVehicle(v, opts) {
    const ctx = this.ctx;
    const px = this.tx(v.x), py = this.ty(v.y);
    const R = this.m(PHYS.BODY_R);

    // sensor cones (the DIRECTIONALITY made visible — the anti-BugWorks feature)
    if (opts.showCones !== false) {
      for (const s of v.sensors) {
        const pose = sensorPose(v, s.mount);
        const half = (s.type === 'LDR') ? LDR.FOV_HALF : (Math.PI * 5 / 180);
        const len = this.m(s.type === 'LDR' ? 0.25 : 0.12);
        // canvas angle: world dir, but y flipped -> negate
        const a = -pose.dir;
        const cx = this.tx(pose.x), cy = this.ty(pose.y);
        ctx.beginPath(); ctx.moveTo(cx, cy);
        ctx.arc(cx, cy, len, a - half, a + half);
        ctx.closePath();
        ctx.fillStyle = (s.type === 'LDR') ? 'rgba(255,221,87,0.10)'
                                           : 'rgba(255,107,107,0.10)';
        ctx.fill();
      }
    }

    // body (rectangle matching the AnaBBot footprint)
    ctx.save();
    ctx.translate(px, py);
    ctx.rotate(-v.heading + Math.PI / 2);   // heading: +Y forward -> rotate so forward is up
    const halfW = this.m(v.bodyW / 2), halfL = this.m(v.bodyL / 2);
    ctx.fillStyle = '#1f6feb'; ctx.strokeStyle = '#58a6ff'; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.rect(-halfW, -halfL, halfW * 2, halfL * 2); ctx.fill(); ctx.stroke();
    // forward indicator (a notch at the front)
    ctx.fillStyle = '#f0f6fc';
    ctx.beginPath(); ctx.moveTo(0, -halfL); ctx.lineTo(-4, -halfL + 7); ctx.lineTo(4, -halfL + 7); ctx.closePath(); ctx.fill();
    // motors on the sides
    ctx.fillStyle = '#58a6ff';
    ctx.fillRect(-halfW - 4, -6, 4, 12); ctx.fillRect(halfW, -6, 4, 12);
    // prominent heading arrow (shown when editing, so orientation is obvious)
    if (opts.showHeadingArrow) {
      const aLen = halfL + 22;
      ctx.strokeStyle = '#ffdd57'; ctx.fillStyle = '#ffdd57'; ctx.lineWidth = 3;
      ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(0, -aLen); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(0, -aLen); ctx.lineTo(-6, -aLen + 10); ctx.lineTo(6, -aLen + 10); ctx.closePath(); ctx.fill();
    }
    ctx.restore();

    // sensor dots
    for (const s of v.sensors) {
      const pose = sensorPose(v, s.mount);
      ctx.fillStyle = (s.type === 'LDR') ? '#ffdd57' : '#ff6b6b';
      ctx.beginPath(); ctx.arc(this.tx(pose.x), this.ty(pose.y), 3, 0, Math.PI * 2); ctx.fill();
    }
  }

  // canvas px -> world m (for click placement of lights)
  toWorld(px, py) {
    return { x: (px - this.ox) / this.scale, y: this.arena.H - (py - this.oy) / this.scale };
  }
}
