"""What the conversion rule's header and the README state, held to what the
engine and the repository say."""

import re

from passport.engine import ROOT, Engine, scratch_dir

RULE = (ROOT / "rules" / "convert.rq").read_text()


def test_the_rule_header_states_the_grouping_the_engine_measures():
    """The header used to name spargebra 0.5 (the engine runs 0.4.6), and to
    describe only '/' and '-'. Every chain it quotes is evaluated here, and the
    header must give the engine's answer for each, and the left-to-right
    answer it would have under ordinary arithmetic."""
    chains = {"7/20*100": ("0.0035", "35"), "8-3-2": ("7", "3"), "8-3+2": ("3", "7"), "100/10/5": ("50", "2")}
    with scratch_dir("arith") as d, Engine(d) as e:
        q = "SELECT " + " ".join(f"({c} AS ?v{i})" for i, c in enumerate(chains)) + " WHERE {}"
        row = e.call("onto_query", query=q)["results"][0]
    header = "\n".join(l for l in RULE.splitlines() if l.startswith("#"))
    for i, (chain, (engine_says, left_to_right)) in enumerate(chains.items()):
        got = re.match(r'"([^"]+)"', row[f"v{i}"]).group(1)
        assert got == engine_says, f"{chain}: the engine now gives {got}; update rules/convert.rq"
        assert chain in header and engine_says in header, chain
    assert "35, 3, 7 and 2" in header
    assert "spargebra 0.5" not in header and "'+'" in header and "'*'" in header


def test_the_readme_links_the_bridge_contracts_note_itself():
    readme = (ROOT / "README.md").read_text()
    links = re.findall(r"\[note on bridge contracts\]\(([^)]+)\)", readme)
    assert links and all(l.startswith("https://github.com/rehan-remade/universal-modder/blob/") and
                         l.endswith("/knowledge/techniques/bridge-contracts-ownership-units-and-lifecycle.md")
                         for l in links), links
