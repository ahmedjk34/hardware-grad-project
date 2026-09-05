"""Charts for the report, drawn with PIL (matplotlib's numpy ABI is broken here)."""
from PIL import Image, ImageDraw, ImageFont
import os, re

FIGS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "figs")
os.makedirs(FIGS, exist_ok=True)
FONT_DIRS = ["/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/TTF", "/usr/share/fonts"]

def font(name, size):
    for d in FONT_DIRS:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    for root, _, files in os.walk("/usr/share/fonts"):
        if name in files:
            return ImageFont.truetype(os.path.join(root, name), size)
    return ImageFont.load_default()

F  = lambda s: font("DejaVuSans.ttf", s)
FB = lambda s: font("DejaVuSans-Bold.ttf", s)

SCALE = 3            # supersample, then downsample for clean text
INK   = (26, 30, 34)
GRID  = (204, 210, 216)
AXIS  = (90, 98, 106)
SER1  = (26, 82, 148)
SER2  = (176, 74, 26)
FILL1 = (26, 82, 148)


class Plot:
    def __init__(self, w, h, xlabel, ylabel, title, xlim, ylim, xticks, yticks,
                 ytickfmt="{:.0f}", xtickfmt="{:.0f}"):
        self.W, self.H = w * SCALE, h * SCALE
        self.im = Image.new("RGB", (self.W, self.H), "white")
        self.d = ImageDraw.Draw(self.im)
        self.L, self.R = 86 * SCALE, 26 * SCALE
        self.T, self.B = 44 * SCALE, 62 * SCALE
        self.x0, self.x1 = xlim
        self.y0, self.y1 = ylim
        self.px0, self.px1 = self.L, self.W - self.R
        self.py0, self.py1 = self.H - self.B, self.T
        f_t, f_a, f_l = FB(15 * SCALE), F(12 * SCALE), F(12 * SCALE)
        self.d.text((self.L, 14 * SCALE), title, font=f_t, fill=INK)
        # grid + ticks
        for v in yticks:
            y = self.py(v)
            self.d.line([(self.px0, y), (self.px1, y)], fill=GRID, width=SCALE)
            t = ytickfmt.format(v)
            bb = self.d.textbbox((0, 0), t, font=f_a)
            self.d.text((self.px0 - 10 * SCALE - (bb[2] - bb[0]), y - (bb[3] - bb[1]) / 2 - 2 * SCALE),
                        t, font=f_a, fill=AXIS)
        for v in xticks:
            x = self.px(v)
            self.d.line([(x, self.py1), (x, self.py0)], fill=GRID, width=SCALE)
            t = xtickfmt.format(v)
            bb = self.d.textbbox((0, 0), t, font=f_a)
            self.d.text((x - (bb[2] - bb[0]) / 2, self.py0 + 9 * SCALE), t, font=f_a, fill=AXIS)
        self.d.line([(self.px0, self.py0), (self.px1, self.py0)], fill=AXIS, width=SCALE)
        self.d.line([(self.px0, self.py0), (self.px0, self.py1)], fill=AXIS, width=SCALE)
        bb = self.d.textbbox((0, 0), xlabel, font=f_l)
        self.d.text(((self.px0 + self.px1) / 2 - (bb[2] - bb[0]) / 2, self.H - 30 * SCALE),
                    xlabel, font=f_l, fill=INK)
        self.ylabel, self.f_l = ylabel, f_l

    def px(self, v): return self.px0 + (v - self.x0) / (self.x1 - self.x0) * (self.px1 - self.px0)
    def py(self, v): return self.py0 + (v - self.y0) / (self.y1 - self.y0) * (self.py1 - self.py0)

    def line(self, pts, colour, width=2, dash=False):
        pts = [(self.px(a), self.py(b)) for a, b in pts]
        if not dash:
            self.d.line(pts, fill=colour, width=width * SCALE, joint="curve")
        else:
            for (ax, ay), (bx, by) in zip(pts, pts[1:]):
                n = max(2, int(((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5 / (9 * SCALE)))
                for i in range(0, n, 2):
                    t0, t1 = i / n, min(1.0, (i + 1) / n)
                    self.d.line([(ax + (bx - ax) * t0, ay + (by - ay) * t0),
                                 (ax + (bx - ax) * t1, ay + (by - ay) * t1)],
                                fill=colour, width=width * SCALE)

    def dots(self, pts, colour, r=4):
        for a, b in pts:
            x, y = self.px(a), self.py(b)
            self.d.ellipse([x - r * SCALE, y - r * SCALE, x + r * SCALE, y + r * SCALE],
                           fill=colour, outline="white", width=SCALE)

    def legend(self, entries, x=None, y=None):
        f = F(12 * SCALE)
        x = self.px0 + 14 * SCALE if x is None else x
        y = self.py1 + 10 * SCALE if y is None else y
        for label, colour, style in entries:
            if style == "dash":
                for i in range(0, 26 * SCALE, 8 * SCALE):
                    self.d.line([(x + i, y + 7 * SCALE), (x + i + 4 * SCALE, y + 7 * SCALE)],
                                fill=colour, width=2 * SCALE)
            else:
                self.d.line([(x, y + 7 * SCALE), (x + 26 * SCALE, y + 7 * SCALE)],
                            fill=colour, width=2 * SCALE)
                self.d.ellipse([x + 13 * SCALE - 4 * SCALE, y + 7 * SCALE - 4 * SCALE,
                                x + 13 * SCALE + 4 * SCALE, y + 7 * SCALE + 4 * SCALE],
                               fill=colour, outline="white", width=SCALE)
            self.d.text((x + 33 * SCALE, y), label, font=f, fill=INK)
            y += 20 * SCALE

    def save(self, name):
        im = self.im
        # rotated y label
        lab = Image.new("RGB", (self.H, 24 * SCALE), "white")
        ImageDraw.Draw(lab).text((0, 0), self.ylabel, font=self.f_l, fill=INK)
        lab = lab.rotate(90, expand=True)
        bb = lab.getbbox()
        im.paste(lab.crop(bb), (10 * SCALE, int((self.py0 + self.py1) / 2 - (bb[3] - bb[1]) / 2)))
        im = im.resize((self.W // SCALE, self.H // SCALE), Image.LANCZOS)
        p = os.path.join(FIGS, name)
        im.save(p, dpi=(200, 200))
        print("wrote", p, im.size)


# ---- data straight out of logs/build.log -------------------------------------
ROOT = "/home/ahmedjk34/Desktop/Work_Dev/Miscellaneous/hardware-grad-project"
txt = open(os.path.join(ROOT, "logs/build.log")).read()
builds = re.findall(r"BUILD\s+\S+ \S+\s+B (\d+) (\d+) (\d+)(.*?)build finished, total ([\d.]+)s", txt, re.S)
rows = []
for c, r, l, body, total in builds:
    d = {int(m.group(1)): float(m.group(3))
         for m in re.finditer(r"phase (\d+) (\w+) took ([\d.]+)s", body)}
    rows.append((int(c), int(r), int(l), d, float(total)))

# Chart 1 — phase 8 (outbound) and phase 13 (return home) against column index,
# for the row-0 builds in VERTICAL mode. A real 90-degree claw rotation shows up
# as phase 9 > 1 s, which is how the single horizontal-mode build is excluded.
vert = [x for x in rows if x[3][9] < 1.0]
out  = [(c, d[8])  for c, r, l, d, t in vert if r == 0]
home = [(c, d[13]) for c, r, l, d, t in vert if r == 0]
def _means(pts):
    g = {}
    for a, b in pts:
        g.setdefault(a, []).append(b)
    return sorted((k, sum(v) / len(v)) for k, v in g.items())
mo, mh = _means(out), _means(home)
p = Plot(560, 340,
         "Target column index (row 0, vertical mode)",
         "Phase duration (s)",
         "X/Y traverse time against column index",
         (0, 6), (0, 6), [0, 1, 2, 3, 4, 5, 6], [0, 1, 2, 3, 4, 5, 6],
         ytickfmt="{:.0f}")
# least-squares fit through the outbound points
n = len(out); sx = sum(a for a, _ in out); sy = sum(b for _, b in out)
sxx = sum(a * a for a, _ in out); sxy = sum(a * b for a, b in out)
m = (n * sxy - sx * sy) / (n * sxx - sx * sx); b0 = (sy - m * sx) / n
p.line([(0, b0), (6, b0 + 6 * m)], (150, 158, 166), width=1, dash=True)
p.line(mo, SER1); p.dots(out, SER1)
p.line(mh, SER2); p.dots(home, SER2)
p.legend([("phase 8 - move X/Y to the target cell", SER1, "line"),
          ("phase 13 - return X/Y to the origin", SER2, "line"),
          ("least-squares fit: t = %.2f + %.3f x col  (s)" % (b0, m), (150, 158, 166), "dash")],
         y=p.py1 + 8 * SCALE)
p.save("fig-traverse-vs-column.png")
print("fit: t = %.4f + %.4f*col" % (b0, m))

# Chart 2 — phase 10 descent against block level, measured against the
# firmware's own ms= prediction.
lev = sorted((l, d[10]) for c, r, l, d, t in rows if (c, r) == (3, 2))
pred = [(k, (2565 - 145.0 * k + 5) / 1000.0) for k in range(0, 5)]
p = Plot(560, 340,
         "Target block level",
         "Phase 10 duration (s)",
         "Descent to level: measured against firmware ETA",
         (0, 4), (1.6, 3.2), [0, 1, 2, 3, 4],
         [1.6, 1.8, 2.0, 2.2, 2.4, 2.6, 2.8, 3.0, 3.2], ytickfmt="{:.1f}")
p.line(pred, (150, 158, 166), width=1, dash=True)
p.line(lev, SER1); p.dots(lev, SER1)
p.legend([("measured on the rig", SER1, "line"),
          ("firmware ETA, ms = 2565 - 145K", (150, 158, 166), "dash")],
         y=p.py1 + 8 * SCALE)
p.save("fig-descent-vs-level.png")
print("levels:", lev)
