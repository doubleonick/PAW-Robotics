"""
paw.py — Game selector and launcher
"""
import argparse
import os
import subprocess
import sys

# Windows/bleak fix (see engine/bluetooth/robot_bt_client.py): set the COM
# threading model to MTA before any dependency indirectly imports pythoncom and
# flips it to STA, which breaks bleak's WinRT BLE scan. Harmless on non-Windows.
sys.coinit_flags = 0  # 0 = COINIT_MULTITHREADED (MTA)

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


def _find_sibling(*path_parts: str) -> str | None:
    """
    Walk up from ROOT looking for a sibling folder matching path_parts.
    Returns absolute path if found, None otherwise.
    e.g. _find_sibling("valentinos", "hub.py") finds ../valentinos/hub.py
    """
    p = ROOT
    for _ in range(6):
        candidate = os.path.join(p, *path_parts)
        if os.path.exists(candidate):
            return os.path.abspath(candidate)
        p = os.path.dirname(p)
    return None


GAMES = {
    "vehicles": {
        "label":       "Valentino's Vehicles",
        "description": "Build sensor-motor wiring and watch emergent behaviour",
        "launcher":    _find_sibling("games", "valentinos", "hub.py") or _find_sibling("valentinos", "hub.py"),
        "available":   True,
    },
    "ethology": {
        "label":       "Robot Ethology",
        "description": "Observe robots and hypothesise their behaviour hierarchies",
        "launcher":    os.path.join(ROOT, "games", "ethology", "hub.py"),
        "available":   True,
    },
    "forcefield": {
        "label":       "Field Trip",
        "description": "Navigate using virtual attractor and repulsor fields",
        "launcher":    os.path.join(ROOT, "games", "field_trip", "hub.py"),
        "available":   True,
    },
    "maze": {
        "label":       "Maze Solver",
        "description": "Navigate robots through mazes using the right control strategy",
        "launcher":    None,
        "available":   False,
    },
    "novel": {
        "label":       "Novel Behaviour",
        "description": "Build a robot from scratch and discover what it can do",
        "launcher":    None,
        "available":   False,
    },
}


def launch_game(key: str) -> None:
    entry = GAMES.get(key)
    if not entry:
        print(f"Unknown game: {key}")
        sys.exit(1)
    if not entry["available"] or not entry["launcher"]:
        print(f"{entry['label']} is not yet available.")
        sys.exit(0)
    launcher = os.path.abspath(entry["launcher"])
    cwd      = os.path.dirname(launcher)
    subprocess.run([sys.executable, launcher], cwd=cwd)


def run_selector() -> None:
    import pygame
    import engine.theme as T
    from engine.professor import DialogueBox

    T.apply(T.load_saved_theme())

    pygame.init()
    import sys as _sys
    _info     = pygame.display.Info()
    _taskbar  = {"win32": 48, "darwin": 50}.get(_sys.platform, 52)
    WW = max(700, _info.current_w  - 8 * 2)
    WH = max(500, _info.current_h  - _taskbar - 8 * 2)
    screen  = pygame.display.set_mode((WW, WH))
    pygame.display.set_caption("PAW Robotics")
    clock   = pygame.time.Clock()

    def make_fonts():
        return T.font_hd(), T.font_md(), T.font_sm()

    font_hd, font_md, font_sm = make_fonts()

    from engine.launch_assets import load_banner, PawBotSprite

    # ---- Layout anchors -----------------------------------------------------
    SWATCH_H  = 44
    HEADER_H  = max(150, min(230, WH // 4))   # black marquee header band
    DLG_H     = 84
    DLG_PAD   = 16
    DLG_Y     = WH - SWATCH_H - 10 - DLG_H    # narration box sits above theme bar
    PAWBOT_H  = int(DLG_H * 1.9)              # sprite height (sits ON the box)

    pawbot = PawBotSprite(target_h=PAWBOT_H)

    from engine.professor import load_script
    SELECTOR_INTRO = load_script(
        "PAW-BOT", "paw_intro",
        fallback="PAW-BOT: Welcome to PAW Robotics!")

    dlg = DialogueBox(WW - DLG_PAD * 2, DLG_H, T.CURRENT)
    dlg.load(SELECTOR_INTRO)

    def advance_dialogue():
        """Advance narration AND swap PAW-Bot's pose when the page turns."""
        page_before = dlg._page
        dlg.advance()
        if dlg._page != page_before:
            pawbot.next_pose()

    last_ms   = pygame.time.get_ticks()
    game_keys = list(GAMES.keys())

    running = True
    while running:
        C_BG      = T.BG
        C_PANEL   = T.PANEL
        C_EDGE    = T.BORDER
        C_TEXT    = T.TEXT
        C_DIM     = T.TEXT_DIM
        C_HEADING = T.WHITE_GREEN
        C_AVAIL   = T.PHOSPHOR
        C_UNAVAIL = T.PANEL_DEEP
        C_HOV     = T.PHOSPHOR_MID

        now_ms  = pygame.time.get_ticks()
        dt      = (now_ms - last_ms) / 1000.0
        last_ms = now_ms
        if not dlg.is_done:
            dlg.update(dt)

        screen.fill(C_BG)
        btn_rects   = {}
        theme_rects = {}
        mx, my = pygame.mouse.get_pos()

        # ---- Black marquee header band ----
        pygame.draw.rect(screen, (0, 0, 0), pygame.Rect(0, 0, WW, HEADER_H))
        banner = load_banner(T.CURRENT)
        if banner is not None:
            bw, bh = banner.get_size()
            target_w = WW - 40
            scale = target_w / bw
            target_h = int(bh * scale)
            if target_h > HEADER_H - 16:
                scale = (HEADER_H - 16) / bh
                target_h = HEADER_H - 16
                target_w = int(bw * scale)
            scaled = pygame.transform.smoothscale(banner, (target_w, target_h))
            screen.blit(scaled, ((WW - target_w) // 2,
                                 (HEADER_H - target_h) // 2))
        pygame.draw.line(screen, C_EDGE, (0, HEADER_H), (WW, HEADER_H), 1)

        # Game buttons (panel below the header)
        y = HEADER_H + 16
        for key in game_keys:
            g     = GAMES[key]
            avail = g["available"]
            r     = pygame.Rect(24, y, WW - 48, 60)
            btn_rects[key] = r
            hov    = r.collidepoint(mx, my) and avail
            bg     = C_HOV if hov else (C_PANEL if avail else C_UNAVAIL)
            border = C_AVAIL if avail else C_EDGE
            if T.BTN_RADIUS > 0:
                pygame.draw.rect(screen, bg, r, border_radius=T.BTN_RADIUS)
                pygame.draw.rect(screen, border, r, 1,
                                 border_radius=T.BTN_RADIUS)
            else:
                pygame.draw.rect(screen, bg, r)
                hi = C_AVAIL if hov else C_EDGE
                lo = C_UNAVAIL
                pygame.draw.line(screen, hi, r.topleft, (r.right-1, r.top))
                pygame.draw.line(screen, hi, r.topleft, (r.left, r.bottom-1))
                pygame.draw.line(screen, lo, (r.left,r.bottom-1), r.bottomright)
                pygame.draw.line(screen, lo, (r.right-1,r.top), r.bottomright)
            screen.blit(font_md.render(g["label"], True,
                                       C_TEXT if avail else C_DIM),
                        (r.x + 18, r.y + 8))
            screen.blit(font_sm.render(g["description"], True,
                                       C_DIM if avail else
                                       tuple(c//2 for c in C_DIM)),
                        (r.x + 18, r.y + 34))
            if not avail:
                soon = font_sm.render("coming soon", True, C_DIM)
                screen.blit(soon, (r.right - soon.get_width() - 16,
                                   r.centery - soon.get_height()//2))
            y += 72

        # PAW-Bot — centered, sitting on top of the narration box
        pawbot.draw(screen, WW // 2, DLG_Y + 6)

        # Dialogue box (full width, above theme bar)
        dlg_rect = pygame.Rect(DLG_PAD, DLG_Y, WW - DLG_PAD*2, DLG_H)
        if not dlg.is_done:
            dlg.draw(screen, DLG_PAD, DLG_Y)
        else:
            ir = pygame.Rect(DLG_PAD, DLG_Y + DLG_H//2 - 12, 120, 24)
            btn_rects["__intro__"] = ir
            hov_i = ir.collidepoint(mx, my)
            pygame.draw.rect(screen, C_PANEL, ir, border_radius=3)
            pygame.draw.rect(screen, C_EDGE, ir, 1, border_radius=3)
            it = font_sm.render("Play Intro", True, C_DIM)
            screen.blit(it, (ir.centerx - it.get_width()//2,
                             ir.centery - it.get_height()//2))

        # Theme bar
        bar_y = WH - SWATCH_H
        T.draw_double_rule(screen, 0, bar_y - 4, WW)
        pygame.draw.rect(screen, T.PANEL_DEEP,
                         pygame.Rect(0, bar_y, WW, SWATCH_H))
        screen.blit(font_sm.render("THEME:", True, C_DIM), (12, bar_y + 14))
        sw_x = 80
        for name in T.THEME_NAMES:
            sc_col  = T.THEME_SWATCHES[name]
            lbl_str = T.THEME_LABELS[name]
            active  = (T.CURRENT == name)
            sw_w    = font_sm.size(lbl_str)[0] + 24
            r       = pygame.Rect(sw_x, bar_y + 8, sw_w, 28)
            theme_rects[name] = r
            hov = r.collidepoint(mx, my)
            if active:
                pygame.draw.rect(screen, sc_col, r, border_radius=4)
                tc = T.BG
            elif hov:
                pygame.draw.rect(screen,
                                 tuple(c//3 for c in sc_col), r,
                                 border_radius=4)
                pygame.draw.rect(screen, sc_col, r, 1, border_radius=4)
                tc = sc_col
            else:
                pygame.draw.rect(screen, T.PANEL, r, border_radius=4)
                pygame.draw.rect(screen,
                                 tuple(c//2 for c in sc_col), r,
                                 1, border_radius=4)
                tc = tuple(c//2 for c in sc_col)
            lt = font_sm.render(lbl_str, True, tc)
            screen.blit(lt, (r.centerx - lt.get_width()//2,
                             r.centery - lt.get_height()//2))
            sw_x += sw_w + 8

        # Exit button — right end of theme bar, never overlaps swatches
        exit_w  = font_sm.size("Exit")[0] + 24
        exit_r  = pygame.Rect(WW - exit_w - 8, bar_y + 8, exit_w, 28)
        btn_rects["__exit__"] = exit_r
        hov_ex = exit_r.collidepoint(mx, my)
        pygame.draw.rect(screen, C_HOV if hov_ex else C_PANEL,
                         exit_r, border_radius=4)
        pygame.draw.rect(screen, T.RED_PH if hov_ex else C_EDGE, exit_r, 1,
                         border_radius=4)
        et = font_sm.render("Exit", True, T.RED_PH if hov_ex else C_DIM)
        screen.blit(et, (exit_r.centerx - et.get_width()//2,
                         exit_r.centery - et.get_height()//2))

        if T.SCANLINES:
            T.draw_scanlines(screen, pygame.Rect(0, 0, WW, WH), alpha=18)

        pygame.display.flip()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_SPACE:
                    if not dlg.is_done:
                        advance_dialogue()
                elif event.key == pygame.K_ESCAPE:
                    running = False

            elif event.type == pygame.MOUSEBUTTONDOWN:
                pos = event.pos
                theme_clicked = False
                for name, r in theme_rects.items():
                    if r.collidepoint(pos):
                        T.apply(name)
                        T.save_theme(name)
                        font_hd, font_md, font_sm = make_fonts()
                        theme_clicked = True
                        break
                if theme_clicked:
                    continue
                if not dlg.is_done and dlg_rect.collidepoint(pos):
                    advance_dialogue()
                    continue
                if "__intro__" in btn_rects and \
                        btn_rects["__intro__"].collidepoint(pos):
                    dlg.load(SELECTOR_INTRO)
                    continue
                if btn_rects.get("__exit__", pygame.Rect(0,0,0,0)).collidepoint(pos):
                    running = False
                    continue
                for key, r in btn_rects.items():
                    if key.startswith("__"):
                        continue
                    if r.collidepoint(pos) and GAMES[key]["available"]:
                        pygame.display.set_mode((1, 1))
                        pygame.display.set_caption("")
                        launch_game(key)
                        screen = pygame.display.set_mode((WW, WH))
                        pygame.display.set_caption("PAW Robotics")
                        font_hd, font_md, font_sm = make_fonts()
                        pygame.event.clear()
                        break

        clock.tick(30)

    pygame.quit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PAW Robotics")
    parser.add_argument("--game", default="",
                        help="Go directly to a game: ethology, vehicles, tutebot, novel")
    args = parser.parse_args()

    if args.game:
        import engine.theme as T
        T.apply(T.load_saved_theme())
        launch_game(args.game)
    else:
        run_selector()
