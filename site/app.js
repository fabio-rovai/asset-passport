// The border desk. Every verdict, number and message it shows is read from
// data/verdicts.json (the engine's output at build time) or from the live
// engine behind api/judge. Nothing here decides whether a thing may cross.
(function () {
  "use strict";
  const $ = (s, r) => (r || document).querySelector(s);
  const OTHER = { craft: "battle", battle: "craft" };
  const LABEL = { craft: "Blockcraft", battle: "Pocket Battlers" };
  const PANEL = { craft: "#craft", battle: "#battle" };
  // The gate order; replaced at boot by the order the build wrote into the data.
  let ORDER = ["signature", "unpack", "rules", "closure", "border"];
  const SPECIFIC = ["Weapon", "Explosive", "HealingConsumable", "CaptureDevice", "Creature", "Item"];
  const NATIVE_MOVES = [
    { kind: "Move", name: "Tackle", cat: "move", home: "battle", stats: { power: 35, type: "Normal" } },
    { kind: "Move", name: "Water Gun", cat: "move", home: "battle", stats: { power: 30, type: "Water" } },
  ];
  const API_BASE = window.ASSET_PASSPORT_API_BASE || "";
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

  let DATA = null, API = null, busy = false, uidN = 0;
  const P = {};
  const inv = { craft: [], battle: [] };
  const games = {};

  function h(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") e.className = v;
      else if (k === "text") e.textContent = v;
      else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) if (kid != null && kid !== false) e.append(kid.nodeType ? kid : String(kid));
    return e;
  }
  const fmt = (n) => (typeof n === "number" ? (Number.isInteger(n) ? n.toLocaleString("en-GB") : String(Math.round(n * 100) / 100)) : String(n));
  const pct = (n, of) => `${Math.round((n / of) * 100)}%`;
  const sleep = (ms) => new Promise((r) => setTimeout(r, reduce ? 0 : ms));
  const gameOfIri = (iri) => (iri && iri.includes("/craft#") ? "craft" : iri && iri.includes("/battle#") ? "battle" : null);
  const local = (t) => (t ? String(t).replace(/^.*[#:]/, "") : t);
  const poss = (label) => (/s$/.test(label) ? `${label}'` : `${label}'s`);
  const NUMBER = ["no", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve"];

  // ------------------------------------------------------------ profiles
  function conventions(ttl) {
    const num = (p) => { const m = ttl.match(new RegExp("ga:" + p + "\\s+([0-9.]+)")); return m ? Number(m[1]) : null; };
    return { maxHp: num("maxPlayerHealth"), hasTypes: /ga:hasElementalTypes\s+true/.test(ttl) };
  }
  const messages = (ttl) => [...ttl.matchAll(/sh:message "([^"]+)"/g)].map((m) => m[1]);
  const capOf = (ttl, path) => { const m = ttl.match(new RegExp("sh:path ga:" + path + "[^\\]]*?sh:max(?:Exclusive|Inclusive) ([0-9.]+)")); return m ? Number(m[1]) : null; };

  // ------------------------------------------------------------ items
  function catFrom(types) {
    const t = new Set(types || []);
    if (t.has("Weapon")) return "weapon";
    if (t.has("Explosive")) return "explosive";
    if (t.has("HealingConsumable")) return "heal";
    if (t.has("CaptureDevice")) return "capture";
    if (t.has("Creature")) return "creature";
    return "other";
  }
  const specific = (types) => SPECIFIC.find((s) => (types || []).includes(s));

  function nativeStats(game, cat, r) {
    if (game === "craft") {
      if (cat === "weapon") return { damage: r.attack ?? 1 };
      if (cat === "explosive") return { damage: r.blastDamage ?? 0 };
      if (cat === "heal") return { hp: r.heals ?? 0, bonus: r.bonusHearts ?? 0 };
      return {};
    }
    if (cat === "creature") return { power: r.movePower ?? 0, move: r.moveName, type: r.type, hp: r.hp };
    if (cat === "heal") return { hp: r.restoresHp ?? 0 };
    if (cat === "capture") return { rate: r.catchRate };
    return {};
  }

  function importedStats(target, cat, c, rec) {
    if (target === "battle") {
      if (cat === "weapon" || cat === "explosive") return { power: c.damageInTarget, type: local(c.typeInTarget) || "Normal" };
      if (cat === "heal") return { hp: c.healInTarget };
    } else {
      if (cat === "creature") return { damage: c.damageInTarget, hp: c.hitPointsInTarget, move: rec && rec.moveName };
      if (cat === "heal") return { hp: c.healInTarget, bonus: 0 };
      if (cat === "weapon" || cat === "explosive") return { damage: c.damageInTarget };
    }
    return {};
  }

  function nativeItem(game, rec) {
    const t = DATA.transfers[`${game}:${rec.id}`];
    const cat = catFrom(t && t.hub_types);
    return { uid: ++uidN, home: game, place: game, id: rec.id, name: rec.name, kind: rec.kind, cat, rec,
             imported: false, stats: nativeStats(game, cat, rec) };
  }
  function importedItem(src, v, target) {
    const cat = catFrom(v.hub_types);
    return { uid: ++uidN, home: src.home, place: target, id: src.id, name: src.name, kind: src.kind, cat, rec: src.rec,
             imported: true, verdict: v, stats: importedStats(target, cat, v.conversion || {}, src.rec) };
  }

  function statLine(game, it) {
    const s = it.stats;
    if (it.cat === "move" || (game === "battle" && (it.cat === "weapon" || it.cat === "explosive"))) return `${s.type} · power ${fmt(s.power)}`;
    if (game === "craft") {
      if (it.cat === "weapon") return `${fmt(s.damage)} damage`;
      if (it.cat === "explosive") return `${fmt(s.damage)} blast damage`;
      if (it.cat === "heal") return `+${fmt(s.hp)} HP${s.bonus ? ` · +${s.bonus} bonus` : ""}`;
      if (it.cat === "creature") return `pet · ${s.move || "attack"} ${fmt(s.damage)}`;
    } else {
      if (it.cat === "heal") return `+${fmt(s.hp)} HP`;
      if (it.cat === "capture") return "catches a weak creature";
      if (it.cat === "creature") return `${s.type} · ${s.move} ${fmt(s.power)}`;
    }
    return "";
  }

  // ------------------------------------------------------------ inventories
  function slot(game, it) {
    const cv = h("canvas", { width: 88, height: 88, "aria-hidden": "true" });
    Sprites.icon(cv.getContext("2d"), it.cat === "move" ? { kind: "Move", home: "battle" } : it, 44, 44, 72, 0);
    if (it.cat === "move") {
      const c = cv.getContext("2d");
      c.fillStyle = { Normal: "#a8a090", Water: "#4aa8e0" }[it.stats.type] || "#a8a090";
      c.beginPath(); c.arc(44, 44, 26, 0, 7); c.fill();
    }
    const tradeable = it.cat !== "move" && !it.imported;
    const btn = h("button", {
      class: "slot" + (it.fresh ? " fresh" : ""), type: "button", role: "listitem",
      "aria-label": `Use ${it.name}`, title: tradeable ? `Click to use. Drag into ${LABEL[OTHER[game]]} to send it.` : "Click to use",
      onclick: (e) => {
        if (e.currentTarget.dataset.dragged) { delete e.currentTarget.dataset.dragged; return; }
        use(game, it);
      },
    }, cv, h("span", { class: "nm", text: it.name }), h("span", { class: "st", text: statLine(game, it) }),
       it.imported ? h("span", { class: "tag pp", text: "passport" }) : null);
    it.fresh = false;
    const wrap = h("div", { class: "slot-wrap" }, btn);
    if (tradeable) {
      btn.addEventListener("pointerdown", (e) => startDrag(e, game, it, cv, btn));
      btn.addEventListener("pointermove", moveDrag);
      btn.addEventListener("pointerup", endDrag);
      btn.addEventListener("pointercancel", endDrag);
      wrap.append(h("button", { class: "send", type: "button", text: `Send to ${LABEL[OTHER[game]]} →`,
                                "aria-label": `Send ${it.name} to ${LABEL[OTHER[game]]}`, onclick: () => send(it) }));
    }
    return wrap;
  }

  function renderInv(game) {
    const box = $(`#${game}-inv`);
    if (game === "craft") {
      box.replaceChildren(h("div", { class: "group" }, h("p", { class: "inv-label", text: "Hotbar" }),
        h("div", { class: "inv", role: "list" }, inv.craft.map((it) => slot("craft", it)))));
      return;
    }
    const groups = [
      ["Moves", NATIVE_MOVES.concat(inv.battle.filter((x) => x.cat === "weapon" || x.cat === "explosive"))],
      ["Bag", inv.battle.filter((x) => x.cat === "heal" || x.cat === "capture" || x.cat === "other")],
      ["Party", inv.battle.filter((x) => x.cat === "creature")],
    ];
    box.replaceChildren(...groups.filter(([, xs]) => xs.length).map(([label, xs]) =>
      h("div", { class: "group" }, h("p", { class: "inv-label", text: label }),
        h("div", { class: "inv", role: "list" }, xs.map((it) => slot("battle", it))))));
  }

  async function use(game, it) {
    if (busy) return;
    busy = true; document.body.classList.add("acting");
    try { await games[game].act(it); } finally { busy = false; document.body.classList.remove("acting"); }
  }

  // ------------------------------------------------------------ drag and drop
  let drag = null;
  const dropTarget = (game) => $(PANEL[OTHER[game]]);
  const sideBySide = () => matchMedia("(min-width: 761px)").matches;

  function startDrag(e, game, it, icon, btn) {
    if (e.button !== 0) return;
    if (e.pointerType === "touch" && !sideBySide()) return;
    drag = { game, it, icon, btn, id: e.pointerId, x0: e.clientX, y0: e.clientY, started: false };
    btn.setPointerCapture(e.pointerId);
  }
  function over(game, x, y) {
    const el = document.elementFromPoint(x, y);
    return !!el && !!(el.closest(PANEL[OTHER[game]]) || el.closest("#desk"));
  }
  function moveDrag(e) {
    if (!drag || e.pointerId !== drag.id) return;
    if (!drag.started) {
      if (Math.hypot(e.clientX - drag.x0, e.clientY - drag.y0) < 6) return;
      drag.started = true;
      const c = h("canvas", { width: 88, height: 88 });
      c.getContext("2d").drawImage(drag.icon, 0, 0);
      drag.ghost = h("div", { class: "ghost", "aria-hidden": "true" }, c, h("span", { text: drag.it.name }));
      document.body.append(drag.ghost);
      document.body.classList.add("dragging");
      const t = dropTarget(drag.game);
      t.dataset.drop = `Drop to send to ${LABEL[OTHER[drag.game]]}`;
      t.classList.add("drop-ready"); $("#desk").classList.add("drop-ready");
    }
    drag.ghost.style.transform = `translate(${e.clientX - 34}px, ${e.clientY - 34}px)`;
    const hot = over(drag.game, e.clientX, e.clientY);
    dropTarget(drag.game).classList.toggle("drop-hot", hot);
    $("#desk").classList.toggle("drop-hot", hot);
  }
  function endDrag(e) {
    if (!drag || e.pointerId !== drag.id) return;
    const d = drag; drag = null;
    if (!d.started) return;
    d.btn.dataset.dragged = "1";
    const hit = e.type === "pointerup" && over(d.game, e.clientX, e.clientY);
    for (const el of [dropTarget(d.game), $("#desk")]) el.classList.remove("drop-ready", "drop-hot");
    document.body.classList.remove("dragging");
    const to = (hit ? $("#desk") : d.btn).getBoundingClientRect();
    d.ghost.style.transition = reduce ? "none" : "transform 300ms ease-in, opacity 300ms ease-in";
    d.ghost.style.transform = `translate(${to.left + to.width / 2 - 34}px, ${to.top + Math.min(to.height / 2, 120) - 34}px) scale(${hit ? 0.6 : 1})`;
    d.ghost.style.opacity = hit ? "0.2" : "0.6";
    setTimeout(() => d.ghost.remove(), reduce ? 0 : 320);
    if (hit) send(d.it);
  }

  // ------------------------------------------------------------ the desk
  const GATE_TEXT = {};
  function resetGates(note) {
    for (const li of document.querySelectorAll(".gate")) {
      li.dataset.state = "idle";
      li.querySelector(".chip").textContent = note || "waiting";
      li.querySelector(".gd").textContent = GATE_TEXT[li.dataset.gate];
    }
  }

  function gatePlan(v) {
    const lane = (v.transcript || []).some((t) => t.tool === "onto_unpack") ? "passport" : "direct";
    const src = gameOfIri(v.source);
    const stop = v.verdict === "refused" ? v.stage : null;
    const out = {};
    for (const g of ORDER) {
      if (stop && ORDER.indexOf(g) > ORDER.indexOf(stop)) { out[g] = { state: "idle", chip: "not reached", note: GATE_TEXT[g] }; continue; }
      if (lane === "direct" && (g === "signature" || g === "rules" || g === "closure") && g !== stop) {
        out[g] = { state: "pass", chip: "same store", note: {
          signature: "Live lane: one engine, one store, no passport. There is nothing in transit to sign.",
          rules: `Live lane: the engine loaded ${poss(LABEL[src] || "the source game")} published rules itself.`,
          closure: `Live lane: the engine worked out what it is itself: ga:${specific(v.hub_types) || "Item"}.`,
        }[g] };
        continue;
      }
      if (g === stop) {
        let note = (v.refusals[0] || {}).message || v.headline;
        if (g === "rules" && v.drift) note += " " + [...v.drift.added.map((l) => "+ " + l), ...v.drift.removed.map((l) => "− " + l)].join("  ");
        out[g] = { state: "fail", chip: "refused", note };
        continue;
      }
      const sig = v.signature || {};
      out[g] = { state: "pass", chip: "pass", note: {
        signature: `Signed by ${sig.label}. It verifies against the key in ${poss(sig.label)} published profile (sha256 ${String(sig.public_key_sha256 || "").slice(0, 12)}…).`,
        unpack: `${lane === "passport" ? "Digests match. " : ""}Lean accepted ${v.proof.derivations} steps.`,
        rules: `Matches ${poss(LABEL[src])} published rules, and ${LABEL[src]} signed it.`,
        closure: `Worked out here: ga:${specific(v.hub_types)}. Nothing left out.`,
        border: "Both SHACL evaluators say: conforms.",
      }[g] };
    }
    if (v.verdict === "undetermined") out.border = { state: "warn", chip: "held", note: v.headline };
    if (v.verdict === "converted_with_loss") out.border.chip = "pass, losses";
    return out;
  }

  async function runGates(v, animate) {
    const plan = gatePlan(v);
    for (const g of ORDER) {
      const li = $(`.gate[data-gate="${g}"]`);
      if (animate && plan[g].state !== "idle") {
        li.dataset.state = "run"; li.querySelector(".chip").textContent = "checking";
        await sleep(300);
      }
      li.dataset.state = plan[g].state;
      li.querySelector(".chip").textContent = plan[g].chip;
      li.querySelector(".gd").textContent = plan[g].note;
    }
  }

  function stampFor(v) {
    switch (v.verdict) {
      case "converted": case "accepted": return ["ok", "Admitted", v.verdict === "converted" ? "converted" : "as is"];
      case "converted_with_loss": return ["loss", "Admitted", "losses declared"];
      case "refused": return ["no", "Refused", `at gate ${ORDER.indexOf(v.stage) + 1}`];
      default: return ["held", "Held", "undetermined"];
    }
  }

  // What the thing does at home, and what it does after the border, in plain words.
  function whatItDoes(v, item, from, to) {
    const r = item.rec || {}, c = v.conversion || {}, cat = catFrom(v.hub_types);
    const F = P[from].maxHp, T = P[to].maxHp, foe = games.battle.foeType();
    let home = "", there = "";
    if (from === "craft") {
      if (cat === "weapon") home = `Hits for ${fmt(r.attack)} of a player's ${F} HP (${pct(r.attack, F)}).`;
      if (cat === "explosive") home = `Blasts for ${fmt(r.blastDamage)} of ${F} HP (${pct(r.blastDamage, F)}).`;
      if (cat === "heal") home = `Heals ${fmt(r.heals)} of ${F} HP${r.bonusHearts ? ` and adds ${r.bonusHearts} bonus HP above the maximum` : ""}.`;
    } else {
      if (cat === "creature") home = `A ${r.type}-type creature. Its ${r.moveName} has power ${fmt(r.movePower)} of ${F} HP (${pct(r.movePower, F)}).`;
      if (cat === "capture") home = "Catches a wild creature once it is weak.";
      if (cat === "heal") home = `Heals ${fmt(r.restoresHp)} of ${F} HP (${pct(r.restoresHp, F)}).`;
    }
    if (v.verdict === "refused" || v.verdict === "undetermined") there = "Never arrives. The border turned it back.";
    else if (to === "battle" && (cat === "weapon" || cat === "explosive")) {
      const t = local(c.typeInTarget) || "Normal", m = Battle.eff(t, foe);
      there = `A ${t}-type move with power ${fmt(c.damageInTarget)} of ${T} (${pct(c.damageInTarget, T)}).` +
        (c.typeInTarget ? " The engine derived the type from what it is made of." : "") +
        (m !== 1 ? ` Against the ${foe}-type wild creature it lands ×${m}: ${fmt(Math.round(c.damageInTarget * m))}.` : "");
    } else if (cat === "heal") there = `Heals ${fmt(c.healInTarget)} of ${T} HP (${pct(c.healInTarget, T)}).`;
    else if (cat === "creature") there = `A pet with ${fmt(c.hitPointsInTarget)} of ${T} HP. Its ${r.moveName || "attack"} hits a zombie for ${fmt(c.damageInTarget)} of ${T} (${pct(c.damageInTarget, T)}).`;
    return [[`In ${LABEL[from]}`, home || "No effect described."], [`In ${LABEL[to]}`, there || "No effect described."]];
  }

  function renderPassport(v, item, from, to, animate) {
    const [cls, word, sub] = stampFor(v);
    const field = (dt, ...dd) => h("div", null, h("dt", { text: dt }), h("dd", null, ...dd));
    const list = (cls2, xs) => (xs.length ? h("ul", { class: cls2 }, xs.map((x) => h("li", { text: x }))) : null);
    const facts = [];
    if (v.signature && v.signature.verified) facts.push(field("Signed by", `${v.signature.label} · key sha256 `,
      h("span", { class: "mono", text: String(v.signature.public_key_sha256).slice(0, 16) + "…" })));
    else if (v.signature) facts.push(field("Signed by", "nobody this border can verify"));
    else if (v.signature === null) facts.push(field("Signed by", "not signed: the live lane is one store, nothing travels"));
    if (v.hub_types && v.hub_types.length) facts.push(field("Classified", h("span", { class: "mono", text: "ga:" + specific(v.hub_types) })));
    if (v.proof && v.proof.status) facts.push(field("Proof", v.proof.status.startsWith("certificate_accepted")
      ? `Lean accepted ${v.proof.derivations} steps (${v.proof.theorem})` : v.proof.status.replace(/_/g, " ")));
    if (v.evaluators && "verified" in v.evaluators)
      facts.push(field("Contract", `verified SHACL: ${word3(v.evaluators.verified)} · SHACL: ${word3(v.evaluators.default)}`));
    const steps = (v.why || []).map((s) => h("li", null, h("span", { class: "rule", text: s.rule + " " }),
      h("span", { class: "mono", text: s.conclusion }), h("br"), h("span", { class: "prem mono", text: "← " + s.premises.join("; ") })));
    const calls = (v.export_transcript || []).concat(v.transcript || []).map((c) => h("li", { class: "mono" },
      h("b", { text: c.tool }), " ", clip(JSON.stringify(c.args), 140), h("br"), h("span", { class: "prem", text: clip(JSON.stringify(c.result), 260) })));
    $("#passport").replaceChildren(h("article", { class: "pp" },
      h("div", { class: "pp-top" }, h("span", { text: "Passport" }), h("span", { text: `${LABEL[from]} → ${LABEL[to]}` })),
      h("h3", { class: "pp-name", text: item.name }),
      h("div", { class: `stamp ${cls}${animate ? " slam" : ""}`, role: "img", "aria-label": `${word}, ${sub}` }, word, h("small", { text: sub })),
      h("div", { class: "does" }, whatItDoes(v, item, from, to).map(([k, t]) => h("div", null, h("b", { text: k }), h("span", { text: t })))),
      list("refusals", (v.refusals || []).map((x) => x.message)),
      list("losses", (v.losses || []).map((x) => x.message)),
      h("dl", null, facts),
      steps.length ? h("details", null, h("summary", { text: `Why the engine calls it ga:${specific(v.hub_types)}` }), h("ol", null, steps)) : null,
      calls.length ? h("details", null, h("summary", { text: `Engine transcript, ${calls.length} calls` }), h("ol", null, calls)) : null,
      v.passport ? h("a", { class: "dl", href: v.passport, download: "", text: "Download this passport (.pack, JSON)" }) : null));
  }
  const word3 = (b) => (b === true ? "conforms" : b === false ? "violation" : "could not run");
  const clip = (s, n) => (s && s.length > n ? s.slice(0, n) + "…" : s);

  async function showVerdict(v, item, from, to, animate) {
    resetGates();
    if (animate) {
      const prev = $("#passport .pp");
      if (prev) prev.classList.add("pending");
      else $("#passport").replaceChildren(h("p", { class: "pp-empty", text: `${item.name} is at the border…` }));
    }
    await runGates(v, animate);
    renderPassport(v, item, from, to, animate);
  }

  async function send(item, verdict) {
    // A crossing waits for the turn in progress to finish, rather than being dropped.
    while (busy) await new Promise((r) => setTimeout(r, 100));
    busy = true;
    const from = item.place, to = OTHER[from];
    inv[from] = inv[from].filter((x) => x !== item);
    renderInv(from);
    const v = verdict || DATA.transfers[`${item.home}:${item.id}`];
    if (window.innerWidth < 1180) $("#desk").scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
    await showVerdict(v, item, from, to, true);
    const imp = land(item, v, from, to);
    busy = false;
    if (imp) {
      await sleep(350);
      if (window.innerWidth < 1180) $(PANEL[to]).scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
      await use(to, imp);   // the thing shows what it does the moment it arrives
    }
  }

  function land(item, v, from, to) {
    if (v.verdict === "refused" || v.verdict === "undetermined") {
      if (!item.forged) inv[from].push(item);
      renderInv(from);
      log(from, `The border turned the ${item.name} back.`);
      return null;
    }
    const imp = importedItem(item, v, to);
    imp.fresh = true;
    inv[to].push(imp);
    renderInv(to);
    return imp;
  }

  // ------------------------------------------------------------ text boxes
  function log(game, text, append) {
    const el = $(`#${game}-log`);
    el.textContent = append && el.textContent ? `${el.textContent} ${text}` : text;
  }
  const say = (game) => async (text) => { log(game, text); await sleep(Math.min(1400, 420 + text.length * 16)); };

  // ------------------------------------------------------------ forge (live)
  const FIELD = {
    attack: "Attack", blastDamage: "Blast damage", heals: "Heals", bonusHearts: "Bonus hearts", material: "Material",
    hp: "HP", movePower: "Move power", moveName: "Move name", type: "Type", restoresHp: "Restores", catchRate: "Catch rate",
  };
  function forgeKinds() {
    const g = $("#forge-game").value;
    $("#forge-kind").replaceChildren(...DATA.games[g].items.map((r) => h("option", { value: r.kind, text: r.name })));
    $("#forge-send").textContent = `Send to ${LABEL[OTHER[g]]}`;
    forgeFields();
  }
  function forgeFields(preset) {
    const g = $("#forge-game").value;
    const rec = DATA.games[g].items.find((r) => r.kind === $("#forge-kind").value);
    const vals = Object.assign({}, rec, preset || {});
    $("#forge-name").value = preset && preset.name ? preset.name : `Forged ${rec.name.toLowerCase()}`;
    $("#forge-fields").replaceChildren(...Object.keys(rec).filter((k) => !["id", "kind", "name"].includes(k)).map((key) => {
      const id = `ff-${key}`;
      const text = typeof rec[key] === "string";
      const unit = text || key === "catchRate" ? "" : `of ${P[g].maxHp}`;
      return h("div", { class: "field" }, h("label", { for: id }, FIELD[key] || key, " ", h("span", { class: "unit", text: unit })),
        h("input", text ? { id, type: "text", maxlength: "24", "data-k": key, value: vals[key] }
                        : { id, type: "number", inputmode: "numeric", step: "1", min: "0", max: "100000", "data-k": key, value: vals[key] }));
    }));
  }
  async function forge(e) {
    e.preventDefault();
    if (!API || busy) return;
    const g = $("#forge-game").value, to = OTHER[g];
    const kind = $("#forge-kind").value;
    const name = ($("#forge-name").value || "Forged item").trim().slice(0, 40);
    const rec = { id: "forged_" + (name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "") || "item"), kind, name };
    for (const inp of document.querySelectorAll("#forge-fields input")) {
      const k = inp.dataset.k;
      if (inp.type === "text") { if (inp.value.trim()) rec[k] = inp.value.trim(); continue; }
      if (inp.value === "") continue;
      const n = Number(inp.value);
      if (!Number.isFinite(n) || n < 0 || n > 100000) { status(`${FIELD[k] || k} must be a number from 0 to 100,000.`, true); inp.focus(); return; }
      rec[k] = n;
    }
    $("#forge-send").disabled = true; $("#forge-result").hidden = true;
    status("Sending to the live engine…");
    try {
      const t0 = performance.now();
      const r = await fetch(`${API_BASE}api/judge`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ game: g, target: to, item: rec }) });
      const v = await r.json();
      if (!r.ok) throw new Error(v.error || `The engine answered ${r.status}.`);
      const item = { uid: ++uidN, home: g, place: g, id: rec.id, name, kind, rec, forged: true, cat: catFrom(v.hub_types) };
      status(`The live engine answered in ${Math.round(performance.now() - t0)} ms.`);
      const [cls, word, sub] = stampFor(v);
      $("#forge-result").replaceChildren(h("b", { text: `${word}, ${sub}` }),
        h("span", { text: (v.refusals[0] || v.losses[0] || {}).message || v.headline }),
        h("a", { href: "#desk", text: "Read the passport at the border desk" }));
      $("#forge-result").dataset.v = cls; $("#forge-result").hidden = false;
      await send(item, v);
    } catch (err) {
      status(`The live engine did not answer: ${err.message}`, true); resetGates();
    } finally { $("#forge-send").disabled = !API; }
  }
  function status(t, err) { const s = $("#forge-status"); s.textContent = t; s.classList.toggle("err", !!err); }

  async function probeApi() {
    try {
      const r = await fetch(`${API_BASE}api/engine`, { cache: "no-store" });
      if (!r.ok) throw new Error(String(r.status));
      API = await r.json();
      $("#forge-engine").textContent = `Live engine: open-ontologies ${API.tag || ""}, sha256 ${String(API.binary_sha256 || "").slice(0, 12)}…`;
    } catch (_) {
      API = null;
      $("#forge-engine").textContent = "This copy of the page has no engine server, so the forge is off. Everything above was judged by the engine when the page was built. To forge live, clone the repo and run python3 local.py.";
    }
    $("#forge-send").disabled = !API;
  }
  const TRIES = [
    ["A gold sword (gold has no type)", "craft", "DiamondSword", { name: "Gold Sword", attack: 4, material: "Gold" }],
    ["A wooden sword", "craft", "DiamondSword", { name: "Wooden Sword", attack: 4, material: "Wood" }],
    ["A sword with attack 20", "craft", "DiamondSword", { name: "Doom Blade", attack: 20, material: "Diamond" }],
    ["An Emberfox with power 100", "battle", "Emberfox", { name: "Infernofox", hp: 100, movePower: 100, moveName: "Inferno", type: "Fire" }],
    ["A potion that heals 100", "battle", "SuperPotion", { name: "Max Potion", restoresHp: 100 }],
  ];

  // ------------------------------------------------------------ smuggling
  // Every card is one entry of DATA.forgeries, in the order the build wrote
  // them: what the forger did, what the engine said, and why, all from the data.
  function renderCards() {
    const n = DATA.forgeries.length;
    $("#smuggle-n").textContent = NUMBER[n] || String(n);
    $("#cards").replaceChildren(...DATA.forgeries.map((f) => {
      const v = f.verdict, thru = v.verdict !== "refused";
      const quote = thru
        ? `verdict: ${v.verdict}. ${Object.entries(v.conversion).map(([k, x]) => `${k} ${fmt(x)}`).join(", ")}`
        : (v.refusals[0] || {}).message;
      const diff = v.drift ? h("pre", { class: "diff" }, ...v.drift.added.map((l) => h("div", { class: "add", text: "+ " + l })),
        ...v.drift.removed.map((l) => h("div", { class: "del", text: "− " + l }))) : null;
      const gate = $(`.gate[data-gate="${v.stage}"] .gn`);
      return h("article", { class: "card" + (thru ? " thru" : "") }, h("h3", { text: f.title }), h("p", { class: "did", text: f.did }),
        h("div", { class: "res" }, h("span", { class: "badge" + (thru ? " thru" : ""), text: thru ? "Gets through" : `Stopped at gate ${ORDER.indexOf(v.stage) + 1}` }),
          h("span", { class: "status", text: thru ? "" : gate ? gate.textContent : v.stage })),
        h("blockquote", { text: quote }), diff, h("p", { class: "why", text: f.why || "" }));
    }));
  }

  function renderSources() {
    const files = [
      ["Game Asset core", "ontology/ga-core.ttl", DATA.files.hub],
      ["Blockcraft profile", "games/craft/profile.ttl", DATA.games.craft.profile],
      ["Pocket Battlers profile", "games/battle/profile.ttl", DATA.games.battle.profile],
      ["Conversion rule", "rules/convert.rq", DATA.files.rule],
      ["Pocket Battlers border", "contracts/battle-border.shacl.ttl", DATA.files.battle_border],
      ["Blockcraft border", "contracts/craft-border.shacl.ttl", DATA.files.craft_border],
      ["Losses into Pocket Battlers", "contracts/battle-loss.shacl.ttl", DATA.files.battle_loss],
      ["Losses into Blockcraft", "contracts/craft-loss.shacl.ttl", DATA.files.craft_loss],
    ];
    $("#sources").replaceChildren(...files.map(([t, p, body]) => h("details", null, h("summary", null, t, " ", h("span", { class: "mono", text: p })), h("pre", { text: body }))));
  }
  function renderFoot() {
    const e = DATA.engine;
    $("#foot").replaceChildren(
      h("p", { text: `Every verdict, number and message on this page was produced by open-ontologies ${e.tool_version} (main at ${e.open_ontologies_rev}) when the page was built, ${DATA.built_at}.` }),
      h("p", { class: "mono", text: `engine sha256 ${e.binary_sha256} · oo-cert sha256 ${e.oo_cert_sha256}` }),
      h("p", null, "Both games, their creatures, their art and their items are original to this demo. ",
        h("a", { href: "https://github.com/fabio-rovai/asset-passport", text: "Source on GitHub" }), " · ",
        h("a", { href: "https://github.com/fabio-rovai/open-ontologies", text: "Open Ontologies" }), "."));
  }

  // ------------------------------------------------------------ boot
  async function boot() {
    for (const li of document.querySelectorAll(".gate")) GATE_TEXT[li.dataset.gate] = li.querySelector(".gd").textContent;
    try { DATA = await (await fetch("data/verdicts.json")).json(); }
    catch (_) {
      $("#passport").replaceChildren(h("p", { class: "pp-empty", text: "The engine's verdicts did not load. Serve this folder over HTTP (python3 local.py) rather than opening the file directly." }));
      return;
    }
    if (Array.isArray(DATA.gates)) ORDER = DATA.gates;
    for (const g of ["craft", "battle"]) { P[g] = conventions(DATA.games[g].profile); if (DATA.games[g].label) LABEL[g] = DATA.games[g].label; }
    // The worked example in "Convert it": the sword's own attack, each game's
    // health as the engine read it from the profile, and the engine's result.
    const swordRec = DATA.games.craft.items.find((r) => r.id === "diamond_sword");
    const swordV = DATA.transfers["craft:diamond_sword"];
    const hpOf = (g) => DATA.games[g].max_player_health ?? P[g].maxHp;
    if (swordRec && swordV && swordV.conversion.damageInTarget != null) {
      $("#ex-convert").textContent = `A Diamond Sword deals ${fmt(swordRec.attack)} of ${poss(LABEL.craft)} ${fmt(hpOf("craft"))} HP, `
        + `and becomes a move with power ${fmt(swordV.conversion.damageInTarget)} of a creature's ${fmt(hpOf("battle"))} HP.`;
    }
    $("#craft-conv").textContent = `${P.craft.maxHp} HP · no types`;
    $("#battle-conv").textContent = `${P.battle.maxHp} HP · every move has a type`;
    const cb = DATA.files.craft_border, bb = DATA.files.battle_border;
    $("#dg-craft").textContent = `${P.craft.maxHp} HP · no types`;
    $("#dg-battle").textContent = `${P.battle.maxHp} HP · typed moves`;
    $("#dg-craft-c").textContent = `under ${capOf(cb, "damageInTarget")} a hit · no capturing`;
    $("#dg-battle-c").textContent = `under ${capOf(bb, "damageInTarget")} a turn · moves need a type`;
    $("#caps").replaceChildren(...[["Pocket Battlers", bb], ["Blockcraft", cb]].map(([n, t]) =>
      h("div", null, h("p", { class: "status", text: n }), h("ul", null, messages(t).filter((m) => !/which game/.test(m)).map((m) => h("li", { text: m }))))));

    games.craft = Craft.create($("#craft-canvas"), { maxHp: P.craft.maxHp, log: (t, a) => log("craft", t, a) });
    games.battle = Battle.create($("#battle-canvas"), { maxHp: P.battle.maxHp, say: say("battle") });
    for (const g of ["craft", "battle"]) inv[g] = DATA.games[g].items.map((r) => nativeItem(g, r));

    // The page opens on a crossing that already happened: the Diamond Sword went to Pocket Battlers.
    const sword = inv.craft.find((x) => x.id === "diamond_sword");
    if (sword) {
      inv.craft = inv.craft.filter((x) => x !== sword);
      const v = DATA.transfers["craft:diamond_sword"];
      await showVerdict(v, sword, "craft", "battle", false);
      land(sword, v, "craft", "battle");
    }
    renderInv("craft"); renderInv("battle");
    log("craft", "Click an item to use it. Drag it into Pocket Battlers to send it across.");
    log("battle", "What will Shellbit do? The Diamond Sword came over from Blockcraft. Try it on the Fire-type.");

    $("#forge-game").addEventListener("change", forgeKinds);
    $("#forge-kind").addEventListener("change", () => forgeFields());
    $("#forge-form").addEventListener("submit", forge);
    $("#try").replaceChildren(...TRIES.map(([label, g, kind, preset]) => h("button", { type: "button", text: label, onclick: () => {
      $("#forge-game").value = g; forgeKinds(); $("#forge-kind").value = kind; forgeFields(preset); $("#forge-send").focus();
    } })));
    forgeKinds();
    probeApi();
    renderCards(); renderSources(); renderFoot();
  }
  boot();
})();
