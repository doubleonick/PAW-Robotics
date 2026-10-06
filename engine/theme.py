"""
engine/theme.py  — multi-theme system
"""
import pygame

_THEMES = {
    "phosphor": dict(
        BG=(10,12,10), PANEL=(13,15,13), PANEL_DEEP=(8,10,8),
        BORDER=(30,58,30), BORDER_DIM=(18,34,18),
        PHOSPHOR=(51,255,87), PHOSPHOR_DIM=(20,90,30), PHOSPHOR_MID=(30,160,50),
        AMBER=(255,149,0), AMBER_DIM=(80,46,0), AMBER_DARK=(40,22,0),
        WHITE_GREEN=(220,255,220), TEXT=(160,220,160), TEXT_DIM=(70,110,70),
        RED_PH=(255,60,60), BLUE_PH=(60,160,255),
        BEH_CRUISE=(51,200,70), BEH_AVOID=(255,180,0),
        BEH_SEEK=(60,230,230), BEH_ESCAPE=(255,60,60),
        FLOOR=(10,18,10), WALL_COLOR=(40,90,40), LIGHT_COLOR=(255,200,50),
        FONT_NAME="couriernew", FONT_FALLBACK="courier",
        SCANLINES=True, BTN_RADIUS=0,
    ),
    "lcars": dict(
        BG=(0,0,0), PANEL=(10,8,16), PANEL_DEEP=(4,3,8),
        BORDER=(80,60,140), BORDER_DIM=(40,30,70),
        PHOSPHOR=(255,153,0), PHOSPHOR_DIM=(120,70,0), PHOSPHOR_MID=(204,102,0),
        AMBER=(255,204,102), AMBER_DIM=(80,64,30), AMBER_DARK=(20,16,8),
        WHITE_GREEN=(255,239,179), TEXT=(204,153,255), TEXT_DIM=(80,60,120),
        RED_PH=(204,51,51), BLUE_PH=(51,153,255),
        BEH_CRUISE=(255,153,0), BEH_AVOID=(255,204,102),
        BEH_SEEK=(51,204,204), BEH_ESCAPE=(204,51,51),
        FLOOR=(8,4,16), WALL_COLOR=(255,153,0), LIGHT_COLOR=(255,220,120),
        FONT_NAME="helvetica", FONT_FALLBACK="arial",
        SCANLINES=False, BTN_RADIUS=18,
    ),
    "blueprint": dict(
        BG=(8,18,52), PANEL=(12,26,72), PANEL_DEEP=(6,14,40),
        BORDER=(80,130,220), BORDER_DIM=(40,70,130),
        PHOSPHOR=(220,240,255), PHOSPHOR_DIM=(80,120,180), PHOSPHOR_MID=(140,180,230),
        AMBER=(255,220,80), AMBER_DIM=(90,80,28), AMBER_DARK=(20,18,6),
        WHITE_GREEN=(240,248,255), TEXT=(180,210,250), TEXT_DIM=(80,110,160),
        RED_PH=(255,80,80), BLUE_PH=(100,200,255),
        BEH_CRUISE=(100,200,255), BEH_AVOID=(255,220,80),
        BEH_SEEK=(100,255,220), BEH_ESCAPE=(255,80,80),
        FLOOR=(6,14,44), WALL_COLOR=(100,160,240), LIGHT_COLOR=(255,240,120),
        FONT_NAME="couriernew", FONT_FALLBACK="courier",
        SCANLINES=False, BTN_RADIUS=0,
    ),
    "sixteenbit": dict(
        BG=(0,0,16), PANEL=(0,8,40), PANEL_DEEP=(0,4,24),
        BORDER=(68,68,204), BORDER_DIM=(28,28,88),
        PHOSPHOR=(68,204,255), PHOSPHOR_DIM=(20,80,120), PHOSPHOR_MID=(40,140,200),
        AMBER=(255,204,0), AMBER_DIM=(100,80,0), AMBER_DARK=(24,20,0),
        WHITE_GREEN=(255,255,255), TEXT=(204,220,255), TEXT_DIM=(80,90,140),
        RED_PH=(255,40,40), BLUE_PH=(40,120,255),
        BEH_CRUISE=(68,204,255), BEH_AVOID=(255,204,0),
        BEH_SEEK=(0,255,160), BEH_ESCAPE=(255,40,40),
        FLOOR=(0,4,28), WALL_COLOR=(68,68,204), LIGHT_COLOR=(255,220,60),
        FONT_NAME="couriernew", FONT_FALLBACK="courier",
        SCANLINES=False, BTN_RADIUS=4,
    ),
}

CURRENT = "phosphor"

# Module-level colour globals — updated by apply()
BG=_THEMES["phosphor"]["BG"]; PANEL=_THEMES["phosphor"]["PANEL"]
PANEL_DEEP=_THEMES["phosphor"]["PANEL_DEEP"]; BORDER=_THEMES["phosphor"]["BORDER"]
BORDER_DIM=_THEMES["phosphor"]["BORDER_DIM"]; PHOSPHOR=_THEMES["phosphor"]["PHOSPHOR"]
PHOSPHOR_DIM=_THEMES["phosphor"]["PHOSPHOR_DIM"]; PHOSPHOR_MID=_THEMES["phosphor"]["PHOSPHOR_MID"]
AMBER=_THEMES["phosphor"]["AMBER"]; AMBER_DIM=_THEMES["phosphor"]["AMBER_DIM"]
AMBER_DARK=_THEMES["phosphor"]["AMBER_DARK"]; WHITE_GREEN=_THEMES["phosphor"]["WHITE_GREEN"]
TEXT=_THEMES["phosphor"]["TEXT"]; TEXT_DIM=_THEMES["phosphor"]["TEXT_DIM"]
RED_PH=_THEMES["phosphor"]["RED_PH"]; BLUE_PH=_THEMES["phosphor"]["BLUE_PH"]
BEH_CRUISE=_THEMES["phosphor"]["BEH_CRUISE"]; BEH_AVOID=_THEMES["phosphor"]["BEH_AVOID"]
BEH_SEEK=_THEMES["phosphor"]["BEH_SEEK"]; BEH_ESCAPE=_THEMES["phosphor"]["BEH_ESCAPE"]
FLOOR=_THEMES["phosphor"]["FLOOR"]; WALL_COLOR=_THEMES["phosphor"]["WALL_COLOR"]
LIGHT_COLOR=_THEMES["phosphor"]["LIGHT_COLOR"]
FONT_NAME=_THEMES["phosphor"]["FONT_NAME"]; FONT_FALLBACK=_THEMES["phosphor"]["FONT_FALLBACK"]
SCANLINES=_THEMES["phosphor"]["SCANLINES"]; BTN_RADIUS=_THEMES["phosphor"]["BTN_RADIUS"]

THEME_NAMES = list(_THEMES.keys())
THEME_SWATCHES = {"phosphor":(51,255,87),"lcars":(255,153,0),
                  "blueprint":(100,160,240),"sixteenbit":(68,204,255)}
THEME_LABELS   = {"phosphor":"PHOSPHOR","lcars":"LCARS",
                  "blueprint":"BLUEPRINT","sixteenbit":"16-BIT"}

def apply(name: str) -> None:
    global CURRENT,BG,PANEL,PANEL_DEEP,BORDER,BORDER_DIM
    global PHOSPHOR,PHOSPHOR_DIM,PHOSPHOR_MID,AMBER,AMBER_DIM,AMBER_DARK
    global WHITE_GREEN,TEXT,TEXT_DIM,RED_PH,BLUE_PH
    global BEH_CRUISE,BEH_AVOID,BEH_SEEK,BEH_ESCAPE
    global FLOOR,WALL_COLOR,LIGHT_COLOR,FONT_NAME,FONT_FALLBACK,SCANLINES,BTN_RADIUS,_fonts
    t=_THEMES.get(name,_THEMES["phosphor"]); CURRENT=name
    BG=t["BG"]; PANEL=t["PANEL"]; PANEL_DEEP=t["PANEL_DEEP"]
    BORDER=t["BORDER"]; BORDER_DIM=t["BORDER_DIM"]
    PHOSPHOR=t["PHOSPHOR"]; PHOSPHOR_DIM=t["PHOSPHOR_DIM"]; PHOSPHOR_MID=t["PHOSPHOR_MID"]
    AMBER=t["AMBER"]; AMBER_DIM=t["AMBER_DIM"]; AMBER_DARK=t["AMBER_DARK"]
    WHITE_GREEN=t["WHITE_GREEN"]; TEXT=t["TEXT"]; TEXT_DIM=t["TEXT_DIM"]
    RED_PH=t["RED_PH"]; BLUE_PH=t["BLUE_PH"]
    BEH_CRUISE=t["BEH_CRUISE"]; BEH_AVOID=t["BEH_AVOID"]
    BEH_SEEK=t["BEH_SEEK"]; BEH_ESCAPE=t["BEH_ESCAPE"]
    FLOOR=t["FLOOR"]; WALL_COLOR=t["WALL_COLOR"]; LIGHT_COLOR=t["LIGHT_COLOR"]
    FONT_NAME=t["FONT_NAME"]; FONT_FALLBACK=t["FONT_FALLBACK"]
    SCANLINES=t["SCANLINES"]; BTN_RADIUS=t["BTN_RADIUS"]; _fonts={}

def save_theme(name: str) -> None:
    import json, os
    path=os.path.join(os.path.dirname(os.path.dirname(__file__)),"settings.json")
    try:
        data={}
        if os.path.exists(path):
            with open(path) as f: data=json.load(f)
        data["theme"]=name
        with open(path,"w") as f: json.dump(data,f,indent=2)
    except Exception: pass

def load_saved_theme() -> str:
    import json, os
    path=os.path.join(os.path.dirname(os.path.dirname(__file__)),"settings.json")
    try:
        with open(path) as f: return json.load(f).get("theme","phosphor")
    except Exception: return "phosphor"

_fonts: dict = {}

def get_font(size: int, bold: bool = False) -> pygame.font.Font:
    key=(size,bold)
    if key not in _fonts:
        for name in (FONT_NAME, FONT_FALLBACK, "monospace"):
            try: _fonts[key]=pygame.font.SysFont(name,size,bold=bold); break
            except Exception: continue
    return _fonts.get(key, pygame.font.Font(None, size))

def font_hd() -> pygame.font.Font: return get_font(26, bold=True)
def font_md() -> pygame.font.Font: return get_font(16)
def font_sm() -> pygame.font.Font: return get_font(13)
def font_lg() -> pygame.font.Font: return get_font(32, bold=True)

def draw_panel(surf, rect, border=True):
    pygame.draw.rect(surf, PANEL, rect)
    if border:
        pygame.draw.rect(surf, BORDER, rect, 1)
        pygame.draw.line(surf, BORDER_DIM, (rect.left+1,rect.top+1), (rect.right-2,rect.top+1))
        pygame.draw.line(surf, BORDER_DIM, (rect.left+1,rect.top+1), (rect.left+1,rect.bottom-2))

def draw_btn(surf, rect, label, font, active=False, disabled=False,
             hover=False, danger=False, color_override=None):
    r = BTN_RADIUS
    if disabled:
        bg,fg,hi,lo = PANEL_DEEP,PHOSPHOR_DIM,BORDER_DIM,PANEL_DEEP
    elif color_override:
        cr,cg,cb = color_override
        bg=(max(0,cr-80),max(0,cg-80),max(0,cb-80))
        fg=(min(255,cr+80),min(255,cg+80),min(255,cb+80))
        hi=(min(255,cr+60),min(255,cg+60),min(255,cb+60))
        lo=(max(0,cr-120),max(0,cg-120),max(0,cb-120))
    elif active:
        bg,fg,hi,lo = PHOSPHOR_DIM,WHITE_GREEN,PHOSPHOR,BORDER
    elif hover:
        bg=tuple(min(255,c+20) for c in PANEL); fg,hi,lo=PHOSPHOR,PHOSPHOR_MID,BORDER
    elif danger:
        bg,fg,hi,lo = AMBER_DARK,AMBER,AMBER_DIM,AMBER_DARK
    else:
        bg,fg,hi,lo = PANEL,WHITE_GREEN,BORDER,PANEL_DEEP

    if r > 0:
        pygame.draw.rect(surf, bg, rect, border_radius=r)
        if not disabled:
            pygame.draw.rect(surf, hi if hover else BORDER, rect, 1, border_radius=r)
    else:
        pygame.draw.rect(surf, bg, rect)
        pygame.draw.line(surf, hi, rect.topleft, (rect.right-1, rect.top))
        pygame.draw.line(surf, hi, rect.topleft, (rect.left, rect.bottom-1))
        pygame.draw.line(surf, lo, (rect.left,rect.bottom-1), rect.bottomright)
        pygame.draw.line(surf, lo, (rect.right-1,rect.top), rect.bottomright)
        if hover and not disabled:
            pygame.draw.rect(surf, PHOSPHOR_DIM, rect.inflate(2,2), 1)

    t = font.render(label, True, fg)
    surf.blit(t, (rect.centerx-t.get_width()//2, rect.centery-t.get_height()//2))

def draw_scanlines(surf, rect, alpha=28):
    if not SCANLINES: return
    s=pygame.Surface((rect.width,rect.height),pygame.SRCALPHA)
    for y in range(0,rect.height,2):
        pygame.draw.line(s,(0,0,0,alpha),(0,y),(rect.width,y))
    surf.blit(s,rect.topleft)

def draw_double_rule(surf, x0, y, x1):
    pygame.draw.line(surf, BORDER,     (x0,y),   (x1,y))
    pygame.draw.line(surf, BORDER_DIM, (x0,y+2), (x1,y+2))

def draw_led_digit(surf, digit, x, y, w, h, color=None):
    col=color or AMBER; dim=tuple(c//5 for c in col); sw=max(2,w//6)
    mx=x+w//2; my=y+h//2
    segs={'a':((x+sw,y),(x+w-sw,y)),'b':((x,y+sw),(x,my-sw//2)),
          'c':((x+w,y+sw),(x+w,my-sw//2)),'d':((x+sw,my),(x+w-sw,my)),
          'e':((x,my+sw//2),(x,y+h-sw)),'f':((x+w,my+sw//2),(x+w,y+h-sw)),
          'g':((x+sw,y+h),(x+w-sw,y+h))}
    ON={'0':'abcefg','1':'cf','2':'acdeg','3':'acdfg','4':'bcdf',
        '5':'abdfg','6':'abdefg','7':'acf','8':'abcdefg','9':'abcdfg',
        ':':'','-':'d',' ':''}
    active=ON.get(digit,'')
    for name,(p0,p1) in segs.items():
        pygame.draw.line(surf, col if name in active else dim, p0, p1, sw)

def draw_led_string(surf, text, x, y, char_w=18, char_h=28, gap=4, color=None):
    cx=x
    for ch in text:
        if ch==':':
            col=color or AMBER; cy=y+char_h//2
            pygame.draw.circle(surf,col,(cx+char_w//2,cy-5),2)
            pygame.draw.circle(surf,col,(cx+char_w//2,cy+5),2)
        else:
            draw_led_digit(surf,ch,cx,y,char_w,char_h,color)
        cx+=char_w+gap
    return cx

def draw_lcars_header(surf, rect, label, font):
    """LCARS pill-cap header bar. Falls back to plain rect on other themes."""
    if CURRENT != "lcars":
        pygame.draw.rect(surf, PHOSPHOR, rect, border_radius=4)
        t=font.render(label, True, BG)
        surf.blit(t,(rect.left+10, rect.centery-t.get_height()//2))
        return
    cap_r=rect.height//2
    pygame.draw.rect(surf, PHOSPHOR,
                     pygame.Rect(rect.left+cap_r, rect.top,
                                 rect.width-cap_r, rect.height))
    pygame.draw.circle(surf, PHOSPHOR, (rect.left+cap_r, rect.centery), cap_r)
    t=font.render(label.upper(), True, BG)
    surf.blit(t,(rect.right-t.get_width()-12, rect.centery-t.get_height()//2))
