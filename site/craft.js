// Blockcraft: one screen, one click per action. You act, the zombie answers.
// A player has 20 HP, drawn as ten hearts. No types, no capturing.
(function () {
  "use strict";
  const W = 256, H = 160, GROUND = 112;
  const HEART = [".kk.kk.", "krrkrrk", "krrrrrk", ".krrrk.", "..krk..", "...k..."];
  const HALF = [".kk.kk.", "krrk..k", "krrk..k", ".krk.k.", "..kkk..", "...k..."];
  const EMPTY = [".kk.kk.", "k..k..k", "k.....k", ".k...k.", "..k.k..", "...k..."];
  const GOLD = [".kk.kk.", "kyykyyk", "kyyyyyk", ".kyyyk.", "..kyk..", "...k..."];

  function create(canvas, hooks) {
    const ctx = canvas.getContext("2d");
    canvas.width = W * 2; canvas.height = H * 2;
    ctx.scale(2, 2);
    const S = Sprites, MAX = hooks.maxHp;
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const st = { hp: Math.round(MAX * 0.6), bonus: 0, zombie: MAX, zAlive: true, pet: null,
                 swing: null, boom: null, fire: null, floats: [], shake: 0 };
    const wait = (ms) => new Promise((r) => setTimeout(r, reduce ? Math.min(ms, 60) : ms));
    const float = (x, y, text, color) => st.floats.push({ x, y, text, color, t: performance.now() });

    async function zombieTurn() {
      if (!st.zAlive) return;
      await wait(450);
      let d = 2;
      const fromBonus = Math.min(st.bonus, d); st.bonus -= fromBonus; d -= fromBonus;
      st.hp -= d; float(64, 76, "-2", "#ff8f8f");
      hooks.log(`The zombie hits back for 2${fromBonus ? ", taken from your gold hearts" : ""}.`, true);
      if (st.hp <= 0) { await wait(500); st.hp = MAX; st.bonus = 0; hooks.log("You fell, and wake up with full hearts.", true); }
    }

    async function hitZombie(dmg, what) {
      st.zombie -= dmg; st.shake = performance.now();
      float(186, 70, "-" + dmg, "#fff");
      if (st.zombie <= 0) {
        st.zAlive = false;
        hooks.log(`${what}: ${dmg} damage. The zombie is defeated.`);
        await wait(900);
        st.zombie = MAX; st.zAlive = true;
        hooks.log("Another zombie shambles in.", true);
        return false;
      }
      hooks.log(`${what}: ${dmg} damage. The zombie has ${st.zombie} of ${MAX} HP left.`);
      return true;
    }

    // One action. Resolves when its animation and the zombie's answer are done.
    async function act(item) {
      const s = item.stats;
      if (item.cat === "weapon") {
        st.swing = { item, t: performance.now() };
        await wait(240);
        if (await hitZombie(s.damage, `You hit the zombie with the ${item.name}`)) await zombieTurn();
      } else if (item.cat === "explosive") {
        st.boom = { item, t: performance.now() };
        hooks.log(`You light the ${item.name}…`);
        await wait(900);
        await hitZombie(s.damage, `The ${item.name} explodes`);
      } else if (item.cat === "heal") {
        const before = st.hp;
        st.hp = Math.min(MAX, st.hp + s.hp);
        st.bonus = Math.max(st.bonus, s.bonus || 0);
        float(64, 76, "+" + (st.hp - before), "#8ff0a0");
        hooks.log(`You use the ${item.name}: +${st.hp - before} HP${s.bonus ? ` and ${s.bonus} gold bonus HP` : ""}.`);
        await zombieTurn();
      } else if (item.cat === "creature") {
        st.pet = item;
        st.fire = { t: performance.now() };
        await wait(420);
        if (await hitZombie(s.damage, `Your pet ${item.name} uses ${s.move || "an attack"}`)) await zombieTurn();
      } else {
        hooks.log(`The ${item.name} does nothing in Blockcraft.`);
      }
    }

    // ------------------------------------------------------------ drawing
    function block(x, y, top) {
      ctx.fillStyle = "#8b5a2b"; ctx.fillRect(x, y, 16, 16);
      ctx.fillStyle = "#6e4420"; ctx.fillRect(x + 3, y + 9, 2, 2); ctx.fillRect(x + 11, y + 5, 2, 2); ctx.fillRect(x + 7, y + 13, 2, 1);
      if (top) { ctx.fillStyle = "#5dbb4c"; ctx.fillRect(x, y, 16, 4); ctx.fillStyle = "#4b9e3d"; ctx.fillRect(x, y + 4, 16, 1); ctx.fillRect(x + 2, y + 4, 2, 2); ctx.fillRect(x + 10, y + 4, 2, 2); }
    }
    function player(x) {
      ctx.fillStyle = "#3b4a9c"; ctx.fillRect(x + 3, GROUND - 12, 4, 12); ctx.fillRect(x + 9, GROUND - 12, 4, 12);
      ctx.fillStyle = "#2bb3a3"; ctx.fillRect(x + 2, GROUND - 24, 12, 12);
      ctx.fillStyle = "#e8b48a"; ctx.fillRect(x + 3, GROUND - 32, 10, 9);
      ctx.fillStyle = "#4e2d14"; ctx.fillRect(x + 3, GROUND - 32, 10, 3);
      ctx.fillStyle = "#1d1f2b"; ctx.fillRect(x + 9, GROUND - 27, 2, 2);
      ctx.fillStyle = "#e8b48a"; ctx.fillRect(x + 14, GROUND - 22, 3, 8);
    }
    function zombie(x, now) {
      const hurt = now - st.shake < 160;
      const dx = hurt ? 2 : 0;
      ctx.fillStyle = "#4a3b6b"; ctx.fillRect(x + 3 + dx, GROUND - 12, 4, 12); ctx.fillRect(x + 9 + dx, GROUND - 12, 4, 12);
      ctx.fillStyle = hurt ? "#ffffff" : "#7a5a3a"; ctx.fillRect(x + 2 + dx, GROUND - 24, 12, 12);
      ctx.fillStyle = hurt ? "#ffffff" : "#6aa84f"; ctx.fillRect(x + 3 + dx, GROUND - 32, 10, 9);
      ctx.fillRect(x - 3 + dx, GROUND - 22, 5, 3);
      ctx.fillStyle = "#1d1f2b"; ctx.fillRect(x + 4 + dx, GROUND - 28, 2, 2); ctx.fillRect(x + 8 + dx, GROUND - 28, 2, 2);
      // its hearts, ten small ones
      for (let i = 0; i < MAX / 2; i++) {
        const v = st.zombie - i * 2;
        ctx.fillStyle = "#1d1f2b"; ctx.fillRect(x - 12 + i * 4, GROUND - 42, 4, 4);
        ctx.fillStyle = v >= 2 ? "#d8413a" : v === 1 ? "#e88a84" : "#3a3d52";
        ctx.fillRect(x - 11 + i * 4, GROUND - 41, 2, 2);
      }
    }

    function frame(now) {
      ctx.fillStyle = "#8fd3ff"; ctx.fillRect(0, 0, W, H);
      ctx.fillStyle = "#a9ddff"; ctx.fillRect(0, 0, W, 40);
      ctx.fillStyle = "#fff3a0"; ctx.fillRect(214, 14, 16, 16);
      ctx.fillStyle = "#ffffff"; ctx.fillRect(40, 24, 34, 8); ctx.fillRect(48, 18, 18, 6); ctx.fillRect(130, 34, 26, 6);
      for (let x = 0; x < W; x += 16) { block(x, GROUND, true); block(x, GROUND + 16, false); block(x, GROUND + 32, false); }
      player(56);
      if (st.pet) S.icon(ctx, st.pet, 30, GROUND - 14, 30, now / 200);
      if (st.zAlive) zombie(180, now);
      // a swing: the item itself, in its home style, arcs through the player's hand
      if (st.swing) {
        const k = (now - st.swing.t) / 260;
        if (k > 1) st.swing = null;
        else { ctx.save(); ctx.translate(74, GROUND - 20); ctx.rotate(-1.4 + k * 2.2); S.icon(ctx, st.swing.item, 10, -6, 20); ctx.restore(); }
      }
      if (st.boom) {
        const k = (now - st.boom.t) / 1300;
        if (k > 1) st.boom = null;
        else if (k < 0.7) { if (Math.floor(k * 12) % 2 === 0 || reduce) S.icon(ctx, st.boom.item, 170, GROUND - 8, 16); }
        else { const r = (k - 0.7) * 120; ctx.fillStyle = "rgba(255,210,120,0.75)"; ctx.fillRect(170 - r, GROUND - 8 - r, r * 2, r * 1.6); }
      }
      if (st.fire) {
        const k = (now - st.fire.t) / 420;
        if (k > 1) st.fire = null;
        else for (let i = 0; i < 5; i++) { ctx.fillStyle = i % 2 ? "#ff8a3d" : "#ffe08a"; ctx.fillRect(40 + k * 140 + i * 3, GROUND - 22 + Math.sin(i + k * 8) * 4, 4, 4); }
      }
      // your hearts, plus gold bonus hearts
      for (let i = 0; i < MAX / 2; i++) {
        const hp = Math.max(0, st.hp);
        S.pixels(ctx, hp >= (i + 1) * 2 ? HEART : hp === i * 2 + 1 ? HALF : EMPTY, 6 + i * 8, 6, 1);
      }
      for (let i = 0; i < Math.ceil(st.bonus / 2); i++) S.pixels(ctx, GOLD, 6 + i * 8, 14, 1);
      ctx.font = "8px Silkscreen, monospace"; ctx.textBaseline = "top";
      ctx.fillStyle = "#1d1f2b"; ctx.fillText(`${Math.max(0, st.hp)} / ${MAX} HP`, 88, 6);
      st.floats = st.floats.filter((f) => now - f.t < 900);
      ctx.font = "10px Silkscreen, monospace";
      for (const f of st.floats) {
        const k = (now - f.t) / 900;
        ctx.fillStyle = "#1d1f2b"; ctx.fillText(f.text, f.x + 1, f.y - k * 14 + 1);
        ctx.fillStyle = f.color; ctx.fillText(f.text, f.x, f.y - k * 14);
      }
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);

    return { act, setPet: (item) => { st.pet = item; } };
  }

  window.Craft = { create };
})();
