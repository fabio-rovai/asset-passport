"""Write docs/assets/border.svg, the animated picture at the top of the README,
and the README's alt text for it, from the engine's output. Nothing in either is
typed by hand: every number and label is read from site/data/verdicts.json, the
gate names from site/index.html, the stamp words from site/app.js, the type
chart and type colours from site/battle.js, the pixel art from site/sprites.js,
and the rule that types the sword from games/craft/profile.ttl.

    python3 scripts/readme_svg.py            # write docs/assets/border.svg and the README's picture line
    python3 scripts/readme_svg.py --check    # regenerate both in memory; exit 1 with a diff if either differs

The picture plays three crossings in a loop with CSS keyframes, which run when
GitHub shows an SVG as an <img> (scripts do not). Below 600 px of rendered width
(a phone) it switches to a narrow layout with fewer, larger words. Under
prefers-reduced-motion it shows a still storyboard of the same three outcomes.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
VERDICTS = SITE / "data" / "verdicts.json"
OUT = ROOT / "docs" / "assets" / "border.svg"
README = ROOT / "README.md"
CRAFT_PROFILE = ROOT / "games" / "craft" / "profile.ttl"
PAGE = "https://fabio-rovai.github.io/asset-passport/"
PICTURE = ("<!-- picture:start -->", "<!-- picture:end -->")

W, H = 1200, 440
ACT = 7.0            # seconds per act
LOOP = 3 * ACT       # one loop plays all three acts
NARROW = 600         # rendered width in CSS px below which the narrow layout shows
MAX_GATES = 5        # the desk has room for this many gate rows

# Palette: the page's own colours (site/style.css and the games' canvases).
PAPER, PAPER2, GUILL, INK, INK2, RULE = "#e6ebe7", "#f5f8f5", "#d3ddd7", "#16202a", "#4a5a62", "#b6c3bc"
OK, LOSS, NO = "#2747a8", "#9a5a12", "#b3302a"
OK_D, LOSS_D, NO_D = "#91a8ff", "#e3a54c", "#ff7b6d"     # the page's dark-theme stamps, used on the dark caption band
NAVY, GREEN = "#1d1f2b", "#7bd36a"
CREAM, TEAL, TEAL_D, SOFT_INK = "#fffaf0", "#35b3a6", "#2f8f86", "#3a3550"

F_BODY = "system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
F_MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace"
F_COND = "'Arial Narrow', 'Roboto Condensed', 'Helvetica Neue', Arial, sans-serif"

WORDS = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]
ORDINALS = ["", "first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth"]


# ------------------------------------------------------------------ sources

def _src(name: str) -> str:
    return (SITE / name).read_text()


def type_chart(js: str) -> tuple[dict, dict]:
    """site/battle.js's CHART (attacker -> defender -> multiplier) and TIMES (multiplier -> word)."""
    body = re.search(r"const CHART = \{(.*?)\n  \};", js, re.S).group(1)
    chart = {a: {d: float(m) for d, m in re.findall(r"(\w+): ([\d.]+)", row)}
             for a, row in re.findall(r"(\w+): \{([^}]*)\}", body)}
    times = {float(k): v for k, v in re.findall(r'([\d.]+): "(\w+)"', re.search(r"const TIMES = \{([^}]*)\}", js).group(1))}
    return chart, times


def type_colours(js: str) -> dict:
    """site/battle.js's TYPE_COLOR: the colour of each type's chip on the battle screen."""
    return dict(re.findall(r'(\w+): "(#[0-9a-fA-F]{6})"', re.search(r"const TYPE_COLOR = \{([^}]*)\}", js).group(1)))


def pixel_art(js: str) -> tuple[dict, dict]:
    """site/sprites.js's palette and Blockcraft item art, keyed by category."""
    px = dict(re.findall(r'(\w): "(#[0-9a-fA-F]{6})"', re.search(r"const PX = \{(.*?)\};", js, re.S).group(1)))
    craft = {cat: re.findall(r'"([^"]+)"', rows)
             for cat, rows in re.findall(r"(\w+): \[(.*?)\]", re.search(r"const CRAFT = \{(.*?)\n  \};", js, re.S).group(1), re.S)}
    return px, craft


def gate_names(html: str) -> dict:
    return dict(re.findall(r'data-gate="(\w+)"[^>]*><span class="gn">([^<]+)</span>', html))


def stamp_words(js: str) -> dict:
    """site/app.js's stampFor: the word and the line under it, for each verdict."""
    ok = re.search(r'case "converted": case "accepted": return \["ok", "(\w+)", v\.verdict === "converted" \? "(\w+)"', js)
    loss = re.search(r'case "converted_with_loss": return \["loss", "(\w+)", "([^"]+)"\]', js)
    no = re.search(r'case "refused": return \["no", "(\w+)", `([^$`]+)\$\{', js)
    return {"converted": (ok.group(1), ok.group(2)), "converted_with_loss": (loss.group(1), loss.group(2)),
            "refused": (no.group(1), no.group(2).strip())}


def num(x) -> str:
    return str(int(x)) if float(x) == int(x) else str(x)


def pct(n, of) -> str:
    """As the page writes it (site/app.js pct)."""
    return f"{round(n / of * 100)}%"


def facts(data: dict, chart: dict, times: dict, gates: dict, stamps: dict, colours: dict | None = None,
          profile: str | None = None) -> dict:
    """Everything the picture says, read from the data and the page's sources.

    The acts are drawn for one story: the sword is admitted and converted, the
    Blast Block is refused, Emberfox is admitted with losses, and each one
    crossed as a signed passport that the receiving side unpacked. If the
    engine now says otherwise, this stops instead of drawing a picture that
    disagrees with it."""
    g = data["games"]
    craft, battle = g["craft"], g["battle"]
    item = {k: {i["id"]: i for i in g[k]["items"]} for k in g}
    sword, blast, fox = item["craft"]["crystal_sword"], item["craft"]["blast_block"], item["battle"]["emberfox"]
    tv = data["transfers"]
    sv, bv, fv = tv["craft:crystal_sword"], tv["craft:blast_block"], tv["battle:emberfox"]
    for v, want in ((sv, "converted"), (bv, "refused"), (fv, "converted_with_loss")):
        if v["verdict"] != want:
            raise SystemExit(f"readme_svg: the picture tells {want} for {v['item_iri']}, and the engine now says "
                             f"{v['verdict']}; redraw the act before regenerating")
        # Every gate before the one that decided is drawn as a pass. That holds
        # only for a passport that was unpacked and whose signature verified.
        unpacked = any(t.get("tool") == "onto_unpack" for t in v.get("transcript") or [])
        if not unpacked or (v.get("signature") or {}).get("verified") is not True:
            raise SystemExit(f"readme_svg: the picture draws {v['item_iri']} crossing as a signed passport that "
                             f"passed each gate before its stop, and this verdict is not that (unpacked: {unpacked}, "
                             f"signature verified: {(v.get('signature') or {}).get('verified')}); redraw the act")
    order = data["gates"]
    if not 1 <= len(order) <= MAX_GATES:
        raise SystemExit(f"readme_svg: the desk has room for {MAX_GATES} gates and the data lists {len(order)}; "
                         "redraw the desk before regenerating")
    wild = battle["scene"]["wild"]
    rock = sv["conversion"]["typeInTarget"].split(":")[-1]
    # The captions say Blockcraft's own rule types the sword; check the rule is there.
    profile = CRAFT_PROFILE.read_text() if profile is None else profile
    rule = (rf"owl:onProperty ga:madeOf ; owl:hasValue craft:{re.escape(sword['material'])} \]\s*rdfs:subClassOf "
            rf"\[ a owl:Restriction ; owl:onProperty ga:elementalType ; owl:hasValue ga:{re.escape(rock)} \]")
    if not re.search(rule, profile):
        raise SystemExit(f"readme_svg: the picture says {craft['label']}'s profile types anything made of "
                         f"{sword['material']} as {rock}, and games/craft/profile.ttl no longer says so; "
                         "redraw act 1 before regenerating")
    mult = chart.get(rock, {}).get(wild["type"], 1)
    hit = round(sv["conversion"]["damageInTarget"] * mult)
    stop = order.index(bv["stage"]) + 1
    loss = fv["losses"][0]["message"]
    # The contract's message is written for any item ("this thing"); the picture names the item.
    loss = loss.replace("this thing's", f"{fox['name']}'s").replace("this thing", fox["name"])
    colours = colours or {}
    return {
        "craft": craft["label"], "battle": battle["label"],
        "cmax": craft["max_player_health"], "bmax": battle["max_player_health"],
        "gates": [gates[k] for k in order], "n": len(order), "stop": stop,
        "sword": sword, "blast": blast, "fox": fox, "sv": sv, "bv": bv, "fv": fv,
        "rock": rock, "mult": mult, "how": times.get(mult, f"x{num(mult)}"), "hit": hit, "loss": loss,
        "wild": wild, "zombie": craft["scene"]["enemy"]["name"],
        "rock_colour": colours.get(rock, "#b59a5a"), "fire_colour": colours.get(fox["type"], "#f08a3c"),
        "wild_colour": colours.get(wild["type"], "#f08a3c"),
        "stamp_ok": stamps["converted"], "stamp_loss": stamps["converted_with_loss"],
        "stamp_no": (stamps["refused"][0], f"{stamps['refused'][1]} {stop}"),
    }


def captions(f: dict) -> list[dict]:
    """Per act: the stamp tone, where it goes, the verdict, the one short line the
    animation shows, and the full sentences the storyboard, <desc> and alt text carry."""
    s, b, x = f["sword"], f["blast"], f["fox"]
    sv, bv, fv = f["sv"]["conversion"], f["bv"]["conversion"], f["fv"]["conversion"]
    cm, bm = f["cmax"], f["bmax"]
    w = f["wild"]
    gate = f["gates"][f["stop"] - 1]
    a1 = {"tone": "ok", "route": f"{s['name']}: {f['craft']} to {f['battle']}.",
          "verdict": f"{f['stamp_ok'][0]}, {f['stamp_ok'][1]}.",
          "line": f"{f['rock']} beats {w['type']}, so it does {f['how']} damage: {w['name']} takes {num(f['hit'])}.",
          "more": [
              f"It hits for {num(s['attack'])} of a player's {num(cm)} HP ({pct(s['attack'], cm)}), and becomes a "
              f"{f['rock']}-type move with power {num(sv['damageInTarget'])} of {num(bm)}.",
              f"{f['craft']}'s rule says anything made of {s['material']} is {f['rock']}-typed, and the engine "
              f"derived the {s['name']}'s type from it.",
              f"{f['rock']} beats {w['type']}: {f['how']} damage. It hits the {w['type']}-type {w['name']} for "
              f"{num(f['hit'])}.",
          ]}
    a2 = {"tone": "no", "route": f"{b['name']}: {f['craft']} to {f['battle']}.",
          "verdict": f"{f['stamp_no'][0]} {f['stamp_no'][1]}, {gate}.",
          "line": f"It would hit for {num(bv['damageInTarget'])} of a creature's {num(bm)} HP, so it is turned back.",
          "more": [
              f"It blasts for {num(b['blastDamage'])} of {num(cm)} HP ({pct(b['blastDamage'], cm)}), so it would "
              f"arrive as {num(bv['damageInTarget'])} of {num(bm)}.",
              f["bv"]["refusals"][0]["message"],
              "The border turns it back, and it never arrives.",
          ]}
    a3 = {"tone": "loss", "route": f"{x['name']}: {f['battle']} to {f['craft']}.",
          "verdict": f"{f['stamp_loss'][0]}, {f['stamp_loss'][1]}.",
          "line": f"As a pet, {x['moveName']} hits the {f['zombie']} for {num(fv['damageInTarget'])} of {num(cm)}.",
          "more": [
              f"{x['name']} is a {x['type']}-type creature. Its {x['moveName']} has power {num(x['movePower'])} "
              f"of {num(bm)} ({pct(x['movePower'], bm)}).",
              f"It arrives as a pet with {num(fv['hitPointsInTarget'])} of {num(cm)} HP, and its {x['moveName']} "
              f"hits a {f['zombie']} for {num(fv['damageInTarget'])} of {num(cm)}.",
              f["loss"],
          ]}
    return [a1, a2, a3]


def alt_text(f: dict) -> str:
    """What the picture shows, for a screen reader or a blocked image: the README's alt text."""
    s, b, x, w = f["sword"], f["blast"], f["fox"], f["wild"]
    n, stop = f["n"], f["stop"]
    every = f"all {WORDS[n]} gates" if n > 1 else "the one gate"
    passed = f"passes {WORDS[stop - 1]} gate{'s' if stop - 1 != 1 else ''}, is refused at the {ORDINALS[stop]}" \
        if stop > 1 else "is refused at the first gate"
    return (f"Three crossings at the border desk between {f['craft']} and {f['battle']}, each checked at "
            f"{WORDS[n]} gates in order. "
            f"A {s['name']} leaves {f['craft']}, passes {every}, is stamped {f['stamp_ok'][0].lower()}, "
            f"{f['stamp_ok'][1]}, and arrives in {f['battle']} as a {f['rock']}-type move with power "
            f"{num(f['sv']['conversion']['damageInTarget'])} of {num(f['bmax'])}. {f['rock']} beats {w['type']}, so "
            f"it does {f['how']} damage and hits the {w['type']}-type {w['name']} for {num(f['hit'])}. "
            f"A {b['name']} {passed}, the {f['gates'][stop - 1].lower()}, because it would hit for "
            f"{num(f['bv']['conversion']['damageInTarget'])} of a creature's {num(f['bmax'])} HP, and it goes back to "
            f"{f['craft']}. "
            f"{x['name']} leaves {f['battle']}, passes {every}, is stamped {f['stamp_loss'][0].lower()}, "
            f"{f['stamp_loss'][1]}, and arrives in {f['craft']} as a pet whose {x['moveName']} hits the "
            f"{f['zombie']} for {num(f['fv']['conversion']['damageInTarget'])} of {num(f['cmax'])}, "
            f"without its {x['type']} type.")


# ------------------------------------------------------------------ drawing helpers

def r1(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s == "-0" else s


def pixels(rows: list[str], px: dict, x: float, y: float, cell: float) -> str:
    """Pixel art as runs of same-coloured cells, one rect per run."""
    out = []
    for j, row in enumerate(rows):
        i = 0
        while i < len(row):
            c = row[i]
            k = i
            while k < len(row) and row[k] == c:
                k += 1
            if c in px:
                out.append(f'<rect x="{r1(x + i * cell)}" y="{r1(y + j * cell)}" width="{r1((k - i) * cell)}" '
                           f'height="{r1(cell)}" fill="{px[c]}"/>')
            i = k
    return "".join(out)


def craft_icon(rows, px, size: float) -> str:
    """Centred on (0, 0) in a box of side size, as Sprites.icon draws it."""
    cell = size * 0.84 / max(len(rows[0]), len(rows))
    return pixels(rows, px, -cell * len(rows[0]) / 2, -cell * len(rows) / 2, cell)


def blob(x, y, rx, ry, fill, w) -> str:
    return (f'<ellipse cx="{r1(x)}" cy="{r1(y)}" rx="{r1(rx)}" ry="{r1(ry)}" fill="{fill}" '
            f'stroke="{SOFT_INK}" stroke-width="{r1(w)}"/>')


def tri(pts, fill, w) -> str:
    p = " ".join(f"{r1(pts[i])},{r1(pts[i + 1])}" for i in range(0, len(pts), 2))
    return f'<polygon points="{p}" fill="{fill}" stroke="{SOFT_INK}" stroke-width="{r1(w)}" stroke-linejoin="round"/>'


def eye(x, y, r) -> str:
    return (f'<circle cx="{r1(x)}" cy="{r1(y)}" r="{r1(r)}" fill="{SOFT_INK}"/>'
            f'<circle cx="{r1(x - r * 0.3)}" cy="{r1(y - r * 0.35)}" r="{r1(r * 0.38)}" fill="#fff"/>')


def flame(x, y, s, cls="") -> str:
    c = f' class="{cls}"' if cls else ""
    return (f'<g{c}><path d="M{r1(x - s * .3)} {r1(y)}Q{r1(x - s * .35)} {r1(y - s * .6)} {r1(x)} {r1(y - s)}'
            f'Q{r1(x + s * .35)} {r1(y - s * .55)} {r1(x + s * .3)} {r1(y)}Z" fill="#ff8a3d" stroke="{SOFT_INK}" '
            f'stroke-width="{r1(max(1, s * .07))}"/><path d="M{r1(x - s * .13)} {r1(y)}Q{r1(x)} {r1(y - s * .5)} '
            f'{r1(x + s * .13)} {r1(y)}Z" fill="#ffe08a"/></g>')


def emberfox(x, y, s) -> str:
    """site/sprites.js CREATURE.Emberfox, standing on (x, y)."""
    w = max(1.2, s * 0.05)
    return "".join([
        flame(x - s * .5, y - s * .28, s * .42, "flick"),
        blob(x - s * .05, y - s * .3, s * .36, s * .26, "#f08a3c", w),
        blob(x + s * .22, y - s * .62, s * .26, s * .24, "#f08a3c", w),
        tri([x + s * .06, y - s * .78, x + s * .12, y - s * 1.02, x + s * .24, y - s * .84], "#f08a3c", w),
        tri([x + s * .26, y - s * .84, x + s * .38, y - s * 1.02, x + s * .42, y - s * .76], "#f08a3c", w),
        blob(x + s * .36, y - s * .54, s * .12, s * .09, "#fff1dc", w),
        eye(x + s * .27, y - s * .66, s * .045),
        *(blob(x + dx * s, y - s * .06, s * .07, s * .06, "#c96a26", w) for dx in (-0.25, 0.12)),
    ])


def cindermole(x, y, s) -> str:
    w = max(1.2, s * 0.05)
    return "".join([
        blob(x, y - s * .4, s * .42, s * .4, "#9a6a4a", w),
        blob(x, y - s * .3, s * .24, s * .2, "#e8c9a0", w),
        blob(x, y - s * .46, s * .08, s * .06, "#e86a8a", w),
        eye(x - s * .16, y - s * .58, s * .05), eye(x + s * .16, y - s * .58, s * .05),
        flame(x, y - s * .78, s * .42, "flick"),
        *(blob(x + dx * s, y - s * .08, s * .12, s * .07, "#7a4e34", w) for dx in (-0.32, 0.32)),
    ])


def shellbit(x, y, s) -> str:
    w = max(1.2, s * 0.05)
    return "".join([
        blob(x, y - s * .38, s * .44, s * .36, "#5cc6e8", w),
        blob(x, y - s * .42, s * .36, s * .3, "#2f8f86", w),
        f'<path d="M{r1(x - s * .2)} {r1(y - s * .52)}H{r1(x + s * .2)}M{r1(x)} {r1(y - s * .7)}V{r1(y - s * .16)}" '
        f'stroke="#bfeee6" stroke-width="{r1(w)}"/>',
        blob(x, y - s * .82, s * .2, s * .17, "#5cc6e8", w),
    ])


def rects(spec, x0, g, k) -> str:
    """Rects given in site/craft.js's canvas units (x offset, y above ground, w, h), scaled by k."""
    return "".join(f'<rect x="{r1(x0 + dx * k)}" y="{r1(g - up * k)}" width="{r1(w * k)}" height="{r1(h * k)}" fill="{c}"/>'
                   for c, dx, up, w, h in spec)


# site/craft.js player() and zombie(), as (colour, x offset, height above ground, width, height).
PLAYER = [("#4b5d3a", 3, 12, 4, 12), ("#4b5d3a", 9, 12, 4, 12), ("#c8553d", 2, 24, 12, 12), ("#5a3a1e", 2, 15, 12, 2),
          ("#e8b48a", 3, 31, 10, 8), ("#e0a93a", 2, 35, 12, 5), ("#e0a93a", 12, 31, 5, 2), ("#1d1f2b", 9, 27, 2, 2),
          ("#e8b48a", 14, 22, 3, 8)]
ZOMBIE = [("#4a4f5a", 3, 12, 4, 12), ("#4a4f5a", 9, 12, 4, 12), ("#7a3346", 2, 24, 12, 12), ("#b4b0bf", 3, 32, 10, 9),
          ("#b4b0bf", -3, 22, 5, 3), ("#1d1f2b", 4, 28, 2, 2), ("#1d1f2b", 8, 28, 2, 2)]


def block(x, y, top) -> str:
    s = (f'<rect x="{x}" y="{y}" width="20" height="20" fill="#d4a868"/><rect x="{x}" y="{y + 6}" width="20" height="3" fill="#b9884c"/>'
         f'<rect x="{x}" y="{y + 15}" width="20" height="1" fill="#b9884c"/><rect x="{x + 19}" y="{y}" width="1" height="20" fill="#9c6f3a"/>')
    if top:
        s += f'<rect x="{x}" y="{y}" width="20" height="4" fill="#7fb069"/>'
    return s


def text(x, y, s, size, fill, family=F_BODY, weight=None, anchor=None, extra="", cls=None) -> str:
    a = [f'x="{r1(x)}"', f'y="{r1(y)}"', f'font-size="{size}"', f'fill="{fill}"', f'font-family="{family}"']
    if weight:
        a.append(f'font-weight="{weight}"')
    if anchor:
        a.append(f'text-anchor="{anchor}"')
    if cls:
        a.append(f'class="{cls}"')
    return f'<text {" ".join(a)}{extra}>{escape(s)}</text>'


def chip(label: str, colour: str) -> str:
    """A type chip as the battle screen draws one, centred on (0, 0)."""
    w = max(64, 11 * len(label) + 18)
    return (f'<g class="chip"><rect x="{r1(-w / 2)}" y="-12" width="{w}" height="24" rx="4" fill="{colour}" '
            f'stroke="{SOFT_INK}" stroke-width="1.2"/>'
            + text(0, 6, label.upper(), 17, "#fff", F_BODY, "800", "middle",
                   f' stroke="{SOFT_INK}" stroke-width="2.4" paint-order="stroke"') + "</g>")


# ------------------------------------------------------------------ animation

class Anim:
    """CSS keyframes over one loop. Each track is a list of (seconds, declarations),
    held flat before its first point and after its last."""

    def __init__(self):
        self.css: list[str] = []
        self.n = 0

    def track(self, pts: list[tuple], ease: str | None = None) -> str:
        self.n += 1
        name = f"k{self.n}"
        pts = sorted(pts, key=lambda p: p[0])
        if pts[0][0] > 0:
            pts = [(0.0, pts[0][1])] + pts
        if pts[-1][0] < LOOP:
            pts = pts + [(LOOP, pts[-1][1])]
        rows = []
        for t, decl in pts:
            e = f"animation-timing-function:{ease};" if ease else ""
            rows.append(f"{r1(min(100, max(0, t / LOOP * 100)))}%{{{decl}{e}}}")
        self.css.append(f"@keyframes {name}{{{''.join(rows)}}}.{name}{{animation:{name} {r1(LOOP)}s linear infinite}}")
        return name


def tf(x, y, rot=0.0, sc=1.0, sy=None) -> str:
    sy = sc if sy is None else sy
    return f"transform:translate({r1(x)}px,{r1(y)}px) rotate({r1(rot)}deg) scale({r1(sc)},{r1(sy)});"


def op(v) -> str:
    return f"opacity:{r1(v)};"


def on_between(t0, t1, fade=0.25) -> list[tuple]:
    return [(t0 - fade if t0 >= fade else 0, op(0)), (t0, op(1)), (t1, op(1)), (t1 + fade, op(0))]


def moves(pts) -> list[tuple]:
    """Keyframes from (seconds, x, y, scale, rotation, opacity) points."""
    return [(t, op(o) + tf(x, y, r, s)) for t, x, y, s, r, o in pts]


# ------------------------------------------------------------------ layout

CRAFT_X, DESK_X, BATTLE_X, TOP, PANEL_W, DESK_W, PANEL_H = 24, 364, 856, 24, 320, 472, 248
GROUND = 222
HOME_CRAFT = (68, 150)         # a Blockcraft item's slot, behind the player
HOME_BATTLE = (1040, 196)      # where a Pocket Battlers thing waits, right of Shellbit
DESK_SPOT = (748, 100)         # where a passport waits on the desk, in the stamp column
STAMP_AT = (750, 200)
PET_AT = (196, GROUND)         # the pet stands here, clear of the player
WILD_AT = (1098, 150)
ZOMBIE_X = 280
ROCK_AT = (1000, 246)          # the converted move's chip, beside Shellbit
GATE_Y0, GATE_DY = 84, 36
CAP_Y = 288
LAMP_SHIFT = -200                  # where the lamps move in the narrow layout
# Things cross the desk above it, so they never pass over a label: up through a
# gap in Blockcraft's title bar, along a lane over the desk's frame, and down
# into the empty stamp column.
CORRIDOR_X, LANE_Y = 222, 14
LANE_IN, CORRIDOR_IN = 0.6, 0.65   # their scale on the lane and in the corridor
ARRIVE = 1.45                      # an item is on the desk this long after its act starts
LEAVE = 3.4                        # and leaves it then


def static_scene(f: dict, px: dict) -> str:
    out = []
    # The panel the picture sits on, so it reads on a light or a dark page.
    out.append(f'<rect width="{W}" height="{H}" rx="18" fill="{PAPER}"/>')
    out.append('<g fill="none" stroke="' + GUILL + '" stroke-width="1">'
               + "".join(f'<circle cx="120" cy="90" r="{r}"/>' for r in range(14, 420, 14))
               + "".join(f'<circle cx="1080" cy="330" r="{r}"/>' for r in range(18, 420, 18)) + "</g>")
    out.append(f'<rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="17" fill="none" stroke="{RULE}" stroke-width="2"/>')

    # Blockcraft: a dark pixel frame with a green title.
    x0 = CRAFT_X
    out.append(f'<rect x="{x0}" y="{TOP}" width="{PANEL_W}" height="{PANEL_H}" fill="{NAVY}"/>'
               f'<rect x="{x0 + 4}" y="{TOP + 4}" width="{PANEL_W - 8}" height="{PANEL_H - 8}" fill="none" stroke="#2c3044" stroke-width="2"/>')
    out.append(text(x0 + 16, 54, f["craft"].upper(), 20, GREEN, F_MONO, "700", cls="w"))
    out.append(text(x0 + 16, 57, f["craft"].upper(), 26, GREEN, F_MONO, "700", cls="n"))
    out.append(text(x0 + PANEL_W - 16, 54, f"{num(f['cmax'])} HP", 18, "#c9cfe0", F_MONO, "700", "end", cls="w"))
    out.append(text(x0 + PANEL_W - 16, 57, f"{num(f['cmax'])} HP", 28, "#e2e6f0", F_MONO, "700", "end", cls="n"))
    sx, sy, sw, sh = x0 + 12, 66, PANEL_W - 24, 194
    out.append(f'<clipPath id="cc"><rect x="{sx}" y="{sy}" width="{sw}" height="{sh}"/></clipPath><g clip-path="url(#cc)">')
    out.append(f'<rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" fill="#8fd3ff"/><rect x="{sx}" y="{sy}" width="{sw}" height="44" fill="#a9ddff"/>')
    out.append(f'<rect x="{sx + sw - 46}" y="{sy + 14}" width="26" height="26" fill="#fff3a0"/>'
               f'<rect x="{sx + 30}" y="{sy + 30}" width="54" height="12" fill="#fff"/><rect x="{sx + 42}" y="{sy + 22}" width="28" height="9" fill="#fff"/>'
               f'<rect x="{sx + 150}" y="{sy + 44}" width="40" height="9" fill="#fff"/>')
    for bx in range(sx, sx + sw, 20):
        out.append(block(bx, GROUND, True) + block(bx, GROUND + 20, False))
    out.append(rects(PLAYER, 92, GROUND, 2))
    # The item slot behind the player, where a Blockcraft thing starts and comes back to.
    out.append(f'<rect x="{HOME_CRAFT[0] - 25}" y="{HOME_CRAFT[1] - 25}" width="50" height="50" fill="#1d1f2b" '
               f'fill-opacity="0.12" stroke="#1d1f2b" stroke-opacity="0.55" stroke-width="2" stroke-dasharray="4 3"/>')
    out.append("</g>")

    # The border desk: security paper, the gates, a place for the stamp.
    out.append(f'<rect x="{DESK_X}" y="{TOP}" width="{DESK_W}" height="{PANEL_H}" rx="6" fill="{PAPER2}" stroke="{INK}" stroke-width="2"/>')
    out.append(text(DESK_X + 18, 56, "BORDER DESK", 22, INK, F_COND, "700", extra=' letter-spacing="2" font-stretch="condensed"', cls="hd"))
    out.append(f'<line x1="{DESK_X + 300}" y1="{TOP + 14}" x2="{DESK_X + 300}" y2="{TOP + PANEL_H - 14}" stroke="{RULE}" stroke-dasharray="4 4"/>')
    for i, name in enumerate(f["gates"]):
        y = GATE_Y0 + i * GATE_DY
        out.append(f'<line x1="{DESK_X + 14}" y1="{y - 22}" x2="{DESK_X + 288}" y2="{y - 22}" stroke="{RULE}" stroke-dasharray="3 3"/>')
        out.append(text(DESK_X + 18, y + 2, str(i + 1), 22, INK2, F_COND, "700", extra=' font-stretch="condensed"', cls="gnum"))
        out.append(text(DESK_X + 44, y, name, 19, INK, F_BODY, "600", cls="w"))
        out.append(f'<circle class="lamp" cx="{DESK_X + 270}" cy="{y - 6}" r="11" fill="#dfe6e2" stroke="{RULE}"/>')

    # Pocket Battlers: a cream frame with a rounded teal border.
    x0 = BATTLE_X
    out.append(f'<rect x="{x0}" y="{TOP}" width="{PANEL_W}" height="{PANEL_H}" rx="16" fill="{CREAM}" stroke="{TEAL}" stroke-width="4"/>'
               f'<rect x="{x0 + 6}" y="{TOP + 6}" width="{PANEL_W - 12}" height="{PANEL_H - 12}" rx="12" fill="none" stroke="{SOFT_INK}" stroke-width="1"/>')
    out.append(text(x0 + 16, 54, f["battle"].upper(), 20, TEAL_D, F_BODY, "800", cls="w"))
    narrow_title = len(f["battle"]) * 12 > 168          # squeeze a long name into the room the narrow HP leaves
    out.append(text(x0 + 16, 57, f["battle"].upper(), 26, TEAL_D, F_COND, "800", cls="n",
                    extra=' textLength="168" lengthAdjust="spacingAndGlyphs"' if narrow_title else ""))
    out.append(text(x0 + PANEL_W - 16, 54, f"{num(f['bmax'])} HP", 18, "#5a5470", F_BODY, "700", "end", cls="w"))
    out.append(text(x0 + PANEL_W - 16, 57, f"{num(f['bmax'])} HP", 28, "#3a3550", F_BODY, "800", "end", cls="n"))
    sx, sy, sw, sh = x0 + 12, 66, PANEL_W - 24, 194
    out.append(f'<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fdf6e3"/><stop offset="1" stop-color="#dff2cf"/></linearGradient>')
    out.append(f'<rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" rx="8" fill="url(#bg)" stroke="{SOFT_INK}" stroke-width="2"/>')
    out.append(f'<clipPath id="bc"><rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" rx="8"/></clipPath><g clip-path="url(#bc)">')
    out.append(blob(WILD_AT[0], WILD_AT[1], 56, 11, "#b6dc9c", 1))
    out.append(blob(sx + 64, sy + sh - 4, 66, 14, "#b6dc9c", 1))
    out.append(shellbit(sx + 64, sy + sh, 72))
    out.append("</g>")

    # The caption band: ink, so its text reads the same on a light or a dark page.
    out.append(f'<rect x="{CRAFT_X}" y="{CAP_Y}" width="{W - 2 * CRAFT_X}" height="{H - CAP_Y - 16}" rx="10" fill="{INK}"/>')
    return "".join(out)


def stamp(cx, cy, word, sub, colour, cls, grow="big") -> str:
    """A rubber stamp centred on (cx, cy), drawn around (0, 0) so the animation can place it."""
    w, h = 170, 84
    body = (f'<rect x="{-w / 2}" y="{-h / 2}" width="{w}" height="{h}" rx="5" fill="none" stroke="{colour}" stroke-width="4"/>'
            f'<rect x="{-w / 2 + 6}" y="{-h / 2 + 6}" width="{w - 12}" height="{h - 12}" rx="3" fill="none" stroke="{colour}" stroke-width="1.5"/>'
            + text(0, 4, word.upper(), 36, colour, F_COND, "800", "middle",
                   f' font-stretch="condensed" letter-spacing="1" textLength="{w - 36}" lengthAdjust="spacingAndGlyphs"')
            + text(0, 30, sub.upper(), 19, colour, F_COND, "700", "middle",
                   f' font-stretch="condensed" letter-spacing="1" textLength="{min(w - 32, 10 * len(sub) + 12)}" lengthAdjust="spacingAndGlyphs"'))
    return f'<g class="{cls}" opacity="0.94"><g class="{grow}">{body}</g></g>'


def to_desk_from_craft(t0: float, home) -> list[tuple]:
    """Up through the gap in Blockcraft's title bar, along the lane over the desk, down into the stamp column."""
    return [(t0, *home, 1, 0, 0), (t0 + .25, *home, 1, 0, 1), (t0 + .4, *home, 1, 0, 1),
            (t0 + .65, CORRIDOR_X, 100, CORRIDOR_IN, 0, 1), (t0 + .85, CORRIDOR_X, LANE_Y, LANE_IN, 0, 1),
            (t0 + 1.2, DESK_SPOT[0], LANE_Y, LANE_IN, 0, 1), (t0 + ARRIVE, *DESK_SPOT, 1, 0, 1)]


def back_over_desk(t0: float, start, rot=0.0) -> list[tuple]:
    """From the stamp column up to the lane, and along it to Blockcraft's corridor."""
    return [(t0, *start, 1, rot, 1), (t0 + .25, DESK_SPOT[0], LANE_Y, LANE_IN, rot / 2, 1),
            (t0 + .65, CORRIDOR_X, LANE_Y, LANE_IN, 0, 1), (t0 + .9, CORRIDOR_X, 100, CORRIDOR_IN, 0, 1)]


def live(f: dict, px: dict, art: dict) -> tuple[str, str]:
    """The animated layer and its CSS."""
    a = Anim()
    out = []
    S, B, X = 0.0, ACT, 2 * ACT                         # when each act starts
    n = f["n"]
    last = n - 1
    lit = [ARRIVE + 0.2 + i * 0.24 for i in range(n)]   # when each gate lights, from an act's start
    stop = f["stop"] - 1
    end = ACT - 0.3                                     # what an act shows holds until here, then fades

    # Gates: a reading bar runs down the list, and each lamp lights as the bar passes.
    bar = []
    for start in (S, B, X):
        upto = stop if start == B else last
        bar += [(start + lit[0] - 0.3, op(0) + tf(0, 0)), (start + lit[0] - 0.15, op(1) + tf(0, 0))]
        for i in range(1, upto + 1):
            bar += [(start + lit[i] - 0.22, op(1) + tf(0, (i - 1) * GATE_DY)), (start + lit[i] - 0.1, op(1) + tf(0, i * GATE_DY))]
        bar += [(start + lit[upto] + 0.25, op(1) + tf(0, upto * GATE_DY)), (start + lit[upto] + 0.45, op(0) + tf(0, upto * GATE_DY))]
    out.append(f'<g class="{a.track(bar)}"><rect x="{DESK_X + 8}" y="{GATE_Y0 - 22}" width="292" height="{GATE_DY}" '
               f'fill="{OK}" opacity="0.10"/></g>')
    for i in range(n):
        y = GATE_Y0 + i * GATE_DY - 6
        cx = DESK_X + 270
        passes, fails = [], []
        # Every act passes each gate it reaches, except the Blast Block at its stop. Emberfox's
        # border contract is a pass too: the page draws "pass, losses" in the pass colour, and
        # the losses are the amber stamp's to say.
        for start, kind in ((S, "pass"), (B, "fail" if i == stop else ("pass" if i < stop else None)), (X, "pass")):
            if kind == "pass":
                passes += on_between(start + lit[i], start + end, 0.12)
            elif kind == "fail":
                fails += on_between(start + lit[i], start + end, 0.12)
        tick = f'<path d="M{cx - 5} {y}l3.5 4 7-8" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>'
        out.append(f'<g class="{a.track(passes)}"><g class="lamp"><circle cx="{cx}" cy="{y}" r="11" fill="{OK}"/>{tick}</g></g>')
        if fails:
            out.append(f'<g class="{a.track(fails)}"><g class="lamp"><circle cx="{cx}" cy="{y}" r="11" fill="{NO}"/>'
                       f'<path d="M{cx - 4.5} {y - 4.5}l9 9m0-9l-9 9" stroke="#fff" stroke-width="2.6" stroke-linecap="round"/></g></g>')
            # The refused gate's name turns red while the act lasts.
            out.append(f'<g class="{a.track(on_between(B + lit[i], B + end, 0.12))}"><g class="w">'
                       f'<rect x="{DESK_X + 40}" y="{GATE_Y0 + i * GATE_DY - 19}" width="210" height="25" fill="{PAPER2}"/>'
                       + text(DESK_X + 44, GATE_Y0 + i * GATE_DY, f["gates"][i], 19, NO, F_BODY, "700") + "</g></g>")

    # Stamps land after the last gate that ran.
    stamp_t = {}
    for start, (word, sub), colour, upto in ((S, f["stamp_ok"], OK, last), (B, f["stamp_no"], NO, stop),
                                            (X, f["stamp_loss"], LOSS, last)):
        t = start + lit[upto] + 0.3
        stamp_t[start] = t
        kf = [(t - 0.01, op(0) + tf(*STAMP_AT, -8, 1.7)), (t, op(0) + tf(*STAMP_AT, -8, 1.7)),
              (t + 0.16, op(1) + tf(*STAMP_AT, -8, 0.92)), (t + 0.26, op(1) + tf(*STAMP_AT, -8, 1)),
              (start + end, op(1) + tf(*STAMP_AT, -8, 1)), (start + ACT - 0.05, op(0) + tf(*STAMP_AT, -8, 1))]
        out.append(stamp(0, 0, word, sub, colour, a.track(kf)))

    # Act 1: the Crystal Sword crosses, becomes a Rock move beside Shellbit, and hits the wild creature.
    land, strike = LEAVE + 0.6, LEAVE + 0.95
    hit_t = S + strike + 0.37
    k1 = moves(to_desk_from_craft(S, HOME_CRAFT) + [
        (S + LEAVE, *DESK_SPOT, 1, 0, 1), (S + LEAVE + .3, 880, 165, 1, 0, 1), (S + land, *HOME_BATTLE, 1, 0, 1),
        (S + strike, *HOME_BATTLE, 1, 0, 1), (S + strike + .35, WILD_AT[0] - 10, WILD_AT[1] - 30, 0.8, 300, 1),
        (S + strike + .42, WILD_AT[0] - 10, WILD_AT[1] - 30, 0.8, 300, 0), (S + ACT, *HOME_CRAFT, 1, 0, 0)])
    out.append(f'<g class="{a.track(k1, "ease-in-out")}"><g id="i-sword">{craft_icon(art["weapon"], px, 56)}</g></g>')
    rock = [(S + land - 0.01, op(0) + tf(*ROCK_AT, 0, 1.6)), (S + land + 0.18, op(1) + tf(*ROCK_AT, 0, 1)),
            (S + end, op(1) + tf(*ROCK_AT, 0, 1)), (S + ACT - 0.05, op(0) + tf(*ROCK_AT, 0, 1))]
    out.append(f'<g class="{a.track(rock)}"><g id="i-rock">{chip(f["rock"], f["rock_colour"])}</g></g>')

    # The wild creature, its health box, and the hit, which stays on screen until the act fades.
    w = f["wild"]
    shake = [(hit_t - 0.01, tf(0, 0))] + [(hit_t + 0.05 * (j + 1), tf(5 if j % 2 == 0 else -5, 0)) for j in range(5)] + [(hit_t + 0.3, tf(0, 0))]
    out.append(f'<g class="{a.track(shake)}">{cindermole(WILD_AT[0], WILD_AT[1], 64)}</g>')
    hx, hy, hw = BATTLE_X + 22, 74, 188
    out.append(f'<rect x="{hx}" y="{hy}" width="{hw}" height="44" rx="5" fill="#fffcf0" stroke="{SOFT_INK}"/>')
    out.append(text(hx + 8, hy + 20, w["name"].upper(), 15, SOFT_INK, F_BODY, "800", cls="w"))
    out.append(f'<g transform="translate({hx + hw - 40} {hy + 15})">{chip(w["type"], f["wild_colour"])}</g>')
    bw = hw - 16
    out.append(f'<rect x="{hx + 8}" y="{hy + 31}" width="{bw}" height="7" fill="{SOFT_INK}"/>')
    left = 1 - f["hit"] / f["bmax"]
    hp = [(hit_t - 0.01, tf(hx + 9, hy + 32, 0, 1, 1)), (hit_t + 0.35, tf(hx + 9, hy + 32, 0, max(0, left), 1)),
          (S + ACT - 0.1, tf(hx + 9, hy + 32, 0, max(0, left), 1)), (S + ACT, tf(hx + 9, hy + 32, 0, 1, 1))]
    out.append(f'<g class="{a.track(hp, "ease-out")}"><rect width="{bw - 2}" height="5" fill="#5cd06a"/></g>')
    fl = [(hit_t - 0.01, op(0) + tf(0, 0)), (hit_t, op(1) + tf(0, 0)), (hit_t + 0.5, op(1) + tf(0, -14)),
          (S + end, op(1) + tf(0, -14)), (S + ACT - 0.05, op(0) + tf(0, -14))]
    out.append(f'<g class="{a.track(fl)}">'
               + text(WILD_AT[0] - 30, WILD_AT[1] + 24, f"-{num(f['hit'])}", 28, "#fff", F_MONO, "800", "end",
                      extra=f' stroke="{SOFT_INK}" stroke-width="5" paint-order="stroke"', cls="dmg")
               + text(WILD_AT[0] - 30, WILD_AT[1] + 56, f"x{num(f['mult'])}", 24, f["rock_colour"], F_MONO, "800", "end",
                      extra=f' stroke="{SOFT_INK}" stroke-width="5" paint-order="stroke"', cls="dmg") + "</g>")

    # Act 2: the Blast Block reaches the desk, is refused, and goes back to its slot.
    bounce = (DESK_X + DESK_W - 30, DESK_SPOT[1])
    k2 = moves(to_desk_from_craft(B, HOME_CRAFT) + [(B + LEAVE, *DESK_SPOT, 1, 0, 1)]
               + back_over_desk(B + LEAVE + .22, bounce, 8)
               + [(B + LEAVE + 1.4, *HOME_CRAFT, 1, 0, 1), (B + end, *HOME_CRAFT, 1, 0, 1), (B + ACT - 0.05, *HOME_CRAFT, 1, 0, 0)])
    out.append(f'<g class="{a.track(k2, "ease-in-out")}"><g id="i-blast">{craft_icon(art["explosive"], px, 54)}</g></g>')
    wall = on_between(B + LEAVE + 0.18, B + LEAVE + 0.9, 0.1)
    out.append(f'<g class="{a.track(wall)}"><rect x="{DESK_X + DESK_W - 7}" y="{TOP + 8}" width="8" height="{PANEL_H - 16}" rx="3" fill="{NO}"/></g>')

    # Act 3: Emberfox crosses the other way, drops its type at the border, becomes a pet and hits the zombie.
    fox_home = (HOME_BATTLE[0], HOME_BATTLE[1] + 10)
    fox_pts = [(X, *fox_home, 1, 0, 0), (X + .25, *fox_home, 1, 0, 1), (X + .4, *fox_home, 1, 0, 1),
               (X + .95, 880, 172, 1, 0, 1), (X + ARRIVE, *DESK_SPOT, 1, 0, 1)]
    pet = (PET_AT[0], PET_AT[1] - 26)
    k3 = moves(fox_pts + back_over_desk(X + LEAVE, DESK_SPOT)
               + [(X + LEAVE + 1.15, *pet, 1, 0, 1), (X + end, *pet, 1, 0, 1), (X + ACT - 0.05, *pet, 1, 0, 0)])
    out.append(f'<g class="{a.track(k3, "ease-in-out")}"><g id="i-fox">{emberfox(0, 26, 54)}</g></g>')
    # Its type chip rides above it to the desk, is struck through when the stamp lands, and falls away.
    dx, dy = 6, -44
    drop = stamp_t[X]
    fire = moves([(t, x + dx, y + dy, s, r, o) for t, x, y, s, r, o in fox_pts]
                 + [(drop + 0.25, DESK_SPOT[0] + dx, DESK_SPOT[1] + dy, 1, 0, 1),
                    (drop + 0.95, DESK_SPOT[0] + dx + 46, DESK_SPOT[1] + dy + 64, 1, 40, 0)])
    strike_line = f'<path d="M-30 9L30 -9" stroke="{NO}" stroke-width="4" stroke-linecap="round"/>'
    struck = [(drop - 0.01, op(0)), (drop, op(1))]
    out.append(f'<g class="{a.track(fire, "ease-in")}"><g id="i-fire">{chip(f["fox"]["type"], f["fire_colour"])}'
               f'<g class="{a.track(struck)}"><g class="chip">{strike_line}</g></g></g></g>')
    fire_t = X + LEAVE + 1.25
    fire = [(fire_t - 0.01, op(0) + tf(pet[0] + 26, GROUND - 40)), (fire_t, op(1) + tf(pet[0] + 26, GROUND - 40)),
            (fire_t + 0.55, op(1) + tf(ZOMBIE_X - 8, GROUND - 44)), (fire_t + 0.6, op(0) + tf(ZOMBIE_X - 8, GROUND - 44))]
    sparks = "".join(f'<rect x="{-i * 7}" y="{(i % 2) * 6 - 3}" width="8" height="8" fill="{"#ffe08a" if i % 2 else "#ff8a3d"}"/>' for i in range(5))
    out.append(f'<g class="{a.track(fire)}">{sparks}</g>')
    zhit = fire_t + 0.58
    zshake = [(zhit - 0.01, tf(0, 0))] + [(zhit + 0.05 * (j + 1), tf(4 if j % 2 == 0 else -4, 0)) for j in range(5)] + [(zhit + 0.3, tf(0, 0))]
    out.append(f'<g class="{a.track(zshake)}">{rects(ZOMBIE, ZOMBIE_X, GROUND, 2)}</g>')
    zb = (ZOMBIE_X - 20, GROUND - 84)
    out.append(f'<rect x="{zb[0]}" y="{zb[1]}" width="72" height="10" fill="{NAVY}"/><rect x="{zb[0] + 2}" y="{zb[1] + 2}" width="68" height="6" fill="#3a3d52"/>')
    zleft = 1 - f["fv"]["conversion"]["damageInTarget"] / f["cmax"]
    zhp = [(zhit - 0.01, tf(zb[0] + 2, zb[1] + 2, 0, 1, 1)), (zhit + 0.3, tf(zb[0] + 2, zb[1] + 2, 0, max(0, zleft), 1)),
           (X + ACT - 0.1, tf(zb[0] + 2, zb[1] + 2, 0, max(0, zleft), 1)), (X + ACT, tf(zb[0] + 2, zb[1] + 2, 0, 1, 1))]
    out.append(f'<g class="{a.track(zhp, "ease-out")}"><rect width="68" height="6" fill="#d8413a"/></g>')
    zf = [(zhit - 0.01, op(0) + tf(0, 0)), (zhit, op(1) + tf(0, 0)), (zhit + 0.5, op(1) + tf(0, -12)),
          (X + end, op(1) + tf(0, -12)), (X + ACT - 0.05, op(0) + tf(0, -12))]
    out.append(f'<g class="{a.track(zf)}">'
               + text(ZOMBIE_X - 12, GROUND - 36, f"-{num(f['fv']['conversion']['damageInTarget'])}", 26, "#fff", F_MONO, "800", "end",
                      extra=f' stroke="{NAVY}" stroke-width="5" paint-order="stroke"', cls="dmg") + "</g>")

    # Captions, one act at a time: where it goes and the verdict, then one short line.
    # The narrow layout drops the verdict (the stamp says it) and sets the rest larger.
    tone = {"ok": OK_D, "no": NO_D, "loss": LOSS_D}
    for k, (start, c) in enumerate(zip((S, B, X), captions(f))):
        t = tone[c["tone"]]
        wide = (text(CRAFT_X + 22, CAP_Y + 48, f"{c['route']} {c['verdict']}", 26, t, F_BODY, "700")
                + text(CRAFT_X + 22, CAP_Y + 98, c["line"], 26, "#e8eee9", F_BODY)
                + "".join(f'<circle cx="{W - 70 + j * 18}" cy="{CAP_Y + 24}" r="5" fill="{t if j == k else "#4a5a62"}"/>' for j in range(3)))
        narrow = (text(CRAFT_X + 20, CAP_Y + 52, c["route"], 38, t, F_BODY, "700")
                  + text(CRAFT_X + 20, CAP_Y + 106, c["line"], 32, "#e8eee9", F_BODY))
        out.append(f'<g class="{a.track(on_between(start + 0.15, start + ACT - 0.2, 0.15))}">'
                   f'<g class="w">{wide}</g><g class="n">{narrow}</g></g>')

    return "".join(out), "".join(a.css)


def still(f: dict, px: dict, art: dict) -> str:
    """The reduced-motion storyboard: all three outcomes at once."""
    out = ['<g class="still">']
    out.append(f'<rect width="{W}" height="{H}" rx="18" fill="{PAPER}"/>'
               f'<rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="17" fill="none" stroke="{RULE}" stroke-width="2"/>')
    cards = [("ok", f["stamp_ok"], craft_icon(art["weapon"], px, 64), f["sword"]["name"], f["craft"], f["battle"]),
             ("no", f["stamp_no"], craft_icon(art["explosive"], px, 62), f["blast"]["name"], f["craft"], f["battle"]),
             ("loss", f["stamp_loss"], emberfox(0, 30, 62), f["fox"]["name"], f["battle"], f["craft"])]
    colour = {"ok": OK, "no": NO, "loss": LOSS}
    bottom = 24 + 392 - 12
    for i, ((t, (word, sub), icon, name, src, dst), c) in enumerate(zip(cards, captions(f))):
        x0 = 24 + i * 388
        out.append(f'<rect x="{x0}" y="24" width="376" height="392" rx="8" fill="{PAPER2}" stroke="{INK}" stroke-width="2"/>')
        out.append(f'<g transform="translate({x0 + 60} 82)">{icon}</g>')
        out.append(f'<g transform="translate({x0 + 262} 82) rotate(-8)">{stamp(0, 0, word, sub, colour[t], "s", "bigs")}</g>')
        wide = [text(x0 + 18, 156, name, 22, colour[t], F_BODY, "700"), text(x0 + 18, 180, f"{src} to {dst}", 18, INK2, F_BODY, "600")]
        y = 186
        for line in c["more"]:
            for part in wrap(line, 37):
                y += 22
                wide.append(text(x0 + 18, y, part, 18, INK, F_BODY))
            y += 5
        narrow = [text(x0 + 18, 176, name, 36, colour[t], F_BODY, "700")]
        y2 = 176
        for part in wrap(f"{src} to {dst}", 20):
            y2 += 36
            narrow.append(text(x0 + 18, y2, part, 30, INK2, F_BODY, "600"))
        y2 += 8
        for part in wrap(c["line"], 21):
            y2 += 36
            narrow.append(text(x0 + 18, y2, part, 30, INK, F_BODY))
        if max(y, y2) > bottom:
            raise SystemExit(f"readme_svg: the storyboard card for {name} runs past its frame "
                             f"(last line at y={max(y, y2)}, frame ends at {bottom}); shorten its text")
        out.append(f'<g class="w">{"".join(wide)}</g><g class="n">{"".join(narrow)}</g>')
    out.append("</g>")
    return "".join(out)


def wrap(s: str, n: int) -> list[str]:
    out, cur = [], ""
    for word in s.split():
        if cur and len(cur) + 1 + len(word) > n:
            out.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}" if cur else word
    return out + ([cur] if cur else [])


def facts_for(data: dict) -> dict:
    """facts() with every page source read from site/."""
    battle_js = _src("battle.js")
    chart, times = type_chart(battle_js)
    return facts(data, chart, times, gate_names(_src("index.html")), stamp_words(_src("app.js")), type_colours(battle_js))


def render(verdicts: Path = VERDICTS) -> str:
    return render_data(json.loads(Path(verdicts).read_text()))


def render_data(data: dict) -> str:
    """The picture for this page data (the content of site/data/verdicts.json)."""
    px, art = pixel_art(_src("sprites.js"))
    f = facts_for(data)
    caps = captions(f)
    anim, css = live(f, px, art)
    style = ("<style>"
             ".still,.n{display:none}"
             ".big,.bigs,.chip,.lamp{transform-box:fill-box;transform-origin:50% 50%}"
             "@keyframes flick{0%,100%{transform:scale(1,1)}50%{transform:scale(0.94,1.1)}}"
             ".flick{transform-box:fill-box;transform-origin:50% 100%;animation:flick .5s ease-in-out infinite}"
             + css +
             # A phone: the picture is drawn at a third of its size, so it shows fewer, larger words.
             # The gate names go, so each lamp moves in beside its number and the stamp has room to grow.
             f"@media (max-width: {NARROW}px){{.w{{display:none}}.n{{display:inline}}.big{{transform:translate(-40px,0) scale(1.3)}}.bigs{{transform:scale(1.15)}}"
             f".chip{{transform:scale(1.6)}}.lamp{{transform:translate({LAMP_SHIFT}px,0) scale(1.5)}}"
             ".gnum{font-size:34px}.dmg{font-size:40px}.hd{font-size:27px}}"
             "@media (prefers-reduced-motion: reduce){.live{display:none}.still{display:inline}"
             "*{animation:none!important}}"
             "</style>")
    desc = (f"Three crossings at the border desk between {f['craft']} and {f['battle']}, each checked at "
            f"{WORDS[f['n']]} gates in order. "
            + " ".join(f"{c['route']} {c['verdict']} {' '.join(c['more'])}" for c in caps))
    title = "Asset Passport: " + " ".join(f"{c['route']} {c['verdict']}" for c in caps)
    return (f"<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 {W} {H}\" width=\"{W}\" height=\"{H}\" "
            "role=\"img\" aria-labelledby=\"t d\">"
            f"<title id=\"t\">{escape(title)}</title><desc id=\"d\">{escape(desc)}</desc>{style}"
            f"<g class=\"live\">{static_scene(f, px)}{anim}</g>{still(f, px, art)}</svg>\n")


# ------------------------------------------------------------------ the README's picture line

def picture_line(data: dict) -> str:
    """The README's first line: the picture, its alt text, and the link to the page."""
    alt = alt_text(facts_for(data))
    if re.search(r"[\[\]\n]", alt):
        raise SystemExit("readme_svg: the alt text holds a bracket or a line break, which would break the Markdown")
    return f"[![{alt}](docs/assets/border.svg)]({PAGE})"


def with_picture(text: str, data: dict) -> str:
    """The README with its picture block written from this data."""
    a, b = PICTURE
    if text.count(a) != 1 or text.count(b) != 1:
        raise SystemExit(f"README.md must hold exactly one {a} ... {b} block")
    head, rest = text.split(a, 1)
    _, tail = rest.split(b, 1)
    return head + a + "\n" + picture_line(data) + "\n" + b + tail


def differences(path: Path = OUT, verdicts: Path = VERDICTS, readme: Path | None = None) -> list[str]:
    """A diff for the picture and for the README's picture line, or [] when both are fresh."""
    readme = README if readme is None else readme
    data = json.loads(Path(verdicts).read_text())
    out = []
    fresh = render_data(data)
    now = Path(path).read_text() if Path(path).exists() else ""
    if now != fresh:
        split = lambda s: s.replace("><", ">\n<").splitlines()  # noqa: E731
        out += list(difflib.unified_diff(split(now), split(fresh), _shown(path), "a fresh render", lineterm="", n=1)) \
            or ["(the files differ only in line endings)"]
    text = Path(readme).read_text()
    want = with_picture(text, data)
    if text != want:
        out += list(difflib.unified_diff(text.splitlines(), want.splitlines(), _shown(readme),
                                         "the picture line the data gives", lineterm="", n=0))
    return out


def _shown(p: Path) -> str:
    p = Path(p)
    return str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)


def write(path: Path = OUT, verdicts: Path = VERDICTS, readme: Path | None = None) -> Path:
    readme = README if readme is None else readme
    data = json.loads(Path(verdicts).read_text())
    svg = render_data(data)
    text = with_picture(Path(readme).read_text(), data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg)
    Path(readme).write_text(text)
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true",
                    help="exit 1 with a diff if docs/assets/border.svg or the README's picture line is not a fresh render")
    ap.add_argument("--verdicts", type=Path, default=VERDICTS)
    a = ap.parse_args(argv)
    if a.check:
        diff = differences(OUT, a.verdicts)
        if diff:
            print("\n".join(diff))
            print("readme_svg --check: docs/assets/border.svg or the README's picture line is not what the data "
                  "gives now (the diff above). Rewrite them with python3 scripts/readme_svg.py.")
            return 1
        print("readme_svg --check: docs/assets/border.svg and the README's picture line are what the data gives now")
        return 0
    p = write(OUT, a.verdicts)
    print(f"wrote {_shown(p)} ({p.stat().st_size // 1024} KB) and the picture line in {_shown(README)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
