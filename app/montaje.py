#!/usr/bin/env python3
"""
Montaje: cortar, copiar, pegar y mover SEGMENTOS DEL VIDEO (el contenido mismo) desde la línea de tiempo de la
pestaña Edición.

Cómo funciona:
  - El trabajo guarda en plan["montaje"] de qué pedazos del video ORIGINAL está hecho el video de trabajo actual
    ([[inicio, fin], ...] en segundos del original). Al principio es un solo pedazo: todo el video.
  - Cada operación arma la nueva lista de pedazos y el video nuevo se corta y une SIEMPRE desde el original
    (no se pierde calidad aunque se hagan muchos cambios). El video nuevo queda en la carpeta _trabajo.
  - Todo lo que está en el plan con tiempos (tomas, pantalla, imágenes, cortes de pausas, encuadres, difuminados,
    transiciones, título), la transcripción y los subtítulos se recortan y se recorren con su pedazo de video,
    así que se van junto con él.
  - El portapapeles (copiar / cortar) se guarda en la carpeta del trabajo: se puede pegar después, incluso
    después de otros cambios.
Los tiempos que recibe son del video de trabajo ACTUAL (sin quitar las pausas: «tiempo original» del plan).
"""
import copy
import json
import subprocess
import time
from pathlib import Path

MIN_SEG = 0.2   # pedazo más corto que se acepta

# listas del plan con elementos {inicio, fin, ...}
LISTAS = ("tomas", "proyeccion", "momentos", "cortes", "encuadres", "encuadre_manual", "encuadre_pantalla",
          "difuminar", "transiciones_camara", "stickers")
PISTAS = ("cara", "camino")     # dentro de un elemento: [[t, ...], ...]
PARES = ("ocultar",)            # dentro de un elemento: [[a, b], ...]


def _leer(p, defecto=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return defecto


def _escribir(p, datos):
    tmp = Path(p).with_suffix(".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


# ----------------------------------------------------------------------------
# recortar lo del plan a un tramo [a, b] y llevarlo a empezar en 0
# ----------------------------------------------------------------------------
def _pista(puntos, a, b):
    out = [[round(p[0] - a, 3)] + list(p[1:]) for p in puntos or [] if isinstance(p, (list, tuple)) and p
           and isinstance(p[0], (int, float)) and a - 2.0 <= p[0] <= b + 2.0]
    if not out and puntos:   # pista de un solo punto (cara fija): se conserva
        p = puntos[0]
        out = [[0.0] + list(p[1:])]
    return out


def _elemento(it, a, b):
    x, y = max(float(it["inicio"]), a), min(float(it["fin"]), b)
    if y - x < 0.03:
        return None
    n = copy.deepcopy(it)
    n["inicio"], n["fin"] = round(x - a, 4), round(y - a, 4)
    for k in PISTAS:
        if isinstance(n.get(k), list) and n[k] and isinstance(n[k][0], (list, tuple)):
            n[k] = _pista(n[k], a, b)
    for k in PARES:
        if isinstance(n.get(k), list):
            n[k] = [[round(max(p[0], a) - a, 3), round(min(p[1], b) - a, 3)] for p in n[k]
                    if p[1] > a and p[0] < b]
    return n


def recortar(plan, palabras, grupos, a, b):
    """Todo lo que cae en [a, b] del video actual, llevado a empezar en 0."""
    d = {"duracion": round(b - a, 4), "listas": {}}
    for k in LISTAS:
        if isinstance(plan.get(k), list):
            d["listas"][k] = [e for e in (_elemento(it, a, b) for it in plan[k]
                                          if isinstance(it, dict) and "inicio" in it and "fin" in it) if e]
    if isinstance(plan.get("cara"), list):
        d["cara"] = _pista(plan["cara"], a, b)
    tf = plan.get("titulo_fin")
    if isinstance(tf, (int, float)) and a <= tf <= b:
        d["titulo_fin"] = round(tf - a, 4)

    def dentro(p):
        m = (float(p["i"]) + float(p["f"])) / 2
        return a <= m < b

    d["palabras"] = [dict(p, i=round(max(0.0, p["i"] - a), 3), f=round(min(b, p["f"]) - a, 3)) for p in palabras or []
                     if dentro(p)]
    gs = []
    for g in grupos or []:
        ws = [dict(p, i=round(max(0.0, p["i"] - a), 3), f=round(min(b, p["f"]) - a, 3)) for p in g.get("palabras", [])
              if dentro(p)]
        if ws:
            n = dict(g, palabras=ws)
            n["i"], n["f"] = round(max(float(g["i"]), a) - a, 3), round(min(float(g["f"]), b) - a, 3)
            if n["f"] <= n["i"]:
                n["i"], n["f"] = ws[0]["i"], ws[-1]["f"]
            gs.append(n)
    d["grupos"] = gs
    return d


def _correr(d, o):
    """Recorre lo recortado para que empiece en o (segundos del video nuevo)."""
    out = {"listas": {}}
    for k, lst in d["listas"].items():
        out["listas"][k] = []
        for it in lst:
            n = copy.deepcopy(it)
            n["inicio"], n["fin"] = round(n["inicio"] + o, 4), round(n["fin"] + o, 4)
            for kk in PISTAS:
                if isinstance(n.get(kk), list) and n[kk] and isinstance(n[kk][0], list):
                    n[kk] = [[round(p[0] + o, 3)] + p[1:] for p in n[kk]]
            for kk in PARES:
                if isinstance(n.get(kk), list):
                    n[kk] = [[round(p[0] + o, 3), round(p[1] + o, 3)] for p in n[kk]]
            out["listas"][k].append(n)
    out["cara"] = [[round(p[0] + o, 3)] + p[1:] for p in d.get("cara") or []]
    out["titulo_fin"] = d["titulo_fin"] + o if "titulo_fin" in d else None
    out["palabras"] = [dict(p, i=round(p["i"] + o, 3), f=round(p["f"] + o, 3)) for p in d["palabras"]]
    out["grupos"] = [dict(g, i=round(g["i"] + o, 3), f=round(g["f"] + o, 3),
                          palabras=[dict(p, i=round(p["i"] + o, 3), f=round(p["f"] + o, 3)) for p in g["palabras"]])
                     for g in d["grupos"]]
    return out


# ----------------------------------------------------------------------------
# pedazos del original
# ----------------------------------------------------------------------------
def montaje_de(plan):
    """[[a, b], ...] del video original de los que está hecho el video actual."""
    if plan.get("montaje"):
        return [list(x) for x in plan["montaje"]]
    return [[0.0, float(plan["info"]["duracion"])]]


def a_original(montaje, a, b):
    """Tramo [a, b] del video ACTUAL -> pedazos del original."""
    out, o = [], 0.0
    for pa, pb in montaje:
        largo = pb - pa
        x, y = max(a, o), min(b, o + largo)
        if y - x > 1e-4:
            out.append([round(pa + (x - o), 4), round(pa + (y - o), 4)])
        o += largo
    return out


def armar_video(original, pedazos, salida, ed, lanzar=None):
    """Corta y une los pedazos del original en un solo video (preciso al cuadro)."""
    gpu = ed.SOLO_GPU or ed.nvenc_disponible()
    audio = ed.tiene_audio(original)
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for a, b in pedazos:
        cmd += ["-ss", f"{a:.4f}", "-t", f"{b - a:.4f}", "-i", str(original)]
    n = len(pedazos)
    if audio:
        filtro = "".join(f"[{k}:v:0][{k}:a:0]" for k in range(n)) + f"concat=n={n}:v=1:a=1[v][a]"
        mapas = ["-map", "[v]", "-map", "[a]", "-c:a", "aac", "-b:a", "256k"]
    else:
        filtro = "".join(f"[{k}:v:0]" for k in range(n)) + f"concat=n={n}:v=1:a=0[v]"
        mapas = ["-map", "[v]"]
    cmd += ["-filter_complex", filtro, *mapas,
            *(["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "16"] if gpu else
              ["-c:v", "libx264", "-preset", "veryfast", "-crf", "15"]),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(salida)]
    if lanzar:
        p = lanzar(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        _, err = p.communicate()
        ok = p.returncode == 0
        err = (err or b"").decode(errors="ignore")
    else:
        r = subprocess.run(cmd, capture_output=True, text=True)
        ok, err = r.returncode == 0, r.stderr
    if not ok:
        raise RuntimeError("No se pudo armar el video: " + (err[-300:] or "ffmpeg falló (¿cancelado?)"))
    return salida


# ----------------------------------------------------------------------------
# operaciones
# ----------------------------------------------------------------------------
def _cuadro(t, fps):
    return round(round(float(t) * fps) / fps, 4)


def _estado(trabajo, I):
    plan, palabras = I.cargar(trabajo)
    if I.estilo_de(plan) == "solo_subtitulos":
        raise ValueError("En «Solo subtítulos» no se reacomoda el video")
    grupos = I.grupos_actuales(trabajo, plan, palabras)
    return plan, palabras, grupos


def largo_editado(datos):
    """Lo que dura el pedazo ya sin las pausas recortadas (lo que se ve en la línea de tiempo)."""
    quitado = sum(max(0.0, c["fin"] - c["inicio"]) for c in datos["listas"].get("cortes", []))
    return max(0.0, datos["duracion"] - quitado)


def copiar(trabajo, a, b, I):
    """Guarda el segmento [a, b] (video actual) en el portapapeles del trabajo."""
    plan, palabras, grupos = _estado(trabajo, I)
    fps = plan["info"]["fps"] or 30
    a, b = _cuadro(max(0.0, a), fps), _cuadro(min(plan["info"]["duracion"], b), fps)
    if b - a < MIN_SEG:
        raise ValueError("El segmento es muy corto")
    clip = {"original": plan.get("video_original") or plan["video"], "pedazos": a_original(montaje_de(plan), a, b),
            "datos": recortar(plan, palabras, grupos, a, b), "fecha": time.strftime("%H:%M:%S")}
    _escribir(Path(trabajo) / "portapapeles.json", clip)
    return largo_editado(clip["datos"])


def portapapeles(trabajo):
    c = _leer(Path(trabajo) / "portapapeles.json")
    return {"duracion": largo_editado(c["datos"])} if c else None


def _aplicar(trabajo, piezas, I, ed, mensaje):
    """piezas: [(pedazos_del_original, datos_recortados)] en el orden nuevo. Arma el video y el plan nuevos."""
    plan, palabras, grupos = _estado(trabajo, I)
    original = plan.get("video_original") or plan["video"]
    pedazos = [p for pz, _ in piezas for p in pz]
    # pedazos seguidos del original se juntan (menos cortes al unir)
    unidos = []
    for p in pedazos:
        if unidos and abs(unidos[-1][1] - p[0]) < 1e-3:
            unidos[-1][1] = p[1]
        else:
            unidos.append(list(p))
    if not unidos or sum(b - a for a, b in unidos) < 1.0:
        raise ValueError("El video quedaría vacío")
    t = Path(trabajo)
    n = int(plan.get("montaje_n", 0)) + 1
    salida = t / f"montaje_{n:02d}.mp4"
    dur_orig = float(plan.get("duracion_original") or plan["info"]["duracion"])
    if len(unidos) == 1 and abs(unidos[0][0]) < 1e-3 and abs(unidos[0][1] - dur_orig) < 0.05:
        nuevo_video = original   # quedó igual que el original
    else:
        armar_video(original, unidos, salida, ed, getattr(I, "lanzar", None))
        nuevo_video = str(salida)
    # plan nuevo
    I.respaldar(trabajo)
    nuevo = {k: v for k, v in plan.items() if k not in LISTAS and k not in ("cara", "titulo_fin")}
    for k in LISTAS:
        if k in plan:
            nuevo[k] = []
    pal_n, grp_n, cara_n, tf = [], [], [], None
    o = 0.0
    for _, d in piezas:
        c = _correr(d, o)
        for k, lst in c["listas"].items():
            if k in nuevo or lst:
                nuevo.setdefault(k, []).extend(lst)
        cara_n += c["cara"]
        pal_n += c["palabras"]
        grp_n += c["grupos"]
        if tf is None and c["titulo_fin"] is not None:
            tf = c["titulo_fin"]
        o += d["duracion"]
    for k in LISTAS:
        if isinstance(nuevo.get(k), list):
            nuevo[k] = [e for e in sorted(nuevo[k], key=lambda e: e["inicio"]) if e["fin"] - e["inicio"] >= 0.03]
    # la imagen de la entrada («Tiktoks Yair») solo va al principio
    if nuevo.get("momentos"):
        nuevo["momentos"] = [m for m in nuevo["momentos"] if not m.get("entrada") or m["inicio"] < 0.01]
    # las tomas cubren todo el video, sin huecos
    if nuevo.get("tomas"):
        for x, y in zip(nuevo["tomas"], nuevo["tomas"][1:]):
            x["fin"] = y["inicio"]
        nuevo["tomas"][0]["inicio"] = 0.0
        nuevo["tomas"][-1]["fin"] = round(o, 4)
    if nuevo.get("encuadres"):
        for x, y in zip(nuevo["encuadres"], nuevo["encuadres"][1:]):
            x["fin"] = y["inicio"]
        nuevo["encuadres"][0]["inicio"] = 0.0
        nuevo["encuadres"][-1]["fin"] = round(o + 1, 4)
    if "cara" in plan:
        nuevo["cara"] = sorted(cara_n, key=lambda p: p[0]) or plan["cara"][:1]
    if "titulo_fin" in plan:
        nuevo["titulo_fin"] = tf if tf is not None else min(plan["titulo_fin"], o)
    nuevo["video_original"] = original
    nuevo["duracion_original"] = dur_orig
    nuevo["video"] = nuevo_video
    nuevo["montaje"] = unidos
    nuevo["montaje_n"] = n
    fps, cuadros, w, h = ed.info_video(nuevo_video)
    nuevo["info"] = dict(plan["info"], fps=fps, cuadros=cuadros, duracion=cuadros / fps if fps else o)
    I.guardar_plan(trabajo, nuevo)
    ed.guardar_json(t / "transcripcion.json", sorted(pal_n, key=lambda p: p["i"]))
    ed.guardar_json(t / "subtitulos.json", sorted(grp_n, key=lambda g: g["i"]))
    return mensaje


def _pieza_actual(plan, palabras, grupos, a, b):
    return (a_original(montaje_de(plan), a, b), recortar(plan, palabras, grupos, a, b))


def cortar(trabajo, a, b, I, ed):
    """Quita el segmento [a, b] del video y lo deja en el portapapeles (para pegarlo en otro lugar)."""
    copiar(trabajo, a, b, I)
    plan, palabras, grupos = _estado(trabajo, I)
    fps, dur = plan["info"]["fps"] or 30, plan["info"]["duracion"]
    a, b = _cuadro(max(0.0, a), fps), _cuadro(min(dur, b), fps)
    piezas = [x for x in (_pieza_actual(plan, palabras, grupos, 0.0, a) if a > 0.01 else None,
                          _pieza_actual(plan, palabras, grupos, b, dur) if dur - b > 0.01 else None) if x]
    largo = largo_editado(_leer(Path(trabajo) / "portapapeles.json")["datos"])
    return _aplicar(trabajo, piezas, I, ed, f"Segmento cortado ({largo:.1f} s). Pégalo con Ctrl+V donde esté el cursor.")


def pegar(trabajo, p, I, ed):
    """Pega lo del portapapeles en el punto p del video actual (lo que sigue se recorre)."""
    clip = _leer(Path(trabajo) / "portapapeles.json")
    if not clip:
        raise ValueError("No hay un segmento copiado (selecciónalo con Shift + arrastrar y Ctrl+C o Ctrl+X)")
    plan, palabras, grupos = _estado(trabajo, I)
    if (clip.get("original") or "") != (plan.get("video_original") or plan["video"]):
        raise ValueError("El segmento copiado es de otro video")
    fps, dur = plan["info"]["fps"] or 30, plan["info"]["duracion"]
    p = _cuadro(min(max(0.0, p), dur), fps)
    piezas = []
    if p > 0.01:
        piezas.append(_pieza_actual(plan, palabras, grupos, 0.0, p))
    piezas.append((clip["pedazos"], clip["datos"]))
    if dur - p > 0.01:
        piezas.append(_pieza_actual(plan, palabras, grupos, p, dur))
    return _aplicar(trabajo, piezas, I, ed, f"Segmento pegado ({largo_editado(clip['datos']):.1f} s).")


def mover(trabajo, a, b, p, I, ed):
    """Mueve el segmento [a, b] para que empiece en p (p fuera del segmento)."""
    plan, palabras, grupos = _estado(trabajo, I)
    fps, dur = plan["info"]["fps"] or 30, plan["info"]["duracion"]
    a, b, p = _cuadro(max(0.0, a), fps), _cuadro(min(dur, b), fps), _cuadro(min(max(0.0, p), dur), fps)
    if b - a < MIN_SEG:
        raise ValueError("El segmento es muy corto")
    if a - 0.01 <= p <= b + 0.01:
        raise ValueError("Suéltalo fuera del mismo segmento")
    pz = lambda x, y: _pieza_actual(plan, palabras, grupos, x, y) if y - x > 0.01 else None  # noqa: E731
    if p < a:
        orden = [pz(0.0, p), pz(a, b), pz(p, a), pz(b, dur)]
    else:
        orden = [pz(0.0, a), pz(b, p), pz(a, b), pz(p, dur)]
    return _aplicar(trabajo, [x for x in orden if x], I, ed, "Segmento movido.")


def duplicar(trabajo, a, b, I, ed):
    """Copia el segmento y lo pega justo después de él."""
    copiar(trabajo, a, b, I)
    return pegar(trabajo, b, I, ed)
