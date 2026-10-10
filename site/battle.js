// Pocket Battlers: a turn-based creature battle. Every move has a type, and
// the type chart decides how hard it lands. A creature has 100 HP.
(function () {
  "use strict";
  const W = 256, H = 160;
  // Attacker type -> defender type -> multiplier; a pair not listed is 1.
  // Every value here is the same as the matching entry in the best-known
  // creature battler's type chart: the cycle of Water over Fire, Fire over
  // Grass and Grass over Water is the genre's mechanic, and we kept it. The
  // choice of six types is ours. A chart is a mechanic, not a name, and no
  // battle text is borrowed: each line about a matchup is made from these values.
  const CHART = {
    Water: { Fire: 2, Rock: 2, Water: 0.5, Grass: 0.5 },
    Fire: { Grass: 2, Steel: 2, Fire: 0.5, Water: 0.5, Rock: 0.5 },
    Grass: { Water: 2, Rock: 2, Fire: 0.5, Grass: 0.5, Steel: 0.5 },
    Rock: { Fire: 2, Steel: 0.5 },
    Steel: { Rock: 2, Fire: 0.5, Water: 0.5, Steel: 0.5 },
    Normal: { Rock: 0.5, Steel: 0.5 },
  };
  const eff = (a, d) => (CHART[a] && CHART[a][d]) || 1;
  const TIMES = { 2: "double", 0.5: "half" };
  // What a type matchup does, in words made from the chart, or null when it is 1.
  function matchup(type, foeType, m) {
    const how = TIMES[m] || `×${m}`;
    if (m > 1) return `${type} beats ${foeType}: ${how} damage.`;
    if (m < 1) return `${foeType} resists ${type}: ${how} damage.`;
    return null;
  }
  const TYPE_COLOR = { Fire: "#f08a3c", Water: "#4aa8e0", Grass: "#5cb85c", Rock: "#b59a5a", Steel: "#8a9bb0", Normal: "#a8a090" };

  function create(canvas, hooks) {
    const ctx = canvas.getContext("2d");
    canvas.width = W * 2; canvas.height = H * 2;
    ctx.scale(2, 2);
    const S = Sprites, MAX = hooks.maxHp;
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    // Every number here comes from the game's scene in the page data
    // (games/battle/scene.json, copied by the build): nothing is typed in this file.
    const sc = hooks.scene || {}, Y = sc.yours || {}, Wd = sc.wild || {};
    const WILD_MOVE = Wd.move, WILD_POWER = Wd.power;
    const mine = { name: Y.name, kind: Y.name, type: Y.type, hp: Y.start_hp };
    const wild = { name: Wd.name, kind: Wd.name, type: Wd.type, hp: MAX, caught: false };
    const st = { shot: null, ally: null, orb: null, floats: [], hitWild: 0, hitMine: 0 };
    const wait = (ms) => new Promise((r) => setTimeout(r, reduce ? Math.min(ms, 60) : ms));
    const float = (x, y, text, color) => st.floats.push({ x, y, text, color, t: performance.now() });

    async function strike(user, power, type, label) {
      const m = eff(type, wild.type);
      const dmg = Math.round(power * m);
      await hooks.say(`${user} goes for ${label}.`);
      // Under reduced motion nothing flies across the screen: no projectile, no orb arc.
      if (!reduce) st.shot = { t: performance.now(), type, item: label === user ? null : st.shotItem };
      await wait(420);
      wild.hp = Math.max(0, wild.hp - dmg); st.hitWild = performance.now();
      float(190, 30, "-" + dmg, "#fff");
      const line = matchup(type, wild.type, m);
      await hooks.say(`${line ? line + " " : ""}${wild.name} loses ${dmg} HP.`);
      if (wild.hp <= 0) {
        await hooks.say(`${wild.name} is knocked out.`);
        await wait(500); wild.hp = MAX;
        await hooks.say(`A fresh ${wild.name} pops up out of the ground.`);
        return false;
      }
      return true;
    }

    async function wildTurn() {
      await wait(300);
      const m = eff(wild.type, mine.type);
      const dmg = Math.round(WILD_POWER * m);
      await hooks.say(`${wild.name} answers with ${WILD_MOVE}.`);
      const line = matchup(wild.type, mine.type, m);
      mine.hp = Math.max(0, mine.hp - dmg); st.hitMine = performance.now();
      float(60, 96, "-" + dmg, "#ff8f8f");
      await hooks.say(`${line ? line + " " : ""}${mine.name} loses ${dmg} HP.`);
      if (mine.hp <= 0) { await hooks.say(`${mine.name} is knocked out. It rests, heals and comes back.`); mine.hp = MAX; }
    }

    // One turn. Resolves when the text box has said everything.
    async function act(item) {
      const s = item.stats;
      if (item.cat === "move" || item.cat === "weapon") {
        st.shotItem = item.cat === "weapon" ? item : null;
        const type = s.type || "Normal";
        if (await strike(mine.name, s.power, type, item.name)) await wildTurn();
      } else if (item.cat === "heal") {
        const before = mine.hp;
        mine.hp = Math.min(MAX, mine.hp + s.hp);
        st.ally = { item, t: performance.now(), heal: true };
        float(60, 96, "+" + (mine.hp - before), "#8ff0a0");
        await hooks.say(`The ${item.name} gives ${mine.name} back ${mine.hp - before} HP.`);
        await wildTurn();
      } else if (item.cat === "capture") {
        if (!reduce) st.orb = { item, t: performance.now() };
        await hooks.say(`You toss the ${item.name}.`);
        await wait(700);
        // The orb's own catch rate decides: it holds a creature whose HP is at
        // most that share of the maximum (a catch rate of 40 holds one at 40 of 100 HP).
        const holds = Math.floor((MAX * (s.rate ?? 0)) / 100);
        if (wild.hp <= holds) {
          await hooks.say(`Caught! The ${item.name} holds the wild ${wild.name}.`);
          await wait(400); wild.hp = MAX;
          await hooks.say(`A fresh ${wild.name} pops up out of the ground.`);
        } else {
          await hooks.say(`It broke out. Weaken it to ${holds} HP or less first.`);
          await wildTurn();
        }
      } else if (item.cat === "creature") {
        st.ally = { item, t: performance.now() };
        st.shotItem = null;
        await hooks.say(`${item.name} jumps in to help.`);
        if (await strike(item.name, s.power, s.type || "Normal", s.move || "an attack")) await wildTurn();
      } else {
        await hooks.say(`The ${item.name} does nothing in Pocket Battlers.`);
      }
    }

    // ------------------------------------------------------------ drawing
    function hpBox(x, y, w, c, showNumbers) {
      ctx.fillStyle = "rgba(255,252,240,0.95)"; ctx.strokeStyle = S.INK; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.roundRect(x, y, w, showNumbers ? 30 : 24, 4); ctx.fill(); ctx.stroke();
      ctx.font = "8px 'Pixelify Sans', monospace"; ctx.textBaseline = "top"; ctx.fillStyle = S.INK;
      ctx.fillText(c.name.toUpperCase(), x + 5, y + 4);
      const tw = ctx.measureText(c.type.toUpperCase()).width + 6;
      ctx.fillStyle = TYPE_COLOR[c.type]; ctx.beginPath(); ctx.roundRect(x + w - tw - 5, y + 3, tw, 9, 2); ctx.fill();
      ctx.fillStyle = "#fff"; ctx.fillText(c.type.toUpperCase(), x + w - tw - 2, y + 4);
      const f = c.hp / MAX;
      ctx.fillStyle = "#3a3550"; ctx.fillRect(x + 5, y + 15, w - 10, 5);
      ctx.fillStyle = f > 0.5 ? "#5cd06a" : f > 0.2 ? "#f2c84b" : "#e8504a";
      ctx.fillRect(x + 6, y + 16, (w - 12) * f, 3);
      if (showNumbers) { ctx.fillStyle = S.INK; ctx.fillText(`${c.hp} / ${MAX} HP`, x + 5, y + 21); }
    }

    function frame(now) {
      const g = ctx.createLinearGradient(0, 0, 0, H);
      g.addColorStop(0, "#fdf6e3"); g.addColorStop(1, "#dff2cf");
      ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
      S.blob(ctx, 190, 72, 46, 10, "#b6dc9c", 1);
      S.blob(ctx, 66, 142, 58, 12, "#b6dc9c", 1);
      // Under reduced motion nothing moves on its own: no idle flicker, no shake, no drifting numbers.
      const t = reduce ? 0 : now / 160;
      const wob = (t0) => (!reduce && now - t0 < 260 ? Math.sin((now - t0) / 20) * 3 : 0);
      if (!(st.orb && now - st.orb.t < 1100 && now - st.orb.t > 500)) S.creature(ctx, wild.kind, 190 + wob(st.hitWild), 70, 46, t);
      S.creature(ctx, mine.kind, 66 + wob(st.hitMine), 140, 58, t);
      if (st.ally) {
        const k = (now - st.ally.t) / 1400;
        if (k > 1) st.ally = null;
        else if (st.ally.heal) S.icon(ctx, st.ally.item, 66, 70 - (reduce ? 0 : k * 10), 20);
        else S.icon(ctx, st.ally.item, 118, 128, 40, t);
      }
      if (st.shot) {
        const k = (now - st.shot.t) / 420;
        if (k > 1) st.shot = null;
        else {
          const x = 80 + k * 108, y = 112 - k * 66;
          if (st.shot.item) { ctx.save(); ctx.translate(x, y); ctx.rotate(k * 6); S.icon(ctx, st.shot.item, 0, 0, 22); ctx.restore(); }
          else { ctx.fillStyle = TYPE_COLOR[st.shot.type] || "#fff"; for (let i = 0; i < 4; i++) { ctx.beginPath(); ctx.arc(x - i * 6, y + i * 4, 4 - i * 0.6, 0, 7); ctx.fill(); } }
        }
      }
      if (st.orb) {
        const k = (now - st.orb.t) / 1100;
        if (k > 1) st.orb = null;
        else { const t = Math.min(1, k * 2); S.icon(ctx, st.orb.item, 70 + t * 120, 110 - t * 60 - Math.sin(t * Math.PI) * 30, 16); }
      }
      hpBox(8, 8, 108, wild, false);
      hpBox(140, 94, 108, mine, true);
      st.floats = st.floats.filter((f) => now - f.t < 900);
      ctx.font = "11px 'Pixelify Sans', monospace";
      for (const f of st.floats) {
        const rise = reduce ? 0 : ((now - f.t) / 900) * 14;
        ctx.fillStyle = S.INK; ctx.fillText(f.text, f.x + 1, f.y - rise + 1);
        ctx.fillStyle = f.color; ctx.fillText(f.text, f.x, f.y - rise);
      }
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);

    // The running HP of both creatures, in words, for the page's status line.
    const status = () => `${mine.name} has ${mine.hp} of ${MAX} HP. The wild ${wild.name} has ${wild.hp} of ${MAX} HP.`;
    return { act, status, foeType: () => wild.type };
  }

  window.Battle = { create, eff: (a, d) => (CHART[a] && CHART[a][d]) || 1 };
})();
