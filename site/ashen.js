// Ashen: a side-on souls-like duel, drawn in ink. One unit is one centimetre,
// and the knight is 180 cm tall. A thousand hit points, stamina for every
// swing, poise to stagger, and a bonfire that refills the flask.
(function () {
  "use strict";
  const CW = 640, CH = 384, GROUND = 318, PX_PER_CM = 0.5;
  const BONFIRE = 74;

  function create(canvas, hooks) {
    const ctx = canvas.getContext("2d");
    canvas.width = CW; canvas.height = CH;
    const S = Sprites;
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const maxHp = hooks.maxHp;
    const armourFactor = hooks.reductionAtMax / hooks.maxArmour; // per point of absorption
    const BONE = S.BONE, EMBER = S.EMBER;

    const k = { x: 190, hp: Math.round(maxHp * 0.7), st: 100, face: 1, swing: -9999, walk: 0,
                dir: 0, lastSpend: 0, dead: 0, weapon: null, armour: null };
    const husk = { x: 480, hp: maxHp, state: "walk", t: 0, hit: -9999, dead: 0 };
    let floats = [];
    let msg = { text: "A and D to walk, Space to swing, E to rest at the bonfire.", until: performance.now() + 7000 };
    const say = (text, ms) => { msg = { text, until: performance.now() + (ms || 2800) }; };
    let flasks = []; // items whose charges the bonfire refills

    // paper grain, made once
    const grain = document.createElement("canvas");
    grain.width = CW; grain.height = CH;
    (function () {
      const g = grain.getContext("2d");
      const grd = g.createRadialGradient(CW * 0.35, CH * 0.45, 40, CW * 0.5, CH * 0.5, CW * 0.75);
      grd.addColorStop(0, "#2b2723"); grd.addColorStop(1, "#141210");
      g.fillStyle = grd; g.fillRect(0, 0, CW, CH);
      let seed = 7;
      const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
      for (let i = 0; i < 2600; i++) {
        g.fillStyle = `rgba(236,228,210,${0.015 + rnd() * 0.03})`;
        g.fillRect(rnd() * CW, rnd() * CH, 1 + rnd() * 2, 1);
      }
      g.globalAlpha = 0.22;
      // a ruined arcade on the horizon
      for (let i = 0; i < 5; i++) {
        const x = 230 + i * 74, top = 170 + (i % 2) * 14;
        S.inkLine(g, x, GROUND - 2, x, top, 3, BONE, 1.6);
        if (i < 4) {
          g.beginPath(); g.strokeStyle = BONE; g.lineWidth = 2.4;
          g.arc(x + 37, top + 4, 37, Math.PI, 0); g.stroke();
        }
      }
      g.globalAlpha = 1;
      S.inkLine(g, 0, GROUND, CW, GROUND + 2, 2.4, BONE, 2);
      for (let x = 8; x < CW; x += 23) S.inkLine(g, x, GROUND + 10 + (x % 3) * 6, x + 12, GROUND + 8 + (x % 3) * 6, 1, "rgba(236,228,210,0.35)", 0.8);
    })();

    const inRest = () => Math.abs(k.x - BONFIRE) < 60;

    function spend(n, now) {
      if (k.st < n) { say("Not enough stamina.", 1200); return false; }
      k.st -= n; k.lastSpend = now; return true;
    }

    function reach() { return k.weapon ? k.weapon.stats.lengthCm * PX_PER_CM : 22; }

    function attack() {
      const now = performance.now();
      if (k.dead || now - k.swing < 380) return;
      const cost = k.weapon ? k.weapon.stats.stamina : 10;
      if (!spend(cost, now)) return;
      k.swing = now;
      const hand = k.x + 14 * k.face;
      const gap = (husk.x - hand) * k.face - 8;
      if (husk.state !== "dead" && gap >= -20 && gap <= reach()) {
        const dmg = k.weapon ? k.weapon.stats.damage : 40;
        husk.hp -= dmg; husk.hit = now;
        floats.push({ x: husk.x, y: GROUND - 110, text: String(dmg), t: now });
        const poise = k.weapon && k.weapon.stats.poise;
        if (poise >= 40 && husk.hp > 0) { husk.state = "stagger"; husk.t = now + 650; }
        if (husk.hp <= 0) {
          husk.state = "dead"; husk.dead = now;
          say(dmg >= maxHp * 0.6 ? "Over half its life in one blow. The border would have stopped that." : "The husk falls.");
        }
      }
    }

    function rest() {
      if (k.dead) return;
      if (!inRest()) { say("Walk to the bonfire to rest.", 1600); return; }
      k.hp = maxHp; k.st = 100;
      let kept = 0;
      for (const f of flasks) if (f.stats.refills) { f.stats.charges = f.stats.maxCharges; kept++; }
      Object.assign(husk, { x: 480, hp: maxHp, state: "walk", t: 0, aggro: false });
      say(kept ? "Rested. Flasks refilled. The husk returns." : "Rested. The husk returns.");
      hooks.changed && hooks.changed();
    }

    function use(item) {
      if (k.dead) return false;
      if (item.cat === "heal") {
        if (!flasks.includes(item)) flasks.push(item);
        if (item.stats.charges <= 0) { say("Empty. Rest at the bonfire to refill it.", 1800); return false; }
        item.stats.charges--;
        const before = k.hp;
        k.hp = Math.min(maxHp, k.hp + item.stats.hp);
        floats.push({ x: k.x, y: GROUND - 110, text: "+" + Math.round(k.hp - before), t: performance.now(), good: true });
        hooks.changed && hooks.changed();
        return !item.stats.refills && item.stats.charges <= 0;
      }
      return false;
    }

    function track(item) { if (item.cat === "heal" && !flasks.includes(item)) flasks.push(item); }

    function equip(item) {
      if (item.cat === "weapon") k.weapon = item;
      if (item.cat === "armour") k.armour = item;
    }
    function unequip(item) {
      if (k.weapon && k.weapon.uid === item.uid) k.weapon = null;
      if (k.armour && k.armour.uid === item.uid) k.armour = null;
      flasks = flasks.filter((f) => f.uid !== item.uid);
    }
    const equipped = (item) => (k.weapon && k.weapon.uid === item.uid) || (k.armour && k.armour.uid === item.uid);

    let last = performance.now();
    function tick(now) {
      const dt = Math.min(0.05, (now - last) / 1000); last = now;
      if (!k.dead && k.dir) {
        k.face = k.dir;
        k.x = Math.max(30, Math.min(CW - 30, k.x + k.dir * 120 * dt));
        k.walk += dt * 9;
      }
      if (now - k.lastSpend > 500) k.st = Math.min(100, k.st + 45 * dt);
      // the husk
      if (husk.state === "dead") {
        if (now - husk.dead > 3200) Object.assign(husk, { x: 560, hp: maxHp, state: "walk", aggro: false });
      } else if (!k.dead) {
        const d = husk.x - k.x;
        if (husk.state === "stagger" && now > husk.t) husk.state = "walk";
        if (Math.abs(d) < 230) husk.aggro = true; // it waits until you come close
        if (husk.state === "walk" && husk.aggro) {
          if (Math.abs(d) > 56) husk.x -= Math.sign(d) * 42 * dt;
          else { husk.state = "windup"; husk.t = now + 560; }
        } else if (husk.state === "windup" && now > husk.t) {
          husk.state = "recover"; husk.t = now + 900;
          if (Math.abs(husk.x - k.x) < 64) {
            const red = k.armour ? Math.min(1, k.armour.stats.absorption * armourFactor) : 0;
            const dmg = Math.round(150 * (1 - red));
            k.hp -= dmg;
            floats.push({ x: k.x, y: GROUND - 110, text: String(dmg), t: now, bad: true });
            if (k.hp <= 0) { k.dead = now; }
          }
        } else if (husk.state === "recover" && now > husk.t) husk.state = "walk";
      }
      if (k.dead && now - k.dead > 1600) {
        k.dead = 0; k.hp = maxHp; k.st = 100; k.x = BONFIRE + 40; k.face = 1;
        for (const f of flasks) if (f.stats.refills) f.stats.charges = f.stats.maxCharges;
        Object.assign(husk, { x: 480, hp: maxHp, state: "walk", aggro: false });
        say("You wake at the bonfire.");
        hooks.changed && hooks.changed();
      }
    }

    function stick(x, face, opts) {
      const o = opts || {};
      const c = o.color || BONE;
      const headY = GROUND - 82, neckY = GROUND - 70, hipY = GROUND - 38;
      const lean = o.lean || 0;
      const step = Math.sin(o.walk || 0) * 9;
      S.inkLine(ctx, x + lean * 0.4, hipY, x + step, GROUND, 2.6, c);
      S.inkLine(ctx, x + lean * 0.4, hipY, x - step, GROUND, 2.6, c);
      S.inkLine(ctx, x + lean, neckY, x + lean * 0.4, hipY, 3, c);
      S.inkCircle(ctx, x + lean, headY, 11, 2.4, c, o.headFill || "#1c1a17");
      return { neck: [x + lean, neckY], hip: [x + lean * 0.4, hipY], head: [x + lean, headY] };
    }

    function drawKnight(now) {
      if (k.dead && now - k.dead > 500) return;
      const p = stick(k.x, k.face, { walk: k.dir ? k.walk : 0 });
      // helmet slit
      S.inkLine(ctx, p.head[0] - 6 * k.face, p.head[1] - 1, p.head[0] + 9 * k.face, p.head[1] - 1, 1.6, BONE, 0.4);
      // armour on the torso, in its home style
      if (k.armour) {
        if (k.armour.home === "blocky") S.drawIcon(ctx, k.armour, p.neck[0], GROUND - 55, 30);
        else {
          S.inkLine(ctx, p.neck[0] - 10, GROUND - 68, p.neck[0] + 10, GROUND - 68, 2, BONE);
          S.inkLine(ctx, p.neck[0] - 10, GROUND - 68, p.neck[0] - 8, GROUND - 42, 2, BONE);
          S.inkLine(ctx, p.neck[0] + 10, GROUND - 68, p.neck[0] + 8, GROUND - 42, 2, BONE);
        }
      }
      const hand = [k.x + 14 * k.face, GROUND - 58];
      S.inkLine(ctx, p.neck[0], GROUND - 66, hand[0], hand[1], 2.4, BONE);
      S.inkLine(ctx, p.neck[0], GROUND - 66, k.x - 10 * k.face, GROUND - 48, 2.2, BONE);
      const t = Math.min(1, (now - k.swing) / 220);
      const swinging = now - k.swing < 220;
      ctx.save();
      ctx.translate(hand[0], hand[1]);
      ctx.scale(k.face, 1);
      ctx.rotate(swinging ? -2.3 + t * 2.9 : -1.05);
      if (k.weapon) S.drawWeapon(ctx, k.weapon, reach());
      ctx.restore();
    }

    function drawHusk(now) {
      if (husk.state === "dead" && now - husk.dead > 900) return;
      const hurt = now - husk.hit < 140;
      const fade = husk.state === "dead" ? 1 - (now - husk.dead) / 900 : 1;
      ctx.save(); ctx.globalAlpha = fade;
      const c = hurt ? "#ffffff" : "#b9ae99";
      const lean = husk.state === "stagger" ? 10 : husk.state === "windup" ? -6 : -4;
      const p = stick(husk.x, -1, { color: c, lean, walk: husk.state === "walk" ? now / 140 : 0 });
      ctx.fillStyle = EMBER;
      ctx.fillRect(p.head[0] - 6, p.head[1] - 2, 2, 2); ctx.fillRect(p.head[0] - 1, p.head[1] - 2, 2, 2);
      const raised = husk.state === "windup";
      S.inkLine(ctx, p.neck[0], GROUND - 66, husk.x - (raised ? 6 : 22), raised ? GROUND - 104 : GROUND - 50, 2.2, c);
      S.inkLine(ctx, p.neck[0], GROUND - 66, husk.x + 10, GROUND - 46, 2, c);
      ctx.restore();
    }

    function drawBonfire(now) {
      S.inkLine(ctx, BONFIRE - 22, GROUND, BONFIRE + 22, GROUND - 2, 3, BONE);
      S.inkLine(ctx, BONFIRE - 14, GROUND - 6, BONFIRE + 16, GROUND - 4, 2, "rgba(236,228,210,0.6)");
      S.inkLine(ctx, BONFIRE + 2, GROUND - 4, BONFIRE - 4, GROUND - 52, 2.2, BONE, 0.6);
      S.inkLine(ctx, BONFIRE - 10, GROUND - 40, BONFIRE + 4, GROUND - 42, 2, BONE, 0.4);
      const fl = reduce ? 0 : now / 120;
      for (let i = 0; i < 3; i++) {
        const h = 26 + Math.sin(fl + i * 2.1) * 6;
        ctx.beginPath();
        ctx.moveTo(BONFIRE - 12 + i * 8, GROUND - 4);
        ctx.quadraticCurveTo(BONFIRE - 14 + i * 9 + Math.sin(fl + i) * 4, GROUND - h * 0.6, BONFIRE - 6 + i * 6, GROUND - h);
        ctx.quadraticCurveTo(BONFIRE - 2 + i * 6, GROUND - h * 0.5, BONFIRE - 4 + i * 8, GROUND - 4);
        ctx.fillStyle = i === 1 ? "rgba(255,196,110,0.9)" : "rgba(240,138,60,0.75)";
        ctx.fill();
      }
      if (inRest() && !k.dead) {
        ctx.font = "italic 15px 'IM Fell English', serif";
        ctx.fillStyle = "rgba(236,228,210,0.8)";
        ctx.fillText("E  rest", BONFIRE - 22, GROUND - 70);
      }
    }

    function bar(x, y, w, h, frac, color, label) {
      ctx.fillStyle = "rgba(0,0,0,0.45)"; ctx.fillRect(x, y, w, h);
      ctx.fillStyle = color; ctx.fillRect(x + 1, y + 1, Math.max(0, (w - 2) * frac), h - 2);
      ctx.strokeStyle = "rgba(236,228,210,0.5)"; ctx.lineWidth = 1; ctx.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1);
      if (label) { ctx.fillStyle = BONE; ctx.fillText(label, x + w + 8, y + h - 1); }
    }

    function drawHud(now) {
      ctx.font = "15px 'IM Fell English', serif";
      ctx.textBaseline = "alphabetic";
      bar(16, 16, 220, 10, Math.max(0, k.hp) / maxHp, "#a8322a", `${Math.max(0, Math.round(k.hp))} / ${maxHp}`);
      bar(16, 32, 160, 8, k.st / 100, "#8fae5e", "stamina");
      const w = k.weapon;
      const label = w ? `${w.name}  ·  ${w.stats.damage} dmg  ·  ${w.stats.lengthCm} cm  ·  ${w.stats.stamina} stamina`
                      : "Bare hands  ·  40 dmg  ·  10 stamina";
      const tw = ctx.measureText(label).width;
      ctx.fillStyle = BONE; ctx.fillText(label, CW - tw - 16, 28);
      if (k.armour) {
        const a = `${k.armour.name}  ·  absorbs ${k.armour.stats.absorption}%`;
        ctx.fillStyle = "rgba(236,228,210,0.75)"; ctx.fillText(a, CW - ctx.measureText(a).width - 16, 46);
      }
      // the husk's bar, boss style
      if (husk.state !== "dead") {
        ctx.font = "italic 15px 'IM Fell English', serif";
        ctx.fillStyle = BONE; ctx.fillText("Husk of the Ashen Road", 170, CH - 30);
        bar(170, CH - 24, 300, 8, Math.max(0, husk.hp) / maxHp, "#a8322a");
      }
      floats = floats.filter((f) => now - f.t < 1000);
      ctx.font = "22px 'IM Fell English', serif";
      for (const f of floats) {
        const kk = (now - f.t) / 1000;
        ctx.fillStyle = f.good ? "#bfe39a" : f.bad ? "#ff9a8a" : "#fff3d6";
        ctx.globalAlpha = 1 - kk * 0.8;
        ctx.fillText(f.text, f.x - 14, f.y - kk * 26);
        ctx.globalAlpha = 1;
      }
      if (msg && now < msg.until) {
        ctx.font = "italic 15px 'IM Fell English', serif";
        ctx.fillStyle = "rgba(236,228,210,0.85)";
        ctx.fillText(msg.text, 16, 66);
      }
      if (k.dead) {
        ctx.fillStyle = "rgba(10,8,6,0.55)"; ctx.fillRect(0, CH / 2 - 40, CW, 70);
        ctx.font = "44px 'IM Fell English', serif";
        ctx.fillStyle = "#a8322a";
        const t = "FALLEN"; ctx.fillText(t, (CW - ctx.measureText(t).width) / 2, CH / 2 + 12);
      }
    }

    function frame(now) {
      tick(now);
      ctx.drawImage(grain, 0, 0);
      drawBonfire(now);
      drawHusk(now);
      drawKnight(now);
      drawHud(now);
      raf = requestAnimationFrame(frame);
    }
    let raf = requestAnimationFrame(frame);

    // ---------------------------------------------------------------- input
    const held = new Set();
    const dirFromHeld = () => { k.dir = (held.has(1) ? 1 : 0) - (held.has(-1) ? 1 : 0); };
    canvas.addEventListener("keydown", (e) => {
      const key = e.key.toLowerCase();
      if (key === "a" || key === "arrowleft") { e.preventDefault(); held.add(-1); dirFromHeld(); }
      if (key === "d" || key === "arrowright") { e.preventDefault(); held.add(1); dirFromHeld(); }
      if (key === " " || key === "j") { e.preventDefault(); attack(); }
      if (key === "e") { e.preventDefault(); rest(); }
    });
    canvas.addEventListener("keyup", (e) => {
      const key = e.key.toLowerCase();
      if (key === "a" || key === "arrowleft") held.delete(-1);
      if (key === "d" || key === "arrowright") held.delete(1);
      dirFromHeld();
    });
    canvas.addEventListener("blur", () => { held.clear(); dirFromHeld(); });
    canvas.addEventListener("pointerdown", (e) => {
      canvas.focus();
      const r = canvas.getBoundingClientRect();
      const x = ((e.clientX - r.left) / r.width) * CW;
      if (Math.abs(x - husk.x) < 40) { k.face = Math.sign(husk.x - k.x) || k.face; attack(); }
      else if (Math.abs(x - BONFIRE) < 40) rest();
    });

    return {
      equip, unequip, use, equipped, attack, rest, track, say,
      hold: (d, on) => { if (on) held.add(d); else held.delete(d); dirFromHeld(); },
    };
  }

  window.Ashen = { create, PX_PER_CM };
})();
