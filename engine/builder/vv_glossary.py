"""
engine/builder/vv_glossary.py
-----------------------------
Valentino's Vehicles wiring-concept glossary content (FW-001 MVP).

Definitions are seeded from PAW-Bot's circuit-board tour script
(scripts/paw_bot/circuit_tour.txt) and the candidate term list. They are written
for the wiring-editor context specifically — e.g. "input" and "output" have
common meanings, but here they're defined as they apply to a neuron on this
board. Refine the wording freely; this module is the single place to edit.

Numbers follow the Field-Trip "Term(n)" highlight convention so the same tokens
can be accent-highlighted in narration/tour text and cross-referenced here.

FUTURE (FW-001): unlock state — show a term only once introduced. The MVP lists
all terms (flat unlock). When unlock-gating lands, filter this list by a seen-set
before constructing the Glossary; the entries themselves don't change.
"""
from engine.glossary import Glossary, GlossaryEntry


_VV_TERMS = [
    (1, "circuit board",
     "The board that wires the robot's senses to its motors. Signals enter at "
     "the sensor pins, flow through neurons you wire up, and leave at the motor "
     "pins to drive the wheels."),
    (2, "sensor",
     "A pin that brings the outside world into the circuit board — light "
     "levels, distances — as an electrical signal the circuit can work with."),
    (3, "motor",
     "A pin that drives a wheel. Whatever signal you route to a motor pin "
     "becomes movement — this is where the circuit's decisions become action."),
    (4, "neuron",
     "A triangle on the board that gathers the signals wired into it, combines "
     "them, and produces a single output. A neuron changes the robot's "
     "'perception' of the world, which in turn shapes the action its motors "
     "take."),
    (5, "input",
     "A pin where a signal ENTERS a neuron. A neuron has several inputs; it adds "
     "them together. Inputs come in two kinds — excitatory and inhibitory."),
    (6, "excitatory",
     "An excitatory (E, green) input pushes a neuron's output UP. Electrically, "
     "it adds current that drives the output higher."),
    (7, "inhibitory",
     "An inhibitory (I, red) input pushes a neuron's output DOWN. Electrically, "
     "it pulls current away, lowering the output."),
    (8, "potentiometer",
     "The knob inside a neuron's triangle — a small dial that sets the neuron's "
     "bias. On the real robot it's a blue trim pot you turn with a screwdriver."),
    (9, "bias",
     "A neuron's resting level, set by its potentiometer, before any input "
     "arrives. Negative bias makes excitatory inputs less effective; positive "
     "bias makes inhibitory inputs less effective."),
    (10, "output",
     "A pin where a neuron's result LEAVES it, to be wired onward (to a motor, "
     "a meter, or another neuron). Each neuron has two: a normal output (N) and "
     "a threshold output (T)."),
    (11, "threshold",
     "The threshold output (T) tells the neuron: don't fire unless the sum of "
     "the inputs is positive. It delays action until enough signal builds up — "
     "unlike the normal output (N), which fires immediately."),
    (12, "meter",
     "A display with a single header pin that shows one signal — a sensor "
     "reading or a neuron's output. There are three. To see anything richer "
     "than one raw sensor, route signals through a neuron and meter its output."),
]


def make_vv_glossary() -> Glossary:
    entries = [GlossaryEntry(term, definition, number=n)
               for (n, term, definition) in _VV_TERMS]
    return Glossary("Wiring Glossary", entries)
