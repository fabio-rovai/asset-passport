// Art for both games, drawn in code. A thing is always drawn in its HOME
// game's style, wherever it ends up: a Blockcraft sword stays chunky pixels in
// Pocket Battlers, and an Emberfox stays soft and round in Blockcraft.
(function () {
  "use strict";

  // ---------------------------------------------------------------- pixels
  const PX = {
    k: "#1d1f2b", w: "#f4f6fb", c: "#8ff4f0", C: "#2fb8c8", b: "#7a4a24", B: "#4e2d14",
    y: "#f6d04d", Y: "#c99a24", r: "#d8413a", R: "#8e2020", g: "#b8bcc6", G: "#6c707b",
  };
  const CRAFT = {
    DiamondSword: [
      "..............kk", ".............kck", "............kcCk", "...........kcCk.",
      "..........kcCk..", ".........kcCk...", "........kcCk....", ".......kcCk.....",
      "..kk..kcCk......", "..kyk.kCk.......", "...kykCk........", "....kbk.........",
      "...kbkyk........", "..kbk.kyk.......", ".kbk...kk.......", ".kk.............",
    ],
    TNT: [
      "kkkkkkkkkkkkkkkk", "krrRrrRrrRrrRrrk", "krrRrrRrrRrrRrrk", "krrRrrRrrRrrRrrk",
      "kwwwwwwwwwwwwwwk", "kkkkwkwwkwkkkwwk", "kwkwwkkwkwwkwwwk", "kwkwwkwkkwwkwwwk",
      "kwkwwkwwkwwkwwwk", "kwwwwwwwwwwwwwwk", "krrRrrRrrRrrRrrk", "krrRrrRrrRrrRrrk",
      "krrRrrRrrRrrRrrk", "krrRrrRrrRrrRrrk", "kkkkkkkkkkkkkkkk",
    ],
    GoldenApple: [
      ".....kk.....", "....kbk.....", "..kkkbkkk...", ".kyyyyyyyk..", "kyywyyyyyyk.",
      "kywyyyyyyYk.", "kyyyyyyyyYk.", "kyyyyyyyYYk.", ".kyyyyyYYk..", ".kYyyyyYYk..",
      "..kkYYYkk...", "....kkk.....",
    ],
  };

  function pixels(ctx, rows, x, y, cell) {
    for (let j = 0; j < rows.length; j++) for (let i = 0; i < rows[j].length; i++) {
      const c = PX[rows[j][i]];
      if (!c) continue;
      ctx.fillStyle = c;
      ctx.fillRect(Math.round(x + i * cell), Math.round(y + j * cell), Math.ceil(cell), Math.ceil(cell));
    }
  }

  // -------------------------------------------------------- soft (Battlers)
  const INK = "#3a3550";
  function blob(ctx, x, y, rx, ry, fill, w) {
    ctx.beginPath(); ctx.ellipse(x, y, rx, ry, 0, 0, Math.PI * 2);
    ctx.fillStyle = fill; ctx.fill(); ctx.lineWidth = w; ctx.strokeStyle = INK; ctx.stroke();
  }
  function tri(ctx, pts, fill, w) {
    ctx.beginPath(); ctx.moveTo(pts[0], pts[1]);
    for (let i = 2; i < pts.length; i += 2) ctx.lineTo(pts[i], pts[i + 1]);
    ctx.closePath(); ctx.fillStyle = fill; ctx.fill(); ctx.lineWidth = w; ctx.strokeStyle = INK; ctx.lineJoin = "round"; ctx.stroke();
  }
  function eye(ctx, x, y, r) {
    ctx.fillStyle = INK; ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.fill();
    ctx.fillStyle = "#fff"; ctx.beginPath(); ctx.arc(x - r * 0.3, y - r * 0.35, r * 0.38, 0, 7); ctx.fill();
  }
  function flame(ctx, x, y, s, t) {
    const f = Math.sin(t || 0) * s * 0.08;
    ctx.beginPath(); ctx.moveTo(x - s * 0.3, y);
    ctx.quadraticCurveTo(x - s * 0.35 + f, y - s * 0.6, x + f, y - s);
    ctx.quadraticCurveTo(x + s * 0.35 - f, y - s * 0.55, x + s * 0.3, y);
    ctx.closePath(); ctx.fillStyle = "#ff8a3d"; ctx.fill(); ctx.lineWidth = Math.max(1, s * 0.07); ctx.strokeStyle = INK; ctx.stroke();
    ctx.beginPath(); ctx.moveTo(x - s * 0.13, y);
    ctx.quadraticCurveTo(x, y - s * 0.5, x + s * 0.13, y); ctx.fillStyle = "#ffe08a"; ctx.fill();
  }

  // Creatures, at size s (about their height), standing on (x, y).
  const CREATURE = {
    Emberfox(ctx, x, y, s, t) {
      const w = Math.max(1.2, s * 0.05);
      flame(ctx, x - s * 0.5, y - s * 0.28, s * 0.42, t);
      blob(ctx, x - s * 0.05, y - s * 0.3, s * 0.36, s * 0.26, "#f08a3c", w);
      blob(ctx, x + s * 0.22, y - s * 0.62, s * 0.26, s * 0.24, "#f08a3c", w);
      tri(ctx, [x + s * 0.06, y - s * 0.78, x + s * 0.12, y - s * 1.02, x + s * 0.24, y - s * 0.84], "#f08a3c", w);
      tri(ctx, [x + s * 0.26, y - s * 0.84, x + s * 0.38, y - s * 1.02, x + s * 0.42, y - s * 0.76], "#f08a3c", w);
      blob(ctx, x + s * 0.36, y - s * 0.54, s * 0.12, s * 0.09, "#fff1dc", w);
      eye(ctx, x + s * 0.27, y - s * 0.66, s * 0.045);
      for (const dx of [-0.25, 0.12]) blob(ctx, x + dx * s, y - s * 0.06, s * 0.07, s * 0.06, "#c96a26", w);
    },
    Cindermole(ctx, x, y, s, t) {
      const w = Math.max(1.2, s * 0.05);
      blob(ctx, x, y - s * 0.4, s * 0.42, s * 0.4, "#9a6a4a", w);
      blob(ctx, x, y - s * 0.3, s * 0.24, s * 0.2, "#e8c9a0", w);
      blob(ctx, x, y - s * 0.46, s * 0.08, s * 0.06, "#e86a8a", w);
      eye(ctx, x - s * 0.16, y - s * 0.58, s * 0.05); eye(ctx, x + s * 0.16, y - s * 0.58, s * 0.05);
      flame(ctx, x, y - s * 0.78, s * 0.42, t);
      for (const dx of [-0.32, 0.32]) blob(ctx, x + dx * s, y - s * 0.08, s * 0.12, s * 0.07, "#7a4e34", w);
    },
    Shellbit(ctx, x, y, s) {           // seen from behind, as your own creature is
      const w = Math.max(1.2, s * 0.05);
      blob(ctx, x, y - s * 0.38, s * 0.44, s * 0.36, "#5cc6e8", w);
      blob(ctx, x, y - s * 0.42, s * 0.36, s * 0.3, "#2f8f86", w);
      ctx.strokeStyle = "#bfeee6"; ctx.lineWidth = w; ctx.beginPath();
      ctx.moveTo(x - s * 0.2, y - s * 0.52); ctx.lineTo(x + s * 0.2, y - s * 0.52);
      ctx.moveTo(x, y - s * 0.7); ctx.lineTo(x, y - s * 0.16); ctx.stroke();
      blob(ctx, x, y - s * 0.82, s * 0.2, s * 0.17, "#5cc6e8", w);
    },
  };

  const SOFT_ICON = {
    CaptureOrb(ctx, cx, cy, s) {
      const r = s * 0.36, w = Math.max(1.2, s * 0.05);
      ctx.save(); ctx.beginPath(); ctx.arc(cx, cy, r, 0, 7); ctx.clip();
      ctx.fillStyle = "#fff4e0"; ctx.fillRect(cx - r, cy - r, r * 2, r * 2);
      ctx.fillStyle = "#35b3a6"; ctx.fillRect(cx - r, cy - r, r * 2, r);
      ctx.restore();
      ctx.lineWidth = w; ctx.strokeStyle = INK;
      ctx.beginPath(); ctx.arc(cx, cy, r, 0, 7); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(cx - r, cy); ctx.lineTo(cx + r, cy); ctx.stroke();
      blob(ctx, cx, cy, r * 0.28, r * 0.28, "#fff", w);
    },
    SuperPotion(ctx, cx, cy, s) {
      const w = Math.max(1.2, s * 0.05);
      blob(ctx, cx, cy + s * 0.1, s * 0.3, s * 0.28, "#b07ce8", w);
      ctx.fillStyle = "rgba(255,255,255,0.6)"; ctx.beginPath(); ctx.ellipse(cx - s * 0.1, cy + s * 0.02, s * 0.06, s * 0.1, -0.4, 0, 7); ctx.fill();
      tri(ctx, [cx - s * 0.1, cy - s * 0.16, cx + s * 0.1, cy - s * 0.16, cx + s * 0.1, cy - s * 0.32, cx - s * 0.1, cy - s * 0.32], "#e6dcf6", w);
      tri(ctx, [cx - s * 0.13, cy - s * 0.32, cx + s * 0.13, cy - s * 0.32, cx + s * 0.13, cy - s * 0.42, cx - s * 0.13, cy - s * 0.42], "#b08a5a", w);
    },
  };

  // ---------------------------------------------------------------- public

  // An icon centred at (cx, cy) in a box of side s, in the item's home style.
  function icon(ctx, item, cx, cy, s, t) {
    ctx.save();
    const rows = CRAFT[item.kind];
    if (rows) {
      const cell = (s * 0.84) / Math.max(rows[0].length, rows.length);
      pixels(ctx, rows, cx - (cell * rows[0].length) / 2, cy - (cell * rows.length) / 2, cell);
    } else if (CREATURE[item.kind]) {
      CREATURE[item.kind](ctx, cx, cy + s * 0.42, s * 0.82, t);
    } else if (SOFT_ICON[item.kind]) {
      SOFT_ICON[item.kind](ctx, cx, cy, s);
    } else if (item.home === "craft") {
      pixels(ctx, CRAFT.DiamondSword, cx - s * 0.42, cy - s * 0.42, (s * 0.84) / 16);
    } else {
      blob(ctx, cx, cy, s * 0.3, s * 0.3, "#e6dcf6", 1.5);
    }
    ctx.restore();
  }

  window.Sprites = { icon, pixels, creature: (ctx, kind, x, y, s, t) => CREATURE[kind] && CREATURE[kind](ctx, x, y, s, t),
                     blob, flame, PX, INK };
})();
