"""
engine/launch_assets.py
-----------------------
Launch-screen assets for paw.py:

  • load_banner(theme)  — per-theme marquee banner, cached, with phosphor
                          fallback for themes that have no banner yet.
  • PawBotSprite        — the PAW-Bot mascot on the launch screen. Loads the
                          sliced pose frames and shows one at a time; advancing
                          the narration picks a new pose pseudo-randomly (never
                          repeating the current one). Poses 0 and 1 are excluded
                          by request.

These are deliberately self-contained so the launch layout in paw.py stays
readable. The marquee is a fixed-colour raster per theme (it does not recolour
like the vector UI); the PAW-Bot poses are likewise raster frames sliced from
the uploaded sprite sheet.
"""
import os
import random
import pygame

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ICONS = os.path.join(_ROOT, "materials", "icons")
_SPRITES = os.path.join(_ROOT, "materials", "sprites", "pawbot")

# Poses to use on the launch screen. pose_2 (lying down) is omitted: it's wide
# and short, so height-based scaling makes it render much larger than the
# others. The remaining five share a roughly square aspect and scale evenly.
_POSE_IDS = [0, 1, 3, 4, 5]

_banner_cache: dict[str, pygame.Surface] = {}
_pose_cache: dict[int, pygame.Surface] = {}


def load_banner(theme: str) -> pygame.Surface | None:
    """Return the marquee banner for `theme`, cached. Falls back to the
    phosphor banner if the themed file is missing; returns None only if even
    the fallback is absent."""
    if theme in _banner_cache:
        return _banner_cache[theme]
    path = os.path.join(_ICONS, f"paw_marquee_{theme}.png")
    if not os.path.exists(path):
        path = os.path.join(_ICONS, "paw_marquee_phosphor.png")
    if not os.path.exists(path):
        return None
    img = pygame.image.load(path).convert_alpha()
    _banner_cache[theme] = img
    return img


def _load_pose(pose_id: int) -> pygame.Surface | None:
    if pose_id in _pose_cache:
        return _pose_cache[pose_id]
    path = os.path.join(_SPRITES, f"pose_{pose_id}.png")
    if not os.path.exists(path):
        return None
    img = pygame.image.load(path).convert_alpha()
    _pose_cache[pose_id] = img
    return img


class PawBotSprite:
    """PAW-Bot on the launch screen. Holds the current pose and swaps to a new
    pseudo-random one (never an immediate repeat) on next_pose()."""

    def __init__(self, target_h: int = 150):
        self.target_h = target_h
        self._ids = [p for p in _POSE_IDS if _load_pose(p) is not None]
        self._current = random.choice(self._ids) if self._ids else None

    def next_pose(self) -> None:
        """Pick a new pose, avoiding an immediate repeat."""
        if len(self._ids) <= 1:
            return
        choices = [p for p in self._ids if p != self._current]
        self._current = random.choice(choices)

    def draw(self, surf: pygame.Surface, anchor_cx: int, anchor_bottom: int) -> None:
        """Draw the current pose scaled to target_h, horizontally centred on
        anchor_cx with its feet at anchor_bottom (so changing pose keeps him
        planted and centred rather than jumping around)."""
        if self._current is None:
            return
        img = _load_pose(self._current)
        if img is None:
            return
        iw, ih = img.get_size()
        scale = self.target_h / ih
        scaled = pygame.transform.smoothscale(
            img, (max(1, int(iw * scale)), max(1, int(ih * scale))))
        x = anchor_cx - scaled.get_width() // 2
        y = anchor_bottom - scaled.get_height()
        surf.blit(scaled, (x, y))
