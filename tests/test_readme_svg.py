"""The animated picture at the top of the README (docs/assets/border.svg) and
its alt text in the README are drawn from the engine's output, and the picture
is safe to show as an image.

  - The committed file and the README's picture line are exactly what
    scripts/readme_svg.py draws from site/data/verdicts.json now, so a rebuilt
    verdict cannot leave a stale picture or a stale alt text behind.
  - It parses as XML, and holds no script, no foreignObject, no external
    reference and no em dash, and it stays under 150 KB.
  - Every number in its text is a number in verdicts.json, or one computed
    from them: a share of a game's health, a gate's position, or a converted
    power times the battle chart's multiplier read from site/battle.js.
  - The numbers the captions are about stand in the right sentences, worked
    out here from verdicts.json and site/battle.js without the generator.

Only the last test needs the engine, and it loads the engine's support code
itself, so the drawing tests run on a machine without one.
"""

import importlib.util
import json
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from passport.engine import ROOT, engine_binary, scratch

SVG = ROOT / "docs" / "assets" / "border.svg"
VERDICTS = ROOT / "site" / "data" / "verdicts.json"
LIMIT = 150 * 1024
NS = "{http://www.w3.org/2000/svg}"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _texts(svg: str) -> list[str]:
    root = ET.fromstring(svg)
    return ["".join(el.itertext()) for el in root.iter() if el.tag in (f"{NS}text", f"{NS}title", f"{NS}desc")]


def _mult(data: dict) -> float:
    """site/battle.js's multiplier for the sword's converted type against the wild creature."""
    chart = (ROOT / "site" / "battle.js").read_text()
    sword = data["transfers"]["craft:crystal_sword"]["conversion"]
    kind, foe = sword["typeInTarget"].split(":")[-1], data["games"]["battle"]["scene"]["wild"]["type"]
    row = re.search(rf"\b{kind}: \{{([^}}]*)\}}", chart).group(1)
    return float(dict(re.findall(r"(\w+): ([\d.]+)", row))[foe])


def _allowed() -> set[float]:
    """The numbers the picture may print: those in verdicts.json that it draws
    on, and the ones computed from them."""
    data = json.loads(VERDICTS.read_text())
    g, t = data["games"], data["transfers"]
    maxes = [g[k]["max_player_health"] for k in ("craft", "battle")]
    base = set(maxes)
    for key, item_id in (("craft", "crystal_sword"), ("craft", "blast_block"), ("battle", "emberfox")):
        item = next(i for i in g[key]["items"] if i["id"] == item_id)
        base |= {v for v in item.values() if isinstance(v, (int, float))}
    for key in ("craft:crystal_sword", "craft:blast_block", "battle:emberfox"):
        base |= {v for v in t[key]["conversion"].values() if isinstance(v, (int, float))}
    shares = {round(n / m * 100) for n in base for m in maxes}
    gates = set(range(1, len(data["gates"]) + 1))
    # The sword's converted power against the wild creature, under site/battle.js's chart.
    mult = _mult(data)
    hits = {round(t["craft:crystal_sword"]["conversion"]["damageInTarget"] * mult), mult}
    return {float(x) for x in base | shares | gates | hits}


def _numbers(svg: str) -> list[float]:
    return [float(n) for s in _texts(svg) for n in re.findall(r"\d+(?:\.\d+)?", s)]


def stray_numbers(svg: str) -> list[float]:
    allowed = _allowed()
    return sorted({n for n in _numbers(svg) if n not in allowed})


def test_the_committed_picture_is_a_fresh_drawing():
    rs = _load("readme_svg")
    assert rs.differences(rs.OUT, VERDICTS) == [], "run python3 scripts/readme_svg.py"
    assert SVG.read_text() == rs.render(VERDICTS)


def test_it_is_safe_to_show_as_an_image():
    raw = SVG.read_bytes()
    assert len(raw) < LIMIT, f"{len(raw)} bytes"
    svg = raw.decode("utf-8")
    root = ET.fromstring(svg)
    assert root.tag == f"{NS}svg" and root.get("viewBox") == "0 0 1200 440"
    tags = {el.tag.split("}")[-1] for el in root.iter()}
    assert not tags & {"script", "foreignObject", "image", "a", "use", "iframe", "object", "embed", "audio", "video"}, tags
    assert {"title", "desc", "style"} <= tags
    for el in root.iter():
        for name, value in el.attrib.items():
            assert not name.split("}")[-1].startswith("on"), (el.tag, name)
            assert "href" not in name, (el.tag, name)
            assert "url(" not in value or re.fullmatch(r"url\(#[\w-]+\)", value), (el.tag, name, value)
    style = "".join(el.text or "" for el in root.iter(f"{NS}style"))
    assert "@import" not in style and "@font-face" not in style and "url(" not in style
    assert re.findall(r"https?://[^\s\"<>)]*", svg) == ["http://www.w3.org/2000/svg"]
    assert chr(0x2014) not in svg  # the em dash
    assert "@keyframes" in style and "prefers-reduced-motion: reduce" in style


def test_every_number_in_its_text_comes_from_the_verdicts():
    svg = SVG.read_text()
    found = _numbers(svg)
    assert found, "the picture prints no numbers at all"
    assert stray_numbers(svg) == []
    # and the numbers the captions are about are there
    data = json.loads(VERDICTS.read_text())
    t = data["transfers"]
    for n in (t["craft:crystal_sword"]["conversion"]["damageInTarget"], t["craft:blast_block"]["conversion"]["damageInTarget"],
              t["battle:emberfox"]["conversion"]["damageInTarget"], data["games"]["craft"]["max_player_health"]):
        assert float(n) in found, n


def test_a_changed_number_is_caught():
    """The checks above can fail: a hand edit of one number in the picture is
    both a stale drawing and a number the verdicts do not give."""
    rs = _load("readme_svg")
    svg = rs.render(VERDICTS)
    hit = next(n for n in sorted(_allowed(), reverse=True) if f"for {int(n)}." in svg)
    bad = svg.replace(f"for {int(hit)}.", f"for {int(hit) + 1}.", 1)
    assert stray_numbers(bad) == [hit + 1]
    planted = scratch("svg") / "border.svg"
    planted.write_text(bad)
    diff = rs.differences(planted, VERDICTS)
    assert any(l.startswith("-") and f"for {int(hit) + 1}." in l for l in diff), diff[:20]
    assert any(l.startswith("+") and f"for {int(hit)}." in l for l in diff), diff[:20]


def test_check_exits_1_with_a_diff_on_a_stale_picture(monkeypatch, capsys):
    rs = _load("readme_svg")
    planted = scratch("svg") / "border.svg"
    shutil.copy(SVG, planted)
    monkeypatch.setattr(rs, "OUT", planted)
    assert rs.main(["--check"]) == 0
    planted.write_text(planted.read_text().replace("Blast Block", "Blast Brick", 1))
    capsys.readouterr()
    assert rs.main(["--check"]) == 1
    out = capsys.readouterr().out
    assert "is not what the data gives now" in out and "Blast Brick" in out


def _readme_picture_line() -> str:
    text = (ROOT / "README.md").read_text()
    return text.split("<!-- picture:start -->\n", 1)[1].split("\n<!-- picture:end -->", 1)[0]


def test_the_captions_put_each_number_in_its_place():
    """Worked out here from verdicts.json and site/battle.js, not by the generator:
    swapping one right number for another allowed one still fails."""
    data = json.loads(VERDICTS.read_text())
    g, t = data["games"], data["transfers"]
    cmax, bmax = g["craft"]["max_player_health"], g["battle"]["max_player_health"]
    sword, blast, fox = (t[k]["conversion"] for k in ("craft:crystal_sword", "craft:blast_block", "battle:emberfox"))
    mult = _mult(data)
    hit = round(sword["damageInTarget"] * mult)
    wild, zombie = g["battle"]["scene"]["wild"]["name"], g["craft"]["scene"]["enemy"]["name"]
    stop = data["gates"].index(t["craft:blast_block"]["stage"]) + 1
    n = lambda x: str(int(x)) if float(x) == int(x) else str(x)  # noqa: E731
    texts = _texts(SVG.read_text())
    shown = texts[2:]          # every <text>; texts[0] and [1] are <title> and <desc>
    alt = _readme_picture_line()
    everything = " | ".join(texts + [alt])
    w, z = re.escape(wild), re.escape(zombie)
    # Every place a sentence states one of these numbers, it states the right one.
    for pattern, want in ((rf"{w} takes (\d+)\.", [n(hit)]),
                          (rf"{w} for (\d+)\.", [n(hit)]),
                          (r"arrive as (\d+) of (\d+)", [n(blast["damageInTarget"]), n(bmax)]),
                          (rf"hits (?:the|a) {z} for (\d+) of (\d+)", [n(fox["damageInTarget"]), n(cmax)]),
                          (r"[Rr]efused at gate (\d+)", [str(stop)]),
                          (r"AT GATE (\d+)", [str(stop)]),
                          (r"move with power (\d+) of (\d+)", [n(sword["damageInTarget"]), n(bmax)])):
        found = [list(m) if isinstance(m, tuple) else [m] for m in re.findall(pattern, everything)]
        assert found, pattern
        assert all(f == want for f in found), (pattern, found, want)
    for exact in (f"-{n(hit)}", f"x{n(mult)}", f"-{n(fox['damageInTarget'])}"):
        assert exact in shown, exact
    for where in (texts[1], alt):
        assert f"for {n(hit)}." in where and f"power {n(sword['damageInTarget'])} of {n(bmax)}" in where


def test_the_readme_alt_text_is_the_generated_one():
    rs = _load("readme_svg")
    data = json.loads(VERDICTS.read_text())
    assert _readme_picture_line() == rs.picture_line(data)
    assert stray_numbers("<svg xmlns='http://www.w3.org/2000/svg'><text>" + _readme_picture_line().replace("&", "&amp;")
                         + "</text></svg>") == []


def test_check_exits_1_on_a_hand_edited_alt_text(monkeypatch, capsys):
    """The planted failure the review found: the alt text said four gates, then
    two, and nothing noticed."""
    rs = _load("readme_svg")
    readme = scratch("svg") / "README.md"
    text = (ROOT / "README.md").read_text()
    edited = text.replace("passes four gates, is refused at the fifth", "passes two gates, is refused at the third", 1)
    assert edited != text
    readme.write_text(edited)
    monkeypatch.setattr(rs, "README", readme)
    capsys.readouterr()
    assert rs.main(["--check"]) == 1
    out = capsys.readouterr().out
    assert "is not what the data gives now" in out and "-[![" in out and "passes two gates" in out


def test_the_picture_stops_when_the_story_changes():
    """facts() refuses to draw an act the engine no longer tells: a direct-lane
    verdict, an unverified signature, more gates than the desk holds, or a
    profile that no longer types the sword."""
    rs = _load("readme_svg")
    base = json.loads(VERDICTS.read_text())
    battle = (ROOT / "site" / "battle.js").read_text()
    chart, times = rs.type_chart(battle)
    args = (chart, times, rs.gate_names((ROOT / "site" / "index.html").read_text()),
            rs.stamp_words((ROOT / "site" / "app.js").read_text()))
    rs.facts(base, *args)
    direct = json.loads(json.dumps(base))
    direct["transfers"]["craft:crystal_sword"]["transcript"] = [
        x for x in direct["transfers"]["craft:crystal_sword"]["transcript"] if x.get("tool") != "onto_unpack"]
    unsigned = json.loads(json.dumps(base))
    unsigned["transfers"]["battle:emberfox"]["signature"]["verified"] = False
    six = json.loads(json.dumps(base))
    six["gates"] = six["gates"] + ["extra"]
    for bad, why in ((direct, "signed passport"), (unsigned, "signed passport"), (six, "room for")):
        with pytest.raises(SystemExit, match=why):
            rs.facts(bad, *args)
    with pytest.raises(SystemExit, match="profile"):
        rs.facts(base, *args, profile="# no rules here")


def test_a_phone_gets_the_narrow_layout_and_reduced_motion_gets_the_still():
    svg = SVG.read_text()
    style = "".join(el.text or "" for el in ET.fromstring(svg).iter(f"{NS}style"))
    assert "@media (max-width: 600px){.w{display:none}.n{display:inline}" in style
    root = ET.fromstring(svg)
    narrow = ["".join(e.itertext()) for e in root.iter() if e.get("class") == "n"]
    assert narrow, "no narrow-layout text"
    assert "@media (prefers-reduced-motion: reduce){.live{display:none}.still{display:inline}" in style


def _engine_with_packs():
    """The engine's support code, or a skip when this machine has no engine."""
    binary = engine_binary()
    if not (Path(binary).exists() or shutil.which(binary)):
        pytest.skip(f"no Open Ontologies engine at {binary}; set OO_BIN")
    import _support
    if not _support.packs_carry_certificates():
        pytest.skip("this engine cannot carry a certificate in a pack (open-ontologies #266, after v2.0.1)")


def test_build_check_fails_on_a_stale_picture(monkeypatch, capsys):
    """scripts/build_site.py --check also checks the picture and its alt text."""
    _engine_with_packs()
    spec = importlib.util.spec_from_file_location("build_site_svg", ROOT / "scripts" / "build_site.py")
    b = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(b)
    planted = scratch("svg") / "border.svg"
    planted.write_text(SVG.read_text().replace("Emberfox", "Emberfax", 1))
    monkeypatch.setattr(b.readme_svg, "OUT", planted)
    with pytest.raises(SystemExit, match="border.svg"):
        b.main(["--check"])
    assert "Emberfax" in capsys.readouterr().out
    # A hand edit of the alt text alone fails it too.
    monkeypatch.setattr(b.readme_svg, "OUT", SVG)
    readme = scratch("svg") / "README.md"
    readme.write_text((ROOT / "README.md").read_text().replace("passes four gates", "passes two gates", 1))
    monkeypatch.setattr(b.readme_svg, "README", readme)
    with pytest.raises(SystemExit, match="alt"):
        b.main(["--check"])
    assert "passes two gates" in capsys.readouterr().out
