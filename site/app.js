// The border desk. Every verdict, number and message it shows is read from
// data/verdicts.json (the engine's output at build time) or from the live
// engine behind api/judge. Nothing here decides whether an item may cross.
(function () {
  "use strict";
  const $ = (s, r) => (r || document).querySelector(s);
  const OTHER = { blocky: "souls", souls: "blocky" };
  const LABEL = { blocky: "Blocky", souls: "Ashen" };
  const ORDER = ["unpack", "rules", "closure", "border"];
  const SPECIFIC = ["TwoHandedWeapon", "MeleeWeapon", "Weapon", "BodyArmour", "Armour",
                    "HealingConsumable", "Consumable", "RespawnAnchor", "Item"];
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

  let DATA = null, API = null, busy = false, uidN = 0;
  const P = {};                       // conventions read from each published profile
  const inv = { blocky: [], souls: [] };
  const selected = { blocky: null, souls: null };
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
  const sleep = (ms) => new Promise((r) => setTimeout(r, reduce ? 0 : ms));
  const gameOfIri = (iri) => (iri && iri.includes("/blocky#") ? "blocky" : iri && iri.includes("/souls#") ? "souls" : null);

  // ------------------------------------------------------------ the profiles

  function conventions(ttl) {
    const num = (p) => { const m = ttl.match(new RegExp("ga:" + p + "\\s+([0-9.]+)")); return m ? Number(m[1]) : null; };
    return { maxHp: num("maxPlayerHealth"), metres: num("metresPerLengthUnit"), maxArmour: num("maxArmourRating"),
             redAtMax: num("damageReductionAtMaxArmour"), defaultStamina: num("defaultStaminaCost") };
  }
  const unitName = (m) => (m === 1 ? "metre" : m === 0.01 ? "centimetre" : `${m} m`);
  function cap(ttl, path) {
    const m = ttl.match(new RegExp("sh:path ga:" + path + "[^\\]]*?sh:maxInclusive ([0-9.]+)"));
    return m ? Number(m[1]) : null;
  }
  const messages = (ttl) => [...ttl.matchAll(/sh:message "([^"]+)"/g)].map((m) => m[1]);

  // ------------------------------------------------------------ items

  function catFrom(types) {
    const t = new Set(types || []);
    if (t.has("Weapon") || t.has("MeleeWeapon")) return "weapon";
    if (t.has("Armour") || t.has("BodyArmour")) return "armour";
    if (t.has("HealingConsumable")) return "heal";
    if (t.has("RespawnAnchor")) return "anchor";
    return "other";
  }
  const specific = (types) => SPECIFIC.find((s) => (types || []).includes(s));

  function nativeStats(game, cat, r) {
    if (game === "blocky") {
      if (cat === "weapon") return { damage: r.attack ?? 1, reach: r.size ?? 1 };
      if (cat === "armour") return { points: r.armorPoints ?? 0 };
      if (cat === "heal") return { hp: r.heals ?? 0, refills: false, charges: 1, maxCharges: 1 };
      return {};
    }
    if (cat === "weapon") return { damage: r.attackRating ?? 40, lengthCm: r.bladeLengthCm ?? 44,
                                   stamina: r.stamina ?? P.souls.defaultStamina, poise: r.poiseDamage ?? 0 };
    if (cat === "armour") return { absorption: r.absorption ?? 0 };
    if (cat === "heal") return { hp: r.restoresHp ?? 0, refills: !!r.refillsAtBonfire, charges: 3, maxCharges: 3 };
    return {};
  }

  function importedStats(target, cat, c) {
    if (target === "blocky") {
      if (cat === "weapon") return { damage: c.damageInTarget, reach: c.lengthInTarget };
      if (cat === "armour") return { points: c.armourInTarget };
      if (cat === "heal") return { hp: c.healInTarget, refills: false, charges: 1, maxCharges: 1 };
    } else {
      if (cat === "weapon") return { damage: c.damageInTarget, lengthCm: c.lengthInTarget, stamina: c.staminaCostInTarget, poise: 0 };
      if (cat === "armour") return { absorption: c.armourInTarget };
      if (cat === "heal") return { hp: c.healInTarget, refills: false, charges: 1, maxCharges: 1 };
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
    return { uid: ++uidN, home: src.home, place: target, id: src.id, name: src.name, kind: src.kind, cat,
             rec: src.rec, imported: true, verdict: v, stats: importedStats(target, cat, v.conversion) };
  }

  function statLine(game, it) {
    const s = it.stats;
    if (game === "blocky") {
      if (it.cat === "weapon") return `${fmt(s.damage)} dmg · ${fmt(s.reach)} ${s.reach === 1 ? "block" : "blocks"}`;
      if (it.cat === "armour") return `${fmt(s.points)} armour points`;
      if (it.cat === "heal") return `+${fmt(s.hp)} HP · single use`;
      if (it.cat === "anchor") return "sets your spawn";
    } else {
      if (it.cat === "weapon") return `${fmt(s.damage)} dmg · ${fmt(s.lengthCm)} cm · ${fmt(s.stamina)} stamina`;
      if (it.cat === "armour") return `absorbs ${fmt(s.absorption)}%`;
      if (it.cat === "heal") return `+${fmt(s.hp)} HP · ${s.charges}/${s.maxCharges}${s.refills ? " · refills" : " · no refill"}`;
    }
    return "no use here";
  }

  // ------------------------------------------------------------ inventories

  function renderInv(game) {
    const box = $(`#${game}-inv`);
    box.replaceChildren();
    for (const it of inv[game]) {
      const cv = h("canvas", { width: 88, height: 88, "aria-hidden": "true" });
      const ctx = cv.getContext("2d");
      ctx.imageSmoothingEnabled = it.home !== "blocky";
      Sprites.drawIcon(ctx, it, 44, 44, 70);
      const eq = games[game].equipped(it);
      const btn = h("button", {
        class: "slot", type: "button", role: "listitem", "aria-pressed": String(selected[game] === it.uid),
        title: it.imported ? null : `Drag into ${LABEL[OTHER[game]]}`,
        onclick: (e) => {
          if (e.currentTarget.dataset.dragged) { delete e.currentTarget.dataset.dragged; return; }
          selected[game] = selected[game] === it.uid ? null : it.uid; renderInv(game);
        },
      }, cv, h("span", { class: "nm", text: it.name }), h("span", { class: "st", text: statLine(game, it) }),
         eq ? h("span", { class: "tag eq", text: "equipped" }) : null,
         it.imported ? h("span", { class: "tag pp", text: "passport" }) : null);
      btn.addEventListener("pointerdown", (e) => startDrag(e, game, it, cv, btn));
      btn.addEventListener("pointermove", moveDrag);
      btn.addEventListener("pointerup", endDrag);
      btn.addEventListener("pointercancel", endDrag);
      box.append(btn);
    }
    renderActions(game);
  }

  function renderActions(game) {
    const box = $(`#${game}-actions`);
    box.replaceChildren();
    const it = inv[game].find((x) => x.uid === selected[game]);
    if (!it) { box.append(h("span", { class: "hint", text: `Drag an item into ${LABEL[OTHER[game]]}, or select it to use or send it.` })); return; }
    const g = games[game];
    if (it.cat === "weapon" || it.cat === "armour") {
      const on = g.equipped(it);
      box.append(h("button", { type: "button", class: "use", text: on ? "Unequip" : "Equip",
        onclick: () => { if (on) g.unequip(it); else { inv[game].filter((x) => x.cat === it.cat).forEach((x) => g.unequip(x)); g.equip(it); } renderInv(game); } }));
    } else if (it.cat === "heal" || it.cat === "anchor") {
      box.append(h("button", { type: "button", class: "use", text: it.cat === "anchor" ? "Place" : "Drink",
        onclick: () => { if (g.use(it)) { inv[game] = inv[game].filter((x) => x !== it); selected[game] = null; } renderInv(game); } }));
    }
    box.append(h("button", { type: "button", class: "send", disabled: it.imported || busy,
      text: `Send to ${LABEL[OTHER[game]]} →`, onclick: () => send(it) }));
    if (it.imported) box.append(h("span", { class: "hint", text: "In this demo a passport is good for one crossing." }));
  }

  // ------------------------------------------------------------ drag and drop

  let drag = null;
  const dropTarget = (game) => $(game === "blocky" ? "#ashen" : "#blocky");
  const sideBySide = () => matchMedia("(min-width: 761px)").matches;

  function startDrag(e, game, it, icon, btn) {
    if (busy || it.imported || e.button !== 0) return;
    if (e.pointerType === "touch" && !sideBySide()) return;   // stacked layout: tap, then Send
    drag = { game, it, icon, btn, id: e.pointerId, x0: e.clientX, y0: e.clientY, started: false };
    btn.setPointerCapture(e.pointerId);
  }

  function over(game, x, y) {
    const el = document.elementFromPoint(x, y);
    return !!el && !!(el.closest(dropTarget(game) === $("#ashen") ? "#ashen" : "#blocky") || el.closest("#desk"));
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
      t.classList.add("drop-ready");
      $("#desk").classList.add("drop-ready");
    }
    drag.ghost.style.transform = `translate(${e.clientX - 34}px, ${e.clientY - 34}px)`;
    const hot = over(drag.game, e.clientX, e.clientY);
    dropTarget(drag.game).classList.toggle("drop-hot", hot);
    $("#desk").classList.toggle("drop-hot", hot);
  }

  function endDrag(e) {
    if (!drag || e.pointerId !== drag.id) return;
    const d = drag; drag = null;
    if (!d.started) return;                                    // it was a click
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
      if (lane === "direct" && (g === "rules" || g === "closure") && g !== stop) {
        out[g] = { state: "pass", chip: "same store", note: g === "rules"
          ? `Live lane: the engine loaded ${LABEL[src] || "the source game"}'s published profile itself, so there is no passport copy to compare.`
          : `Live lane: the engine worked out the item's classes itself: ${v.hub_types && v.hub_types.length ? "ga:" + specific(v.hub_types) : "none"}.` };
        continue;
      }
      if (g === stop) {
        let note = (v.refusals[0] || {}).message || v.headline;
        if (g === "rules" && v.drift) note += " " + [...v.drift.added.map((l) => "+ " + l), ...v.drift.removed.map((l) => "− " + l)].join("  ");
        out[g] = { state: "fail", chip: "refused", note };
        continue;
      }
      out[g] = { state: "pass", chip: "pass", note: {
        unpack: `${lane === "passport" ? "Digests match. " : ""}Lean accepted ${v.proof.derivations} steps (${v.proof.theorem}).`,
        rules: `Matches ${LABEL[src]}'s published profile.`,
        closure: `Worked out here: ga:${specific(v.hub_types)}. Nothing left out.`,
        border: `Verified SHACL and SHACL both say: conforms.`,
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
        await sleep(360);
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

  function conversionRows(v, item, from, to) {
    const c = v.conversion || {}, r = item.rec || {};
    const hp = (n, g) => `${fmt(n)} of ${fmt(P[g].maxHp)} HP`;
    const len = (n, g) => (g === "blocky" ? `${fmt(n)} ${n === 1 ? "block" : "blocks"}` : `${fmt(n)} cm`);
    const arm = (n, g) => (g === "blocky" ? `${fmt(n)} of ${fmt(P.blocky.maxArmour)} armour points` : `${fmt(n)}% absorption`);
    const F = from === "blocky" ? { dmg: "attack", len: "size", arm: "armorPoints", heal: "heals" }
                                : { dmg: "attackRating", len: "bladeLengthCm", arm: "absorption", heal: "restoresHp" };
    const rows = [];
    if ("damageInTarget" in c) rows.push(["Damage", hp(r[F.dmg], from), hp(c.damageInTarget, to)]);
    if ("lengthInTarget" in c) rows.push(["Length", len(r[F.len], from), len(c.lengthInTarget, to)]);
    if ("armourInTarget" in c) rows.push(["Armour", arm(r[F.arm], from), arm(c.armourInTarget, to)]);
    if ("healInTarget" in c) rows.push(["Heals", hp(r[F.heal], from), hp(c.healInTarget, to)]);
    if ("staminaCostInTarget" in c)
      rows.push(["Stamina", c.staminaCostDefaulted ? "none" : fmt(r.stamina),
                 c.staminaCostDefaulted ? `${fmt(c.staminaCostInTarget)}, ${LABEL[to]}'s default` : fmt(c.staminaCostInTarget)]);
    return rows;
  }

  function renderPassport(v, item, from, to, animate) {
    const [cls, word, sub] = stampFor(v);
    const field = (dt, ...dd) => h("div", null, h("dt", { text: dt }), h("dd", null, ...dd));
    const fields = [];
    if (v.hub_types && v.hub_types.length) fields.push(field("Classified", h("span", { class: "mono", text: "ga:" + specific(v.hub_types) })));
    for (const [k, a, b] of conversionRows(v, item, from, to))
      fields.push(field(k, a, h("span", { class: "arrow", text: "→" }), h("span", { class: "to", text: b })));
    if (v.proof && v.proof.status)
      fields.push(field("Proof", v.proof.status.startsWith("certificate_accepted")
        ? `Lean accepted ${v.proof.derivations} steps (${v.proof.theorem})`
        : v.proof.status.replace(/_/g, " ")));
    if (v.evaluators && "verified" in v.evaluators)
      fields.push(field("Contract", `verified SHACL: ${word3(v.evaluators.verified)} · SHACL: ${word3(v.evaluators.default)}`));

    const list = (cls2, xs) => (xs.length ? h("ul", { class: cls2 }, xs.map((x) => h("li", { text: x }))) : null);
    const steps = (v.why || []).map((s) => h("li", null, h("span", { class: "rule", text: s.rule + " " }),
      h("span", { class: "mono", text: s.conclusion }), h("br"), h("span", { class: "prem mono", text: "← " + s.premises.join("; ") })));
    const calls = (v.export_transcript || []).concat(v.transcript || []).map((c) => h("li", { class: "mono" },
      h("b", { text: c.tool }), " ", clip(JSON.stringify(c.args), 140), h("br"),
      h("span", { class: "prem", text: clip(JSON.stringify(c.result), 260) })));

    const stamp = h("div", { class: `stamp ${cls}${animate ? " slam" : ""}`, role: "img", "aria-label": `${word}, ${sub}` }, word, h("small", { text: sub }));
    $("#passport").replaceChildren(h("article", { class: "pp" },
      h("div", { class: "pp-top" }, h("span", { text: "Passport" }), h("span", { text: `${LABEL[from]} → ${LABEL[to]}` })),
      h("h3", { class: "pp-name", text: item.name }),
      h("p", { class: "pp-iri mono", text: shortIri(v.item_iri) || `${from}:${item.id}` }),
      stamp,
      h("dl", null, fields),
      list("refusals", (v.refusals || []).map((r) => r.message)),
      list("losses", (v.losses || []).map((l) => l.message)),
      list("notes", v.notes || []),
      steps.length ? h("details", null, h("summary", { text: `Why the engine calls it ga:${specific(v.hub_types)}` }), h("ol", null, steps)) : null,
      calls.length ? h("details", null, h("summary", { text: `Engine transcript, ${calls.length} calls` }), h("ol", null, calls)) : null,
      v.passport ? h("a", { class: "dl", href: v.passport, download: "" , text: "Download this passport (.pack, JSON)" }) : null,
    ));
  }
  const word3 = (b) => (b === true ? "conforms" : b === false ? "violation" : "could not run");
  const clip = (s, n) => (s && s.length > n ? s.slice(0, n) + "…" : s);
  const shortIri = (iri) => iri && iri.replace(/^.*\/asset-passport\/(\w+)#/, "$1:");

  async function showVerdict(v, item, from, to, animate) {
    resetGates();
    if (animate) {
      // Fade the last passport in place while the gates run, so the page keeps its height.
      const prev = $("#passport .pp");
      if (prev) prev.classList.add("pending");
      else $("#passport").replaceChildren(h("p", { class: "pp-empty", text: `${item.name} is at the border…` }));
    }
    await runGates(v, animate);
    renderPassport(v, item, from, to, animate);
  }

  async function send(item) {
    if (busy) return;
    busy = true;
    const from = item.place, to = OTHER[from];
    games[from].unequip(item);
    inv[from] = inv[from].filter((x) => x !== item);
    selected[from] = null;
    renderInv(from); renderInv(to);
    const v = DATA.transfers[`${item.home}:${item.id}`];
    if (window.innerWidth < 1180) $("#desk").scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
    await showVerdict(v, item, from, to, true);
    land(item, v, from, to);
    busy = false;
    renderInv(from); renderInv(to);
  }

  function land(item, v, from, to) {
    if (v.verdict === "refused" || v.verdict === "undetermined") {
      if (item.place === from && !item.forged) inv[from].push(item);
      games[from].say(`${item.name} was turned back at the border.`);
      return null;
    }
    const imp = importedItem(item, v, to);
    inv[to].push(imp);
    if (games[to].track) games[to].track(imp);
    games[to].say(`${imp.name} arrived with its passport.`);
    return imp;
  }

  // ------------------------------------------------------------ forge (live)

  const FIELD = {
    attack: ["Attack", () => `HP of ${P.blocky.maxHp}`], size: ["Size", () => "blocks"],
    armorPoints: ["Armour", () => `points of ${P.blocky.maxArmour}`], heals: ["Heals", () => "HP"],
    attackRating: ["Attack rating", () => `HP of ${fmt(P.souls.maxHp)}`], bladeLengthCm: ["Blade length", () => "cm"],
    poiseDamage: ["Poise damage", () => ""], stamina: ["Stamina", () => "per swing"],
    restoresHp: ["Restores", () => "HP"], refillsAtBonfire: ["Refills at bonfire", () => ""],
    absorption: ["Absorption", () => "%"],
  };

  function forgeKinds() {
    const g = $("#forge-game").value;
    const sel = $("#forge-kind");
    sel.replaceChildren(...DATA.games[g].items.map((r) => h("option", { value: r.kind, text: r.name })));
    $("#forge-send").textContent = `Send to ${LABEL[OTHER[g]]}`;
    forgeFields();
  }

  function forgeFields(preset) {
    const g = $("#forge-game").value;
    const rec = DATA.games[g].items.find((r) => r.kind === $("#forge-kind").value);
    const vals = Object.assign({}, rec, preset || {});
    $("#forge-name").value = preset && preset.name ? preset.name : `Forged ${rec.name.toLowerCase()}`;
    const box = $("#forge-fields");
    box.replaceChildren();
    for (const key of Object.keys(rec).filter((k) => !["id", "kind", "name"].includes(k))) {
      const [label, unit] = FIELD[key] || [key, () => ""];
      const id = `ff-${key}`;
      const input = typeof rec[key] === "boolean"
        ? h("input", { id, type: "checkbox", "data-k": key, checked: !!vals[key] })
        : h("input", { id, type: "number", inputmode: "decimal", step: "any", min: "0", max: "100000", "data-k": key, value: vals[key] });
      box.append(h("div", { class: "field" }, h("label", { for: id }, label, " ", h("span", { class: "unit", text: unit() })), input));
    }
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
      if (inp.type === "checkbox") { rec[k] = inp.checked; continue; }
      if (inp.value === "") continue;
      const n = Number(inp.value);
      if (!Number.isFinite(n) || n < 0 || n > 100000) { status(`${FIELD[k] ? FIELD[k][0] : k} must be a number from 0 to 100,000.`, true); inp.focus(); return; }
      rec[k] = n;
    }
    busy = true; $("#forge-send").disabled = true;
    status("Sending to the live engine…");
    $("#forge-result").hidden = true;
    resetGates("waiting");
    $("#passport").replaceChildren(h("p", { class: "pp-empty", text: `${name} is at the border. The live engine is judging it…` }));
    try {
      const t0 = performance.now();
      const r = await fetch("api/judge", { method: "POST", headers: { "content-type": "application/json" },
                                           body: JSON.stringify({ game: g, target: to, item: rec }) });
      const v = await r.json();
      if (!r.ok) throw new Error(v.error || `The engine answered ${r.status}.`);
      const item = { uid: ++uidN, home: g, place: g, id: rec.id, name, kind, rec, forged: true, cat: catFrom(v.hub_types) };
      await showVerdict(v, item, g, to, true);
      land(item, v, g, to);
      renderInv(to);
      const [cls, word, sub] = stampFor(v);
      const said = (v.refusals[0] || v.losses[0] || {}).message || v.headline;
      $("#forge-result").replaceChildren(h("b", { text: `${word}, ${sub}` }), h("span", { text: said }),
        h("a", { href: "#desk", text: v.verdict === "refused" ? "Read the passport at the border desk" : `Read the passport, then find ${name} in ${LABEL[to]}'s inventory` }));
      $("#forge-result").dataset.v = cls;
      $("#forge-result").hidden = false;
      status(`The live engine answered in ${Math.round(performance.now() - t0)} ms.`);
    } catch (err) {
      status(`The live engine did not answer: ${err.message}`, true);
      resetGates();
    } finally {
      busy = false; $("#forge-send").disabled = !API;
    }
  }
  function status(t, err) { const s = $("#forge-status"); s.textContent = t; s.classList.toggle("err", !!err); }

  async function probeApi() {
    try {
      const r = await fetch("api/engine", { cache: "no-store" });
      if (!r.ok) throw new Error(String(r.status));
      API = await r.json();
      $("#forge-engine").textContent = `Live engine: open-ontologies ${API.tag || API.tool_version || ""}, sha256 ${String(API.binary_sha256 || "").slice(0, 12)}…`;
    } catch (_) {
      API = null;
      $("#forge-engine").textContent = "This copy of the page has no engine server, so the forge is off. Everything above was judged by the engine when the page was built. To forge live, clone the repo and run python3 local.py.";
    }
    $("#forge-send").disabled = !API;
  }

  const TRIES = [
    ["A Blocky sword at the cap", "blocky", "DiamondSword", { name: "Sword at the cap", attack: 12, size: 1 }],
    ["One point over", "blocky", "DiamondSword", { name: "Sword over the cap", attack: 13, size: 1 }],
    ["A 250 cm greatsword", "souls", "Greatsword", { name: "Zweihander", attackRating: 420, bladeLengthCm: 250, poiseDamage: 60, stamina: 32 }],
    ["Full Blocky armour in one piece", "blocky", "IronChestplate", { name: "Netherplate", armorPoints: 20 }],
    ["A flask that heals everything", "souls", "EmberFlask", { name: "Sun flask", restoresHp: 1000, refillsAtBonfire: true }],
  ];

  // ------------------------------------------------------------ smuggling

  const WHY = {
    tamper: "The digest covers the graph, so any edit without a new digest is caught before anything loads.",
    false_step: "Lean checks every step against its premises. No premise in the passport makes a bed a melee weapon.",
    own_rules: "Lean accepted this proof, because it is sound over the doctored premises. Ashen compares the passport's rules with Blocky's published profile and finds the changed line.",
    unhook: "A proof can show that what it says follows. It cannot show that the sender said everything that follows. So Ashen works out the item's classes itself and compares.",
    lie: "A passport proves the paperwork follows from Blocky's published rules. It cannot prove the sender told the truth about what the item is. That needs Blocky to sign what it exports, which this demo does not do yet.",
  };
  const CARD_ORDER = ["tamper", "false_step", "own_rules", "unhook", "lie"];

  function renderCards() {
    const by = Object.fromEntries(DATA.forgeries.map((f) => [f.name, f]));
    $("#cards").replaceChildren(...CARD_ORDER.filter((n) => by[n]).map((n) => {
      const f = by[n], v = f.verdict;
      const thru = v.verdict !== "refused";
      const quote = thru
        ? `verdict: ${v.verdict}. ${Object.entries(v.conversion).filter(([k]) => k.endsWith("InTarget")).map(([k, x]) => `${k} ${fmt(x)}`).join(", ")}`
        : (v.refusals[0] || {}).message;
      const diff = v.drift ? h("pre", { class: "diff" },
        ...v.drift.added.map((l) => h("div", { class: "add", text: "+ " + l })),
        ...v.drift.removed.map((l) => h("div", { class: "del", text: "− " + l }))) : null;
      return h("article", { class: "card" + (thru ? " thru" : "") },
        h("h3", { text: f.title }),
        h("p", { class: "did", text: f.did }),
        h("div", { class: "res" },
          h("span", { class: "badge" + (thru ? " thru" : ""), text: thru ? "Gets through" : `Stopped at gate ${ORDER.indexOf(v.stage) + 1}` }),
          h("span", { class: "status", text: thru ? "" : gateName(v.stage) })),
        h("blockquote", { text: quote }),
        diff,
        h("p", { class: "why", text: WHY[n] || "" }));
    }));
  }
  const gateName = (s) => $(`.gate[data-gate="${s}"] .gn`).textContent;

  // ------------------------------------------------------------ sources, footer

  function renderSources() {
    const files = [
      ["Game Asset core", "ontology/ga-core.ttl", DATA.files.hub],
      ["Blocky profile", "games/blocky/profile.ttl", DATA.games.blocky.profile],
      ["Ashen profile", "games/souls/profile.ttl", DATA.games.souls.profile],
      ["Conversion rule", "rules/convert.rq", DATA.files.rule],
      ["Ashen border", "contracts/souls-border.shacl.ttl", DATA.files.souls_border],
      ["Blocky border", "contracts/blocky-border.shacl.ttl", DATA.files.blocky_border],
      ["Blocky losses", "contracts/blocky-loss.shacl.ttl", DATA.files.blocky_loss],
    ];
    $("#sources").replaceChildren(...files.map(([t, p, body]) =>
      h("details", null, h("summary", null, t, " ", h("span", { class: "mono", text: p })), h("pre", { text: body }))));
  }

  function renderFoot() {
    const e = DATA.engine;
    $("#foot").replaceChildren(
      h("p", { text: `Every verdict, number and message on this page was produced by open-ontologies ${e.tool_version} (main at ${e.open_ontologies_rev}) when the page was built, ${e.built_at || DATA.built_at}. The forge asks the released engine live.` }),
      h("p", { class: "mono", text: `engine sha256 ${e.binary_sha256} · oo-cert sha256 ${e.oo_cert_sha256}` }),
      h("p", null, "Both games, their art and their items are original to this demo. ", h("a", { href: "https://github.com/fabio-rovai/open-ontologies", text: "Open Ontologies on GitHub" }), "."));
  }

  // ------------------------------------------------------------ boot

  async function boot() {
    for (const li of document.querySelectorAll(".gate")) GATE_TEXT[li.dataset.gate] = li.querySelector(".gd").textContent;
    try {
      DATA = await (await fetch("data/verdicts.json")).json();
    } catch (err) {
      $("#passport").replaceChildren(h("p", { class: "pp-empty", text: "The engine's verdicts did not load. Serve this folder over HTTP (python3 local.py) rather than opening the file directly." }));
      return;
    }
    for (const g of ["blocky", "souls"]) P[g] = conventions(DATA.games[g].profile);
    $("#blocky-conv").textContent = `1 block = 1 ${unitName(P.blocky.metres)} · ${P.blocky.maxHp} HP · whole numbers`;
    $("#souls-conv").textContent = `1 unit = 1 ${unitName(P.souls.metres)} · ${fmt(P.souls.maxHp)} HP · stamina · bonfires`;
    $("#dg-blocky").textContent = `${unitName(P.blocky.metres)}s · ${P.blocky.maxHp} HP`;
    $("#dg-souls").textContent = `${unitName(P.souls.metres)}s · ${fmt(P.souls.maxHp)} HP`;
    const bb = DATA.files.blocky_border, sb = DATA.files.souls_border;
    $("#dg-blocky-c").textContent = `≤ ${cap(bb, "damageInTarget")} HP a hit · ≤ ${fmt(cap(bb, "lengthInTarget"))} blocks`;
    $("#dg-souls-c").textContent = `≤ ${fmt(cap(sb, "damageInTarget"))} HP a hit${/hasValue ga:RespawnAnchor/.test(sb) ? " · no anchors" : ""}`;
    $("#caps").replaceChildren(...[["Ashen", sb], ["Blocky", bb]].map(([n, t]) =>
      h("div", null, h("p", { class: "status", text: n }), h("ul", null, messages(t).filter((m) => !/which game/.test(m)).map((m) => h("li", { text: m }))))));

    games.blocky = Blocky.create($("#blocky-canvas"), { maxHp: P.blocky.maxHp, reductionPerPoint: P.blocky.redAtMax / P.blocky.maxArmour });
    games.souls = Ashen.create($("#ashen-canvas"), { maxHp: P.souls.maxHp, maxArmour: P.souls.maxArmour, reductionAtMax: P.souls.redAtMax,
                                                      changed: () => renderInv("souls") });
    for (const g of ["blocky", "souls"]) inv[g] = DATA.games[g].items.map((r) => nativeItem(g, r));
    for (const it of inv.souls) if (it.cat === "heal") games.souls.track(it);
    const equipFirst = (g, cat) => { const it = inv[g].find((x) => x.cat === cat); if (it) games[g].equip(it); };
    equipFirst("blocky", "armour"); equipFirst("souls", "weapon"); equipFirst("souls", "armour");

    // The page opens on a crossing that already happened: the Diamond Sword went to Ashen.
    const sword = inv.blocky.find((x) => x.id === "diamond_sword");
    if (sword) {
      inv.blocky = inv.blocky.filter((x) => x !== sword);
      const v = DATA.transfers["blocky:diamond_sword"];
      await showVerdict(v, sword, "blocky", "souls", false);
      land(sword, v, "blocky", "souls");
      selected.souls = null;
    }
    renderInv("blocky"); renderInv("souls");

    // pads
    document.querySelectorAll("[data-b]").forEach((b) => b.addEventListener("click", () => {
      const a = b.dataset.b, g = games.blocky;
      if (a === "attack") g.attack(); else g.move(...{ left: [-1, 0], right: [1, 0], up: [0, -1], down: [0, 1] }[a]);
    }));
    document.querySelectorAll("[data-a]").forEach((b) => {
      const a = b.dataset.a, g = games.souls;
      if (a === "left" || a === "right") {
        const d = a === "left" ? -1 : 1;
        b.addEventListener("pointerdown", (e) => { e.preventDefault(); b.setPointerCapture(e.pointerId); g.hold(d, true); });
        for (const ev of ["pointerup", "pointercancel", "lostpointercapture"]) b.addEventListener(ev, () => g.hold(d, false));
      } else b.addEventListener("click", () => (a === "rest" ? g.rest() : g.attack()));
    });

    // forge
    $("#forge-game").addEventListener("change", forgeKinds);
    $("#forge-kind").addEventListener("change", () => forgeFields());
    $("#forge-form").addEventListener("submit", forge);
    $("#try").replaceChildren(...TRIES.map(([label, g, kind, preset]) => h("button", { type: "button", text: label, onclick: () => {
      $("#forge-game").value = g; forgeKinds(); $("#forge-kind").value = kind; forgeFields(preset); $("#forge-send").focus();
    } })));
    forgeKinds();
    probeApi();

    renderCards();
    renderSources();
    renderFoot();
  }

  boot();
})();
