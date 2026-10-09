// Item art. An item is always drawn in its HOME game's style, wherever it is:
// a Blocky sword stays chunky pixels inside Ashen's ink world, and an Ashen
// greatsword stays ink inside Blocky's grass. That is the merge, made visible.
(function () {
  "use strict";

  // ------------------------------------------------------------ pixel (Blocky)

  const PX = {
    k: "#1d1f2b", w: "#f4f6fb", c: "#7ef0f0", C: "#2fb8c8", d: "#167a8a",
    b: "#7a4a24", B: "#4e2d14", g: "#b8bcc6", G: "#868b98", s: "#e2e5ec",
    r: "#d23c3c", R: "#8e2020", y: "#f2c84b", o: "#6b4a2a",
  };

  // Weapons are drawn along +x, handle at the origin, tip at length L.
  const PIXEL_WEAPON = {
    DiamondSword: [
      "...k.............",
      "..kyk...kkkkkkkk.",
      "kbBbkkkkcccccccck",
      "..kyk...kCCCCCCk.",
      "...k.....kkkkkk..",
    ],
  };

  const PIXEL_ICON = {
    IronChestplate: [
      "..kk......kk..",
      ".kgskkkkkkgsk.",
      ".kgssggggssgk.",
      ".kGgsggggsgGk.",
      "..kGgsgsgsGk..",
      "..kGgggggggk..",
      "..kGgsgsgsgk..",
      "..kGggggggGk..",
      "..kkGGGGGGkk..",
      "...kkkkkkkk...",
    ],
    Bed: [
      "..............",
      "kkkkkkkkkkkkkk",
      "kwwwkrrrrrrrrk",
      "kwwwkrRrrRrrrk",
      "kkkkkrrrrrrrrk",
      "kooooooooooook",
      "ko..........ok",
      "ko..........ok",
    ],
  };

  function drawPixels(ctx, rows, x, y, cell) {
    for (let j = 0; j < rows.length; j++) {
      const row = rows[j];
      for (let i = 0; i < row.length; i++) {
        const c = PX[row[i]];
        if (!c) continue;
        ctx.fillStyle = c;
        ctx.fillRect(Math.round(x + i * cell), Math.round(y + j * cell), Math.ceil(cell), Math.ceil(cell));
      }
    }
  }

  // --------------------------------------------------------------- ink (Ashen)

  // Jitter from the geometry, never from the clock, so a still line stays still.
  function jit(a, b, s) {
    const v = Math.sin(a * 12.9898 + b * 78.233 + s * 37.719) * 43758.5453;
    return (v - Math.floor(v)) - 0.5;
  }

  function inkLine(ctx, x1, y1, x2, y2, w, color, amp) {
    const a = amp == null ? 1.2 : amp;
    ctx.strokeStyle = color;
    ctx.lineCap = "round";
    for (let pass = 0; pass < 2; pass++) {
      ctx.lineWidth = pass ? w * 0.55 : w;
      ctx.beginPath();
      const n = Math.max(2, Math.round(Math.hypot(x2 - x1, y2 - y1) / 12));
      for (let i = 0; i <= n; i++) {
        const t = i / n;
        const x = x1 + (x2 - x1) * t + jit(x1 + i, y2, pass) * a * (i && i < n ? 1 : 0.3);
        const y = y1 + (y2 - y1) * t + jit(y1 + i, x2, pass + 3) * a * (i && i < n ? 1 : 0.3);
        if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y);
      }
      ctx.stroke();
    }
  }

  function inkCircle(ctx, cx, cy, r, w, color, fill) {
    ctx.beginPath();
    const n = Math.max(10, Math.round(r * 1.4));
    for (let i = 0; i <= n; i++) {
      const t = (i / n) * Math.PI * 2;
      const rr = r + jit(cx + i, cy, r) * Math.min(1.5, r * 0.15);
      const x = cx + Math.cos(t) * rr, y = cy + Math.sin(t) * rr;
      if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y);
    }
    if (fill) { ctx.fillStyle = fill; ctx.fill(); }
    ctx.strokeStyle = color; ctx.lineWidth = w; ctx.stroke();
  }

  const BONE = "#ece4d2";
  const EMBER = "#f08a3c";

  function inkWeapon(ctx, kind, L, color) {
    const w = Math.max(1, L / 40);
    const c = color || BONE;
    const grip = L * 0.2;
    inkCircle(ctx, 0, 0, Math.max(1.5, L * 0.035), w, c, c);
    inkLine(ctx, 0, 0, grip, 0, w * 1.6, c, w);
    inkLine(ctx, grip, -L * 0.09, grip, L * 0.09, w * 1.4, c, w);
    const bw = kind === "Greatsword" ? L * 0.05 : L * 0.035;
    inkLine(ctx, grip, -bw, L * 0.94, -bw * 0.4, w, c, w * 0.8);
    inkLine(ctx, grip, bw, L * 0.94, bw * 0.4, w, c, w * 0.8);
    inkLine(ctx, L * 0.94, -bw * 0.4, L, 0, w, c, w * 0.5);
    inkLine(ctx, L * 0.94, bw * 0.4, L, 0, w, c, w * 0.5);
    inkLine(ctx, grip + 2, 0, L * 0.85, 0, w * 0.5, c, w * 0.6);
  }

  function inkIcon(ctx, kind, cx, cy, s, color) {
    const c = color || BONE;
    const w = Math.max(1, s / 22);
    if (kind === "EmberFlask") {
      ctx.save();
      const g = ctx.createRadialGradient(cx, cy + s * 0.12, 1, cx, cy + s * 0.12, s * 0.42);
      g.addColorStop(0, "rgba(255,170,90,0.95)"); g.addColorStop(1, "rgba(240,138,60,0)");
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(cx, cy + s * 0.12, s * 0.42, 0, 7); ctx.fill();
      ctx.restore();
      inkCircle(ctx, cx, cy + s * 0.14, s * 0.24, w, c, "rgba(240,138,60,0.55)");
      inkLine(ctx, cx - s * 0.07, cy - s * 0.1, cx - s * 0.07, cy - s * 0.3, w, c);
      inkLine(ctx, cx + s * 0.07, cy - s * 0.1, cx + s * 0.07, cy - s * 0.3, w, c);
      inkLine(ctx, cx - s * 0.1, cy - s * 0.33, cx + s * 0.1, cy - s * 0.33, w * 1.4, c);
      return;
    }
    if (kind === "KnightArmour") {
      const x = cx, y = cy;
      inkLine(ctx, x - s * 0.3, y - s * 0.3, x - s * 0.12, y - s * 0.36, w, c);
      inkLine(ctx, x + s * 0.3, y - s * 0.3, x + s * 0.12, y - s * 0.36, w, c);
      inkLine(ctx, x - s * 0.12, y - s * 0.36, x, y - s * 0.26, w, c);
      inkLine(ctx, x + s * 0.12, y - s * 0.36, x, y - s * 0.26, w, c);
      inkLine(ctx, x - s * 0.3, y - s * 0.3, x - s * 0.24, y + s * 0.3, w, c);
      inkLine(ctx, x + s * 0.3, y - s * 0.3, x + s * 0.24, y + s * 0.3, w, c);
      inkLine(ctx, x - s * 0.24, y + s * 0.3, x + s * 0.24, y + s * 0.3, w, c);
      inkLine(ctx, x, y - s * 0.26, x, y + s * 0.3, w * 0.6, c);
      inkLine(ctx, x - s * 0.22, y, x + s * 0.22, y, w * 0.6, c);
      return;
    }
    // A shape for anything forged with no picture of its own.
    inkCircle(ctx, cx, cy, s * 0.28, w, c);
    inkLine(ctx, cx - s * 0.1, cy, cx + s * 0.1, cy, w, c);
  }

  // ------------------------------------------------------------------ public

  const WEAPON_KINDS = new Set(["DiamondSword", "Greatsword"]);

  // Draw a weapon along +x from the current origin, length L, in its home style.
  function drawWeapon(ctx, item, L) {
    if (item.home === "blocky") {
      const rows = PIXEL_WEAPON[item.kind] || PIXEL_WEAPON.DiamondSword;
      const cell = L / rows[0].length;
      drawPixels(ctx, rows, 0, -cell * rows.length / 2, cell);
    } else {
      inkWeapon(ctx, item.kind, L);
    }
  }

  // Draw an item centred at (cx, cy) inside a box of side s.
  function drawIcon(ctx, item, cx, cy, s) {
    ctx.save();
    if (WEAPON_KINDS.has(item.kind) || item.cat === "weapon") {
      ctx.translate(cx - s * 0.36, cy + s * 0.36);
      ctx.rotate(-Math.PI / 4);
      drawWeapon(ctx, item, s * 1.02);
    } else if (item.home === "blocky") {
      const rows = PIXEL_ICON[item.kind] || PIXEL_ICON.IronChestplate;
      const cell = (s * 0.86) / Math.max(rows[0].length, rows.length);
      drawPixels(ctx, rows, cx - cell * rows[0].length / 2, cy - cell * rows.length / 2, cell);
    } else {
      inkIcon(ctx, item.kind, cx, cy, s);
    }
    ctx.restore();
  }

  window.Sprites = { drawIcon, drawWeapon, drawPixels, inkLine, inkCircle, jit, BONE, EMBER, PX };
})();
