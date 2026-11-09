// Generador de los stickers animados del Editor Vertical (lo usan la pestaña Edición, para dibujar a la medida
// los stickers de línea cuando se estiran, y la herramienta que hace las hojas de assets/stickers).
(function () {
// Generador de los stickers animados del Editor Vertical.
// Cada sticker = 2 capas por cuadro: «fijo» (contornos negros / blanco) y «color» (en blanco y grises: la
// plataforma la tiñe del color elegido). Cuadros: INTRO de entrada + LOOP que se repite mientras dura.
const S = 320, FPS = 24, INTRO = 12, LOOP = 24, F = INTRO + LOOP, COLS = 6;
const ease = (x) => 1 - Math.pow(1 - Math.min(1, Math.max(0, x)), 3);
const back = (x) => { x = Math.min(1, Math.max(0, x)); const c1 = 1.9, c3 = c1 + 1; return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2); };
function rnd(seed) { let s = seed; return () => { s = (s * 16807) % 2147483647; return (s - 1) / 2147483646; }; }

// trazo a mano alzada: dibuja la fracción «fr» de la polilínea con punta afilada al inicio y al final
function trazo(ctx, pts, fr, w, color, taper = true) {
  if (fr <= 0) return;
  const n = Math.max(2, Math.floor((pts.length - 1) * Math.min(1, fr)) + 1);
  ctx.strokeStyle = color; ctx.lineCap = "round"; ctx.lineJoin = "round";
  for (let i = 1; i < n; i++) {
    const u = i / (pts.length - 1);
    let k = 1;
    if (taper) k = Math.min(1, 0.35 + u * 6) * Math.min(1, 0.25 + (1 - u) * 5);
    ctx.lineWidth = w * k;
    ctx.beginPath(); ctx.moveTo(pts[i - 1][0], pts[i - 1][1]); ctx.lineTo(pts[i][0], pts[i][1]); ctx.stroke();
  }
}
function poly(ctx, pts) { ctx.beginPath(); pts.forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])); ctx.closePath(); }
function grad(ctx, x0, y0, x1, y1, a = "#fff", b = "#cfcfcf") { const g = ctx.createLinearGradient(x0, y0, x1, y1); g.addColorStop(0, a); g.addColorStop(1, b); return g; }
function pop(k, dur = INTRO) { return k < dur ? back(k / (dur - 1)) : 1; }

const C = S / 2;
const ST = {
  // ---- stickers de línea: se dibujan a la medida (FW x FH) con el grosor según el lado corto ----
  circulo(f, c, k, q) {
    const pts = [], cx = FW / 2, cy = FH / 2;
    for (let i = 0; i <= 160; i++) {
      const a = -1.9 + (i / 160) * Math.PI * 2.12, osc = (1 + 0.035 * Math.sin(2 * a + 0.7)) * (1 - 0.06 * i / 160);
      pts.push([cx + FW * 0.36 * osc * Math.cos(a) * 1.02, cy + FH * 0.36 * osc * Math.sin(a)]);
    }
    trazo(c, pts, ease(k / (INTRO - 1)), MN * 0.045, "#fff");
  },
  ovalo(f, c, k, q) {
    const pts = [], cx = FW / 2, cy = FH / 2;
    for (let i = 0; i <= 220; i++) {
      const u = i / 220, a = -2.3 + u * Math.PI * 2 * 1.85;
      const rx = FW * (0.44 - 0.03 * u), ry = FH * (0.24 - 0.02 * u);
      pts.push([cx + rx * Math.cos(a) + MN * 0.019 * Math.sin(u * 9), cy + ry * Math.sin(a) - MN * 0.025 * u + FH * 0.02]);
    }
    trazo(c, pts, ease(k / (INTRO - 1)), MN * 0.03, "#fff");
  },
  rectangulo(f, c, k, q) {
    const x0 = FW * 0.1, y0 = FH * 0.22, x1 = FW * 0.9, y1 = FH * 0.78, m = MN / 320, pts = [];
    const lados = [[[x0 - 8 * m, y0 + 4 * m], [x1 + 10 * m, y0 - 4 * m]], [[x1 + 2 * m, y0 - 12 * m], [x1 - 4 * m, y1 + 10 * m]],
                   [[x1 + 8 * m, y1], [x0 - 8 * m, y1 + 6 * m]], [[x0, y1 + 12 * m], [x0 + 6 * m, y0 - 14 * m]]];
    for (const [a, b] of lados) for (let i = 0; i <= 50; i++) { const u = i / 50; pts.push([a[0] + (b[0] - a[0]) * u + Math.sin(u * 3.1) * 3 * m, a[1] + (b[1] - a[1]) * u + Math.sin(u * 3.1) * 4 * m]); }
    trazo(c, pts, ease(k / (INTRO - 1)), MN * 0.04, "#fff");
  },
  marco(f, c, k, q) {   // rectángulo recto y delgado (esquinas en ángulo), se dibuja alrededor desde la esquina de arriba
    const g = MN * 0.028, x0 = FW * 0.05 + g, y0 = FH * 0.2 + g, x1 = FW * 0.95 - g, y1 = FH * 0.8 - g;
    const pts = [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]];
    const fr = Math.min(1, Math.max(0, ease(k / (INTRO - 1))));
    let total = 0; const lados = [];
    for (let i = 1; i < pts.length; i++) { const d = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]); lados.push(d); total += d; }
    if (fr <= 0) return;
    c.strokeStyle = "#fff"; c.lineWidth = g; c.lineJoin = "miter"; c.lineCap = "square";
    c.beginPath(); c.moveTo(x0, y0);
    let falta = total * fr;
    for (let i = 1; i < pts.length && falta > 0; i++) {
      const u = Math.min(1, falta / lados[i - 1]);
      c.lineTo(pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * u, pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * u);
      falta -= lados[i - 1];
    }
    if (fr >= 1) c.closePath();
    c.stroke();
  },
  subrayado(f, c, k, q) {
    const pts = [], ondas = 4 * Math.max(1, Math.round(FW / FH * 2) / 2), n = Math.round(100 * Math.max(1, FW / FH));
    for (let i = 0; i <= n; i++) { const u = i / n; pts.push([FW * 0.05 + u * FW * 0.9, FH / 2 + Math.sin(u * Math.PI * ondas) * FH * 0.035 + (u - 0.5) * -FH * 0.04]); }
    trazo(c, pts, ease(k / (INTRO - 1)), MN * 0.045, "#fff");
  },
  tachado(f, c, k, q) {
    const pts = [];
    for (let i = 0; i <= 60; i++) { const u = i / 60; pts.push([FW * 0.04 + u * FW * 0.92, FH / 2 + FH * 0.05 - u * FH * 0.1 + Math.sin(u * 3) * MN * 0.0125]); }
    trazo(c, pts, ease(k / (INTRO * 0.7)), MN * 0.07, "#fff", false);
  },
  flecha_abajo(f, c, k, q) {
    const caida = k < INTRO ? (1 - back(k / (INTRO - 1))) * -S * 0.5 : 0;
    const bob = k >= INTRO ? Math.sin(q * Math.PI * 2) * S * 0.05 : 0;
    const dy = caida + bob, w = S;
    const pts = [[w * 0.42, w * 0.06], [w * 0.58, w * 0.05], [w * 0.565, w * 0.55], [w * 0.72, w * 0.55], [w * 0.5, w * 0.92], [w * 0.28, w * 0.56], [w * 0.435, w * 0.56]].map(p => [p[0], p[1] + dy]);
    poly(f, pts); f.lineJoin = "miter"; f.lineWidth = S * 0.035; f.strokeStyle = "#000"; f.stroke();
    f.lineWidth = S * 0.014; f.strokeStyle = "#fff"; f.stroke();   // filo blanco por fuera, como el de Filmora
    poly(c, pts); c.fillStyle = grad(c, 0, w * 0.05 + dy, 0, w * 0.92 + dy, "#fff", "#d9d9d9"); c.fill();
  },
  flecha_recta(f, c, k, q) {
    const entra = k < INTRO ? (1 - ease(k / (INTRO - 1))) * -S * 0.6 : 0;
    const emp = k >= INTRO ? Math.sin(q * Math.PI * 2) * S * 0.04 : 0;
    const dx = entra + emp;
    const pts = [[S * 0.06, S * 0.43], [S * 0.6, S * 0.43], [S * 0.6, S * 0.3], [S * 0.94, S * 0.5], [S * 0.6, S * 0.7], [S * 0.6, S * 0.57], [S * 0.06, S * 0.57]].map(p => [p[0] + dx, p[1]]);
    f.globalAlpha = c.globalAlpha = k < INTRO ? ease(k / 5) : 1;
    poly(f, pts); f.lineJoin = "miter"; f.lineWidth = S * 0.035; f.strokeStyle = "#000"; f.stroke();
    poly(c, pts); c.fillStyle = grad(c, 0, S * 0.3, 0, S * 0.7, "#fff", "#d4d4d4"); c.fill();
    f.globalAlpha = c.globalAlpha = 1;
  },
  flecha_curva(f, c, k, q) {
    // cinta que engrosa a lo largo de una curva + punta
    const P = (u) => { const a = [S * 0.08, S * 0.18], b = [S * 0.18, S * 0.78], d = [S * 0.62, S * 0.8], e = [S * 0.86, S * 0.66];
      const m = 1 - u; return [m * m * m * a[0] + 3 * m * m * u * b[0] + 3 * m * u * u * d[0] + u * u * u * e[0], m * m * m * a[1] + 3 * m * m * u * b[1] + 3 * m * u * u * d[1] + u * u * u * e[1]]; };
    const fr = ease(k / (INTRO - 1)), N = 80, izq = [], der = [];
    const fin = Math.max(0.02, fr * 0.9);
    for (let i = 0; i <= N; i++) {
      const u = (i / N) * fin, p = P(u), p2 = P(Math.min(1, u + 0.01));
      let nx = -(p2[1] - p[1]), ny = p2[0] - p[0]; const l = Math.hypot(nx, ny) || 1; nx /= l; ny /= l;
      const w = S * (0.012 + 0.055 * Math.min(1, u * 1.6));
      izq.push([p[0] + nx * w, p[1] + ny * w]); der.push([p[0] - nx * w, p[1] - ny * w]);
    }
    poly(c, izq.concat(der.reverse())); c.fillStyle = grad(c, S * 0.1, S * 0.2, S * 0.8, S * 0.7, "#b8b8b8", "#fff"); c.fill();
    if (fr > 0.55) {
      const s = Math.min(1, (fr - 0.55) / 0.3), p = P(fin), p0 = P(fin - 0.02);
      let tx = p[0] - p0[0], ty = p[1] - p0[1]; const l = Math.hypot(tx, ty); tx /= l; ty /= l;
      const L = S * 0.2 * s, W = S * 0.13 * s;
      poly(c, [[p[0] + tx * L, p[1] + ty * L], [p[0] - ty * W - tx * L * 0.1, p[1] + tx * W - ty * L * 0.1], [p[0] + ty * W - tx * L * 0.1, p[1] - tx * W - ty * L * 0.1]]);
      c.fillStyle = "#fff"; c.fill();
    }
  },
  tache(f, c, k, q) {
    const s1 = k < INTRO ? back(Math.min(1, k / (INTRO * 0.55))) : 1, s2 = k < INTRO ? back(Math.max(0, (k - INTRO * 0.35) / (INTRO * 0.6))) : 1;
    const pul = k >= INTRO ? 1 + 0.03 * Math.sin(q * Math.PI * 2) : 1;
    c.save(); c.translate(C, C); c.scale(pul, pul); c.fillStyle = "#fff";
    const L = S * 0.4, W = S * 0.075;
    c.save(); c.rotate(Math.PI / 4); c.scale(s1, 1); c.fillRect(-L, -W, 2 * L, 2 * W); c.restore();
    c.save(); c.rotate(-Math.PI / 4); c.scale(s2, 1); if (s2 > 0) c.fillRect(-L, -W, 2 * L, 2 * W); c.restore();
    c.restore();
  },
  palomita(f, c, k, q) {
    const pts = [];
    for (let i = 0; i <= 30; i++) { const u = i / 30; pts.push([S * 0.12 + u * S * 0.24, S * 0.52 + u * S * 0.24]); }
    for (let i = 1; i <= 60; i++) { const u = i / 60; pts.push([S * 0.36 + u * S * 0.52, S * 0.76 - u * S * 0.6 - Math.sin(u * 3) * 6]); }
    trazo(c, pts, ease(k / (INTRO - 1)), S * 0.085, "#fff", false);
  },
  mano(f, c, k, q) {
    // tap: la mano se aprieta y salen ondas del dedo
    let s = pop(k);
    let ondas = -1;
    if (k >= INTRO) { const t = q * 2 % 1; s = 1 - 0.08 * Math.sin(Math.min(1, t / 0.3) * Math.PI); ondas = t; }
    const tipx = S * 0.43, tipy = S * 0.12;
    if (ondas >= 0 && ondas < 0.85) {
      for (const d of [0, 0.25]) {
        const u = (ondas - d) / 0.6; if (u <= 0 || u >= 1) continue;
        c.globalAlpha = 1 - u; c.lineWidth = S * 0.028; c.strokeStyle = "#fff";
        c.beginPath(); c.arc(tipx, tipy, S * (0.05 + 0.2 * u), 0, Math.PI * 2); c.stroke();
      }
      c.globalAlpha = 1;
    }
    f.save(); f.translate(S * 0.5, S * 0.62); f.scale(s, s); f.translate(-S * 0.5, -S * 0.62);
    const rr = (x, y, w, h, r) => { f.beginPath(); f.roundRect(x, y, w, h, r); };
    const partes = [
      () => rr(S * 0.37, S * 0.13, S * 0.12, S * 0.5, S * 0.06),       // índice
      () => rr(S * 0.47, S * 0.36, S * 0.11, S * 0.26, S * 0.055),     // medio
      () => rr(S * 0.56, S * 0.40, S * 0.10, S * 0.24, S * 0.05),      // anular
      () => rr(S * 0.645, S * 0.45, S * 0.09, S * 0.22, S * 0.045),    // meñique
      () => { f.beginPath(); f.moveTo(S * 0.38, S * 0.55); f.lineTo(S * 0.27, S * 0.47); f.quadraticCurveTo(S * 0.2, S * 0.43, S * 0.17, S * 0.5); f.quadraticCurveTo(S * 0.15, S * 0.55, S * 0.21, S * 0.62); f.lineTo(S * 0.36, S * 0.82); f.closePath(); }, // pulgar
      () => { f.beginPath(); f.moveTo(S * 0.33, S * 0.55); f.lineTo(S * 0.735, S * 0.55); f.quadraticCurveTo(S * 0.75, S * 0.75, S * 0.7, S * 0.9); f.lineTo(S * 0.4, S * 0.9); f.quadraticCurveTo(S * 0.33, S * 0.78, S * 0.3, S * 0.72); f.closePath(); }, // palma
    ];
    f.strokeStyle = "#000"; f.lineJoin = "round"; f.lineWidth = S * 0.05;
    partes.forEach(p => { p(); f.stroke(); });
    f.fillStyle = "#fff"; partes.forEach(p => { p(); f.fill(); });
    f.lineWidth = S * 0.018; f.lineCap = "round";
    for (const x of [0.49, 0.56, 0.63]) { f.beginPath(); f.moveTo(S * x, S * 0.7); f.lineTo(S * x, S * 0.82); f.stroke(); }
    f.restore();
  },
  exclamacion(f, c, k, q) { signo(f, c, k, q, "!"); },
  interrogacion(f, c, k, q) { signo(f, c, k, q, "?"); },
  destello(f, c, k, q) {
    // líneas de énfasis alrededor (como «¡mira esto!»)
    const n = 10;
    c.lineCap = "round"; c.strokeStyle = "#fff";
    for (let i = 0; i < n; i++) {
      const a = (i / n) * Math.PI * 2 - Math.PI / 2;
      const ent = k < INTRO ? ease((k - i * 0.4) / 6) : 1;
      const lat = k >= INTRO ? Math.sin((q + i / n * 0.5) * Math.PI * 2) : 0;
      const r0 = S * (0.24 + 0.02 * lat), r1 = r0 + S * (0.14 + 0.03 * lat) * ent;
      if (ent <= 0) continue;
      c.lineWidth = S * (i % 2 ? 0.03 : 0.045);
      c.beginPath(); c.moveTo(C + r0 * Math.cos(a), C + r0 * Math.sin(a)); c.lineTo(C + r1 * Math.cos(a), C + r1 * Math.sin(a)); c.stroke();
    }
  },
  explosion(f, c, k, q) {
    const s = pop(k) * (k >= INTRO ? 1 + 0.035 * Math.sin(q * Math.PI * 4) : 1);
    const R = rnd(11), pts = [], n = 14;
    const rs = Array.from({ length: n * 2 }, (_, i) => i % 2 ? 0.27 + R() * 0.05 : 0.42 + R() * 0.06);
    for (let i = 0; i < n * 2; i++) { const a = (i / (n * 2)) * Math.PI * 2; pts.push([C + Math.cos(a) * S * rs[i] * s, C + Math.sin(a) * S * rs[i] * s * 0.85]); }
    poly(f, pts); f.lineJoin = "miter"; f.lineWidth = S * 0.035; f.strokeStyle = "#000"; f.stroke();
    poly(c, pts); c.fillStyle = grad(c, 0, S * 0.1, 0, S * 0.9, "#fff", "#dadada"); c.fill();
  },
  enfoque(f, c, k, q) {
    // cuatro esquinas que se cierran sobre lo que se quiere señalar
    const e = k < INTRO ? ease(k / (INTRO - 1)) : 1;
    const resp = k >= INTRO ? 1 + 0.025 * Math.sin(q * Math.PI * 2) : 1;
    const m = (0.9 - 0.45 * e) * resp;   // medio tamaño relativo (empieza más abierto)
    c.globalAlpha = Math.min(1, e * 1.6);
    const hx = FW * 0.42 * m / 0.45, hy = FH * 0.3 * m / 0.45, L = MN * 0.12;
    c.strokeStyle = "#fff"; c.lineWidth = MN * 0.04; c.lineCap = "round"; c.lineJoin = "round";
    for (const [sx, sy] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) {
      const x = FW / 2 + sx * hx, y = FH / 2 + sy * hy;
      c.beginPath(); c.moveTo(x - sx * L, y); c.lineTo(x, y); c.lineTo(x, y - sy * L); c.stroke();
    }
    c.globalAlpha = 1;
  },
};
function signo(f, c, k, q, ch) {
  const s = pop(k), rot = k >= INTRO ? Math.sin(q * Math.PI * 2) * 0.1 : (1 - s) * 0.6;
  for (const [ctx, capa] of [[f, "f"], [c, "c"]]) {
    ctx.save(); ctx.translate(C, S * 0.55); ctx.rotate(rot); ctx.scale(s, s);
    ctx.font = `900 ${S * 0.82}px P`; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    if (capa === "f") { ctx.lineJoin = "round"; ctx.lineWidth = S * 0.05; ctx.strokeStyle = "#000"; ctx.strokeText(ch, 0, 0); }
    else { ctx.fillStyle = grad(ctx, 0, -S * 0.35, 0, S * 0.35, "#fff", "#d6d6d6"); ctx.fillText(ch, 0, 0); }
    ctx.restore();
  }
}

const LINEA = ["circulo", "ovalo", "rectangulo", "marco", "enfoque", "subrayado", "tachado"];
let FW = S, FH = S, MN = S;   // medida del cuadro de los stickers de línea
// arma la hoja de un sticker: izquierda = capa fija, derecha = capa de color.
// prop = alto / ancho (solo los de línea se dibujan a la medida; los demás son cuadrados)
function hojaCanvas(tipo, prop = 1, lado = S) {
  if (LINEA.includes(tipo) && Math.abs(prop - 1) > 0.005) {
    if (prop < 1) { FW = lado; FH = Math.max(16, Math.round(lado * prop)); } else { FH = lado; FW = Math.max(16, Math.round(lado / prop)); }
  } else { FW = FH = S; }
  MN = Math.min(FW, FH);
  const filas = Math.ceil(F / COLS);
  const cv = document.createElement("canvas"); cv.width = FW * COLS * 2; cv.height = FH * filas;
  const g = cv.getContext("2d");
  const a = document.createElement("canvas"), b = document.createElement("canvas");
  a.width = b.width = FW; a.height = b.height = FH;
  const ga = a.getContext("2d"), gb = b.getContext("2d");
  for (let k = 0; k < F; k++) {
    const fx = (k % COLS) * FW, fy = Math.floor(k / COLS) * FH;
    ga.clearRect(0, 0, FW, FH); gb.clearRect(0, 0, FW, FH);
    const q = k >= INTRO ? (k - INTRO) / LOOP : 0;
    ga.save(); gb.save();
    ST[tipo](ga, gb, k, q);
    ga.restore(); gb.restore();
    g.drawImage(a, fx, fy); g.drawImage(b, FW * COLS + fx, fy);
  }
  return cv;
}
function hoja(tipo, prop = 1) { return hojaCanvas(tipo, prop).toDataURL("image/png"); }
if (typeof window !== "undefined") { window.TIPOS = Object.keys(ST); window.META = { S, FPS, INTRO, LOOP, F, COLS }; window.STK_LINEA = LINEA; window.hojaCanvas = hojaCanvas; }
})();
