/* vehicle.js — the vehicle: body, sensors, optional neurons, meters, motors.
 *
 * v3 wiring model — matches the physical Ana BBot board and the Python engine
 * (engine/signals.py), so a wiring that works here means the same thing there:
 *
 *   WIRE COLOUR = WEIGHT, not excite/inhibit:  blue = 1x, green = 2x, red = 3x.
 *   EXCITE vs INHIBIT comes from WHICH INPUT the wire lands on (E or I), exactly
 *   as it does on the board.
 *
 *   DEFAULT is DIRECT wiring: sensor -> motor. Neurons are OPTIONAL; add them
 *   (up to 6, laid out as 3 rows of 2 like the board) when you want to combine
 *   or offset signals.
 *
 *   METERS M1/M2/M3 are permanently installed. Each takes exactly ONE wire, from
 *   a sensor or a neuron. They are DISPLAY ONLY and never affect the motors.
 *
 *   ONE shared BIAS pot sits between the motors: a resting speed applied to both,
 *   so a vehicle can idle forward even with no neurons in the circuit.
 *
 * Evaluation (feed-forward, so it can never loop):
 *     sensors -> neurons   N = clamp(bias + Σ sign*weight*sensor, 0, 1)
 *     sensors/neurons -> meters   M = clamp(weight*source, 0, 1)      [display]
 *     sensors/neurons -> motors   V = clamp(sharedBias + Σ sign*weight*src, 0, 1)
 */
import { sensorPose, readLDR, readIR, clamp } from './sim.js?v=7';

export const WIRE_WEIGHT = { blue: 1, green: 2, red: 3 };
export const WIRE_COLORS = ['blue', 'green', 'red'];
export const MAX_NEURONS = 6;
export const MOTOR_SLOTS = 4;      // headers per motor bank, as on the board

export class Vehicle {
  constructor() {
    // Robot pose (world metres / radians). Set by the arena on spawn.
    this.x = 0; this.y = 0; this.heading = Math.PI / 2; // start facing +Y (up)

    this.bodyW = 0.090;   // m — width (left-right)
    this.bodyL = 0.110;   // m — length (front-back)

    this.mountPoints = [
      { id: 'LDR_L', x: -0.038, y: 0.050, angle:  35 },
      { id: 'IR_L',  x: -0.015, y: 0.055, angle:   0 },
      { id: 'IR_R',  x:  0.015, y: 0.055, angle:   0 },
      { id: 'LDR_R', x:  0.038, y: 0.050, angle: -35 },
    ];
    this.loadout  = { LDR_L: 'LDR', IR_L: 'IR', IR_R: 'IR', LDR_R: 'LDR' };
    this.channels = { LDR_L: 'W', IR_L: 'W', IR_R: 'W', LDR_R: 'W' };

    this._rebuildSensors();

    // Neurons: NONE by default; up to MAX_NEURONS, added/removed LIFO.
    // Each: { id, bias, inputs:[{srcId, sign, color}] }   (srcId = sensor id)
    this.neurons = [];

    // Meters: permanently installed, exactly ONE input each, display only.
    // Each: { id, input: null | { srcId, color } }
    this.meters = [
      { id: 'M1', input: null },
      { id: 'M2', input: null },
      { id: 'M3', input: null },
    ];

    // Motors: wire targets with FORWARD and REVERSE banks, like the board's
    // FL/BL and FR/BR headers — there is no excite/inhibit at a motor. You pick
    // a direction; a reverse wire subtracts from forward. Four slots per bank.
    // Each: { id, fwd:[{srcId,color}], rev:[{srcId,color}] }
    this.motors = [
      { id: 'L', fwd: [], rev: [] },
      { id: 'R', fwd: [], rev: [] },
    ];

    // The single pot between the motors: a resting speed applied to BOTH.
    this.bias = 0;

    this._readings   = {};
    this._neuronVals = {};
    this._meterVals  = { M1: 0, M2: 0, M3: 0 };
    this._motorCmd   = { L: 0, R: 0 };
  }

  _rebuildSensors() {
    this.sensors = [];
    for (const mp of this.mountPoints) {
      const type = this.loadout[mp.id];
      if (type === 'LDR' || type === 'IR') {
        const s = { id: mp.id, type, mount: { x: mp.x, y: mp.y, angle: mp.angle } };
        if (type === 'LDR') s.channel = this.channels[mp.id] || 'W';
        this.sensors.push(s);
      }
    }
  }

  _liveSourceIds() {
    return new Set([...this.sensors.map(s => s.id), ...this.neurons.map(n => n.id)]);
  }

  /* Drop wires whose source no longer exists (sensor removed / neuron deleted). */
  _pruneDeadInputs() {
    const live = this._liveSourceIds();
    for (const n of this.neurons)
      n.inputs = n.inputs.filter(i => live.has(i.srcId) && i.srcId !== n.id);
    for (const m of this.motors) {
      m.fwd = m.fwd.filter(i => live.has(i.srcId));
      m.rev = m.rev.filter(i => live.has(i.srcId));
    }
    for (const mt of this.meters)
      if (mt.input && !live.has(mt.input.srcId)) mt.input = null;
  }

  setMount(mountId, type) {
    this.loadout[mountId] = type;
    this._rebuildSensors();
    this._pruneDeadInputs();
  }
  setChannel(mountId, channel) {
    this.channels[mountId] = channel;
    this._rebuildSensors();
  }

  // ── Neurons: add / remove (LIFO), capped at MAX_NEURONS ──────────────────
  addNeuron() {
    if (this.neurons.length >= MAX_NEURONS) return null;
    const id = 'N' + (this.neurons.length + 1);
    this.neurons.push({ id, bias: 0, inputs: [] });
    return id;
  }
  /* Remove the most recently added neuron (LIFO) and any wires touching it. */
  removeLastNeuron() {
    if (!this.neurons.length) return null;
    const gone = this.neurons.pop();
    this._pruneDeadInputs();
    return gone.id;
  }
  setNeuronBias(neuronId, bias) {
    const n = this.neurons.find(n => n.id === neuronId);
    if (n) n.bias = clamp(bias, -1, 1);
  }
  /* The single shared motor bias (the pot between the motors). */
  setBias(bias) { this.bias = clamp(bias, -1, 1); }

  _target(id) {
    return this.neurons.find(n => n.id === id)
        || this.motors.find(m => m.id === id)
        || this.meters.find(m => m.id === id)
        || null;
  }
  _isMeter(id)  { return this.meters.some(m => m.id === id); }
  _isMotor(id)  { return this.motors.some(m => m.id === id); }
  _isNeuron(id) { return this.neurons.some(n => n.id === id); }

  readSensors(lights, walls) {
    const out = {};
    for (const s of this.sensors) {
      const pose = sensorPose(this, s.mount);
      out[s.id] = (s.type === 'LDR') ? readLDR(pose, lights, walls, s.channel)
                                     : readIR(pose, walls);
    }
    this._readings = out;
    return out;
  }

  evaluate(readings) {
    const w = c => WIRE_WEIGHT[c] || 1;

    // Stage 1 — neurons (sensor inputs only, so the graph cannot loop).
    const nv = {};
    for (const n of this.neurons) {
      let sum = n.bias;
      for (const i of n.inputs) sum += i.sign * w(i.color) * (readings[i.srcId] || 0);
      nv[n.id] = clamp(sum, 0, 1);
    }
    this._neuronVals = nv;

    const srcVal = id => (id in nv) ? nv[id] : (readings[id] || 0);

    // Stage 2 — meters (display only; never touch the motors).
    const mv = {};
    for (const mt of this.meters)
      mv[mt.id] = mt.input ? clamp(w(mt.input.color) * srcVal(mt.input.srcId), 0, 1) : 0;
    this._meterVals = mv;

    // Stage 3 — motors: forward bank minus reverse bank, plus the shared bias
    // (a forward resting speed). Matches the Python engine's (FL - BL).
    const motor = { L: 0, R: 0 };
    for (const m of this.motors) {
      let f = this.bias, r = 0;
      for (const i of m.fwd) f += w(i.color) * srcVal(i.srcId);
      for (const i of m.rev) r += w(i.color) * srcVal(i.srcId);
      motor[m.id] = clamp(f - r, -1, 1);
    }
    this._motorCmd = motor;
    return motor;
  }

  /* Wire from a SOURCE (sensor or neuron) to a TARGET (neuron E/I, motor E/I,
   * or a meter). sign is +1 (E) / -1 (I) and is ignored by meters. Meters hold
   * exactly ONE wire, so a new wire replaces whatever was there. */
  /* port: for a NEURON it is the sign (+1 excite / -1 inhibit); for a MOTOR it is
   * the direction 'fwd' | 'rev'; meters ignore it. */
  connect(srcId, targetId, port = +1, color = 'blue') {
    const t = this._target(targetId);
    if (!t || srcId === targetId) return;
    if (!WIRE_WEIGHT[color]) color = 'blue';
    if (this._isMeter(targetId)) { t.input = { srcId, color }; return; }
    if (this._isMotor(targetId)) {
      const dir = (port === 'rev' || port === -1) ? 'rev' : 'fwd';
      // a source occupies one slot per motor: drop it from both banks first
      t.fwd = t.fwd.filter(i => i.srcId !== srcId);
      t.rev = t.rev.filter(i => i.srcId !== srcId);
      if (t[dir].length < MOTOR_SLOTS) t[dir].push({ srcId, color });
      return;
    }
    // A neuron may only be driven by sensors (keeps evaluation feed-forward).
    if (this._isNeuron(targetId) && this._isNeuron(srcId)) return;
    t.inputs = t.inputs.filter(i => i.srcId !== srcId);
    t.inputs.push({ srcId, sign: port, color });
  }
  disconnect(srcId, targetId) {
    const t = this._target(targetId);
    if (!t) return;
    if (this._isMeter(targetId)) { if (t.input && t.input.srcId === srcId) t.input = null; return; }
    if (this._isMotor(targetId)) {
      t.fwd = t.fwd.filter(i => i.srcId !== srcId);
      t.rev = t.rev.filter(i => i.srcId !== srcId);
      return;
    }
    t.inputs = t.inputs.filter(i => i.srcId !== srcId);
  }
  /* Cycle a wire's colour blue -> green -> red -> blue (weight 1 -> 2 -> 3). */
  cycleWireColor(srcId, targetId) {
    const t = this._target(targetId);
    if (!t) return;
    const wire = this._isMeter(targetId)
      ? (t.input && t.input.srcId === srcId ? t.input : null)
      : this._isMotor(targetId)
        ? (t.fwd.find(i => i.srcId === srcId) || t.rev.find(i => i.srcId === srcId))
        : t.inputs.find(i => i.srcId === srcId);
    if (!wire) return;
    const idx = WIRE_COLORS.indexOf(wire.color);
    wire.color = WIRE_COLORS[(idx + 1) % WIRE_COLORS.length];
  }
  /* Sever wiring. By default the NEURONS THEMSELVES SURVIVE, keeping their
   * biases — a preset should rewire the vehicle without throwing away neurons
   * the player added, so you can add neurons, switch preset, and watch the same
   * neurons shape the new behaviour. Meter wiring is instrumentation (display
   * only, no effect on behaviour) so it survives too unless asked otherwise. */
  clearWiring({ removeNeurons = false, resetNeuronBias = false,
                clearMeters = false, resetBias = true } = {}) {
    if (removeNeurons) this.neurons = [];
    for (const n of this.neurons) { n.inputs = []; if (resetNeuronBias) n.bias = 0; }
    for (const m of this.motors) { m.fwd = []; m.rev = []; }
    if (clearMeters) for (const mt of this.meters) mt.input = null;
    if (resetBias) this.bias = 0;
    this._pruneDeadInputs();
  }

  toJSON() {
    return {
      loadout:  { ...this.loadout },
      channels: { ...this.channels },
      sensors:  this.sensors.map(s => ({ ...s })),
      bias:     this.bias,
      neurons:  this.neurons.map(n => ({
        id: n.id, bias: n.bias, inputs: n.inputs.map(i => ({ ...i })),
      })),
      meters:   this.meters.map(m => ({ id: m.id, input: m.input ? { ...m.input } : null })),
      motors:   this.motors.map(m => ({ id: m.id,
                    fwd: m.fwd.map(i => ({ ...i })), rev: m.rev.map(i => ({ ...i })) })),
    };
  }
  loadJSON(data) {
    if (data.loadout)  this.loadout  = { ...this.loadout,  ...data.loadout };
    if (data.channels) this.channels = { ...this.channels, ...data.channels };
    if (data.loadout || data.channels) this._rebuildSensors();
    if (typeof data.bias === 'number') this.bias = clamp(data.bias, -1, 1);
    if (data.neurons) {
      this.neurons = data.neurons.slice(0, MAX_NEURONS).map(nd => ({
        id: nd.id, bias: nd.bias || 0,
        inputs: (nd.inputs || []).map(i => ({ color: 'blue', ...i })),
      }));
    }
    if (data.meters) {
      for (const md of data.meters) {
        const mt = this.meters.find(m => m.id === md.id);
        if (mt) mt.input = md.input ? { color: 'blue', ...md.input } : null;
      }
    }
    if (data.motors) {
      for (const md of data.motors) {
        const m = this.motors.find(m => m.id === md.id);
        if (m) {
          m.fwd = (md.fwd || []).slice(0, MOTOR_SLOTS).map(i => ({ color: 'blue', ...i }));
          m.rev = (md.rev || []).slice(0, MOTOR_SLOTS).map(i => ({ color: 'blue', ...i }));
        }
      }
    }
    this._pruneDeadInputs();
  }
}
