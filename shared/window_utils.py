"""
shared/window_utils.py
-----------------------
Canonical window-sizing for all Curious Robotics games.

All games call get_window_size() at startup.  This returns the largest
window that fits within the usable desktop area — i.e. maximized within
the OS toolbar bounds, not full-screen.

Platform notes
--------------
Windows  : taskbar is typically 40–48 px; pygame reports the full monitor
           height in current_h so we subtract TASKBAR_H.
macOS    : menu bar ~24 px + dock ~70 px; pygame current_h already excludes
           the menu bar on most versions, so a smaller reserve is enough.
Linux    : varies by desktop; 48 px is a safe default.

A small CHROME_MARGIN (8 px each side) is subtracted so the window
border and resize handles don't clip to the screen edge.
"""

from __future__ import annotations
import sys
import pygame

# OS-specific reserves (pixels)
_TASKBAR = {
    "win32":  48,   # Windows taskbar
    "darwin": 50,   # macOS menu bar + some dock margin
}
_TASKBAR_DEFAULT = 52

_CHROME_MARGIN = 8   # border/shadow on each side


def get_window_size(min_w: int = 800, min_h: int = 500) -> tuple[int, int]:
    """
    Return (width, height) for a maximized-but-not-fullscreen window.

    Must be called after pygame.init().

    Subtracts the OS taskbar height and a small chrome margin so the
    window fits cleanly within the desktop without overlapping the taskbar
    or clipping to the screen edge.
    """
    info      = pygame.display.Info()
    taskbar_h = _TASKBAR.get(sys.platform, _TASKBAR_DEFAULT)

    w = max(min_w, info.current_w  - _CHROME_MARGIN * 2)
    h = max(min_h, info.current_h  - taskbar_h - _CHROME_MARGIN * 2)

    return w, h
