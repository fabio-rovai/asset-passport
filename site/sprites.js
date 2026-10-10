// Art for both games, drawn in code. A thing is always drawn in its HOME
// game's style, wherever it ends up: a Blockcraft sword stays chunky pixels in
// Pocket Battlers, and an Emberfox stays soft and round in Blockcraft.
(function () {
  "use strict";

  // ---------------------------------------------------------------- pixels
  const PX = {
    k: "#1d1f2b", w: "#f4f6fb", c: "#bfe9f2", C: "#5aa6c8", b: "#7a4a24", B: "#4e2d14",
    y: "#f6d04d", Y: "#c99a24", r: "#d8413a", R: "#8e2020", g: "#b8bcc6", G: "#6c707b",
    p: "#9a6ad6", P: "#5b3a8e", o: "#ff8a3d", l: "#6cc24a", L: "#3f8a2c",
    v: "#e6c8ff", V: "#a578e6", n: "#ffc96b", O: "#d55f1c", d: "#4a4e5a", D: "#2c2f38", e: "#6b7080",
  };
  // Item art is keyed by what the engine says a thing is (its category), not by
  // a game's own name for it, so a game can rename its items freely.
  // Blockcraft's item art, our own: a sword with a faceted lilac crystal blade,
  // a gold guard and a violet pommel stone; a dark block with a lit fuse and a
  // burst mark on its face; and a star-shaped orange fruit with a leaf.
  const CRAFT = {
    weapon: [
      "............kkk.", "...........kwvVk", "..........kwvVk.", ".........kwvVVk.",
      "........kwvVkk..", ".......kwvVk....", "......kwvVVk....", ".kk..kwvVkk.....",
      ".kyk.kvVk.......", "..kykVVk........", "...kyYk.........", "..kbkyYk........",
      ".kBk..kYk.......", "kPk....kk.......", "kk..............",
    ],
    explosive: [
      "..........y.o.", ".........oyo..", "........bo....", ".......b......",
      ".kkkkkkkkkkkk.", ".keeeeeeeeeek.", ".kedrdoodrdDk.", ".keddoyyoddDk.",
      ".keroyyyyorDk.", ".keroyyyyorDk.", ".keddoyyoddDk.", ".kedrdoodrdDk.",
      ".keDDDDDDDDDk.", ".kkkkkkkkkkkk.",
    ],
    heal: [
      "......kblLk...", "......kk......", ".....knnk.....", ".....knnk.....",
      "...kkknokkk...", ".kknnnoooookk.", "knnnnnoooooOOk", ".knnnoooooOOk.",
      "..kkoooooOkk..", "...kooooOOk...", "...koooOOOk...", "..koookkOOOk..",
      "..kook..kOOk..", "...kk....kk...",
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
    // A glass bubble ringed by a teal band, with a gold spark inside.
    capture(ctx, cx, cy, s) {
      const r = s * 0.36, w = Math.max(1.2, s * 0.05);
      blob(ctx, cx, cy, r, r, "#e4f5f8", w);
      ctx.fillStyle = "rgba(255,255,255,0.8)"; ctx.beginPath(); ctx.ellipse(cx - r * 0.38, cy - r * 0.4, r * 0.16, r * 0.26, -0.6, 0, 7); ctx.fill();
      ctx.save(); ctx.translate(cx, cy); ctx.rotate(-0.5);
      ctx.beginPath(); ctx.ellipse(0, 0, r * 1.12, r * 0.3, 0, 0, 7); ctx.lineWidth = w * 1.6; ctx.strokeStyle = "#2f8f86"; ctx.stroke();
      ctx.restore();
      const q = r * 0.36, n = r * 0.1;
      tri(ctx, [cx, cy - q, cx + n, cy - n, cx + q, cy, cx + n, cy + n, cx, cy + q, cx - n, cy + n, cx - q, cy, cx - n, cy - n], "#f2c84b", Math.max(1, w * 0.7));
    },
    // A round glass bottle of pink fizz under a red cap, with bubbles rising.
    heal(ctx, cx, cy, s) {
      const w = Math.max(1.2, s * 0.05), r = s * 0.29, by = cy + s * 0.12;
      tri(ctx, [cx - s * 0.08, by - r - s * 0.02, cx + s * 0.08, by - r - s * 0.02, cx + s * 0.08, cy - s * 0.3, cx - s * 0.08, cy - s * 0.3], "#e8f6fb", w);
      blob(ctx, cx, by, r, r, "#e8f6fb", w);
      ctx.save(); ctx.beginPath(); ctx.arc(cx, by, r - w * 0.5, 0, 7); ctx.clip();
      ctx.fillStyle = "#f07ab0"; ctx.fillRect(cx - r, by - r * 0.15, r * 2, r * 1.2);
      ctx.fillStyle = "#f7a8cc"; ctx.fillRect(cx - r, by - r * 0.15, r * 2, r * 0.16);
      ctx.restore();
      ctx.strokeStyle = INK; ctx.lineWidth = w; ctx.beginPath(); ctx.arc(cx, by, r, 0, 7); ctx.stroke();
      tri(ctx, [cx - s * 0.12, cy - s * 0.3, cx + s * 0.12, cy - s * 0.3, cx + s * 0.12, cy - s * 0.4, cx - s * 0.12, cy - s * 0.4], "#d8413a", w);
      ctx.fillStyle = "rgba(255,255,255,0.7)"; ctx.beginPath(); ctx.ellipse(cx - r * 0.5, by - r * 0.4, r * 0.12, r * 0.24, -0.5, 0, 7); ctx.fill();
      for (const [dx, dy, br] of [[-0.1, 0.22, 0.05], [0.12, 0.3, 0.04], [0.04, 0.12, 0.035], [0.16, 0.1, 0.03], [0.2, -0.3, 0.035], [0.28, -0.42, 0.025]]) {
        ctx.beginPath(); ctx.arc(cx + dx * s, cy + dy * s, br * s, 0, 7);
        ctx.fillStyle = "rgba(255,255,255,0.85)"; ctx.fill(); ctx.lineWidth = Math.max(0.6, w * 0.5); ctx.strokeStyle = INK; ctx.stroke();
      }
    },
  };

  // ---------------------------------------------------------------- public

  // An icon centred at (cx, cy) in a box of side s, in the item's home style.
  function icon(ctx, item, cx, cy, s, t) {
    ctx.save();
    const rows = item.home === "craft" && CRAFT[item.cat];
    if (rows) {
      const cell = (s * 0.84) / Math.max(rows[0].length, rows.length);
      pixels(ctx, rows, cx - (cell * rows[0].length) / 2, cy - (cell * rows.length) / 2, cell);
    } else if (CREATURE[item.kind]) {
      CREATURE[item.kind](ctx, cx, cy + s * 0.42, s * 0.82, t);
    } else if (item.home === "battle" && SOFT_ICON[item.cat]) {
      SOFT_ICON[item.cat](ctx, cx, cy, s);
    } else if (item.home === "craft") {
      pixels(ctx, CRAFT.weapon, cx - s * 0.42, cy - s * 0.42, (s * 0.84) / 16);
    } else {
      blob(ctx, cx, cy, s * 0.3, s * 0.3, "#e6dcf6", 1.5);
    }
    ctx.restore();
  }

  window.Sprites = { icon, pixels, creature: (ctx, kind, x, y, s, t) => CREATURE[kind] && CREATURE[kind](ctx, x, y, s, t),
                     blob, flame, PX, INK };
})();
