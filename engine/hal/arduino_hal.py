"""
engine/hal/arduino_hal.py
--------------------------
Mocked Arduino HAL.

Provides the Arduino C++ API surface as Python callables injected into the
sketch's namespace.  The sketch is transpiled from .ino to Python on load,
then setup() is called once and loop() is called every simulation tick.

Key design decisions
--------------------
* delay() is NON-BLOCKING.  A call to delay(ms) records a resume timestamp
  and returns immediately.  Subsequent loop() calls are suppressed until the
  timer expires, perfectly replicating the blocking behaviour without
  freezing the physics engine or renderer.
* millis() uses wall-clock time (real-time faithful per spec).
* Pin reads/writes are dispatched through a pin-map supplied by the
  simulation layer so the HAL never touches real hardware.
* The transpiler handles the most common C++ → Python patterns found in
  this codebase.  It is intentionally minimal — just enough to run the
  EthologyRobot sketch family.
"""

from __future__ import annotations

import re
import time
import math
import logging
from typing import Callable, Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Transpiler  (C++ .ino → Python)
# ---------------------------------------------------------------------------

class SketchTranspiler:
    """
    Lightweight regex-based C++ → Python transpiler.
    Handles the patterns present in ethologyPrototypeV2 and its class tree.
    """

    # Ordered list of (pattern, replacement) applied in sequence
    _RULES: list[tuple[str, str]] = [
        # Remove #include, #pragma, #ifndef, #define, #endif
        (r'^\s*#(include|pragma|ifndef|define|endif|ifdef|else)[^\n]*\n?', ''),

        # constexpr uint8_t FOO = val  →  FOO = val
        (r'\bconstexpr\s+\S+\s+(\w+)\s*=\s*([^;]+);', r'\1 = \2'),

        # const <type> FOO = val  →  FOO = val
        (r'\bconst\s+\S+\s+(\w+)\s*=\s*([^;]+);', r'\1 = \2'),

        # Typed declarations with initialisation  (int x = 5;)
        (r'\b(?:int|float|double|bool|uint8_t|uint16_t|uint32_t|int8_t|'
         r'int16_t|int32_t|unsigned\s+long|unsigned\s+int|long|byte|'
         r'String|boolean)\s+(\w+)\s*=\s*([^;]+);',
         r'\1 = \2'),

        # Typed declarations without initialisation (int x;) → x = None
        (r'\b(?:int|float|double|bool|uint8_t|uint16_t|uint32_t|int8_t|'
         r'int16_t|int32_t|unsigned\s+long|unsigned\s+int|long|byte|'
         r'String|boolean)\s+(\w+)\s*;',
         r'\1 = None'),

        # Typed declaration with constructor init: "Type var = Type(args);"
        (r'^(\s*)[A-Z]\w*\s+(\w+)\s*=\s*([A-Z]\w*\s*\([^)]*\))\s*;', r'\1\2 = \3'),
        # Bare class instance declarations with args: "ClassName varName(args);"
        (r'^(\s*)([A-Z][\w:<>*&]+)\s+(\w+)\s*\(([^)]*)\)\s*;', r'\1\3 = \2(\4)'),
        # Bare class instance declarations no args: "ClassName varName;"
        (r'^(\s*)([A-Z]\w+)\s+(\w+)\s*;', r'\1\3 = \2()'),

        # void funcname() → def funcname()  (handles setup, loop, hierarchy, etc.)
        (r'\bvoid\s+(\w+)\s*\(\s*\)', r'def \1()'),

        # Serial.begin(...) → pass
        (r'Serial\.begin\s*\([^)]*\)\s*;', 'pass  # Serial.begin'),

        # Serial.print / Serial.println → print()
        # Use (.+) not ([^)]*) to handle nested parens like getRawData()
        (r'Serial\.println\s*\((.+)\)\s*;', r'print(\1)'),
        (r'Serial\.print\s*\((.+)\)\s*;', r'print(\1, end="")'),

        # Remove C++ type casts  (int)x → int(x)  handled separately
        # (unsigned long) cast
        (r'\(unsigned\s+long\)', ''),

        # C++ logical operators → Python
        (r'\|\|', 'or'),
        (r'&&', 'and'),
        (r'\!(?!=)', 'not '),

        # true/false → True/False
        (r'\btrue\b', 'True'),
        (r'\bfalse\b', 'False'),

        # nullptr → None
        (r'\bnullptr\b', 'None'),

        # Remove semicolons at end of lines
        (r';(\s*(?:#[^\n]*)?)$', r'\1'),

        # C++ // comments are already Python comments — leave them.

        # Braces: opening brace on same or next line → colon + remove brace
        # We do this with a post-pass in _remove_braces()
    ]

    @classmethod
    def transpile(cls, source: str) -> str:
        # Normalise line endings (Windows CRLF -> LF) before any processing
        code = source.replace('\r\n', '\n').replace('\r', '\n')

        # Apply regex rules
        for pattern, repl in cls._RULES:
            code = re.sub(pattern, repl, code, flags=re.MULTILINE)

        # Remove C-style block comments /* ... */
        code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)

        # Remove C++ line comments // ...
        # Must be done AFTER block comments and BEFORE brace removal
        code = re.sub(r'//[^\n]*', '', code)

        # Brace removal and indentation
        code = cls._remove_braces(code)

        # Fix else/else-if (they need to be de-indented one level after })
        code = cls._fix_else(code)

        return code

    @classmethod
    def _remove_braces(cls, code: str) -> str:
        """
        Convert C-style brace blocks to Python-style indented blocks.

        Key rules:
        - '}' decreases indent BEFORE the line is emitted
        - '{' increases indent AFTER the line is emitted
        - else/elif on a bare line (no braces): must be at the SAME level
          as the preceding if.  After the closing '}' already decreased
          indent by 1, a bare else would emit at the right level — BUT if
          the C++ was:   }\n  else {   (else on its own line, no brace on
          same line as }), the } already decreased indent, and else emits
          correctly.  If else has no braces at all on its line we need to
          emit at current indent (already decreased by the preceding }).
        """
        # Pre-process: split "} else {" onto separate logical lines
        # so closing brace, else keyword, and opening brace are handled
        # independently by the indent tracker.
        code = re.sub(r'\}\s*else\s*\{', '}\nelse {\n', code)
        code = re.sub(r'\}\s*else\s*if\s*\(', '}\nelif (', code)

        lines_in = code.split('\n')
        lines_out: list[str] = []
        indent = 0
        indent_str = '    '
        prev_was_close = False   # track if previous non-empty line closed a block

        for raw_line in lines_in:
            line = raw_line.rstrip()

            open_count  = line.count('{')
            close_count = line.count('}')

            clean = line.replace('{', '').replace('}', '').rstrip()
            stripped = clean.strip()

            # Decrease indent for closing braces BEFORE emitting
            if close_count > open_count:
                indent = max(0, indent - (close_count - open_count))

            if stripped:
                is_else_elif = bool(re.match(r'^(else\b|elif\b)', stripped))

                # A bare else/elif (no braces on this line) after a closing brace:
                # the } already decreased indent, so else should emit at current
                # indent (which is now correct — same as the if level).
                # But a bare else with NO preceding } on previous line needs
                # to go back one level.
                if is_else_elif and open_count == 0 and close_count == 0 and not prev_was_close:
                    emit_indent = max(0, indent - 1)
                else:
                    emit_indent = indent

                needs_colon = (
                    re.match(r'^(def |if |elif |else|for |while |class )', stripped)
                    and not stripped.endswith(':')
                    and not stripped.endswith(',')
                )
                if needs_colon:
                    clean = clean.rstrip() + ':'
                lines_out.append(indent_str * emit_indent + clean.strip())
                prev_was_close = close_count > open_count

            # Increase indent for opening braces AFTER emitting
            if open_count > close_count:
                indent += (open_count - close_count)

        return '\n'.join(lines_out)

    @classmethod
    def _fix_else(cls, code: str) -> str:
        """Ensure else/elif lines are at the same indent as their if."""
        # This is handled naturally by _remove_braces since } decreases indent
        # before else is emitted.  No extra work needed.
        return code


# ---------------------------------------------------------------------------
# TimedAction  — non-blocking delay emulation
# ---------------------------------------------------------------------------

class TimedAction:
    """Tracks a non-blocking timed motor command."""

    def __init__(self):
        self._end_time: float = 0.0  # wall-clock seconds

    def start(self, duration_seconds: float) -> None:
        if duration_seconds > 0:
            self._end_time = time.monotonic() + duration_seconds

    def is_active(self) -> bool:
        return time.monotonic() < self._end_time

    def cancel(self) -> None:
        self._end_time = 0.0


# ---------------------------------------------------------------------------
# Arduino HAL
# ---------------------------------------------------------------------------

class ArduinoHAL:
    """
    Provides the Arduino API surface to a loaded sketch namespace.

    Pin reads/writes are dispatched to callbacks registered by the simulation:
        read_pin(pin: int|str)  → int/float
        write_pin(pin: int|str, value: int|float) → None

    Motor output is extracted by reading pin values set via write_pin
    on the motor pins declared in robot config.
    """

    def __init__(self,
                 read_callback: Callable[[Any], float],
                 write_callback: Callable[[Any, float], None]):
        self._read_pin  = read_callback
        self._write_pin = write_callback

        self._start_time = time.monotonic()
        self._timed_action = TimedAction()

        # Sketch namespace populated by load_sketch()
        self._namespace: dict[str, Any] = {}
        self._setup_fn: Callable | None = None
        self._loop_fn:  Callable | None = None
        self._sketch_loaded = False

    # ------------------------------------------------------------------
    # Sketch loading
    # ------------------------------------------------------------------

    def load_sketch(self, sketch_path: str) -> None:
        """Load and transpile a .ino file, then exec it into our namespace."""
        with open(sketch_path, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
        # Normalise line endings (handles Windows CRLF files)
        source = source.replace("\r\n", "\n").replace("\r", "\n")

        python_code = SketchTranspiler.transpile(source)
        logger.debug("Transpiled sketch:\n%s", python_code)

        # Build the namespace with all Arduino API functions
        ns = self._build_namespace()
        try:
            exec(compile(python_code, sketch_path, 'exec'), ns)
        except Exception as e:
            logger.error("Error executing transpiled sketch: %s", e)
            logger.error("Transpiled code was:\n%s", python_code)
            raise

        self._namespace = ns
        self._setup_fn = ns.get("setup")
        self._loop_fn  = ns.get("loop")
        self._sketch_loaded = True
        logger.info("Sketch loaded from %s", sketch_path)

    def load_sketch_from_ino_source(self, ino_source: str,
                                    label: str = "<target>") -> None:
        """Transpile and load a .ino source string — never touches disk."""
        source = ino_source.replace("\r\n", "\n").replace("\r", "\n")
        python_code = SketchTranspiler.transpile(source)
        logger.debug("Transpiled in-memory sketch:\n%s", python_code)
        ns = self._build_namespace()
        try:
            exec(compile(python_code, label, 'exec'), ns)
        except Exception as e:
            logger.error("Error executing transpiled sketch %s: %s", label, e)
            logger.error("Transpiled code:\n%s", python_code)
            raise
        self._namespace = ns
        self._setup_fn  = ns.get("setup")
        self._loop_fn   = ns.get("loop")
        self._sketch_loaded = True

    def load_sketch_from_source(self, python_source: str,
                                label: str = "<sketch>") -> None:
        """Load already-transpiled Python source (for testing)."""
        ns = self._build_namespace()
        exec(compile(python_source, label, 'exec'), ns)
        self._namespace = ns
        self._setup_fn = ns.get("setup")
        self._loop_fn  = ns.get("loop")
        self._sketch_loaded = True

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def call_setup(self) -> None:
        if self._setup_fn:
            try:
                self._setup_fn()
            except Exception as e:
                logger.error("setup() raised: %s", e)

    def call_loop(self) -> None:
        """
        Call loop() unless a timed action is still active (emulating delay).
        """
        if not self._loop_fn:
            return
        if self._timed_action.is_active():
            return   # still inside a delay() — skip this tick
        try:
            self._loop_fn()
        except Exception as e:
            logger.error("loop() raised: %s", e)

    # ------------------------------------------------------------------
    # Arduino API — injected into sketch namespace
    # ------------------------------------------------------------------

    def _millis(self) -> int:
        return int((time.monotonic() - self._start_time) * 1000)

    def _micros(self) -> int:
        return int((time.monotonic() - self._start_time) * 1_000_000)

    def _delay(self, ms: float) -> None:
        """Non-blocking delay: records resume time, returns immediately."""
        self._timed_action.start(ms / 1000.0)

    def _delay_microseconds(self, us: float) -> None:
        self._timed_action.start(us / 1_000_000.0)

    def _pin_mode(self, pin, mode) -> None:
        pass  # No-op in simulation

    def _digital_write(self, pin, value) -> None:
        self._write_pin(pin, value)

    def _digital_read(self, pin) -> int:
        return int(self._read_pin(pin))

    def _analog_write(self, pin, value) -> None:
        self._write_pin(pin, value)

    def _analog_read(self, pin) -> int:
        return int(self._read_pin(pin))

    @staticmethod
    def _map(value, in_min, in_max, out_min, out_max) -> float:
        if in_max == in_min:
            return out_min
        return (value - in_min) * (out_max - out_min) / (in_max - in_min) + out_min

    @staticmethod
    def _constrain(value, lo, hi):
        return max(lo, min(hi, value))

    @staticmethod
    def _abs(x):
        return abs(x)

    @staticmethod
    def _sqrt(x):
        return math.sqrt(x)

    @staticmethod
    def _min(a, b):
        return min(a, b)

    @staticmethod
    def _max(a, b):
        return max(a, b)

    # ------------------------------------------------------------------
    # Serial (stub — prints to Python stdout / logger)
    # ------------------------------------------------------------------

    class _Serial:
        @staticmethod
        def begin(baud: int) -> None:
            pass

        @staticmethod
        def print(value, *args) -> None:
            logger.debug("[Serial] %s", value)

        @staticmethod
        def println(value="", *args) -> None:
            logger.debug("[Serial] %s", value)

        @staticmethod
        def available() -> int:
            return 0

        @staticmethod
        def read() -> int:
            return -1

    # ------------------------------------------------------------------
    # Namespace builder
    # ------------------------------------------------------------------

    def _build_namespace(self) -> dict[str, Any]:
        """Return a dict that serves as the sketch's global namespace."""
        from engine.hal.sketch_bridge import SketchBridge
        bridge_names = SketchBridge.install(self)

        # Pin mode constants
        INPUT        = 0
        OUTPUT       = 1
        INPUT_PULLUP = 2
        HIGH         = 1
        LOW          = 0
        A0, A1, A2, A3, A4, A5 = 0, 1, 2, 3, 4, 5

        ns: dict[str, Any] = {**bridge_names, **{
            # Constants
            "INPUT":        INPUT,
            "OUTPUT":       OUTPUT,
            "INPUT_PULLUP": INPUT_PULLUP,
            "HIGH":         HIGH,
            "LOW":          LOW,
            "A0": A0, "A1": A1, "A2": A2,
            "A3": A3, "A4": A4, "A5": A5,
            "True": True, "False": False,
            "None": None,

            # Core functions
            "millis":            self._millis,
            "micros":            self._micros,
            "delay":             self._delay,
            "delayMicroseconds": self._delay_microseconds,
            "pinMode":           self._pin_mode,
            "digitalWrite":      self._digital_write,
            "digitalRead":       self._digital_read,
            "analogWrite":       self._analog_write,
            "analogRead":        self._analog_read,
            "map":               self._map,
            "constrain":         self._constrain,
            "abs":               self._abs,
            "sqrt":              self._sqrt,
            "min":               self._min,
            "max":               self._max,

            # Serial stub
            "Serial": self._Serial(),

            # Python builtins needed inside sketch
            "print": print,
            "int":   int,
            "float": float,
            "str":   str,
            "bool":  bool,
            "range": range,
            "len":   len,
        }}
        return ns
