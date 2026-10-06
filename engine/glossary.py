"""
engine/glossary.py
------------------
A shared, game-agnostic glossary (FW-001 MVP).

A `Glossary` holds a list of entries (term + definition, with an optional
number for the Field-Trip-style "Term(n)" highlight convention) and knows how to
render itself as a MODAL overlay: the player opens it, reads, and closes it —
"pick up the glossary, read it, put it down." It does not pause a true game loop
on its own; the caller decides when to show it and routes clicks/keys to it.

Scope note (MVP): this is populated for Valentino's Vehicles wiring concepts for
now, but the mechanism is deliberately game-agnostic so other games can supply
their own entries later. Content lives in per-game data (see
`engine/builder/vv_glossary.py`).

FUTURE (FW-001): "unlock state" — a term becomes visitable only once the player
has been introduced to it. The MVP shows ALL entries (flat unlock). When unlock
state is added, filter `entries` by a seen-set before display; the rendering
here does not need to change.
"""
from __future__ import annotations
import pygame


class GlossaryEntry:
    __slots__ = ("term", "definition", "number")

    def __init__(self, term: str, definition: str, number: int | None = None):
        self.term = term
        self.definition = definition
        self.number = number


class Glossary:
    """A collection of glossary entries plus a modal overlay renderer."""

    def __init__(self, title: str, entries: list[GlossaryEntry]):
        self.title = title
        self.entries = list(entries)
        self._open = False
        self._scroll = 0
        self._close_btn: pygame.Rect | None = None
        self._scroll_max = 0

    # ── open / close ──────────────────────────────────────────────────────
    @property
    def is_open(self) -> bool:
        return self._open

    def open(self) -> None:
        self._open = True
        self._scroll = 0

    def close(self) -> None:
        self._open = False

    # ── lookup (for clickable-term jumps later) ───────────────────────────
    def find(self, term: str) -> GlossaryEntry | None:
        t = term.strip().lower()
        for e in self.entries:
            if e.term.lower() == t:
                return e
        return None

    # ── input ─────────────────────────────────────────────────────────────
    def handle_event(self, event: pygame.event.Event,
                     screen_rect: pygame.Rect) -> bool:
        """Route an event to the open glossary. Returns True if consumed.
        Closes on the X button, Escape, or a click on the dimmed backdrop
        outside the panel."""
        if not self._open:
            return False
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.close(); return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._close_btn and self._close_btn.collidepoint(event.pos):
                self.close(); return True
            panel = self._panel_rect(screen_rect)
            if not panel.collidepoint(event.pos):
                self.close(); return True   # click-away closes
            return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button in (4, 5):
            self._scroll += (-30 if event.button == 4 else 30)
            self._scroll = max(0, min(self._scroll, self._scroll_max))
            return True
        return False

    # ── geometry ──────────────────────────────────────────────────────────
    def _panel_rect(self, screen_rect: pygame.Rect) -> pygame.Rect:
        w = min(720, int(screen_rect.width * 0.7))
        h = min(560, int(screen_rect.height * 0.8))
        return pygame.Rect(screen_rect.centerx - w // 2,
                           screen_rect.centery - h // 2, w, h)

    # ── render ────────────────────────────────────────────────────────────
    def draw(self, surf: pygame.Surface, screen_rect: pygame.Rect) -> None:
        if not self._open:
            return
        import engine.theme as T
        accent = T.PHOSPHOR
        bg = T.PANEL_DEEP
        text = getattr(T, "TEXT", (215, 235, 215))
        dim = T.TEXT_DIM
        border = T.PHOSPHOR

        # dim backdrop
        dimmer = pygame.Surface(screen_rect.size, pygame.SRCALPHA)
        dimmer.fill((0, 0, 0, 170))
        surf.blit(dimmer, screen_rect.topleft)

        panel = self._panel_rect(screen_rect)
        pygame.draw.rect(surf, bg, panel, border_radius=8)
        pygame.draw.rect(surf, border, panel, 2, border_radius=8)

        f_title = self._font(22, bold=True)
        f_term = self._font(17, bold=True)
        f_def = self._font(15)

        # header
        surf.blit(f_title.render(self.title, True, accent),
                  (panel.x + 20, panel.y + 14))
        # close button (X)
        cb = pygame.Rect(panel.right - 38, panel.y + 12, 26, 26)
        pygame.draw.rect(surf, bg, cb, border_radius=4)
        pygame.draw.rect(surf, border, cb, 1, border_radius=4)
        surf.blit(f_term.render("\u2715", True, accent),
                  (cb.centerx - f_term.size("\u2715")[0] // 2,
                   cb.centery - f_term.get_height() // 2))
        self._close_btn = cb

        pygame.draw.line(surf, dim, (panel.x + 16, panel.y + 50),
                         (panel.right - 16, panel.y + 50), 1)

        # entries (clipped + scrollable)
        body = pygame.Rect(panel.x + 16, panel.y + 58,
                           panel.width - 32, panel.height - 74)
        prev_clip = surf.get_clip()
        surf.set_clip(body)
        y = body.y - self._scroll
        lh_def = f_def.get_height() + 2
        for e in self.entries:
            label = (f"{e.term}" if e.number is None
                     else f"{e.term} ({e.number})")
            surf.blit(f_term.render(label, True, accent), (body.x, y))
            y += f_term.get_height() + 2
            y = self._wrap(surf, f_def, e.definition, text,
                           body.x + 12, y, body.width - 12, lh_def)
            y += 12
        content_h = (y + self._scroll) - body.y
        self._scroll_max = max(0, content_h - body.height)
        surf.set_clip(prev_clip)

        # scroll hint
        if self._scroll_max > 0:
            hint = f_def.render("scroll for more", True, dim)
            surf.blit(hint, (panel.right - hint.get_width() - 20,
                             panel.bottom - hint.get_height() - 8))

    def _wrap(self, surf, font, text, color, x, y, max_w, lh) -> int:
        for para in text.split("\n"):
            line = ""
            for word in para.split():
                test = (line + " " + word).strip()
                if font.size(test)[0] > max_w and line:
                    surf.blit(font.render(line, True, color), (x, y))
                    line = word; y += lh
                else:
                    line = test
            if line:
                surf.blit(font.render(line, True, color), (x, y))
                y += lh
        return y

    @staticmethod
    def _font(size, bold=False):
        try:
            return pygame.font.SysFont("consolas", size, bold=bold)
        except Exception:
            return pygame.font.Font(None, size)
