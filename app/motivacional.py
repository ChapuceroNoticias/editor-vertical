"""
Estilo "Tiktoks Motivacionales" (plantilla con "estilo": "motivacional").

Cómo se ve (medido en los edits manuales):
- Nacho a pantalla completa. El encuadre alterna entre "lejos" (toda la altura del video) y "cerca"
  (≈1.19x, anclado abajo) en los cortes de pausa, cada 3-7 s.
- Título al inicio en un recuadro negro redondeado con borde blanco (fuente AkuKamu), unos 3 s, sin subtítulos.
- Subtítulos por frase (Staatliches, blancos con contorno y sombra), que desaparecen en las pausas.
- Pausas: las menores a 0.5 s quedan intactas; las largas se acortan dejando más silencio al final de una
  oración (efecto dramático) que en una coma.
- Pocas imágenes (2 a 4 por video), a pantalla completa, unos 3 s, con zoom lento y una entrada girando.
- Sin música.

El editor (editor.py) asigna el módulo en `ed` antes de llamar a estas funciones.
"""
import json
import math
import re
import subprocess
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ed = None  # módulo editor (lo asigna editor.py)

FIN_ORACION = re.compile(r"[.!?:…]+[\"'»”]*$")
COMA = re.compile(r"[,;]+[\"'»”]*$")
ABREVIATURAS = {"mr", "mrs", "ms", "sr", "sra", "srta", "dr", "dra", "lic", "ing", "prof", "st", "etc", "vs", "jr", "no"}


def fin_oracion(palabra):
    """True si la palabra cierra una oración (no cuenta 'Mr.', 'Sr.', 'Dr.'...)."""
    if not FIN_ORACION.search(palabra):
        return False
    if palabra.endswith(".") and ed.solo_letras(palabra) in ABREVIATURAS:
        return False
    return True


# ----------------------------------------------------------------------------
# Rostro
# ----------------------------------------------------------------------------
def pista_rostro(video, info, cada=0.5):
    """Posición de la cara cada 'cada' segundos, muy suavizada (el encuadre casi no se mueve)."""
    det = ed.DetectorCara()
    cap = cv2.VideoCapture(str(video))
    fps = info["fps"]
    paso = max(1, int(round(fps * cada)))
    puntos, idx = [], 0
    total = info["cuadros"] or 1
    while True:
        if idx % paso == 0:
            ok, fr = cap.read()
            if not ok:
                break
            esc = 960 / fr.shape[1]
            c = det.mayor(cv2.resize(fr, None, fx=esc, fy=esc))
            if c and c[3] > 0.08 * fr.shape[0] * esc:
                x, y, w, h = [v / esc for v in c]
                puntos.append([idx / fps, x + w / 2, y + h / 2, w, h])
            if len(puntos) % 20 == 0:
                ed.Progreso.paso(0.18 * idx / total, "Buscando la cara")
        else:
            if not cap.grab():
                break
        idx += 1
    cap.release()
    if not puntos:
        W, H = info["ancho"], info["alto"]
        return [[0.0, W / 2, H * 0.35, H * 0.25, H * 0.33]]
    a = np.array(puntos, float)
    # mediana móvil de ±4 s y luego promedio: quita brincos del detector
    v = max(1, int(4 / cada))
    sm = a.copy()
    for k in range(len(a)):
        lo, hi = max(0, k - v), min(len(a), k + v + 1)
        sm[k, 1:] = np.median(a[lo:hi, 1:], 0)
    ker = np.ones(2 * v + 1) / (2 * v + 1)
    for c in range(1, 5):
        pad = np.pad(sm[:, c], v, mode="edge")
        sm[:, c] = np.convolve(pad, ker, "valid")
    return [[round(float(x), 2) for x in r] for r in sm]


def pista_fija_moti(plan, pl, pista):
    """Tomas fijas también en este estilo: el recuadro no persigue a Nacho; si se sale, salta en un corte."""
    info = plan["info"]
    W, H = pl["salida"]["ancho"], pl["salida"]["alto"]
    cfg_t = pl.get("toma_fija", {})
    w = recorte(cara_en(pista, 0.0), "cerca", info["ancho"], info["alto"], W, H, pl.get("encuadre", {}))[2]
    puntos = [c["fin"] for c in plan.get("cortes", [])]
    return ed.pista_fija(pista, w, cfg_t, puntos)


def cara_en(pista, t):
    if len(pista) == 1:
        return pista[0][1:]
    ts = [p[0] for p in pista]
    return [float(np.interp(t, ts, [p[k] for p in pista])) for k in (1, 2, 3, 4)]


def recorte(cara, zoom, src_w, src_h, W, H, cfg):
    """Ventana (x0, y0, w, h) del video original para el encuadre 'lejos', 'cerca' o 'titulo'.
    'titulo' (mientras está el título): más cerca y con la cara arriba, para que el recuadro no tape la boca."""
    cx, cy, fw, fh = cara
    asp = W / H
    h = src_h * cfg.get("alto_lejos", 1.0)
    w = h * asp
    if w > src_w:
        w = float(src_w)
        h = w / asp
    if zoom in ("cerca", "titulo"):
        z = cfg.get("zoom_titulo", 1.3) if zoom == "titulo" else cfg.get("zoom_cerca", 1.19)
        w, h = w / z, h / z
    x0 = cx + cfg.get("desplazamiento_x", 0.05) * fw - w / 2
    if zoom == "titulo":
        y0 = cy - h * cfg.get("cara_y_titulo", 0.34)
    elif cfg.get("ancla", "abajo") == "abajo":
        y0 = src_h - h
        # que no se corte la cabeza: el pelo empieza ~0.85 del alto de la cara arriba del centro
        y0 = min(y0, max(0.0, cy - fh * 0.9))
    else:
        y0 = cy - h * 0.38
    x0 = min(max(x0, 0), src_w - w)
    y0 = min(max(y0, 0), src_h - h)
    return ed.ajuste_aprendido(x0, y0, w, h, [0, 0, src_w, src_h], cfg)


def recorte_entrada(cara, src_w, src_h, W, H, pl):
    """«Tiktoks Yair»: ventana (x0, y0, w, h) del video original para la franja de arriba durante el título.
    Medido de los videos de ejemplo contra su video base: casi todo el alto del original (alto_ventana) y la cara
    centrada a lo ancho y en el tercio de arriba. Es fija (no persigue a Yair)."""
    cfg = pl.get("entrada") or {}
    alto_p = cfg.get("alto_persona", 1201)
    cx, cy, fw, fh = cara
    asp = W / alto_p
    h = src_h * cfg.get("alto_ventana", 0.933)
    w = h * asp
    if w > src_w:
        w = float(src_w)
        h = w / asp
    x0 = cx - w * cfg.get("cara_x", 0.51)
    y0 = cy - h * cfg.get("cara_y", 0.34)
    x0 = min(max(x0, 0), src_w - w)
    y0 = min(max(y0, 0), src_h - h)
    return x0, y0, w, h


# ----------------------------------------------------------------------------
# Pausas
# ----------------------------------------------------------------------------
def energia(video):
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-map", "0:a:0", "-ac", "1", "-ar", "8000",
                        "-f", "s16le", "-"], capture_output=True)
    a = np.frombuffer(r.stdout, np.int16).astype(np.float32)
    n = len(a) // 80
    if n < 100:
        return None
    rms = np.sqrt((a[:n * 80].reshape(n, 80) ** 2).mean(1))
    db = 20 * np.log10(rms / 32768 + 1e-9)
    return np.convolve(db, np.ones(3) / 3, "same")  # 100 valores por segundo


def palabra_antes(palabras, t):
    """Última palabra que termina antes del silencio que empieza en t."""
    mejor = None
    for p in palabras:
        if p["f"] <= t + 0.3 and p["i"] < t:
            mejor = p
        elif p["i"] >= t:
            break
    return mejor


def calcular_cortes(video, info, palabras, cfg, dramaticas=()):
    """Acorta las pausas largas. Deja más silencio al final de una oración y mucho más en las 'dramáticas'."""
    if not cfg.get("activar", True) or not info.get("audio"):
        return []
    db = energia(video)
    if db is None:
        return []
    voz = db[db > -70]
    ref = np.percentile(voz if len(voz) else db, 70)
    bajo = db < ref - cfg.get("umbral_rel_db", 16)
    fps = info["fps"]
    dur = len(db) / 100
    pausa_min = cfg.get("pausa_min_seg", 0.5)
    antes = cfg.get("dejar_antes_seg", 0.10)
    dramaticas = sorted(dramaticas)
    tramos = ed.runs(list(bajo))
    hay_voz = [k for k in range(len(bajo)) if not bajo[k]]
    cortes = []

    def agregar(a, b):
        a = math.ceil(a * fps) / fps
        b = math.ceil(b * fps) / fps
        if b - a >= 1.5 / fps:
            cortes.append({"inicio": round(a, 4), "fin": round(b, 4)})

    if hay_voz:
        primera, ultima = hay_voz[0] / 100, hay_voz[-1] / 100
        if primera > cfg.get("inicio_dejar_seg", 0.08) + 0.05:
            agregar(0.0, primera - cfg.get("inicio_dejar_seg", 0.08))
    else:
        return []
    for i, j in tramos:
        ini, fin = i / 100, j / 100
        if ini <= primera or fin >= ultima or fin - ini < pausa_min:
            continue
        p = palabra_antes(palabras, ini)
        txt = p["p"] if p else ""
        largo = min(1.0, (fin - ini - pausa_min) / 0.7)
        if p and any(abs(p["f"] - d) < 0.05 for d in dramaticas):
            despues = cfg.get("dejar_dramatico_seg", 0.95)
        elif fin_oracion(txt):
            despues = cfg.get("dejar_oracion_seg", 0.40) + 0.25 * largo
            if fin - ini > 1.0:
                despues = max(despues, cfg.get("dejar_oracion_larga_seg", 0.6))
        elif COMA.search(txt):
            despues = cfg.get("dejar_coma_seg", 0.15)
        else:
            despues = cfg.get("dejar_frase_seg", 0.22) + 0.15 * largo
        if despues + antes >= fin - ini - 0.05:
            continue
        agregar(ini + despues, fin - antes)
    fin_v = ultima + cfg.get("final_dejar_seg", 0.5)
    if fin_v < dur - 0.1:
        agregar(fin_v, info["duracion"] + 1.0)
    cortes.sort(key=lambda c: c["inicio"])
    log_txt = sum(c["fin"] - c["inicio"] for c in cortes)
    ed.log(f"{len(cortes)} pausas acortadas, {log_txt:.1f}s quitados")
    return cortes


def a_editado(t, cortes):
    """Tiempo del video original -> tiempo en el video editado."""
    return ed.a_editado(t, cortes)


def puntos_de_corte(cortes, duracion):
    """Tiempos (originales) donde el video editado brinca: ahí se puede cambiar el encuadre sin que se note."""
    return [c["fin"] for c in cortes if 0.05 < c["fin"] < duracion - 0.3]


# ----------------------------------------------------------------------------
# Encuadres cerca / lejos
# ----------------------------------------------------------------------------
def silencios_cortos(video, cfg):
    """Pausitas que no se recortan (respiros) donde también se puede cambiar el encuadre sin que se note:
    tiempos (originales) a la mitad de cada silencio de al menos 'silencio_min_seg'."""
    db = energia(video)
    if db is None:
        return []
    voz = db[db > -70]
    ref = np.percentile(voz if len(voz) else db, 70)
    bajo = db < ref - cfg.get("umbral_silencio_db", 12)
    minimo = cfg.get("silencio_min_seg", 0.12)
    return [round((i + j) / 200, 3) for i, j in ed.runs(list(bajo)) if (j - i) / 100 >= minimo]


def plan_encuadres(cortes, duracion, cfg, palabras=None, silencios=None):
    """Alterna cerca / lejos. Cambia en los brincos de los cortes (cuando ya pasaron 'ritmo_seg' del cambio
    anterior). Si pasa mucho sin un corte ('max_sin_cambio_seg'), cambia en un respiro (silencio corto) o al
    inicio de una frase, para que el ritmo de cambios se mantenga."""
    ritmo = cfg.get("ritmo_seg", [3.2, 5.5, 4.0, 6.5, 4.5, 3.5, 6.0, 5.0])
    max_sin = cfg.get("max_sin_cambio_seg")
    estado = cfg.get("inicial", "cerca")
    out, ini, k = [], 0.0, 0
    ultimo_e = 0.0
    buenos = set(puntos_de_corte(cortes, duracion))
    segundos = set()   # respiros e inicios de frase: solo si ya pasó mucho sin un corte
    otros = set()      # cualquier inicio de palabra: último recurso
    dentro = lambda t: any(c["inicio"] - 0.05 <= t <= c["fin"] + 0.05 for c in cortes)  # noqa: E731
    for t in silencios or []:
        if 0.3 < t < duracion - 0.3 and not dentro(t):
            segundos.add(round(t, 4))
    if palabras and cfg.get("cambiar_en_frases", False):
        previa = None
        for w in palabras:
            i = float(w["i"])
            if 0.05 < i < duracion - 0.3 and not dentro(i):
                pausa = previa is not None and (i - float(previa["f"]) >= 0.12 or
                                                str(previa.get("p", "")).rstrip()[-1:] in ".,;:?!")
                (segundos if pausa else otros).add(round(i - 0.03, 4))
            previa = w
    for t in sorted(buenos | segundos | otros):
        te = a_editado(t, cortes)
        espera = ritmo[k % len(ritmo)]
        if t in buenos:
            necesita = espera
        elif t in segundos:
            necesita = max(espera, max_sin) if max_sin else espera * 1.5
        else:
            necesita = (max_sin or espera) * 1.5
        if te - ultimo_e >= necesita:
            out.append({"inicio": round(ini, 4), "fin": round(t, 4), "zoom": estado})
            estado = "lejos" if estado == "cerca" else "cerca"
            ini, ultimo_e, k = t, te, k + 1
    out.append({"inicio": round(ini, 4), "fin": round(duracion + 1, 4), "zoom": estado})
    return out


def fin_titulo_voz(palabras, titulo, cortes, cfg):
    """Si Nacho dice el título al empezar, el título se quita justo cuando termina de decirlo (así no tapa los
    subtítulos de lo que sigue). None si no lo dice al principio."""
    clave = [w for w in (_sin_signos(x) for x in (titulo or "").split()) if w and w not in DEBILES]
    if not clave or not palabras:
        return None
    tmax = cfg.get("max_seg", 5.0) + 1.0
    necesarias = max(1, round(len(clave) * 0.75))
    vistos = set()
    for p in palabras:
        if a_editado(float(p["i"]), cortes) > tmax:
            break
        w = _sin_signos(str(p.get("p", "")))
        if w in clave:
            vistos.add(w)
            if len(vistos) >= necesarias:
                fin = float(p["f"]) + 0.12
                # mínimo para que se alcance a leer
                t = fin
                while a_editado(t, cortes) < cfg.get("min_voz_seg", 1.2):
                    t += 0.05
                return round(t, 4)
    return None


def fin_titulo(cortes, duracion, cfg):
    """El título se queda hasta el primer corte después de 'min_seg' (en tiempo editado)."""
    tmin, tmax = cfg.get("min_seg", 3.0), cfg.get("max_seg", 5.0)
    for t in puntos_de_corte(cortes, duracion):
        te = a_editado(t, cortes)
        if tmin <= te <= tmax:
            return round(t, 4)
        if te > tmax:
            break
    # sin corte cerca: tiempo original equivalente a tmin
    t = 0.0
    while a_editado(t, cortes) < tmin and t < duracion:
        t += 0.05
    return round(t, 4)


# ----------------------------------------------------------------------------
# Subtítulos por frase
# ----------------------------------------------------------------------------
# palabras que no deben quedar al final de un subtítulo (se van al siguiente)
DEBILES = {"a", "al", "ante", "con", "contra", "de", "del", "desde", "en", "entre", "hacia", "hasta", "para", "por",
           "sin", "sobre", "tras", "el", "la", "los", "las", "lo", "un", "una", "unos", "unas", "y", "e", "o", "u",
           "ni", "que", "se", "su", "sus", "mi", "mis", "tu", "tus", "nuestro", "nuestra", "nuestros", "nuestras",
           "este", "esta", "estos", "estas", "ese", "esa", "esos", "esas", "muy", "más", "mas", "tan", "como", "si",
           "no", "me", "te", "le", "les", "nos", "cuando", "donde", "porque", "pero", "sino", "aunque", "es", "son",
           "ha", "han", "hay", "fue", "era", "cada", "todo", "toda", "todos", "todas", "otro", "otra"}
# palabras que suelen empezar una idea nueva (buen lugar para cortar ANTES de ellas)
INICIOS = {"y", "pero", "porque", "que", "como", "sino", "cuando", "donde", "aunque", "mientras", "pues", "entonces",
           "incluso", "es", "ya", "sin", "o"}


def _sin_signos(p):
    return re.sub(r"[^\wáéíóúüñ]", "", p.lower())


def puntuar_con_ia(palabras, ia):
    """Pide al modelo local que corrija la puntuación (¿? ¡! . ,) sin cambiar palabras, y la copia a la
    transcripción. Whisper a veces junta oraciones o no marca las preguntas."""
    if not ia or not ia.disponible or len(palabras) < 8:
        return palabras
    import difflib
    out = [dict(p) for p in palabras]
    bloque = 220
    cambios = 0
    for a in range(0, len(out), bloque):
        trozo = out[a:a + bloque]
        texto = " ".join(p["p"] for p in trozo)
        prompt = (
            "Corrige SOLO la puntuación de esta transcripción en español de un video hablado: separa las oraciones "
            "con punto, marca las preguntas con ¿ ? y las exclamaciones con ¡ !, y pon comas donde haga falta. "
            "NO cambies, agregues, quites ni reordenes palabras. Respeta mayúsculas de nombres propios.\n"
            "Responde SOLO JSON: {\"texto\": \"...\"}\n\n" + texto)
        try:
            nuevo = str(ia.json(prompt).get("texto", "")).split()
        except Exception as e:
            ed.log(f"No pude corregir la puntuación ({e})")
            continue
        base = [ed.solo_letras(p["p"]) for p in trozo]
        nueva = [ed.solo_letras(w) for w in nuevo]
        sm = difflib.SequenceMatcher(None, base, nueva, autojunk=False)
        if sm.ratio() < 0.9:
            ed.log("El modelo cambió demasiadas palabras; dejo la puntuación de whisper en ese tramo")
            continue
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag != "equal":
                continue
            for d in range(i2 - i1):
                w_old, w_new = trozo[i1 + d]["p"], nuevo[j1 + d]
                if w_old != w_new:
                    trozo[i1 + d]["p"] = w_new
                    cambios += 1
    if cambios:
        ed.log(f"Puntuación corregida en {cambios} palabras")
    return out


def agrupar_frases(palabras, cfg):
    """Subtítulos por idea: corta en la puntuación (separa cada pregunta), en las pausas y antes de 'y', 'pero',
    'porque'...; nunca deja 'el', 'de', 'que'... al final de un subtítulo. Máximo ~2 renglones."""
    max_car = cfg.get("max_caracteres", 42)
    ideal = cfg.get("caracteres_ideal", 26)
    n = len(palabras)
    if not n:
        return []

    def corte(k):
        """Puntos por cortar entre la palabra k y la k+1 (muy negativo = no cortar ahí)."""
        a, b = palabras[k]["p"], palabras[k + 1]["p"]
        hueco = palabras[k + 1]["i"] - palabras[k]["f"]
        pts = min(1.0, max(0.0, hueco) / 0.45) * 60
        if fin_oracion(a) or b[:1] in "¿¡":
            pts += 120
        elif COMA.search(a):
            pts += 55
        elif _sin_signos(b) in INICIOS:
            pts += 35
        if _sin_signos(a) in DEBILES and not re.search(r"[.,;:!?…]$", a):
            pts -= 90
        if a[:1].isupper() and b[:1].isupper() and not re.search(r"[.,;:!?…]$", a):
            pts -= 80  # no partir un nombre propio (Anne / Hathaway)
        return pts

    def forzado(k):
        a, b = palabras[k]["p"], palabras[k + 1]["p"]
        hueco = palabras[k + 1]["i"] - palabras[k]["f"]
        return fin_oracion(a) or b[:1] in "¿¡" or hueco > cfg.get("pausa_forzada_seg", 0.7)

    largo = lambda i, j: len(" ".join(p["p"] for p in palabras[i:j]))
    # programación dinámica: mejor forma de partir palabras[0:j]
    mejor = [(-1e18, -1)] * (n + 1)
    mejor[0] = (0.0, -1)
    for j in range(1, n + 1):
        for i in range(j - 1, -1, -1):
            L = largo(i, j)
            if L > max_car and j - i > 1:
                break
            if i < j - 1 and any(forzado(k) for k in range(i, j - 1)):
                break  # un grupo no puede cruzar el fin de una oración o una pausa larga
            if mejor[i][0] <= -1e17:
                continue
            v = mejor[i][0] - 30 - abs(L - ideal) * 0.8
            if L < 10:
                v -= 35
            if j < n:
                v += corte(j - 1)
            if v > mejor[j][0]:
                mejor[j] = (v, i)
    cortes, j = [], n
    while j > 0:
        i = mejor[j][1]
        cortes.append((i, j))
        j = i
    grupos = [palabras[i:j] for i, j in reversed(cortes)]
    out = []
    for k, g in enumerate(grupos):
        fin = g[-1]["f"] + 0.1
        if k + 1 < len(grupos):
            fin = min(fin, grupos[k + 1][0]["i"])
        out.append({"i": g[0]["i"], "f": round(fin, 3), "palabras": g})
    return out


def partir_en_titulo(grupos, t_fin):
    """El subtítulo que empieza durante el título y termina después: se queda solo con las palabras que se
    dicen ya sin título (antes se perdía completo). Los que caen todo dentro del título no se muestran."""
    if not t_fin:
        return grupos
    out = []
    for g in grupos:
        if g["i"] < t_fin - 0.05 < g["f"]:
            resto = [p for p in g.get("palabras", []) if p["i"] >= t_fin - 0.15]
            if resto:
                out.append(dict(g, i=round(max(t_fin, resto[0]["i"]), 3), palabras=resto))
            continue
        out.append(g)
    return out


class SubtitulosFrase:
    """Texto blanco con contorno negro y sombra, centrado, sin palabra resaltada."""

    def __init__(self, grupos, cfg, W, H):
        self.grupos = sorted(grupos, key=lambda g: g["i"])
        self.cfg, self.W, self.H = cfg, W, H
        self.f = ImageFont.truetype(str(ed.ruta(cfg["fuente"])), cfg["tam"])
        self.cache = {}

    def activo(self, t):
        """El subtítulo que va en t (si dos se enciman, el que empezó al último)."""
        elegido = None
        for gi, g in enumerate(self.grupos):
            if g["i"] <= t < g["f"]:
                elegido = gi
            elif g["i"] > t + 30:
                break
        return elegido

    def _lineas(self, texto, f, ancho):
        palabras, lineas, act = texto.split(), [], ""
        for p in palabras:
            prueba = (act + " " + p).strip()
            if act and f.getlength(prueba) > ancho:
                lineas.append(act)
                act = p
            else:
                act = prueba
        if act:
            lineas.append(act)
        # equilibra dos renglones (evita uno muy largo y otro de una palabra)
        if len(lineas) == 2:
            todas = texto.split()
            mejor = None
            for k in range(1, len(todas)):
                a, b = " ".join(todas[:k]), " ".join(todas[k:])
                wa, wb = f.getlength(a), f.getlength(b)
                if wa <= ancho and wb <= ancho:
                    d = abs(wa - wb) + (0 if wa >= wb else 40)  # mejor el primero un poco más largo
                    if mejor is None or d < mejor[0]:
                        mejor = (d, [a, b])
            if mejor:
                lineas = mejor[1]
        return lineas

    def imagen(self, gi):
        if gi in self.cache:
            return self.cache[gi]
        cfg = self.cfg
        texto = " ".join(p["p"] for p in self.grupos[gi]["palabras"])
        if cfg.get("mayusculas", True):
            texto = texto.upper()
        f = self.f
        ancho = cfg["ancho_max"]
        tam = cfg["tam"]
        pals = self.grupos[gi]["palabras"]
        if any(p.get("salto") for p in pals[:-1]):
            # renglones que puso el usuario (Shift+Enter): se respetan; si uno no cabe, se achica la letra
            lineas, act = [], []
            for p in pals:
                act.append(p["p"].upper() if cfg.get("mayusculas", True) else p["p"])
                if p.get("salto"):
                    lineas.append(" ".join(act))
                    act = []
            if act:
                lineas.append(" ".join(act))
            while max(f.getlength(ln) for ln in lineas) > ancho and tam > cfg.get("tam_min", 56):
                tam -= 4
                f = ImageFont.truetype(str(ed.ruta(cfg["fuente"])), tam)
        else:
            lineas = self._lineas(texto, f, ancho)
            while len(lineas) > cfg.get("max_lineas", 2) and tam > cfg.get("tam_min", 56):
                tam -= 4
                f = ImageFont.truetype(str(ed.ruta(cfg["fuente"])), tam)
                lineas = self._lineas(texto, f, ancho)
        paso = tam * cfg.get("interlineado", 1.1)
        cx, cy = cfg["centro"]
        c = cfg.get("contorno", 4)
        sx, sy = cfg.get("sombra", [3, 4])
        capa = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
        sombra = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
        d, ds = ImageDraw.Draw(capa), ImageDraw.Draw(sombra)
        y0 = cy - paso * (len(lineas) - 1) / 2
        for k, ln in enumerate(lineas):
            y = y0 + k * paso
            ds.text((cx + sx, y + sy), ln, font=f, anchor="mm", fill=(0, 0, 0, 255), stroke_width=c,
                    stroke_fill=(0, 0, 0, 255))
            d.text((cx, y), ln, font=f, anchor="mm", fill=ed.hex_rgb(cfg["color"]), stroke_width=c,
                   stroke_fill=ed.hex_rgb(cfg["color_contorno"]))
        sombra = sombra.filter(ImageFilter.GaussianBlur(cfg.get("sombra_difusa", 2)))
        a = np.array(sombra)
        a[:, :, 3] = (a[:, :, 3] * cfg.get("sombra_opacidad", 0.7)).astype(np.uint8)
        sombra = Image.fromarray(a)
        sombra.alpha_composite(capa)
        sup = ed.a_superposicion(sombra)
        self.cache[gi] = sup
        return sup


CORTAS = {"a", "al", "de", "del", "el", "la", "las", "los", "lo", "en", "y", "e", "o", "u", "que", "un", "una",
          "con", "por", "para", "se", "su", "sus", "mi", "tu", "no", "es", "ni", "le", "les", "me", "te", "nos"}


def repartir_lineas(palabras, f, ancho, max_lineas):
    """Reparte las palabras en el menor número de renglones, parejos y sin dejar 'a', 'de', 'el'... al final."""
    n = len(palabras)
    mejor = None
    for lineas_n in range(1, min(max_lineas, n) + 1):
        def cortes_posibles(inicio, quedan):
            if quedan == 1:
                yield [palabras[inicio:]]
                return
            for k in range(inicio + 1, n - quedan + 2):
                for resto in cortes_posibles(k, quedan - 1):
                    yield [palabras[inicio:k]] + resto
        for op in cortes_posibles(0, lineas_n):
            txt = [" ".join(x) for x in op]
            anchos = [f.getlength(x) for x in txt]
            if max(anchos) > ancho:
                continue
            pena = max(anchos) - min(anchos)
            pena += sum(400 for x in op[:-1] if ed.solo_letras(x[-1]) in CORTAS)
            pena += 300 if len(op[-1]) == 1 and len(op) > 1 and len(op[-1][0]) <= 3 else 0
            if mejor is None or pena < mejor[0]:
                mejor = (pena, txt, any(ed.solo_letras(x[-1]) in CORTAS for x in op[:-1]))
        if mejor:
            return mejor[1], mejor[2]
    return None, False


# ----------------------------------------------------------------------------
# «Tiktoks Yair»: título en dos cuadros (arriba naranja con letra negra, abajo rojo con letra blanca)
# ----------------------------------------------------------------------------
def es_yair(pl):
    return (pl.get("titulo") or {}).get("tipo") == "dos_cuadros"


def partes_titulo(titulo):
    """«TIEMBLA SALINAS – VAN CONTRA GRANJAS DE BOTS» -> ("TIEMBLA SALINAS", "VAN CONTRA GRANJAS DE BOTS").
    Sirve el guion largo (–, —) o el corto (-) con espacios. Sin guion, todo va en el cuadro de arriba."""
    t = (titulo or "").strip()
    m = re.search(r"\s+[–—-]+\s+|[–—]", t)
    if not m:
        return t, ""
    return t[:m.start()].strip(), t[m.end():].strip()


def _cuadro_titulo(cfg, caja, texto, W, H):
    """Un cuadro del título (capa transparente del tamaño del cuadro) con el texto ajustado a lo ancho."""
    if not texto:
        return None
    fuente = str(ed.ruta(cfg["fuente"]))
    x, ancho = cfg.get("x", 150), cfg.get("ancho", 780)
    y, alto = caja["y"], caja["alto"]
    texto = texto.upper() if cfg.get("mayusculas", True) else texto
    # tamaño para que las mayúsculas midan alto_letra; si no cabe a lo ancho, más chico
    prueba = ImageFont.truetype(fuente, 100)
    cap100 = prueba.getbbox("H")[3] - prueba.getbbox("H")[1]
    tam = max(20, int(round(100 * cfg.get("alto_letra", 76) / max(1, cap100))))
    libre = ancho - 2 * cfg.get("relleno_x", 34)
    ex = cfg.get("escala_x", 1.04)   # en Photoshop la letra sale un poco más ancha
    while tam > 20:
        f = ImageFont.truetype(fuente, tam)
        b = f.getbbox(texto)
        if (b[2] - b[0]) * ex + cfg.get("inclinacion", 0.0) * cap100 * tam / 100 <= libre:
            break
        tam -= 2
    f = ImageFont.truetype(fuente, tam)
    cap = f.getbbox("H")[3] - f.getbbox("H")[1]
    capa = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(capa)
    d.rectangle([x, y, x + ancho - 1, y + alto - 1], fill=ed.hex_rgb(caja["fondo"]))
    # el texto se dibuja aparte y se estira a lo ancho (escala_x), centrado en el cuadro
    b = f.getbbox(texto)
    tw, th = b[2] - b[0] + 8, H
    letras = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    base = y + alto / 2 + cap / 2
    ImageDraw.Draw(letras).text((4 - b[0], base), texto, font=f, anchor="ls", fill=ed.hex_rgb(caja["color"]))
    nw = max(1, int(round(tw * ex)))
    letras = letras.resize((nw, th), Image.LANCZOS)
    k = cfg.get("inclinacion", 0.0)   # letra cursiva, como en Photoshop (inclinación hacia la derecha)
    if k:
        extra = int(abs(k) * th) + 2
        ancho_n = nw + extra
        # cada fila se recorre a la derecha según su altura sobre la línea base
        letras = letras.transform((ancho_n, th), Image.AFFINE, (1, k, -k * base, 0, 1, 0), resample=Image.BICUBIC)
        nw_vis = nw
    else:
        nw_vis = nw
    # la inclinación recorre la parte de arriba de las letras: se compensa para que se vea centrado
    capa.alpha_composite(letras, (int(round(x + ancho / 2 - nw_vis / 2 - k * cap / 2)), 0))
    return ed.a_superposicion(capa)


# Movimiento de los cuadros del título, medido cuadro a cuadro en los videos de ejemplo (px a 1080 de ancho,
# respecto a su lugar final). Desde la derecha entra con rebote; desde la izquierda, frenando suave.
_MOV_DERECHA = ([0.033, 0.067, 0.10, 0.133, 0.167, 0.20, 0.233, 0.267, 0.30, 0.333, 0.367, 0.40, 0.433, 0.467,
                 0.50, 0.533, 0.567, 0.60, 0.633, 0.667, 0.70],
                [545, 142, 46, -14, -44, -40, -24, -5, 10, 16, 12, 5, -2, -4, -4, -2, 0, 2, 2, 1, 0])
_MOV_IZQUIERDA = ([0.10, 0.133, 0.167, 0.20, 0.233, 0.267, 0.30, 0.333, 0.367, 0.40, 0.433, 0.467, 0.50, 0.533,
                   0.567, 0.60, 0.633, 0.667, 0.70, 0.733, 0.767, 0.80],
                  [-920, -265, -222, -186, -156, -132, -112, -92, -78, -64, -52, -43, -34, -28, -22, -16, -12, -8,
                   -6, -4, -2, 0])


def desplazamiento_caja(lado, te, W):
    """Corrimiento horizontal del cuadro en el segundo te de la entrada (None = aún no aparece)."""
    ts, xs = _MOV_DERECHA if lado == "derecha" else _MOV_IZQUIERDA
    if te < ts[0] - 1e-3:
        return None
    return int(round(float(np.interp(te, ts, xs)) * W / 1080))


def capa_titulo_yair(cfg, titulo, W, H):
    """(cuadro de arriba, cuadro de abajo) como capas para ed.pegar; cualquiera puede ser None."""
    arriba, abajo = partes_titulo(titulo)
    return (_cuadro_titulo(cfg, cfg["arriba"], arriba, W, H), _cuadro_titulo(cfg, cfg["abajo"], abajo, W, H))


def _unir_capas(capas, W, H):
    lienzo = np.zeros((H, W, 3), np.float32)
    alfa = np.zeros((H, W, 1), np.float32)
    for c in capas:
        if c is None:
            continue
        bgr, a, (x0, y0, x1, y1) = c
        zona, za = lienzo[y0:y1, x0:x1], alfa[y0:y1, x0:x1]
        lienzo[y0:y1, x0:x1] = bgr * a + zona * (1 - a)
        alfa[y0:y1, x0:x1] = a + za * (1 - a)
    ys, xs = np.where(alfa[:, :, 0] > 0)
    if not len(ys):
        return None
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    return (lienzo[y0:y1, x0:x1], alfa[y0:y1, x0:x1], (int(x0), int(y0), int(x1), int(y1)))


def imagen_entrada(plan):
    """Ruta de la imagen de la entrada (momento marcado «entrada» con foto) o None."""
    for m in plan.get("momentos", []):
        if m.get("entrada") and m.get("imagenes") and not m.get("oculto"):
            return m["imagenes"][0]
    return None


def fondo_entrada(plan, pl, W, H, previa=False, lienzo_persona=None):
    """Parte de abajo de la entrada (BGR, W x alto): la imagen que se puso, o si aún no hay, un recuadro gris
    con aviso (vistas previas) / Yair desenfocado (video final)."""
    ya = (pl.get("entrada") or {}).get("alto_persona", 1201)
    alto = H - ya
    ruta_img = imagen_entrada(plan)
    if ruta_img:
        im = ed.leer_img(ruta_img)
        if im is not None:
            return ed.ajustar(im, W, alto, "cubrir", 0.5)
    if previa or lienzo_persona is None:
        g = np.full((alto, W, 3), 38, np.uint8)
        cv2.rectangle(g, (24, 24), (W - 25, alto - 25), (90, 90, 90), 3)
        img = Image.fromarray(g)
        d = ImageDraw.Draw(img)
        try:
            f = ImageFont.truetype(str(ed.ruta("assets/AkuKamu.otf")), 64)
        except Exception:
            f = None
        d.text((W / 2, alto / 2 - 30), "IMAGEN DE LA ENTRADA", font=f, anchor="mm", fill=(200, 200, 200))
        d.text((W / 2, alto / 2 + 40), "SÚBELA EN EDICIÓN · PANEL IMAGEN", font=f and ImageFont.truetype(
            str(ed.ruta("assets/AkuKamu.otf")), 40), anchor="mm", fill=(150, 150, 150))
        return np.array(img)
    abajo = cv2.resize(lienzo_persona[H - alto:], (W, alto))
    return (cv2.GaussianBlur(abajo, (0, 0), 25) * 0.55).astype(np.uint8)


def capa_vista_previa_yair(plan, pl, W, H):
    """Para las vistas previas en vivo (Edición / Subtítulos): cuadros del título + la parte de abajo de la
    entrada (imagen o aviso), como una sola capa transparente."""
    cfg = pl["titulo"]
    a, b = capa_titulo_yair(cfg, plan.get("titulo", ""), W, H)
    ya = (pl.get("entrada") or {}).get("alto_persona", 1201)
    abajo = fondo_entrada(plan, pl, W, H, previa=True).astype(np.float32)
    capa_abajo = (abajo, np.ones((H - ya, W, 1), np.float32), (0, ya, W, H))
    return _unir_capas([capa_abajo, a, b], W, H)


def capa_titulo(cfg, titulo, W, H):
    """Recuadro negro redondeado con borde blanco y el título en mayúsculas, centrado."""
    if not titulo:
        return None
    if cfg.get("tipo") == "dos_cuadros":   # «Tiktoks Yair»: los dos cuadros juntos (ya en su lugar)
        return _unir_capas(capa_titulo_yair(cfg, titulo, W, H), W, H)
    texto = titulo.upper() if cfg.get("mayusculas", True) else titulo
    fuente = str(ed.ruta(cfg["fuente"]))
    x0, x1 = cfg["caja_x"]
    pad_x, pad_y = cfg.get("relleno", [60, 100])
    ancho_txt = (x1 - x0) - 2 * pad_x
    tam, primera = cfg["tam"], None
    while tam > 60:
        f = ImageFont.truetype(fuente, tam)
        lineas, fea = repartir_lineas(texto.split(), f, ancho_txt, cfg.get("max_lineas", 4))
        if lineas and primera is None:
            primera = (tam, lineas)
        # un poco más chico si así ningún renglón termina en "a", "de", "el"...
        if lineas and (not fea or tam < cfg["tam"] * 0.7):
            if fea:
                tam, lineas = primera
            break
        tam -= 4
    else:
        tam, lineas = primera if primera else (tam, [texto])
    f = ImageFont.truetype(fuente, tam)
    paso = tam * cfg.get("interlineado", 1.08)
    cap = f.getbbox("H")[3] - f.getbbox("H")[1]
    alto_txt = paso * (len(lineas) - 1) + cap
    alto = alto_txt + 2 * pad_y
    cy = cfg.get("centro_y", 1502)
    y0, y1 = cy - alto / 2, cy + alto / 2
    capa = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(capa)
    borde = cfg.get("borde", 7)
    d.rounded_rectangle([x0, y0, x1, y1], radius=cfg.get("radio", 70), fill=ed.hex_rgb(cfg["color_caja"]),
                        outline=ed.hex_rgb(cfg["color_borde"]), width=borde)
    cxm = (x0 + x1) / 2
    base0 = cy - alto_txt / 2 + cap
    for k, ln in enumerate(lineas):
        d.text((cxm, base0 + k * paso), ln, font=f, anchor="ms", fill=ed.hex_rgb(cfg["color"]))
    return ed.a_superposicion(capa)


# ----------------------------------------------------------------------------
# Momentos con imagen
# ----------------------------------------------------------------------------
def elegir_momentos(palabras, cortes, duracion, titulo, cfg, ia, contexto, t_titulo):
    """Muy pocas imágenes: solo cuando se nombra a alguien o algo concreto y reconocible."""
    if not palabras or not ia or not ia.disponible:
        return []
    fr = ed.frases(palabras, pausa=0.5)
    maximo = max(1, int(duracion // cfg.get("cada_seg", 40)))
    lineas = "\n".join(f"{k}. {f['texto']}" for k, f in enumerate(fr))
    prompt = (
        "Eres editor de videos motivacionales cortos (TikTok) de un conductor mexicano. Casi todo el video es él "
        "hablando a cámara; solo de vez en cuando aparece una FOTO a pantalla completa por unos 3 segundos.\n"
        f"CONTEXTO: {json.dumps(contexto, ensure_ascii=False)}\n\n"
        f"Elige entre 1 y {maximo} frases donde se NOMBRA a una persona conocida, una marca, un lugar o algo muy "
        "concreto que se reconozca en una foto (ej. 'Mr. Beast', 'Lula', 'López Obrador'). Si en una frase se "
        "enumeran varias personas, puedes elegir esa frase y dar una búsqueda por persona en 'lista'.\n"
        "NUNCA elijas ideas abstractas (valores, honestidad, éxito), ni al conductor (Nacho Rodríguez).\n"
        "Para cada una: 'palabra' = la palabra exacta de la frase donde empieza la mención; 'busqueda' con el nombre "
        "completo bien escrito; 'claves' = 1 a 3 palabras que deben aparecer en la página de una foto correcta.\n"
        "Responde SOLO JSON: {\"momentos\": [{\"frase\": numero, \"palabra\": \"...\", \"que_mostrar\": \"...\", "
        "\"busqueda\": \"...\", \"claves\": [\"...\"], \"lista\": [{\"busqueda\": \"...\", \"claves\": [\"...\"]}]}]}\n\n"
        f"Título: {titulo}\n\nFrases:\n{lineas}"
    )
    res = {}
    for _ in range(2):
        try:
            res = ia.json(prompt)
            if res.get("momentos"):
                break
        except Exception as e:
            ed.log(f"El modelo no respondió bien al elegir momentos ({e})")
    puntos = puntos_de_corte(cortes, duracion)
    dmin, dmax = cfg.get("duracion_min", 2.5), cfg.get("duracion_max", 3.5)
    momentos = []
    for m in res.get("momentos", []) if isinstance(res, dict) else []:
        try:
            k = int(m.get("frase", -1))
        except (TypeError, ValueError):
            continue
        if not (0 <= k < len(fr)):
            continue
        b = str(m.get("busqueda", "")).strip()
        if not b or "nacho" in b.lower():
            continue
        # inicio: la palabra de la mención (si la encontramos) o el inicio de la frase
        pal = ed.solo_letras(str(m.get("palabra", "")))
        ini = fr[k]["i"]
        if pal:
            for p in palabras:
                if fr[k]["i"] - 0.01 <= p["i"] <= fr[k]["f"] and ed.solo_letras(p["p"]) == pal:
                    ini = p["i"]
                    break
        cerca = [t for t in puntos if ini - 1.0 <= t <= ini + 0.3]
        if cerca:
            ini = min(cerca, key=lambda t: abs(t - ini))
        ini = max(ini, t_titulo)
        partes = []
        lista = m.get("lista") if isinstance(m.get("lista"), list) else []
        for x in lista:
            if isinstance(x, dict) and str(x.get("busqueda", "")).strip():
                partes.append(x)
        if not partes:
            partes = [{"busqueda": b, "claves": m.get("claves") or []}]
        partes = partes[:4]
        largo = dmin if len(partes) > 1 else (dmin + dmax) / 2
        fin_obj = ini + largo * len(partes)
        fin = fin_obj
        # termina en un corte cercano si hay
        fines = [t for t in puntos if fin_obj - 0.6 <= t <= fin_obj + 0.8]
        if fines:
            fin = min(fines, key=lambda t: abs(t - fin_obj))
        fin = min(fin, duracion - 0.5)
        if fin - ini < dmin * 0.8:
            continue
        if any(ini < x["fin"] and fin > x["inicio"] for x in momentos):
            continue
        claves = [str(c).strip() for c in (partes[0].get("claves") or []) if str(c).strip()][:3]
        momentos.append({
            "inicio": round(ini, 3), "fin": round(fin, 3), "estilo": "completa",
            "busqueda": b, "busquedas": [b], "que_mostrar": str(m.get("que_mostrar", b)),
            "texto": fr[k]["texto"], "claves": claves, "tema": (contexto or {}).get("tema", ""),
            "partes": [{"busqueda": str(x["busqueda"]).strip(),
                        "claves": [str(c).strip() for c in (x.get("claves") or []) if str(c).strip()][:3]}
                       for x in partes],
            "imagenes": []})
    momentos.sort(key=lambda x: x["inicio"])
    ed.log(f"{len(momentos)} momentos con imagen")
    return momentos[:maximo + 2]


def buscar_imagenes_momentos(momentos, cfg, trabajo, ia):
    """Una imagen por parte (si se enumeran varias personas, una de cada una)."""
    for i, m in enumerate(momentos, 1):
        ed.Progreso.paso(0.62 + 0.36 * (i - 1) / max(1, len(momentos)), f"Buscando imágenes ({i} de {len(momentos)})")
        imgs = []
        for j, parte in enumerate(m.get("partes") or [{"busqueda": m["busqueda"], "claves": m.get("claves")}]):
            r = ed.buscar_imagenes([parte["busqueda"]], 1, Path(trabajo) / "imagenes", f"momento{i:02d}_{j + 1}", ia,
                                   m.get("que_mostrar", "") if len(m.get("partes", [])) <= 1 else parte["busqueda"],
                                   cfg.get("max_candidatos", 8), cfg.get("puntaje_min", 7),
                                   claves=parte.get("claves"), contexto=m.get("tema", ""))
            imgs += r
        m["imagenes"] = imgs
        ed.log(f"Momento {i} ({m['inicio']:.1f}-{m['fin']:.1f}s) '{m['busqueda']}': {len(imgs)} imágenes")


def elegir_dramaticas(palabras, ia, contexto, duracion, cfg):
    """Fines de oración donde conviene una pausa larga (las frases más contundentes)."""
    finales = [p for p in palabras if fin_oracion(p["p"])]
    elegidas = []
    if finales:
        elegidas.append(finales[-1]["f"])  # el remate del video
    if not ia or not ia.disponible or len(finales) < 3:
        return elegidas
    n = max(1, int(duracion // cfg.get("dramaticas_cada_seg", 45)))
    oraciones, act = [], []
    for p in palabras:
        act.append(p)
        if fin_oracion(p["p"]):
            oraciones.append(act)
            act = []
    lineas = "\n".join(f"{k}. {' '.join(x['p'] for x in o)}" for k, o in enumerate(oraciones))
    prompt = (
        "Eres editor de videos motivacionales. En el video se deja una pausa dramática (silencio de casi un segundo) "
        f"después de las oraciones más contundentes o emotivas. Elige las {n} oraciones que más lo merecen "
        "(remates, conclusiones fuertes, frases para reflexionar). No elijas oraciones que solo dan contexto.\n"
        "Responde SOLO JSON: {\"oraciones\": [numero, ...]}\n\n" + lineas)
    try:
        res = ia.json(prompt)
        for k in res.get("oraciones", [])[:n]:
            k = int(k)
            if 0 <= k < len(oraciones):
                elegidas.append(oraciones[k][-1]["f"])
    except Exception as e:
        ed.log(f"No pude elegir las pausas dramáticas ({e})")
    return sorted(set(elegidas))


# ----------------------------------------------------------------------------
# Análisis
# ----------------------------------------------------------------------------
def analizar(args, video, pl, pl_path, trabajo):
    fps, n, w, h = ed.info_video(video)
    info = {"fps": fps, "cuadros": n, "ancho": w, "alto": h, "duracion": n / fps if fps else 0,
            "audio": ed.tiene_audio(video)}
    ed.Progreso.paso(0.0, "Buscando la cara")
    pista = pista_rostro(video, info)

    if args.transcripcion:
        palabras = ed.limpiar_transcripcion(ed.cargar_json(args.transcripcion))
    elif args.sin_subtitulos or not info["audio"]:
        palabras = []
    else:
        palabras = ed.transcribir(video, args.whisper_modelo, args.dispositivo)

    ed.Progreso.paso(0.48, "Entendiendo el tema del video")
    ia = None if args.sin_ia else ed.IA(args.url_ollama, args.modelo_ollama,
                                        "none" if args.sin_verificar or not ed.IMAGENES_AUTOMATICAS
                                        else args.modelo_vision)
    contexto = ed.analizar_tema(palabras, args.titulo, ia)
    ed.aplicar_correcciones(palabras, contexto.get("correcciones"))
    if palabras and pl["subtitulos"].get("puntuar_con_ia", True):
        ed.Progreso.paso(0.52, "Corrigiendo la puntuación")
        palabras = puntuar_con_ia(palabras, ia)
    ed.guardar_json(trabajo / "transcripcion.json", palabras)
    if (trabajo / "subtitulos.json").exists():
        (trabajo / "subtitulos.json").unlink()

    ed.Progreso.paso(0.54, "Recortando pausas")
    cfg_c = pl.get("cortes", {})
    dram = elegir_dramaticas(palabras, ia, contexto, info["duracion"], cfg_c) if palabras else []
    cortes = [] if args.sin_cortes else calcular_cortes(video, info, palabras, cfg_c, dram)
    encuadres = plan_encuadres(cortes, info["duracion"], pl.get("encuadre", {}), palabras,
                               silencios_cortos(video, pl["encuadre"]) if pl.get("encuadre", {}).get("max_sin_cambio_seg")
                               else None)
    t_titulo = fin_titulo_voz(palabras, args.titulo, cortes, pl["titulo"]) or fin_titulo(cortes, info["duracion"], pl["titulo"])

    cfg_m = pl["momentos"]
    if args.imagenes or args.sin_web or not ed.IMAGENES_AUTOMATICAS:
        momentos = []   # sin imágenes automáticas: se agregan a mano en la pestaña Edición
        if not ed.IMAGENES_AUTOMATICAS:
            ed.log("Sin imágenes automáticas: agrégalas a mano en la pestaña Edición si hacen falta")
        elif args.imagenes:
            ed.log("Con estilo motivacional las imágenes propias se agregan desde la interfaz, en cada momento")
    else:
        ed.Progreso.paso(0.58, "Eligiendo dónde van las imágenes")
        momentos = elegir_momentos(palabras, cortes, info["duracion"], args.titulo, cfg_m, ia, contexto, t_titulo)
        buscar_imagenes_momentos(momentos, cfg_m, trabajo, ia)
        sin = [m for m in momentos if not m["imagenes"]]
        if sin:
            ed.log(f"{len(sin)} momentos se quedan sin imagen porque no encontré fotos correctas")
        momentos = [m for m in momentos if m["imagenes"]]

    if es_yair(pl) and args.titulo:
        # espacio para la imagen de la entrada (abajo, mientras está el título): se pone a mano en Edición
        momentos.insert(0, {"inicio": 0.0, "fin": round(t_titulo, 3), "estilo": "completa", "entrada": True,
                            "busqueda": "Imagen de la entrada", "busquedas": [], "que_mostrar": "", "texto": "",
                            "imagenes": [], "prioridad": "imagen"})
    plan = {
        "estilo": "motivacional",
        "video": str(video),
        "plantilla": str(pl_path),
        "titulo": args.titulo,
        "titulo_fin": t_titulo,
        "info": info,
        "contexto": contexto,
        "cara": pista,
        "encuadres": encuadres,
        "pausas_dramaticas": dram,
        "tomas": [{"inicio": 0.0, "fin": info["duracion"], "layout": "persona"}],
        "proyeccion": [],
        "momentos": momentos,
        "cortes": cortes,
    }
    ed.guardar_json(trabajo / "plan.json", plan)
    ed.log(f"Plan guardado en {trabajo / 'plan.json'}")
    ed.Progreso.paso(1.0, "Análisis terminado")
    return trabajo


# ----------------------------------------------------------------------------
# Render
# ----------------------------------------------------------------------------
def escena_en(plan, pl, t):
    """Qué se ve en el tiempo t (original) para el editor de encuadre: la ventana automática de Nacho
    o {tipo: imagen} durante los momentos con imagen."""
    info = plan["info"]
    W, H = pl["salida"]["ancho"], pl["salida"]["alto"]
    cortes = sorted(plan.get("cortes", []), key=lambda c: c["inicio"])
    te = a_editado(t, cortes)
    for k, m in enumerate(plan.get("momentos", [])):
        if m.get("entrada"):
            continue   # la imagen de la entrada va abajo, Yair sigue arriba
        if m.get("imagenes") and not m.get("oculto") and a_editado(m["inicio"], cortes) - 1e-6 <= te < a_editado(m["fin"], cortes):
            return {"tipo": "imagen", "mom": k, "pv": -1}
    z = "cerca"
    for e in plan.get("encuadres") or [{"inicio": 0, "fin": 1e9, "zoom": "cerca"}]:
        if e["inicio"] - 1e-6 <= t < e["fin"]:
            z = e["zoom"]
            break
    if t < plan.get("titulo_fin", 3.0) and plan.get("titulo"):
        z = "titulo"
    pista = plan.get("cara") or [[0.0, info["ancho"] / 2, info["alto"] * 0.35, info["alto"] * 0.25, info["alto"] * 0.33]]
    pista = plan.get("_pista_fija") or pista_fija_moti(plan, pl, pista)
    if z == "titulo" and es_yair(pl):   # entrada: Yair arriba con su propio encuadre
        alto_p = (pl.get("entrada") or {}).get("alto_persona", 1201)
        auto = recorte_entrada(cara_en(pista, 0.0), info["ancho"], info["alto"], W, H, pl)
        return {"tipo": "dividida", "region": [0.0, 0.0, float(info["ancho"]), float(info["alto"])],
                "aspect": W / alto_p, "auto": [float(v) for v in auto], "mom": -1, "pv": -1}
    auto = recorte(cara_en(pista, t), z, info["ancho"], info["alto"], W, H, pl.get("encuadre", {}))
    return {"tipo": "persona", "region": [0.0, 0.0, float(info["ancho"]), float(info["alto"])], "aspect": W / H,
            "auto": [float(v) for v in auto], "mom": -1, "pv": -1}


def girar_entrada(fondo, nuevo, p, cfg):
    """El cuadro nuevo entra desde la derecha, girando sobre su esquina superior izquierda. p de 0 a 1."""
    if p >= 1:
        return nuevo
    H, W = fondo.shape[:2]
    e = 1 - (1 - p) ** 2.2 if p > 0 else 0.0
    ang = cfg.get("angulo", 40) * (1 - e)
    x_tl = W * (1 - e)
    a = math.radians(ang)
    # (u, v) -> (x_tl + u·cos + v·sen, -u·sen + v·cos): el borde izquierdo baja inclinado hacia la derecha
    M = np.float32([[math.cos(a), math.sin(a), x_tl], [-math.sin(a), math.cos(a), 0]])
    capa = cv2.warpAffine(nuevo, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    masc = cv2.warpAffine(np.full((H, W), 255, np.uint8), M, (W, H), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT)
    m = (masc.astype(np.float32) / 255.0)[:, :, None]
    return (capa * m + fondo * (1 - m)).astype(np.uint8)


def render(args, trabajo, plan, pl):
    info = plan["info"]
    W, H = pl["salida"]["ancho"], pl["salida"]["alto"]
    fps = info["fps"]
    salida = Path(args.salida) if args.salida else trabajo / (Path(plan["video"]).stem + "_vertical.mp4")
    cortes = sorted(plan.get("cortes", []), key=lambda c: c["inicio"])
    encuadres = plan.get("encuadres") or [{"inicio": 0, "fin": 1e9, "zoom": "cerca"}]
    pista = plan.get("cara") or [[0.0, info["ancho"] / 2, info["alto"] * 0.35, info["alto"] * 0.25, info["alto"] * 0.33]]
    pista = pista_fija_moti(plan, pl, pista)  # tomas fijas: el encuadre no persigue a Nacho
    cfg_e = pl.get("encuadre", {})
    cfg_tr = pl.get("transicion", {})
    t_tr = cfg_tr.get("duracion_seg", 0.12)
    manual = plan.get("encuadre_manual") or []

    titulo = capa_titulo(pl["titulo"], plan.get("titulo", ""), W, H)
    t_titulo = plan.get("titulo_fin", 3.0)
    yair = es_yair(pl)
    tit_yair = capa_titulo_yair(pl["titulo"], plan.get("titulo", ""), W, H) if yair else (None, None)
    palabras = ed.cargar_json(trabajo / "transcripcion.json") if (trabajo / "transcripcion.json").exists() else []
    grupos = ed.sin_cortados(ed.grupos_subtitulos(trabajo, palabras, pl["subtitulos"]), cortes)
    if titulo is not None:
        grupos = partir_en_titulo(grupos, t_titulo)
    por_frase = pl["subtitulos"].get("modo") == "frases"
    if por_frase:
        subs = SubtitulosFrase(grupos, pl["subtitulos"], W, H)
    else:   # palabra por palabra, como Clips Chapuceros («Tiktoks Yair»)
        subs = ed.Subtitulos(grupos, pl["subtitulos"])
        area_subs = ((pl.get("layouts") or {}).get("persona") or {}).get("subtitulos", {}).get("area", [40, 1490, 860, 200])

    momentos = sorted([m for m in plan.get("momentos", []) if m.get("imagenes") and not m.get("oculto")
                       and not m.get("entrada")], key=lambda m: m["inicio"])
    # tiempos de cada imagen en el video editado (para las transiciones)
    for m in momentos:
        m["_ei"], m["_ef"] = a_editado(m["inicio"], cortes), a_editado(m["fin"], cortes)
    cfg_m = pl["momentos"]
    cache_img = {}

    def imagen(mom, k, fase):
        p = mom["imagenes"][k]
        clave = (p, id(mom), k)
        if clave not in cache_img:
            im = ed.leer_img(p)
            if im is None:
                ed.log(f"No pude leer la imagen {p}")
                im = np.zeros((H, W, 3), np.uint8)
            e = ed.encuadre_de(mom, k, 0, cfg_m, im)
            cache_img[clave] = (ed.preparar_imagen(im, W, H, e), e)
        im, e = cache_img[clave]
        return ed.encuadrar(im, W, H, fase, e)

    def persona(frame, t):
        z = "cerca"
        for e in encuadres:
            if e["inicio"] - 1e-6 <= t < e["fin"]:
                z = e["zoom"]
                break
        if t < t_titulo and titulo is not None:
            z = "titulo"
        x0, y0, cw, ch = recorte(cara_en(pista, t), z, frame.shape[1], frame.shape[0], W, H, cfg_e)
        if manual:
            x0, y0, cw, ch = ed.ventana_manual(manual, t, [0, 0, frame.shape[1], frame.shape[0]], W / H,
                                               (x0, y0, cw, ch))
        s = W / cw
        M = np.float32([[s, 0, -x0 * s], [0, s, -y0 * s]])
        img = cv2.warpAffine(frame, M, (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        return ed.enfocar(img, cfg_e.get("nitidez", 0.3))

    cfg_ent = pl.get("entrada") or {}
    alto_p = cfg_ent.get("alto_persona", 1201)
    cfg_tit = pl.get("titulo") or {}
    abajo_cache = {}

    def ventana_entrada(frame, t):
        """Encuadre propio de la entrada (franja de arriba), con la corrección a mano si la hay."""
        src_h, src_w = frame.shape[:2]
        x0, y0, cw, ch = recorte_entrada(cara_en(pista, 0.0), src_w, src_h, W, H, pl)
        if manual:
            x0, y0, cw, ch = ed.ventana_manual(manual, t, [0, 0, src_w, src_h], W / alto_p, (x0, y0, cw, ch))
        s = W / cw
        M = np.float32([[s, 0, -x0 * s], [0, s, -y0 * s]])
        img = cv2.warpAffine(frame, M, (W, alto_p), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        return ed.enfocar(img, cfg_e.get("nitidez", 0.3))

    def entrada_yair(frame, t, te):
        lienzo = np.empty((H, W, 3), np.uint8)
        lienzo[:alto_p] = ventana_entrada(frame, t)
        if "img" not in abajo_cache:
            abajo_cache["img"] = fondo_entrada(plan, pl, W, H, previa=bool(getattr(args, "previa", False)),
                                               lienzo_persona=persona(frame, t))
        lienzo[alto_p:] = abajo_cache["img"]
        for capa, caja in zip(tit_yair, (cfg_tit.get("arriba", {}), cfg_tit.get("abajo", {}))):
            if capa is None:
                continue
            dx = desplazamiento_caja(caja.get("entra_desde", "izquierda"), te, W)
            if dx is not None:
                ed.pegar(lienzo, capa, dx, 0)
        return lienzo

    a_cfg = pl.get("audio", {})
    musica = ed.ruta(a_cfg.get("musica")) if a_cfg.get("musica") and not args.sin_musica else None
    hay_musica = bool(musica and Path(musica).exists())
    f_audio, map_audio = ed.filtro_audio(pl, info, hay_musica, cortes)

    cmd, salida, paso, tam = ed.salida_render(args, trabajo, plan, pl, W, H, fps, hay_musica, musica, f_audio,
                                              map_audio, salida)
    previa = paso > 1 or getattr(args, "previa", False)
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    vista = ed.VistaPrevia(trabajo, W, H, fps, solo_diseno=previa)

    cap = cv2.VideoCapture(plan["video"])
    idx, ci, n_out = 0, 0, 0
    total = info["cuadros"] or 1
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t = idx / fps
        idx += 1
        if idx % max(1, int(fps)) == 0:
            ed.Progreso.paso(idx / total, "Armando el video")
        while ci < len(cortes) and t >= cortes[ci]["fin"] - 1e-6:
            ci += 1
        if ci < len(cortes) and cortes[ci]["inicio"] - 1e-6 <= t < cortes[ci]["fin"] - 1e-6:
            continue
        te = n_out / fps
        n_out += 1
        if paso > 1 and (n_out - 1) % paso:
            continue   # vista previa ligera: solo se arma uno de cada «paso» cuadros

        mom = None
        for m in momentos:
            if m["_ei"] - 1e-6 <= te < m["_ef"] + t_tr:
                mom = m
                break
        if mom is None:
            lienzo = persona(frame, t)
        else:
            imgs = mom["imagenes"]
            dur = max(0.1, (mom["_ef"] - mom["_ei"]) / len(imgs))
            if te >= mom["_ef"]:
                # salida: Nacho entra girando sobre la última imagen
                fondo = imagen(mom, len(imgs) - 1, 1.0)
                lienzo = girar_entrada(fondo, persona(frame, t), (te - mom["_ef"]) / t_tr, cfg_tr)
            else:
                k = max(0, min(int((te - mom["_ei"]) // dur), len(imgs) - 1))
                local = te - mom["_ei"] - k * dur
                actual = imagen(mom, k, min(1.0, local / dur))
                if local < t_tr:
                    fondo = persona(frame, t) if k == 0 else imagen(mom, k - 1, 1.0)
                    lienzo = girar_entrada(fondo, actual, local / t_tr, cfg_tr)
                else:
                    lienzo = actual

        if t < t_titulo and yair and titulo is not None:
            # entrada de «Tiktoks Yair»: Yair arriba, imagen abajo y los dos cuadros del título entrando de lado
            lienzo = entrada_yair(frame, t, te)
            vista.escribir(lienzo, te, "titulo")
        elif t < t_titulo:
            ed.pegar(lienzo, titulo)
            vista.escribir(lienzo, te, "titulo")
        else:
            vista.escribir(lienzo, te, "frases")
            act = subs.activo(t) if not previa else None   # la vista previa va sin subtítulos (se dibujan en vivo)
            if act is not None and por_frase:
                ed.pegar(lienzo, subs.imagen(act), 0, ed.desplazamiento_subs(subs.grupos[act], H))
            elif act is not None:
                sx, sy, sw, sh = area_subs
                sy += ed.desplazamiento_subs(subs.grupos[act[0]], H)
                ed.pegar(lienzo, subs.imagen(act[0], act[1], sw, sh), sx, sy)
        try:
            ff.stdin.write((cv2.resize(lienzo, tam, interpolation=cv2.INTER_AREA) if previa else lienzo).tobytes())
        except (BrokenPipeError, OSError):  # ffmpeg se cerró (el error real sale arriba en el registro)
            break
    cap.release()
    try:
        ff.stdin.close()
    except OSError:
        pass
    if ff.wait() != 0:
        raise SystemExit("ffmpeg falló al codificar")
    return ed.cerrar_render(args, trabajo, vista, salida, fps, paso)
