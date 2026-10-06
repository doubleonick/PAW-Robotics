"""
engine/professor.py
---------------------
Professor Ray Kensington — procedurally drawn portrait.

Based on reference sketch: three-quarter view, wide expressive eyes,
full beard, prominent nose, open mid-speech smile, red tie, elbow patch
on extended right arm. Golden-brown hair receding at top.

draw_ray(surf, x, y, h, theme) draws Ray with bottom-left at (x,y),
height h, width = h * 2/3.
"""

import pygame
import math
import re

# Narration keyword markup:
#   *term*(n)   -> highlight the term in accent colour (no footnote)
#   <term>(n)   -> highlight AND show definition (n) as a page footnote
# 'term' may be multiple words. The (n) is optional but conventional.
_KW_HILITE_RE = re.compile(r'\*([^*]+?)\*(?:\((\d+)\))?')
_KW_FOOT_RE   = re.compile(r'<([^>]+?)>(?:\((\d+)\))?')

def _parse_keywords(text: str):
    """Convert a page string with *..*(n) / <..>(n) markup into:
      - display tokens: list of (word, is_keyword)
      - footnotes: ordered list of footnote numbers referenced via <..>
    Delimiters are stripped; the (n) is kept appended to the term so the
    reader sees 'Seek(2)'. Multi-word terms become multiple keyword tokens."""
    footnotes: list[int] = []
    # Build a clean string with markers removed, tracking which spans are
    # keywords. We do it by replacing matches with sentinels, then tokenising.
    spans = []  # (start, end, text_with_number)
    def _hilite_sub(m):
        term = m.group(1).strip()
        num  = m.group(2)
        return term + (f"({num})" if num else ""), False
    # We can't easily carry color through a plain string, so tokenise directly.
    tokens = []  # (word, is_keyword)
    i = 0
    # Combined scan: find the next * or < markup, whichever comes first.
    pattern = re.compile(r'\*([^*]+?)\*(?:\((\d+)\))?|<([^>]+?)>(?:\((\d+)\))?')
    last = 0
    for m in pattern.finditer(text):
        # plain text before the match
        if m.start() > last:
            for w in text[last:m.start()].split(' '):
                if w != '':
                    tokens.append((w, False))
        if m.group(1) is not None:          # *term*(n) highlight-only
            term, num = m.group(1).strip(), m.group(2)
        else:                                # <term>(n) highlight + footnote
            term, num = m.group(3).strip(), m.group(4)
            if num:
                footnotes.append(int(num))
        disp = term + (f"({num})" if num else "")
        for j, w in enumerate(disp.split(' ')):
            if w != '':
                tokens.append((w, True))
        last = m.end()
    if last < len(text):
        for w in text[last:].split(' '):
            if w != '':
                tokens.append((w, False))
    return tokens, footnotes

# Legacy single-word term token (kept for the simple highlight path).
_TERM_RE = re.compile(r'[A-Za-z][\w\-]*\(\d+\)[.,!?;:]?')


def _theme_colors(theme: str) -> dict:
    if theme == "lcars":
        return dict(
            outline=(255, 153, 0), skin=(20, 10, 40),
            hair=(255, 153, 0), beard=(204, 102, 0),
            shirt=(30, 50, 120), jacket=(20, 30, 80),
            patch=(255, 200, 60), tie=(204, 51, 51),
            trousers=(20, 30, 80), teeth=(255, 239, 179),
            lw_factor=1.0,
        )
    elif theme == "blueprint":
        return dict(
            outline=(220, 240, 255), skin=(12, 26, 72),
            hair=(255, 220, 80), beard=(180, 160, 60),
            shirt=(240, 248, 255), jacket=(80, 130, 220),
            patch=(255, 220, 80), tie=(255, 80, 80),
            trousers=(80, 130, 220), teeth=(240, 248, 255),
            lw_factor=1.0,
        )
    elif theme == "sixteenbit":
        return dict(
            outline=(0, 0, 16), skin=(255, 200, 160),
            hair=(160, 110, 20), beard=(140, 95, 18),
            shirt=(240, 240, 240), jacket=(120, 120, 130),
            patch=(200, 160, 30), tie=(180, 30, 30),
            trousers=(100, 100, 110), teeth=(255, 255, 200),
            lw_factor=1.5,
        )
    else:  # phosphor
        return dict(
            outline=(51, 255, 87), skin=(15, 40, 20),
            hair=(80, 200, 90), beard=(60, 160, 70),
            shirt=(35, 80, 40), jacket=(20, 60, 25),
            patch=(120, 220, 100), tie=(160, 50, 50),
            trousers=(18, 50, 22), teeth=(180, 255, 180),
            lw_factor=1.0,
        )


def draw_ray(surf: pygame.Surface,
             x: int, y: int, h: int,
             theme: str = "phosphor") -> None:
    """Draw Ray with bottom-left at (x, y), height h, width h*2/3."""
    w = h * 2 // 3
    C = _theme_colors(theme)

    def lw(f=1.0):
        return max(1, int(h / 90 * f * C["lw_factor"]))

    def px(fx): return x + int(w * fx)
    def py(fy): return y + int(h * fy)
    def sc(f):  return max(1, int(h * f))

    ol  = C["outline"]
    sk  = C["skin"]
    hr  = C["hair"]
    br  = C["beard"]
    sh  = C["shirt"]
    jk  = C["jacket"]
    pt  = C["patch"]
    ti  = C["tie"]
    tr  = C["trousers"]
    te  = C["teeth"]

    # ── Body ──────────────────────────────────────────────────────────────────

    # Trousers / legs (lower third)
    pygame.draw.polygon(surf, tr, [
        (px(0.20), py(0.65)),
        (px(0.80), py(0.65)),
        (px(0.75), py(1.00)),
        (px(0.58), py(1.00)),
        (px(0.50), py(0.83)),
        (px(0.42), py(1.00)),
        (px(0.25), py(1.00)),
    ])
    pygame.draw.polygon(surf, ol, [
        (px(0.20), py(0.65)),
        (px(0.80), py(0.65)),
        (px(0.75), py(1.00)),
        (px(0.58), py(1.00)),
        (px(0.50), py(0.83)),
        (px(0.42), py(1.00)),
        (px(0.25), py(1.00)),
    ], lw(1))

    # Jacket body — slightly asymmetric (3/4 view)
    pygame.draw.polygon(surf, jk, [
        (px(0.15), py(0.33)),
        (px(0.85), py(0.30)),
        (px(0.82), py(0.65)),
        (px(0.18), py(0.65)),
    ])

    # Shirt visible strip
    pygame.draw.polygon(surf, sh, [
        (px(0.42), py(0.34)),
        (px(0.60), py(0.34)),
        (px(0.63), py(0.65)),
        (px(0.38), py(0.65)),
    ])

    # Tie — wide red, prominent
    pygame.draw.polygon(surf, ti, [
        (px(0.44), py(0.36)),
        (px(0.58), py(0.36)),
        (px(0.62), py(0.58)),
        (px(0.50), py(0.64)),
        (px(0.38), py(0.58)),
    ])
    # Tie knot
    pygame.draw.ellipse(surf, ti,
        pygame.Rect(px(0.44), py(0.34), sc(0.14), sc(0.05)))
    # Tie outline
    pygame.draw.polygon(surf, ol, [
        (px(0.44), py(0.36)),
        (px(0.58), py(0.36)),
        (px(0.62), py(0.58)),
        (px(0.50), py(0.64)),
        (px(0.38), py(0.58)),
    ], lw(1))

    # Left lapel
    pygame.draw.polygon(surf, jk, [
        (px(0.15), py(0.33)),
        (px(0.44), py(0.36)),
        (px(0.38), py(0.65)),
        (px(0.18), py(0.65)),
    ])
    # Right lapel (3/4 view — narrower)
    pygame.draw.polygon(surf, jk, [
        (px(0.85), py(0.30)),
        (px(0.58), py(0.36)),
        (px(0.63), py(0.65)),
        (px(0.82), py(0.65)),
    ])

    # Jacket outline
    pygame.draw.polygon(surf, ol, [
        (px(0.15), py(0.33)),
        (px(0.85), py(0.30)),
        (px(0.82), py(0.65)),
        (px(0.18), py(0.65)),
    ], lw(1))

    # Left arm — hanging, slight forward angle
    pygame.draw.line(surf, jk,
        (px(0.15), py(0.33)), (px(0.08), py(0.55)), sc(0.09))
    pygame.draw.line(surf, jk,
        (px(0.08), py(0.55)), (px(0.10), py(0.68)), sc(0.08))
    pygame.draw.line(surf, ol,
        (px(0.15), py(0.33)), (px(0.08), py(0.55)), lw(1))
    pygame.draw.line(surf, ol,
        (px(0.08), py(0.55)), (px(0.10), py(0.68)), lw(1))
    # Left hand
    pygame.draw.ellipse(surf, sk,
        pygame.Rect(px(0.06), py(0.67), sc(0.09), sc(0.07)))

    # Right arm — extended forward and slightly raised (gesture)
    r_shoulder = (px(0.85), py(0.30))
    r_elbow    = (px(0.95), py(0.43))
    r_wrist    = (px(0.88), py(0.33))
    pygame.draw.line(surf, jk, r_shoulder, r_elbow, sc(0.09))
    pygame.draw.line(surf, jk, r_elbow, r_wrist, sc(0.08))
    pygame.draw.line(surf, ol, r_shoulder, r_elbow, lw(1))
    pygame.draw.line(surf, ol, r_elbow, r_wrist, lw(1))

    # Elbow patch — golden oval on right arm
    ep_cx = (r_shoulder[0] + r_elbow[0]) // 2 + sc(0.02)
    ep_cy = (r_shoulder[1] + r_elbow[1]) // 2
    pygame.draw.ellipse(surf, pt,
        pygame.Rect(ep_cx - sc(0.06), ep_cy - sc(0.04),
                    sc(0.12), sc(0.08)))
    pygame.draw.ellipse(surf, ol,
        pygame.Rect(ep_cx - sc(0.06), ep_cy - sc(0.04),
                    sc(0.12), sc(0.08)), lw(1))
    # Stitch lines on patch
    for i in range(3):
        sy = ep_cy - sc(0.025) + i * sc(0.025)
        pygame.draw.line(surf, ol,
            (ep_cx - sc(0.04), sy), (ep_cx + sc(0.04), sy), lw(0.5))

    # Right hand — open, relaxed, palm forward
    hx, hy = r_wrist[0] + sc(0.02), r_wrist[1] - sc(0.03)
    pygame.draw.ellipse(surf, sk,
        pygame.Rect(hx - sc(0.07), hy - sc(0.05), sc(0.11), sc(0.09)))
    pygame.draw.ellipse(surf, ol,
        pygame.Rect(hx - sc(0.07), hy - sc(0.05), sc(0.11), sc(0.09)), lw(1))
    # Fingers
    for fdx, fdy in [(-0.06,-0.07),(-0.02,-0.09),(0.02,-0.09),(0.05,-0.07)]:
        pygame.draw.line(surf, sk,
            (hx + sc(fdx*0.4), hy - sc(0.02)),
            (hx + sc(fdx),     hy + sc(fdy)), lw(1.2))
        pygame.draw.line(surf, ol,
            (hx + sc(fdx*0.4), hy - sc(0.02)),
            (hx + sc(fdx),     hy + sc(fdy)), lw(0.7))
    # Thumb
    pygame.draw.line(surf, sk,
        (hx - sc(0.05), hy + sc(0.01)),
        (hx - sc(0.09), hy - sc(0.04)), lw(1.2))
    pygame.draw.line(surf, ol,
        (hx - sc(0.05), hy + sc(0.01)),
        (hx - sc(0.09), hy - sc(0.04)), lw(0.7))

    # ── Head ──────────────────────────────────────────────────────────────────
    # Neck
    pygame.draw.rect(surf, sk,
        pygame.Rect(px(0.43), py(0.23), sc(0.14), sc(0.08)))

    # Collar
    pygame.draw.polygon(surf, sh, [
        (px(0.43), py(0.24)),
        (px(0.50), py(0.30)),
        (px(0.57), py(0.24)),
    ])
    pygame.draw.polygon(surf, ol, [
        (px(0.43), py(0.24)),
        (px(0.50), py(0.30)),
        (px(0.57), py(0.24)),
    ], lw(1))

    # Head — wider than tall, slightly squared at jaw
    head_cx = px(0.50)
    head_cy = py(0.13)
    head_rx = sc(0.20)  # wider
    head_ry = sc(0.16)  # not as tall
    head_rect = pygame.Rect(head_cx - head_rx, head_cy - head_ry,
                            head_rx * 2, head_ry * 2)
    pygame.draw.ellipse(surf, sk, head_rect)
    pygame.draw.ellipse(surf, ol, head_rect, lw(1))

    # Jaw squaring — add some width to lower portion
    jaw_rect = pygame.Rect(head_cx - int(head_rx*0.85), head_cy,
                           int(head_rx*1.70), head_ry)
    pygame.draw.ellipse(surf, sk, jaw_rect)

    # ── Hair ──────────────────────────────────────────────────────────────────
    # Receding — present on sides, sparse/gone at top centre
    # Left side hair (thick)
    for a in range(140, 200, 8):
        rad = math.radians(a)
        sx  = head_cx + int(head_rx * 1.02 * math.cos(rad))
        sy  = head_cy - int(head_ry * 1.02 * math.sin(rad))
        ex  = head_cx + int(head_rx * 1.22 * math.cos(rad))
        ey  = head_cy - int(head_ry * 1.22 * math.sin(rad))
        pygame.draw.line(surf, hr, (sx, sy), (ex, ey), lw(1.5))
    # Right side / back
    for a in range(-20, 40, 8):
        rad = math.radians(a)
        sx  = head_cx + int(head_rx * 1.00 * math.cos(rad))
        sy  = head_cy - int(head_ry * 1.00 * math.sin(rad))
        ex  = head_cx + int(head_rx * 1.18 * math.cos(rad))
        ey  = head_cy - int(head_ry * 1.18 * math.sin(rad))
        pygame.draw.line(surf, hr, (sx, sy), (ex, ey), lw(1.5))
    # Sparse top centre (receding) — just a few strokes
    for a in range(75, 110, 12):
        rad = math.radians(a)
        sx  = head_cx + int(head_rx * 0.80 * math.cos(rad))
        sy  = head_cy - int(head_ry * 0.95 * math.sin(rad))
        ex  = head_cx + int(head_rx * 0.95 * math.cos(rad))
        ey  = head_cy - int(head_ry * 1.08 * math.sin(rad))
        pygame.draw.line(surf, hr, (sx, sy), (ex, ey), lw(1))

    # ── Beard ─────────────────────────────────────────────────────────────────
    # Full beard — covers lower face heavily, hatched strokes
    beard_top_y = head_cy + int(head_ry * 0.20)
    beard_bot_y = head_cy + int(head_ry * 1.40)
    # Base beard shape
    pygame.draw.ellipse(surf, br,
        pygame.Rect(head_cx - int(head_rx * 0.82),
                    beard_top_y,
                    int(head_rx * 1.64),
                    int(head_ry * 1.35)))
    # Hatching strokes for texture
    for i in range(16):
        bx0 = head_cx - int(head_rx * 0.70) + i * sc(0.025)
        by0 = beard_top_y + sc(0.01)
        by1 = min(beard_bot_y, by0 + sc(0.04) + (i % 3) * sc(0.015))
        pygame.draw.line(surf, ol, (bx0, by0), (bx0 + sc(0.01), by1), lw(0.8))

    # Blend upper beard back to skin (keeps cheeks visible)
    cheek_rect = pygame.Rect(head_cx - int(head_rx*0.75), beard_top_y - sc(0.01),
                             int(head_rx*1.50), int(head_ry*0.40))
    pygame.draw.ellipse(surf, sk, cheek_rect)

    # ── Face features ─────────────────────────────────────────────────────────

    # Ear (right, partially visible)
    ear_rect = pygame.Rect(head_cx + head_rx - lw(2), head_cy - sc(0.02),
                           sc(0.06), sc(0.10))
    pygame.draw.ellipse(surf, sk, ear_rect)
    pygame.draw.ellipse(surf, ol, ear_rect, lw(1))

    # Eyebrows — expressive, slightly raised
    for brow_dx, brow_slant in [(-0.12, 2), (0.08, -2)]:
        bx0 = head_cx + sc(brow_dx - 0.06)
        bx1 = head_cx + sc(brow_dx + 0.06)
        by0 = head_cy - sc(0.07)
        pygame.draw.line(surf, ol,
            (bx0, by0 + brow_slant),
            (bx1, by0 - brow_slant), lw(1.5))

    # Eyes — large, wide-open, expressive (slightly bugged)
    for ex_off in [-0.13, 0.10]:
        ecx = head_cx + sc(ex_off)
        ecy = head_cy - sc(0.02)
        er  = sc(0.048)
        # White
        pygame.draw.circle(surf, sk, (ecx, ecy), er)
        pygame.draw.circle(surf, ol, (ecx, ecy), er, lw(1.2))
        # Iris
        pygame.draw.circle(surf, ol, (ecx + lw(1), ecy), int(er * 0.55))
        # Pupil highlight
        pygame.draw.circle(surf, sk,
            (ecx + lw(1) + int(er * 0.15),
             ecy - int(er * 0.15)), max(1, int(er * 0.18)))

    # Nose — long, prominent, slopes slightly right, rounded at tip
    nose_top = (head_cx + sc(0.02), head_cy - sc(0.00))
    nose_bot = (head_cx + sc(0.05), head_cy + sc(0.09))
    pygame.draw.line(surf, ol, nose_top, nose_bot, lw(1))
    # Rounded tip
    pygame.draw.circle(surf, ol, nose_bot, lw(2))
    # Nostril flare
    pygame.draw.arc(surf, ol,
        pygame.Rect(nose_bot[0] - sc(0.04),
                    nose_bot[1] - sc(0.01),
                    sc(0.08), sc(0.025)),
        math.radians(195), math.radians(345), lw(1))

    # Mouth — open, wide smile showing teeth, mid-speech
    mouth_cx = head_cx + sc(0.02)
    mouth_cy = head_cy + sc(0.12)
    mouth_w  = sc(0.11)
    mouth_h  = sc(0.05)
    # Upper lip arc
    pygame.draw.arc(surf, ol,
        pygame.Rect(mouth_cx - mouth_w, mouth_cy - mouth_h,
                    mouth_w * 2, mouth_h * 2),
        math.radians(10), math.radians(170), lw(1.2))
    # Teeth (white/pale fill inside mouth)
    teeth_rect = pygame.Rect(mouth_cx - int(mouth_w * 0.80),
                             mouth_cy - int(mouth_h * 0.3),
                             int(mouth_w * 1.60), int(mouth_h * 1.0))
    pygame.draw.ellipse(surf, te, teeth_rect)
    # Lower lip / chin line
    pygame.draw.arc(surf, ol,
        pygame.Rect(mouth_cx - mouth_w, mouth_cy,
                    mouth_w * 2, int(mouth_h * 1.5)),
        math.radians(190), math.radians(350), lw(1.2))
    # Mouth corners
    pygame.draw.circle(surf, ol, (mouth_cx - mouth_w, mouth_cy), lw(1))
    pygame.draw.circle(surf, ol, (mouth_cx + mouth_w, mouth_cy), lw(1))

    # Moustache (subtle — merges with beard)
    for side, dx in [(-1, -0.04), (1, 0.04)]:
        pygame.draw.arc(surf, br,
            pygame.Rect(mouth_cx + sc(dx) - sc(0.04),
                        mouth_cy - sc(0.055),
                        sc(0.08), sc(0.04)),
            math.radians(180) if side > 0 else math.radians(0),
            math.radians(360) if side > 0 else math.radians(180),
            lw(1.5))


# ── Dialogue system ───────────────────────────────────────────────────────────

import os as _os
SCRIPTS_DIR = _os.path.join(
    _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
    "scripts")

# Speaker name → (folder, color_attr_on_T)
# color_attr_on_T is an attribute name on engine.theme to look up at draw time
SPEAKER_MAP = {
    "PAW-BOT": ("paw_bot", "WHITE_GREEN"),
    "ROBOT A": ("robot_a", "RED_PH"),
    "ROBOT B": ("robot_b", "BLUE_PH"),
    "SYSTEM":  ("system",  "PHOSPHOR"),
}


def _parse_script(text: str) -> list:
    """
    Parse script text into page dicts:
      {"speaker": "PAW-BOT", "text": "...", "pause": False}
    Blank lines separate pages.
    SPEAKER: prefix (e.g. PAW-BOT:, ROBOT A:) sets the speaker for that page.
    [pause] inserts an auto-advance beat.
    """
    pages = []
    for block in text.strip().split("\n\n"):
        block = block.strip()
        if not block:
            continue
        if block.lower().strip() == "[pause]":
            pages.append({"speaker": "", "text": "", "pause": True})
            continue
        # Detect SPEAKER: prefix — check all known speakers first (longest match)
        speaker = ""
        body    = block
        for spk in sorted(SPEAKER_MAP.keys(), key=len, reverse=True):
            prefix = spk + ":"
            if block.upper().startswith(prefix):
                speaker = spk
                body    = block[len(prefix):].strip()
                # Remove any remaining lines that start with the same prefix
                lines = body.split("\n")
                cleaned = []
                for ln in lines:
                    if ln.upper().startswith(prefix):
                        cleaned.append(ln[len(prefix):].strip())
                    else:
                        cleaned.append(ln)
                body = " ".join(cleaned).strip()
                break
        pages.append({"speaker": speaker, "text": body, "pause": False})
    return pages


def load_script(character: str, script_name: str,
                fallback: str = "") -> str:
    """
    Load a script file from scripts/<character>/<script_name>.txt
    Returns raw text, or fallback string if file not found.
    """
    folder = SPEAKER_MAP.get(character.upper(), (character.lower(),))[0]
    path   = _os.path.join(SCRIPTS_DIR, folder, script_name + ".txt")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return fallback


class DialogueBox:
    """
    Pokémon-style typing dialogue box with multi-speaker support.

    Speaker labels are colored by character:
      PAW-BOT → theme WHITE_GREEN
      ROBOT A → theme RED_PH
      ROBOT B → theme BLUE_PH

    Usage:
      dlg = DialogueBox(w, h)
      dlg.load_file("paw_bot", "ethology_intro") # from scripts/paw_bot/
      dlg.load("PAW-BOT: Hello!\\n\\nPAW-BOT: Page two.") # from string
      dlg.update(dt)
      dlg.draw(surf, x, y)
      dlg.advance()   # Space/click
      dlg.skip()      # Escape
    """

    CHARS_PER_SEC = 40

    def __init__(self, w: int, h: int, theme: str = "phosphor",
                 font_size: int | None = None,
                 highlight_terms: bool = False):
        self._w      = w
        self._h      = h
        self._pages: list = []
        self._page   = 0
        self._chars  = 0.0
        self._done   = False
        # When True, tokens of the form "Term(n)" in the body are rendered in
        # the theme accent colour (a generic vocabulary-highlight; the box does
        # not know or care what the terms mean). Off by default so existing
        # callers are unchanged.
        self._highlight_terms = highlight_terms
        # Footnote definitions, keyed by number: {n: "definition text"}. Set via
        # set_glossary(); used to render <term>(n) page footnotes.
        self._glossary: dict[int, str] = {}
        # font_size=None uses the legacy h//5 formula (preserves original behaviour)
        # Pass an explicit font_size to use a fixed size (e.g. 13 for narrative text)
        size = font_size if font_size is not None else max(12, h // 5)
        try:
            self._font = pygame.font.SysFont("couriernew", size)
        except Exception:
            self._font = pygame.font.SysFont("monospace", size)

    def load(self, text: str) -> None:
        self._pages = _parse_script(text)
        self._page  = 0
        self._chars = 0.0
        self._done  = len(self._pages) == 0

    def load_file(self, character: str, script_name: str,
                  fallback: str = "") -> None:
        text = load_script(character, script_name, fallback)
        self.load(text if text else fallback)

    def append_file(self, character: str, script_name: str,
                    fallback: str = "") -> None:
        """Append pages from a script file to current dialogue."""
        text  = load_script(character, script_name, fallback)
        extra = _parse_script(text if text else fallback)
        if self._done:
            self._pages = extra
            self._page  = 0
            self._chars = 0.0
            self._done  = len(extra) == 0
        else:
            self._pages.extend(extra)

    @property
    def is_done(self) -> bool:
        return self._done

    def update(self, dt: float) -> None:
        if self._done or not self._pages:
            return
        page = self._pages[self._page]
        if page.get("pause"):
            # Auto-advance after 0.8s — reuse chars as a timer
            self._chars += dt
            if self._chars >= 0.8:
                self._advance_page()
            return
        self._chars = min(len(page["text"]),
                          self._chars + self.CHARS_PER_SEC * dt)

    def current_text(self) -> str:
        """Return the text of the current page, or empty string."""
        if self._done or not self._pages or self._page >= len(self._pages):
            return ""
        return self._pages[self._page].get("text", "")

    @property
    def is_last_page(self) -> bool:
        """True when the current page is the final page (not yet advanced past)."""
        if self._done or not self._pages:
            return False
        return self._page >= len(self._pages) - 1

    def advance(self) -> None:
        if self._done or not self._pages:
            self._done = True
            return
        page = self._pages[self._page]
        if page.get("pause"):
            self._advance_page()
            return
        if self._chars < len(page["text"]):
            self._chars = float(len(page["text"]))  # snap to end
        else:
            self._advance_page()

    def _advance_page(self) -> None:
        self._page += 1
        self._chars = 0.0
        if self._page >= len(self._pages):
            self._done = True

    def retreat(self) -> None:
        """Go back one page. Already-seen pages show fully revealed (no
        re-typing). No-op on the first page. Universal: any narration that
        uses DialogueBox gains backward paging."""
        if not self._pages:
            return
        if self._done:
            # was past the end — re-enter on the last page, fully shown
            self._done = True if len(self._pages) == 0 else False
            self._page = len(self._pages) - 1
        elif self._page > 0:
            self._page -= 1
        self._chars = float(len(self._pages[self._page].get("text", "")))

    @property
    def has_prev(self) -> bool:
        return bool(self._pages) and self._page > 0 and not self._done

    def set_glossary(self, defs: dict) -> None:
        """Provide footnote definitions {number: text} for <term>(n) markup."""
        self._glossary = dict(defs)

    def skip(self) -> None:
        self._done = True

    def draw(self, surf: pygame.Surface, x: int, y: int) -> None:
        if self._done or not self._pages:
            return

        import engine.theme as T
        bg  = T.PANEL_DEEP
        brd = T.BORDER
        dim = T.TEXT_DIM

        page = self._pages[self._page]
        if page.get("pause"):
            return  # blank during pause beat

        speaker  = page.get("speaker", "")
        body     = page.get("text", "")
        visible  = body[:int(self._chars)]

        # Speaker color
        spk_col = T.WHITE_GREEN
        if speaker in SPEAKER_MAP:
            attr    = SPEAKER_MAP[speaker][1]
            spk_col = getattr(T, attr, T.WHITE_GREEN)

        box = pygame.Rect(x, y, self._w, self._h)
        pygame.draw.rect(surf, bg, box, border_radius=4)
        pygame.draw.rect(surf, brd, box, 2, border_radius=4)

        fnt = self._font
        pad = 10

        # Speaker label
        if speaker:
            lbl = fnt.render(speaker + ":", True, spk_col)
            surf.blit(lbl, (x + pad, y + 5))
            text_y = y + fnt.get_linesize() + 6
        else:
            text_y = y + 6

        # Parse keyword markup into coloured tokens + this page's footnotes.
        if self._highlight_terms:
            tokens, foot_nums = _parse_keywords(visible)
        else:
            tokens = [(w, False) for w in visible.split()]
            foot_nums = []

        tx     = x + pad
        max_w  = self._w - pad * 2
        accent = getattr(T, "AMBER", spk_col)
        line_h = fnt.get_linesize() + 1
        space_w = fnt.size(" ")[0]

        # If this page has footnotes, pre-measure their height and a separator
        # rule, and reserve that zone at the BOTTOM of the box. Footnotes are
        # anchored so their last line sits just above the bottom border.
        foot_defs = [(n, self._glossary.get(n, "")) for n in foot_nums
                     if self._glossary.get(n)]
        foot_font = fnt
        foot_lines_all = []   # list of (n_label_or_None, line_str) for layout
        if foot_defs:
            for n, definition in foot_defs:
                head = f"({n}) "
                full = head + definition
                # wrap definition to box width
                words = full.split(' ')
                cur = ""
                first = True
                for w in words:
                    test = (cur + " " + w).strip()
                    if foot_font.size(test)[0] <= max_w:
                        cur = test
                    else:
                        foot_lines_all.append(cur)
                        cur = w
                if cur:
                    foot_lines_all.append(cur)
        foot_h = (len(foot_lines_all) * line_h + 8) if foot_lines_all else 0
        sep_y  = y + self._h - foot_h - 6 if foot_h else None
        body_bottom = (sep_y - 4) if sep_y else (y + self._h - 6)

        # Render body tokens, wrapping within [text_y, body_bottom).
        cx = tx
        cy = text_y
        for word, is_kw in tokens:
            ww = fnt.size(word)[0]
            if cx > tx and cx + ww > tx + max_w:
                cx = tx
                cy += line_h
            col = accent if (is_kw and self._highlight_terms) else spk_col
            surf.blit(fnt.render(word, True, col), (cx, cy))
            cx += ww + space_w

        # Render bottom-anchored footnotes with a separator rule.
        if foot_lines_all and sep_y is not None:
            pygame.draw.line(surf, dim, (tx, sep_y),
                             (x + self._w - pad, sep_y), 1)
            fy = sep_y + 6
            for line in foot_lines_all:
                surf.blit(foot_font.render(line, True, accent), (tx, fy))
                fy += line_h

        # Paging prompts: << (back) on the left when a previous page exists,
        # >> (forward) on the right when more pages remain.
        if self._chars >= len(body):
            pages_left = len(self._pages) - self._page - 1
            if self._page > 0:
                back = fnt.render("<<", True, dim)
                surf.blit(back, (x + 8,
                                 y + self._h - back.get_height() - 5))
            prompt = fnt.render(
                ">>" if pages_left > 0 else ">> (done)", True, dim)
            surf.blit(prompt, (x + self._w - prompt.get_width() - 8,
                               y + self._h - prompt.get_height() - 5))

