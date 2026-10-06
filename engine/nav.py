"""
engine/nav.py
--------------
Shared navigation helpers: Back button and confirm-back overlay.

Usage in any game hub:
    from engine.nav import NavOverlay

    # In __init__:
    self._nav = NavOverlay(back_destination="the game menu")

    # In _draw_panel (after all other content):
    self._nav.draw_back_btn(surf, layout, font_sm, theme)

    # In event handling (MOUSEBUTTONDOWN, before other checks):
    if self._nav.handle_click(pos, layout):
        return   # overlay consumed the click

    # In main loop (after draw):
    if self._nav.confirmed:
        return   # exit the run() loop — caller handles return to menu
"""

import pygame
from typing import Optional


class NavOverlay:
    """
    Manages the Back button and its confirm-back overlay.

    The button is always drawn and always responsive — narrator state
    is never a gate.  Pressing Back raises an overlay asking for
    confirmation; OK confirms exit, Cancel dismisses.
    """

    def __init__(self, back_destination: str = "the previous screen"):
        self.back_destination = back_destination
        self.confirmed        = False   # set True when user confirms OK
        self._active          = False   # overlay visible

    # ── Public API ────────────────────────────────────────────────────────────

    def request_back(self) -> None:
        """Show the confirm overlay. Call when Back is pressed."""
        self._active = True

    def cancel(self) -> None:
        """Dismiss the overlay without navigating."""
        self._active = False

    def confirm(self) -> None:
        """Confirm navigation — caller should exit its run() loop."""
        self._active  = False
        self.confirmed = True

    def reset(self) -> None:
        """Reset for reuse (e.g. if hub re-enters a sub-state)."""
        self.confirmed = False
        self._active   = False

    # ── Draw ─────────────────────────────────────────────────────────────────

    def draw_back_btn(self, surf: pygame.Surface, layout,
                      font_sm: pygame.font.Font, theme) -> None:
        """
        Draw the Back button at layout.back_btn_rect.
        Call after all other panel content so it sits on top.
        """
        import engine.theme as T
        r      = layout.back_btn_rect
        mx, my = pygame.mouse.get_pos()
        hov    = r.collidepoint(mx, my)
        radius = T.BTN_RADIUS

        pygame.draw.rect(surf, T.PANEL_DEEP, r, border_radius=radius)
        border_col = T.PHOSPHOR_MID if hov else T.BORDER
        pygame.draw.rect(surf, border_col, r, 1, border_radius=radius)

        lbl = font_sm.render("Back", True,
                             T.WHITE_GREEN if hov else T.TEXT_DIM)
        surf.blit(lbl, (r.centerx - lbl.get_width()  // 2,
                        r.centery - lbl.get_height() // 2))

    def draw_overlay(self, surf: pygame.Surface,
                     ww: int, wh: int,
                     font_ui: pygame.font.Font,
                     font_sm: pygame.font.Font,
                     btn_rects: dict) -> None:
        """
        Draw the confirm-back overlay.  Populates btn_rects with
        'btn_back_ok' and 'btn_back_cancel' for click handling.
        Call only when self._active is True.
        """
        if not self._active:
            return

        import engine.theme as T

        # Dim backdrop
        overlay = pygame.Surface((ww, wh), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        surf.blit(overlay, (0, 0))

        # Dialog box
        dw, dh = 420, 148
        dx     = (ww - dw) // 2
        dy     = (wh - dh) // 2
        pygame.draw.rect(surf, T.PANEL,      (dx, dy, dw, dh), border_radius=8)
        pygame.draw.rect(surf, T.BORDER,     (dx, dy, dw, dh), 1, border_radius=8)
        pygame.draw.rect(surf, T.PANEL_DEEP, (dx, dy, dw, 36), border_radius=8)

        # Title
        tt = font_ui.render("Go back?", True, T.WHITE_GREEN)
        surf.blit(tt, (dx + 16, dy + 8))

        # Body
        dest = self.back_destination
        body = font_sm.render(f"Return to {dest}?", True, T.TEXT)
        surf.blit(body, (dx + 16, dy + 52))

        # Buttons
        btn_w  = 90
        btn_h  = 32
        gap    = 12
        total  = btn_w * 2 + gap
        bx     = dx + (dw - total) // 2
        btn_y  = dy + dh - btn_h - 14

        ok_r  = pygame.Rect(bx,          btn_y, btn_w, btn_h)
        can_r = pygame.Rect(bx+btn_w+gap, btn_y, btn_w, btn_h)
        btn_rects["btn_back_ok"]     = ok_r
        btn_rects["btn_back_cancel"] = can_r

        mx, my = pygame.mouse.get_pos()
        for rect, label, accent in [(ok_r, "OK", True), (can_r, "Cancel", False)]:
            hov = rect.collidepoint(mx, my)
            bg  = T.PHOSPHOR_MID if (hov and accent) else \
                  T.PANEL_DEEP   if hov              else \
                  T.PANEL
            brd = T.PHOSPHOR if accent else T.BORDER
            pygame.draw.rect(surf, bg,  rect, border_radius=T.BTN_RADIUS)
            pygame.draw.rect(surf, brd, rect, 1, border_radius=T.BTN_RADIUS)
            lt = font_sm.render(label, True,
                                T.WHITE_GREEN if accent else T.TEXT_DIM)
            surf.blit(lt, (rect.centerx - lt.get_width()  // 2,
                           rect.centery - lt.get_height() // 2))

    # ── Event helpers ─────────────────────────────────────────────────────────

    def handle_click(self, pos: tuple, layout,
                     btn_rects: dict) -> bool:
        """
        Call at the top of click handling.
        Returns True if the overlay or Back button consumed the click
        (caller should skip all other click processing).
        """
        if self._active:
            if btn_rects.get("btn_back_ok",     pygame.Rect(0,0,0,0)).collidepoint(pos):
                self.confirm()
            elif btn_rects.get("btn_back_cancel", pygame.Rect(0,0,0,0)).collidepoint(pos):
                self.cancel()
            return True   # overlay always consumes clicks while active

        # layout may be None if the caller manages the Back button itself
        if layout is not None and layout.back_btn_rect.collidepoint(pos):
            self.request_back()
            return True

        # Also check if the caller registered a Back button in btn_rects
        if btn_rects.get("btn_back_menu", pygame.Rect(0,0,0,0)).collidepoint(pos):
            self.request_back()
            return True

        return False

    def handle_key(self, key: int) -> bool:
        """
        Handle keyboard shortcuts for the overlay.
        Returns True if consumed.
        """
        if not self._active:
            return False
        if key == pygame.K_ESCAPE:
            self.confirm(); return True
        if key == pygame.K_RETURN:
            self.cancel();  return True
        return False

    @property
    def is_active(self) -> bool:
        return self._active
