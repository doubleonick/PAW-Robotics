"""
packaging/re_hierarchy_builder/intro_screens.py
-----------------------------------------------
The two screens shown before the Hierarchy Builder in the classroom app:

  1. Role selection — "Welcome to Robot Ethology! ... Student / Instructor".
       Student   -> straight to the Hierarchy Builder.
       Instructor-> the Setup screen.
  2. Instructor Setup — instructions + "Initialize Robot" (launch the BLE
       scaffolding sketch in the Arduino IDE) + "Continue" (-> Builder).

Both are self-contained pygame screens with their own event loops. They share
the builder's theme so the app feels like one piece. Each returns a simple
string the caller acts on; neither imports PyBullet or the game.
"""
from __future__ import annotations

import pygame
import engine.theme as T


# ── shared helpers ───────────────────────────────────────────────────────────
def _screen_size():
    info = pygame.display.Info()
    taskbar = 50
    return max(820, info.current_w - 16), max(560, info.current_h - taskbar - 16)


def _wrap(text, font, max_w):
    """Word-wrap a paragraph to fit max_w pixels; returns a list of lines."""
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if font.size(trial)[0] <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _button(surf, rect, label, font, hover, accent=False):
    bg = T.PANEL if not hover else T.PANEL_DEEP
    edge = T.WHITE_GREEN if accent else T.PHOSPHOR
    pygame.draw.rect(surf, bg, rect, border_radius=6)
    pygame.draw.rect(surf, edge, rect, 2 if accent else 1, border_radius=6)
    lt = font.render(label, True, edge)
    surf.blit(lt, (rect.centerx - lt.get_width() // 2,
                   rect.centery - lt.get_height() // 2))


# ── Screen 1: role selection ─────────────────────────────────────────────────
def role_select(screen) -> str:
    """Show the welcome / role screen. Returns 'student', 'instructor',
    or 'quit'."""
    WW, WH = screen.get_size()
    f_title = T.get_font(30, bold=True)
    f_body = T.get_font(18)
    f_btn = T.get_font(20, bold=True)

    title = "Welcome to Robot Ethology!"
    prompt = ("Please indicate your role in this lab by pressing "
              "'Student' or 'Instructor'.")

    bw, bh, gap = 260, 70, 40
    cx = WW // 2
    by = WH // 2 + 20
    student_r = pygame.Rect(cx - bw - gap // 2, by, bw, bh)
    instr_r = pygame.Rect(cx + gap // 2, by, bw, bh)

    clock = pygame.time.Clock()
    while True:
        mouse = pygame.mouse.get_pos()
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                return "quit"
            if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
                return "quit"
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                if student_r.collidepoint(e.pos):
                    return "student"
                if instr_r.collidepoint(e.pos):
                    return "instructor"

        screen.fill(T.BG)
        tt = f_title.render(title, True, T.WHITE_GREEN)
        screen.blit(tt, (cx - tt.get_width() // 2, WH // 4))
        for i, line in enumerate(_wrap(prompt, f_body, int(WW * 0.7))):
            ls = f_body.render(line, True, T.TEXT)
            screen.blit(ls, (cx - ls.get_width() // 2,
                             WH // 4 + 60 + i * 28))
        _button(screen, student_r, "Student", f_btn,
                student_r.collidepoint(mouse))
        _button(screen, instr_r, "Instructor", f_btn,
                instr_r.collidepoint(mouse), accent=True)
        pygame.display.flip()
        clock.tick(60)


# ── Screen 2: instructor setup ───────────────────────────────────────────────
INSTRUCTOR_TEXT = (
    "Press the 'Initialize Robot' button to launch the Arduino IDE with a "
    "sketch that has all of the scaffolding for the Robot Ethology lab. "
    "Connect your Arduino, select your board and port, and upload the sketch. "
    "Once your upload is done, return to this page and press 'Continue'. "
    "You will then be taken to the Hierarchy Builder your students will use, "
    "and you will build the target hierarchy(ies) that you will be using in "
    "your lab. Make sure the target robot is on and running the sketch you "
    "uploaded, and, once your hierarchy is what you want, press 'Send via BLE' "
    "in the Builder. For reference see the README.md file in the "
    "'RE Hierarchy Builder' folder where this application lives."
)


def instructor_setup(screen, on_initialize) -> str:
    """Show the instructor setup screen.

    on_initialize: a zero-arg callable that launches the BLE scaffolding sketch
    (returns a status string or None). Returns 'continue' or 'quit'.
    """
    WW, WH = screen.get_size()
    f_title = T.get_font(28, bold=True)
    f_body = T.get_font(17)
    f_btn = T.get_font(18, bold=True)
    f_status = T.get_font(15)

    title = "Robot Ethology — Instructor Setup"
    status = ""

    margin = int(WW * 0.12)
    text_w = WW - margin * 2
    lines = _wrap(INSTRUCTOR_TEXT, f_body, text_w)

    bw, bh = 220, 56
    init_r = pygame.Rect(margin, WH - 130, bw, bh)
    cont_r = pygame.Rect(WW - margin - bw, WH - 130, bw, bh)

    clock = pygame.time.Clock()
    while True:
        mouse = pygame.mouse.get_pos()
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                return "quit"
            if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
                return "quit"
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                if init_r.collidepoint(e.pos):
                    try:
                        result = on_initialize()
                        status = result or "Launched Arduino IDE \u2014 upload the sketch."
                    except Exception as ex:
                        status = f"Could not launch: {ex}"
                elif cont_r.collidepoint(e.pos):
                    return "continue"

        screen.fill(T.BG)
        tt = f_title.render(title, True, T.WHITE_GREEN)
        screen.blit(tt, (margin, WH // 8))
        T.draw_double_rule(screen, margin, WH // 8 + 44, WW - margin)
        y = WH // 8 + 64
        for line in lines:
            ls = f_body.render(line, True, T.TEXT)
            screen.blit(ls, (margin, y))
            y += 26
        if status:
            ss = f_status.render(status, True, T.PHOSPHOR)
            screen.blit(ss, (margin, WH - 165))
        _button(screen, init_r, "Initialize Robot", f_btn,
                init_r.collidepoint(mouse), accent=True)
        _button(screen, cont_r, "Continue", f_btn,
                cont_r.collidepoint(mouse))
        pygame.display.flip()
        clock.tick(60)
