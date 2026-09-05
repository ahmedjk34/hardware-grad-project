#!/usr/bin/env python3
"""Render the two wiring diagrams as SVG, straight from a netlist.

Nothing here is drawn by hand or by a model: the controller is a labelled pin
strip, every peripheral is a box, and every wire is one row of the NET table
below. The pin numbers are transcribed from the firmware sources and are the
only place they appear, so the drawing cannot disagree with the machine.

  Mega : arduino/build_test_v1/build_test_v1.ino  SECTION 1, 1B, 1C, 6
  Uno  : arduino/belt_v1/belt_v1.ino              header comment + pin consts
"""

import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "figs")
os.makedirs(OUT, exist_ok=True)

# ---------------------------------------------------------------- palette ---
INK        = "#1a1a1a"
BOARD_FILL = "#e8eef7"
BOARD_EDGE = "#1a365b"
SIG        = "#1a5fb4"   # signal wires
PWR12      = "#c01c28"   # 12 V
PWR5       = "#e66100"   # 5 V
GND        = "#3d3846"   # ground
NOTE_FILL  = "#fff6da"
NOTE_EDGE  = "#c9a227"
BOX_FILL   = "#ffffff"
BOX_EDGE   = "#5e5c64"
FONT       = "Times New Roman, Georgia, serif"
MONO       = "Consolas, DejaVu Sans Mono, monospace"


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


class SVG:
    def __init__(self, w, h):
        self.w, self.h, self.parts = w, h, []

    def rect(self, x, y, w, h, fill=BOX_FILL, edge=BOX_EDGE, sw=1.2, rx=3, dash=None):
        d = ' stroke-dasharray="%s"' % dash if dash else ""
        self.parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
            f'fill="{fill}" stroke="{edge}" stroke-width="{sw}"{d}/>')

    def line(self, x1, y1, x2, y2, col=SIG, sw=1.4, dash=None):
        d = ' stroke-dasharray="%s"' % dash if dash else ""
        self.parts.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{col}" '
            f'stroke-width="{sw}" stroke-linecap="round"{d}/>')

    def poly(self, pts, col=SIG, sw=1.4, dash=None):
        d = ' stroke-dasharray="%s"' % dash if dash else ""
        p = " ".join("%g,%g" % q for q in pts)
        self.parts.append(
            f'<polyline points="{p}" fill="none" stroke="{col}" stroke-width="{sw}" '
            f'stroke-linecap="round" stroke-linejoin="round"{d}/>')

    def text(self, x, y, s, size=11, col=INK, anchor="start", weight="normal",
             font=FONT, style="normal"):
        self.parts.append(
            f'<text x="{x}" y="{y}" font-family="{font}" font-size="{size}" '
            f'fill="{col}" text-anchor="{anchor}" font-weight="{weight}" '
            f'font-style="{style}">{esc(s)}</text>')

    def dot(self, x, y, r=3, col=SIG):
        self.parts.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{col}"/>')

    def save(self, name):
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" '
                f'height="{self.h}" viewBox="0 0 {self.w} {self.h}">'
                f'<rect width="{self.w}" height="{self.h}" fill="white"/>')
        p = os.path.join(OUT, name)
        open(p, "w").write(head + "".join(self.parts) + "</svg>")
        print("wrote", p)
        return p


def draw(title, subtitle, board, left, right, notes, rails, outname, W=1180):
    """board: (label, sublabel).  left/right: list of peripheral dicts."""
    rowh, boxh, boxw = 42, 32, 232
    n = max(len(left), len(right))
    s = SVG(W, 100)

    s.text(30, 36, title, size=17, weight="bold")
    s.text(30, 57, subtitle, size=10.5, col="#5e5c64", style="italic")

    # --- controller, centre ---
    bw = 224
    bh = n * rowh + 26
    bx, by = (W - bw) / 2, 96
    s.rect(bx, by, bw, bh, fill=BOARD_FILL, edge=BOARD_EDGE, sw=2, rx=6)
    s.text(bx + bw / 2, by + 26, board[0], size=13.5, weight="bold", anchor="middle")
    s.text(bx + bw / 2, by + 43, board[1], size=9, col="#5e5c64", anchor="middle")

    def side(items, is_left):
        y = by + 62
        for it in items:
            px = bx if is_left else bx + bw
            col = it.get("col", SIG)
            s.dot(px, y, 3.2, BOARD_EDGE)
            # pin number, sitting just above the wire so nothing overlaps
            s.text(px + (-10 if is_left else 10), y - 5, "pin " + it["pin"], size=9.5,
                   weight="bold", font=MONO, col=BOARD_EDGE,
                   anchor="end" if is_left else "start")
            bxx = bx - 92 - boxw if is_left else bx + bw + 92
            wire_end = bxx + boxw if is_left else bxx
            s.line(px, y, wire_end, y, col=col, sw=1.6)
            s.rect(bxx, y - boxh / 2, boxw, boxh, fill=BOX_FILL, edge=BOX_EDGE, sw=1)
            s.text(bxx + 9, y - 1, it["to"], size=10, font=MONO)
            if it.get("note"):
                s.text(bxx + 9, y + 12, it["note"], size=8.5, col="#5e5c64",
                       style="italic")
            y += rowh

    side(left, True)
    side(right, False)

    # --- USB link to the Pi, from the bottom of the board ---
    uy = by + bh
    piy = uy + 46
    s.line(bx + bw / 2, uy, bx + bw / 2, piy, col=GND, sw=1.6, dash="5 3")
    s.rect(bx + bw / 2 - 118, piy, 236, 30, fill=BOX_FILL, edge=BOARD_EDGE, sw=1.4)
    s.text(bx + bw / 2, piy + 20, "Raspberry Pi 5   (USB: power + serial)",
           size=10, anchor="middle", font=MONO)

    # --- power rails ---
    ry = piy + 78
    for i, (name, col, txt) in enumerate(rails):
        yy = ry + i * 34
        s.text(76, yy - 7, name + "  \u2014  " + txt, size=9.5, col=col, weight="bold")
        s.line(76, yy, W - 76, yy, col=col, sw=2.8)

    # --- notes ---
    ny = ry + len(rails) * 34 + 16
    for note in notes:
        lines = note["lines"]
        h = 16 * len(lines) + 16
        s.rect(76, ny, W - 152, h, fill=NOTE_FILL, edge=NOTE_EDGE, sw=1, rx=4)
        for j, ln in enumerate(lines):
            s.text(90, ny + 20 + j * 16, ln, size=9.5)
        ny += h + 10

    s.h = int(ny + 24)
    return s.save(outname)


# ============================================================== MEGA ========
# arduino/build_test_v1/build_test_v1.ino
mega_left = [
    {"pin": "2",  "to": "TB6600 #1  DIR",   "note": "CoreXY motor 1"},
    {"pin": "3",  "to": "TB6600 #1  STEP",  "note": "NEMA17"},
    {"pin": "4",  "to": "TB6600 #1  ENABLE","note": "ACTIVE LOW"},
    {"pin": "8",  "to": "TB6600 #2  DIR",   "note": "CoreXY motor 2"},
    {"pin": "9",  "to": "TB6600 #2  STEP",  "note": "NEMA17"},
    {"pin": "10", "to": "TB6600 #2  ENABLE","note": "ACTIVE LOW"},
    {"pin": "11", "to": "TB6600 #3  DIR",   "note": "Z axis"},
    {"pin": "12", "to": "TB6600 #3  STEP",  "note": "no ENABLE line fitted"},
]
mega_right = [
    {"pin": "30", "to": "LIMIT SW  X",      "note": "NC, pull-up  |  X home / zero"},
    {"pin": "31", "to": "LIMIT SW  Y",      "note": "NC, pull-up  |  Y home / zero"},
    {"pin": "28", "to": "LIMIT SW  Z bottom","note": "NC, pull-up  |  Z zero, GROUND ref"},
    {"pin": "29", "to": "LIMIT SW  Z top",  "note": "NC, pull-up  |  far-end stop only"},
    {"pin": "6",  "to": "GRIPPER SERVO",    "note": "OPEN 0 deg / CLOSE 52 deg", "col": PWR5},
    {"pin": "38", "to": "ULN2003  IN1",     "note": "black", "col": PWR5},
    {"pin": "36", "to": "ULN2003  IN2",     "note": "green", "col": PWR5},
    {"pin": "39", "to": "ULN2003  IN3",     "note": "blue",  "col": PWR5},
    {"pin": "37", "to": "ULN2003  IN4",     "note": "red",   "col": PWR5},
]
draw(
    "Figure — Arduino MEGA 2560, gantry controller: complete wiring",
    "Every pin transcribed from arduino/build_test_v1/build_test_v1.ino",
    ("Arduino MEGA 2560", "GANTRY  —  firmware build_test_v1"),
    mega_left, mega_right,
    rails=[
        ("12 V", PWR12, "motor supply for TB6600 #1, #2, #3"),
        ("5 V",  PWR5,  "from LM2596 — gripper servo, ULN2003 / 28BYJ-48"),
        ("GND",  GND,   "common ground: PSU, buck converter, board, all drivers, all switches"),
    ],
    notes=[
        {"lines": [
            "COIL ORDER: the Stepper library is constructed IN1, IN3, IN2, IN4  =  pins 38, 39, 36, 37.",
            "Wiring the ULN2003 in numerical pin order (36, 37, 38, 39) gives a motor that buzzes and does not turn.",
        ]},
        {"lines": [
            "LIMIT SWITCHES: all four are plain micro switches, normally closed, one leg to the pin and one to GND,",
            "read through the AVR internal pull-ups. A broken wire then reads as a tripped switch and stops the axis,",
            "which is the safe failure. Pin 29 stops the Z axis but does NOT redefine zero; pin 28 is Z's zero.",
        ]},
        {"lines": [
            "SERVO AND STEPPER POWER come from the 5 V rail, not from the board's own 5 V pin.",
            "USB to the Raspberry Pi carries both the serial link (9600 8N1) and board power.",
        ]},
    ],
    outname="fig-wiring-mega.svg")

# =============================================================== UNO ========
# arduino/belt_v1/belt_v1.ino
uno_left = [
    {"pin": "2",  "to": "A4988  DIR",  "note": "belt direction"},
    {"pin": "3",  "to": "A4988  STEP", "note": "NEMA17 conveyor, 150 steps/s"},
]
uno_right = [
    {"pin": "4",  "to": "EXIT HC-SR04  TRIG", "note": "container exit"},
    {"pin": "5",  "to": "EXIT HC-SR04  ECHO", "note": "block left the hopper"},
    {"pin": "8",  "to": "STAGE HC-SR04  TRIG","note": "pickup point"},
    {"pin": "9",  "to": "STAGE HC-SR04  ECHO","note": "block reached [0,0]"},
    {"pin": "6",  "to": "ALIGNMENT SERVO",    "note": "rest 90 deg / nudge 120 deg", "col": PWR5},
    {"pin": "12", "to": "CONTAINER SERVO",    "note": "closed 20 / stage 90 / open 160", "col": PWR5},
]
draw(
    "Figure — Arduino Uno, feeder controller: complete wiring",
    "Every pin transcribed from arduino/belt_v1/belt_v1.ino",
    ("Arduino Uno", "FEEDER  —  firmware belt_v1, protocol 2"),
    uno_left, uno_right,
    rails=[
        ("12 V", PWR12, "A4988 motor supply"),
        ("5 V",  PWR5,  "from LM2596 — both servos, both HC-SR04, A4988 logic / Vref"),
        ("GND",  GND,   "common ground, shared with the Mega side"),
    ],
    notes=[
        {"lines": [
            "A4988 ENABLE is tied directly to GROUND, not driven by the Arduino. There is no enable pin in the firmware.",
        ]},
        {"lines": [
            "ULTRASONIC SENSORS: detection threshold is distance < 10.0 cm. The echo timeout is 30 ms and reports",
            "\"no echo\", which is never treated as a detection — 'I heard nothing' and 'nothing is there' are different.",
        ]},
        {"lines": [
            "SERVO POWER comes from the 5 V rail, not the Uno's 5 V pin. USB to the Raspberry Pi carries both the",
            "serial link (9600 8N1, protocol 2) and board power. This board has NO connection to the Arduino MEGA.",
        ]},
    ],
    outname="fig-wiring-uno.svg")
