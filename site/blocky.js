// Blocky: a top-down block miner. One tile is one block is one metre. Twenty
// hit points, drawn as ten hearts. No stamina, no poise, no checkpoints.
(function () {
  "use strict";
  const T = 16, W = 20, H = 12;
  const MAP = [
    "TTTTTTTTTTTTTTTTTTTT",
    "T.....SS.....~~~...T",
    "T..f.........~~~...T",
    "T......DDDD........T",
    "T...DDDD..DDD....f.T",
    "T...D.......D......T",
    "T.DDD...SS..DDDD...T",
    "T.......SS.....D...T",
    "T..f...........D.S.T",
    "T......~~......DDD.T",
    "T......~~..........T",
    "TTTTTTTTTTTTTTTTTTTT",
  ];
  const SOLID = new Set(["T", "S", "~"]);
  const HEART = [".kk.kk.", "krrkrrk", "krrrrrk", ".krrrk.", "..krk..", "...k..."];
  const HALF = [".kk.kk.", "krrk..k", "krrk..k", ".krk.k.", "..kkk..", "...k..."];
  const EMPTY = [".kk.kk.", "k..k..k", "k.....k", ".k...k.", "..k.k..", "...k..."];
  const SHIELD = [".kkkkk.", "kgggggk", "kgsssgk", "kgsssgk", ".kgggk.", "..kkk.."];

  function hash(x, y) {
    const v = Math.sin(x * 127.1 + y * 311.7) * 43758.5453;
    return v - Math.floor(v);
  }

  function create(canvas, hooks) {
    const ctx = canvas.getContext("2d");
    canvas.width = W * T; canvas.height = H * T;
    ctx.imageSmoothingEnabled = false;
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const S = Sprites;
    const maxHp = hooks.maxHp;
    const perPoint = hooks.reductionPerPoint;

    const st = {
      x: 3, y: 6, face: 1, hp: Math.round(maxHp * 0.7), spawn: { x: 3, y: 6 }, bed: null,
      weapon: null, armour: null, swing: 0, target: null, lastStep: 0, dead: 0,
      mob: { x: 14, y: 7, hp: maxHp, alive: true, next: 0, hit: 0, respawn: 0, bob: 0 },
      floats: [], msg: { text: "Arrow keys or tap to walk. Space or Attack to swing.", until: 6000 },
      kills: 0,
    };

    const solid = (x, y) => x < 0 || y < 0 || x >= W || y >= H || SOLID.has(MAP[y][x]);
    const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
    const say = (text, ms) => { st.msg = { text, until: performance.now() + (ms || 2600) }; };

    function step(dx, dy) {
      if (st.dead) return;
      if (dx) st.face = dx;
      const nx = st.x + dx, ny = st.y + dy;
      if (solid(nx, ny) || (st.mob.alive && st.mob.x === nx && st.mob.y === ny)) return;
      st.x = nx; st.y = ny;
    }

    function attack() {
      if (st.dead) return;
      const now = performance.now();
      if (now - st.swing < 260) return;
      st.swing = now;
      const dmg = st.weapon ? st.weapon.stats.damage : 1;
      const reach = st.weapon ? st.weapon.stats.reach : 1;
      const m = st.mob;
      if (!m.alive) return;
      if (dist(st, m) <= reach + 0.25) {
        m.hp -= dmg; m.hit = now;
        st.floats.push({ x: m.x * T + 8, y: m.y * T, text: "-" + dmg, t: now });
        if (m.hp <= 0) {
          m.alive = false; m.respawn = now + 2600; st.kills++;
          say(dmg >= maxHp ? "One hit. That is why borders cap damage." : "Mossling down.");
        }
      } else {
        say("Out of reach: " + fmt(reach) + (reach === 1 ? " block." : " blocks."), 1600);
      }
    }

    function use(item) {
      if (st.dead) return false;
      if (item.cat === "heal") {
        const before = st.hp;
        st.hp = Math.min(maxHp, st.hp + item.stats.hp);
        st.floats.push({ x: st.x * T + 8, y: st.y * T, text: "+" + Math.round(st.hp - before), t: performance.now(), good: true });
        say(item.stats.refills ? "Healed." : "Healed. Blocky has no checkpoints, so the flask is gone.");
        return !item.stats.refills; // consumed
      }
      if (item.cat === "anchor") {
        st.spawn = { x: st.x, y: st.y }; st.bed = { x: st.x, y: st.y };
        say("Spawn set. You will wake here.");
        return false;
      }
      return false;
    }

    function equip(item) {
      if (item.cat === "weapon") st.weapon = item;
      if (item.cat === "armour") st.armour = item;
    }
    function unequip(item) {
      if (st.weapon && st.weapon.uid === item.uid) st.weapon = null;
      if (st.armour && st.armour.uid === item.uid) st.armour = null;
    }
    const equipped = (item) => (st.weapon && st.weapon.uid === item.uid) || (st.armour && st.armour.uid === item.uid);

    function tick(now) {
      // walking toward a tapped tile
      if (st.target && now - st.lastStep > 110) {
        st.lastStep = now;
        const dx = Math.sign(st.target.x - st.x), dy = Math.sign(st.target.y - st.y);
        const bx = st.x, by = st.y;
        if (dx && !solid(st.x + dx, st.y)) step(dx, 0); else if (dy) step(0, dy);
        if (st.x === bx && st.y === by && dy && !solid(st.x, st.y + dy)) step(0, dy);
        if ((st.x === st.target.x && st.y === st.target.y) || (st.x === bx && st.y === by)) st.target = null;
      }
      const m = st.mob;
      if (!m.alive && now > m.respawn) {
        Object.assign(m, { x: 16, y: 3, hp: maxHp, alive: true });
      }
      if (m.alive && !st.dead && now > m.next) {
        m.next = now + 700;
        const d = dist(st, m);
        if (d <= 1.5) {
          if (!m.lastBite || now - m.lastBite > 1400) {
            m.lastBite = now;
            const red = st.armour ? st.armour.stats.points * perPoint : 0;
            const dmg = 3 * (1 - red);
            st.hp -= dmg;
            st.floats.push({ x: st.x * T + 8, y: st.y * T, text: "-" + fmt(Math.round(dmg * 10) / 10), t: now, bad: true });
            if (st.hp <= 0) {
              st.dead = now + 1400;
            }
          }
        } else {
          const toward = d < 6;
          const dx = toward ? Math.sign(st.x - m.x) : [-1, 0, 1][Math.floor(hash(now, 1) * 3)];
          const dy = toward ? Math.sign(st.y - m.y) : [-1, 0, 1][Math.floor(hash(now, 2) * 3)];
          const tryMove = (mx, my) => {
            const nx = m.x + mx, ny = m.y + my;
            if (!solid(nx, ny) && !(nx === st.x && ny === st.y)) { m.x = nx; m.y = ny; return true; }
            return false;
          };
          if (!(dx && tryMove(dx, 0))) if (dy) tryMove(0, dy);
        }
      }
      if (st.dead && now > st.dead) {
        st.dead = 0; st.hp = maxHp; st.x = st.spawn.x; st.y = st.spawn.y;
        say(st.bed ? "You woke at your bed." : "You fell. Back at spawn.");
      }
    }

    function drawTile(x, y, c, now) {
      const px = x * T, py = y * T, h = hash(x, y);
      ctx.fillStyle = h > 0.5 ? "#5dbb4c" : "#57b347";
      ctx.fillRect(px, py, T, T);
      for (let i = 0; i < 3; i++) {
        ctx.fillStyle = "#4fa33f";
        ctx.fillRect(px + Math.floor(hash(x + i, y) * 14), py + Math.floor(hash(y, x + i) * 14), 2, 1);
      }
      if (c === "D") {
        ctx.fillStyle = "#b58a55"; ctx.fillRect(px, py, T, T);
        ctx.fillStyle = "#9c7342";
        ctx.fillRect(px + Math.floor(h * 12), py + 4, 3, 2); ctx.fillRect(px + 3, py + Math.floor(h * 12), 2, 2);
      } else if (c === "S") {
        ctx.fillStyle = "#8b8f9a"; ctx.fillRect(px, py, T, T);
        ctx.fillStyle = "#a9adb7"; ctx.fillRect(px + 1, py + 1, 7, 6); ctx.fillRect(px + 9, py + 9, 6, 5);
        ctx.fillStyle = "#6c707b"; ctx.fillRect(px, py + 15, T, 1); ctx.fillRect(px + 15, py, 1, T);
      } else if (c === "~") {
        ctx.fillStyle = "#3a7bd5"; ctx.fillRect(px, py, T, T);
        ctx.fillStyle = "#6fa3ee";
        const o = reduce ? 0 : Math.floor(now / 400 + h * 4) % 4;
        ctx.fillRect(px + 2 + o * 2, py + 4, 4, 1); ctx.fillRect(px + 8 - o, py + 11, 4, 1);
      } else if (c === "T") {
        ctx.fillStyle = "#6b4a2a"; ctx.fillRect(px + 6, py + 9, 4, 7);
        ctx.fillStyle = "#2f7d32"; ctx.fillRect(px + 1, py + 1, 14, 10);
        ctx.fillStyle = "#3d9a40"; ctx.fillRect(px + 3, py + 2, 6, 4);
        ctx.fillStyle = "#245f27"; ctx.fillRect(px + 1, py + 10, 14, 1);
      } else if (c === "f") {
        ctx.fillStyle = "#f2c84b"; ctx.fillRect(px + 5, py + 6, 2, 2);
        ctx.fillStyle = "#e9e4f4"; ctx.fillRect(px + 10, py + 9, 2, 2);
      }
    }

    function drawPlayer(now) {
      const px = st.x * T, py = st.y * T;
      const f = st.face;
      // legs, body, head
      ctx.fillStyle = "#2d3b8f"; ctx.fillRect(px + 5, py + 11, 2, 4); ctx.fillRect(px + 9, py + 11, 2, 4);
      const shirt = st.armour && st.armour.home === "blocky" ? "#b8bcc6" : "#2bb3a3";
      ctx.fillStyle = shirt; ctx.fillRect(px + 4, py + 6, 8, 6);
      ctx.fillStyle = "#e8b48a"; ctx.fillRect(px + 4, py + 1, 8, 6);
      ctx.fillStyle = "#4e2d14"; ctx.fillRect(px + 4, py + 1, 8, 2);
      ctx.fillStyle = "#1d1f2b"; ctx.fillRect(px + (f > 0 ? 9 : 5), py + 4, 2, 1);
      if (st.armour && st.armour.home !== "blocky") {
        // an Ashen cuirass, still ink, on a pixel body
        S.inkLine(ctx, px + 4, py + 6, px + 12, py + 6, 1, S.BONE, 0.3);
        S.inkLine(ctx, px + 4, py + 6, px + 5, py + 12, 1, S.BONE, 0.3);
        S.inkLine(ctx, px + 12, py + 6, px + 11, py + 12, 1, S.BONE, 0.3);
      }
      if (st.weapon) {
        const t = Math.min(1, (now - st.swing) / 200);
        const swinging = now - st.swing < 200;
        const L = st.weapon.stats.reach * T;
        ctx.save();
        ctx.translate(px + (f > 0 ? 12 : 4), py + 9);
        ctx.scale(f, 1);
        ctx.rotate(swinging ? (-1.9 + t * 2.4) : -0.6);
        S.drawWeapon(ctx, st.weapon, L);
        ctx.restore();
      }
    }

    function drawMob(now) {
      const m = st.mob;
      if (!m.alive) return;
      const px = m.x * T, py = m.y * T;
      const bob = reduce ? 0 : Math.round(Math.sin(now / 220 + m.x) * 1);
      const hurt = now - m.hit < 160;
      ctx.fillStyle = "#1d1f2b"; ctx.fillRect(px + 1, py + 3 + bob, 14, 12);
      ctx.fillStyle = hurt ? "#f4f6fb" : "#7bd36a"; ctx.fillRect(px + 2, py + 4 + bob, 12, 10);
      ctx.fillStyle = hurt ? "#f4f6fb" : "#5ab24b"; ctx.fillRect(px + 2, py + 11 + bob, 12, 3);
      ctx.fillStyle = "#1d1f2b"; ctx.fillRect(px + 5, py + 7 + bob, 2, 2); ctx.fillRect(px + 10, py + 7 + bob, 2, 2);
      // its hit points, as a bar of whole points
      const w = 14, filled = Math.max(0, Math.round((m.hp / maxHp) * w));
      ctx.fillStyle = "#1d1f2b"; ctx.fillRect(px + 1, py - 1, w + 2, 3);
      ctx.fillStyle = "#d23c3c"; ctx.fillRect(px + 2, py, filled, 1);
    }

    function drawHud(now) {
      // hearts
      for (let i = 0; i < maxHp / 2; i++) {
        const hp = Math.max(0, Math.round(st.hp));
        const rows = hp >= (i + 1) * 2 ? HEART : hp === i * 2 + 1 ? HALF : EMPTY;
        S.drawPixels(ctx, rows, 4 + i * 8, 4, 1);
      }
      if (st.armour) {
        const pts = Math.round(st.armour.stats.points);
        for (let i = 0; i < Math.ceil(pts / 2); i++) S.drawPixels(ctx, SHIELD, 4 + i * 8, 12, 1);
      }
      ctx.font = "8px Silkscreen, monospace";
      ctx.textBaseline = "top";
      const w = st.weapon;
      const label = w ? `${w.name.toUpperCase()}  ${fmt(w.stats.damage)} DMG  ${fmt(w.stats.reach)} BLK` : "FIST  1 DMG  1 BLK";
      const tw = ctx.measureText(label).width;
      ctx.fillStyle = "rgba(29,31,43,0.72)"; ctx.fillRect(W * T - tw - 10, 3, tw + 7, 11);
      ctx.fillStyle = "#f4f6fb"; ctx.fillText(label, W * T - tw - 6, 5);
      // floating numbers
      st.floats = st.floats.filter((f) => now - f.t < 900);
      for (const f of st.floats) {
        const k = (now - f.t) / 900;
        ctx.fillStyle = "#1d1f2b"; ctx.fillText(f.text, f.x - 4 + 1, f.y - 6 - k * 10 + 1);
        ctx.fillStyle = f.good ? "#7ef0a0" : f.bad ? "#ff8f8f" : "#f4f6fb";
        ctx.fillText(f.text, f.x - 4, f.y - 6 - k * 10);
      }
      if (st.msg && now < st.msg.until) {
        const mw = ctx.measureText(st.msg.text).width;
        ctx.fillStyle = "rgba(29,31,43,0.8)"; ctx.fillRect(4, H * T - 15, Math.min(W * T - 8, mw + 8), 11);
        ctx.fillStyle = "#f4f6fb"; ctx.fillText(st.msg.text, 8, H * T - 13);
      }
      if (st.dead) {
        ctx.fillStyle = "rgba(160,20,20,0.45)"; ctx.fillRect(0, 0, W * T, H * T);
        ctx.fillStyle = "#f4f6fb"; ctx.font = "16px Silkscreen, monospace";
        const t = "YOU FELL"; ctx.fillText(t, (W * T - ctx.measureText(t).width) / 2, H * T / 2 - 8);
      }
    }

    function frame(now) {
      tick(now);
      for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) drawTile(x, y, MAP[y][x], now);
      if (st.bed) {
        const b = { home: "blocky", kind: "Bed", cat: "anchor" };
        S.drawIcon(ctx, b, st.bed.x * T + 8, st.bed.y * T + 8, 15);
      }
      drawMob(now);
      drawPlayer(now);
      drawHud(now);
      raf = requestAnimationFrame(frame);
    }
    let raf = requestAnimationFrame(frame);

    // ---------------------------------------------------------------- input
    const KEYS = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1],
                   a: [-1, 0], d: [1, 0], w: [0, -1], s: [0, 1] };
    canvas.addEventListener("keydown", (e) => {
      const k = KEYS[e.key] || KEYS[e.key.toLowerCase && e.key.toLowerCase()];
      if (k) { e.preventDefault(); st.target = null; step(k[0], k[1]); }
      if (e.key === " " || e.key === "j" || e.key === "J") { e.preventDefault(); attack(); }
    });
    canvas.addEventListener("pointerdown", (e) => {
      canvas.focus();
      const r = canvas.getBoundingClientRect();
      const tx = Math.floor(((e.clientX - r.left) / r.width) * W);
      const ty = Math.floor(((e.clientY - r.top) / r.height) * H);
      if (st.mob.alive && tx === st.mob.x && ty === st.mob.y) { st.face = Math.sign(tx - st.x) || st.face; attack(); return; }
      st.target = { x: tx, y: ty };
    });

    return {
      equip, unequip, use, equipped, attack,
      move: (dx, dy) => { st.target = null; step(dx, dy); },
      say,
    };
  }

  function fmt(n) {
    return Number.isInteger(n) ? String(n) : String(Math.round(n * 100) / 100);
  }

  window.Blocky = { create };
})();
