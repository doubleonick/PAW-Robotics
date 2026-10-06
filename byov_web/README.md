# BYOV — Build Your Own Vehicle (web)

A browser-based Braitenberg-vehicle simulator and digital twin of the physical
PAW lab AnaBBot. Sensors model real directionality (cone of operation), unlike
BugWorks' omnidirectional approximation.

## Two screens (toggle in the header)
- **Build robot** — the rectangular AnaBBot drawn top-down (motors on the sides,
  sensors at the front). Overlaid wiring editor: by DEFAULT you drag a wire from
  a front sensor straight to a motor's FORWARD or REVERSE bank (four sockets
  each, like the board's FL/BL and FR/BR) — no neurons involved. Motors have no
  excite/inhibit: you choose a direction, and a reverse wire subtracts from
  forward, exactly as (FL - BL) in engine/vehicle.py. Wire COLOUR is WEIGHT (blue 1x, green 2x, red 3x), matching
  the physical board and engine/signals.py; excite vs inhibit comes from which
  input the wire lands on. Meters M1/M2/M3 are permanently installed, take one
  wire each and are display only. One shared pot between the motors sets a
  resting speed. Neurons are OPTIONAL: the +/- buttons beside the robot add and
  remove them (up to 6, LIFO), laid out 3 rows of 2 like the board.

## Run it
Hosted: open the GitHub Pages link for this repo. (Must be served over http —
ES modules are blocked over file://. Locally: `python3 -m http.server` then open
http://localhost:8000 .)

## Files
- index.html / style.css — two-screen UI
- sim.js         — physics: differential drive + DIRECTIONAL sensors (core)
- vehicle.js     — body, front mounts, optional neurons, meters, weighted wiring
- editor_view.js — Screen 1: robot + wiring editor (drag-to-connect)
- arena.js       — world, grid editing, canvas rendering
- app.js         — screen toggle, tools, run loop, presets, record/export
