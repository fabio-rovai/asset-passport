"""The animated picture at the top of the README (docs/assets/border.svg) is
drawn from the engine's output, and is safe to show as an image.

  - The committed file is exactly what scripts/readme_svg.py draws from
    site/data/verdicts.json now, so a rebuilt verdict cannot leave a stale
    picture behind.
  - It parses as XML, and holds no script, no foreignObject, no external
    reference and no em dash, and it stays under 150 KB.
  - Every number in its text is a number in verdicts.json, or one computed
    from them: a share of a game's health, a gate's position, or a converted
    power times the battle chart's multiplier read from site/battle.js.
"""

import importlib.util
import json
import re
import shutil
import xml.etree.ElementTree as ET

import pytest
from _support import needs_packs

from passport.engine import ROOT, scratch

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
    chart = (ROOT / "site" / "battle.js").read_text()
    sword = t["craft:crystal_sword"]["conversion"]
    kind, foe = sword["typeInTarget"].split(":")[-1], g["battle"]["scene"]["wild"]["type"]
    row = re.search(rf"\b{kind}: \{{([^}}]*)\}}", chart).group(1)
    mult = float(dict(re.findall(r"(\w+): ([\d.]+)", row))[foe])
    hits = {round(sword["damageInTarget"] * mult)}
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


@needs_packs
def test_build_check_fails_on_a_stale_picture(monkeypatch, capsys):
    """scripts/build_site.py --check also checks the picture."""
    spec = importlib.util.spec_from_file_location("build_site_svg", ROOT / "scripts" / "build_site.py")
    b = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(b)
    planted = scratch("svg") / "border.svg"
    planted.write_text(SVG.read_text().replace("Emberfox", "Emberfax", 1))
    monkeypatch.setattr(b.readme_svg, "OUT", planted)
    with pytest.raises(SystemExit, match="border.svg"):
        b.main(["--check"])
    assert "Emberfax" in capsys.readouterr().out
