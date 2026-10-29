"""
Estilo "Solo subtítulos": recibe un clip YA EDITADO y solo le pone los subtítulos.

- Transcribe con whisper, limpia repeticiones, corrige nombres con el modelo local y corrige la puntuación
  (¿? ¡! . ,) sin cambiar palabras.
- Arma los subtítulos (palabra por palabra estilo Chapucero, o por frase estilo Motivacional, según la plantilla).
- No recorta, no reencuadra, no cambia el audio: el video sale igual, con los subtítulos encima.
- Funciona con videos verticales u horizontales: la posición y el tamaño se ajustan al tamaño del video.

El editor (editor.py) asigna el módulo en `ed` antes de llamar a estas funciones.
"""
import subprocess
from pathlib import Path

import cv2
import numpy as np

ed = None  # módulo editor (lo asigna editor.py)


def medidas(pl, W, H):
    """Área y tamaños de los subtítulos ajustados al tamaño de este video."""
    cfg = dict(pl["subtitulos"])
    vertical = H >= W
    ref = pl["referencia_vertical" if vertical else "referencia_horizontal"]
    rw, rh = ref["tam_video"]
    s = min(W / rw, H / rh)
    cfg["tam"] = max(16, int(round(cfg["tam"] * s)))
    cfg["tam_min"] = max(12, int(round(cfg.get("tam_min", cfg["tam"]) * s)))
    cfg["contorno"] = max(1, int(round(cfg.get("contorno", 4) * s)))
    if cfg.get("modo") == "frases":
        cx, cy = ref["centro"]
        cfg["centro"] = [cx * W / rw, cy * H / rh]
        cfg["ancho_max"] = int(ref["ancho_max"] * W / rw)
        if cfg.get("sombra"):
            cfg["sombra"] = [v * s for v in cfg["sombra"]]
        area = None
    else:
        x, y, w, h = ref["area"]
        area = [int(x * W / rw), int(y * H / rh), int(w * W / rw), int(h * H / rh)]
    return cfg, area


def franja_en(frame, cfg):
    """Si el cuadro tiene la franja azul de los subtítulos (pantalla dividida), devuelve (y0, y1); si no, None."""
    H, W = frame.shape[:2]
    esc = 4
    peq = cv2.resize(frame, (W // esc, H // esc), interpolation=cv2.INTER_AREA).astype(np.int16)
    B, G, R = peq[..., 0], peq[..., 1], peq[..., 2]
    # azul oscuro y saturado (la franja); la camisa azul claro de Nacho o un cielo no cuentan
    azul = (B > R + cfg.get("azul_dif_r", 40)) & (B > G + cfg.get("azul_dif_g", 15)) & (B > 70) & \
           (G < B * cfg.get("azul_max_g", 0.55)) & (R < B * cfg.get("azul_max_r", 0.35))
    frac = azul.mean(1)
    filas = frac > cfg.get("azul_fraccion", 0.7)
    # renglones con letras encima siguen siendo franja si aún tienen bastante azul
    debiles = frac > cfg.get("azul_fraccion_letras", 0.3)
    mejor, k = None, 0
    while k < len(filas):
        if filas[k]:
            j, huecos = k, 0
            while j + 1 < len(filas) and (debiles[j + 1] or huecos < 2):
                huecos = 0 if debiles[j + 1] else huecos + 1
                j += 1
            while j > k and not filas[j]:
                j -= 1
            if mejor is None or j - k > mejor[1] - mejor[0]:
                mejor = (k, j)
            k = j + 1
        else:
            k += 1
    if not mejor:
        return None
    y0, y1 = mejor[0] * esc, (mejor[1] + 1) * esc
    alto = (y1 - y0) / H
    if not cfg.get("azul_alto_min", 0.05) <= alto <= cfg.get("azul_alto_max", 0.2):
        return None
    # la franja va a media pantalla: si toca el borde de arriba o de abajo es otra cosa azul (documento, imagen)
    if y0 < H * 0.05 or y1 > H * 0.95:
        return None
    return y0, y1


def detectar_franjas(video, info, cfg):
    """Tramos del video con la franja azul: [[inicio, fin, y0, y1], ...]."""
    cap = cv2.VideoCapture(str(video))
    fps = info["fps"]
    paso = max(1, int(round(fps / 4)))
    muestras, idx = [], 0
    total = info["cuadros"] or 1
    while True:
        if idx % paso == 0:
            ok, fr = cap.read()
            if not ok:
                break
            muestras.append((idx / fps, franja_en(fr, cfg)))
            if len(muestras) % 40 == 0:
                ed.Progreso.paso(0.45 * idx / total, "Buscando dónde van los subtítulos")
        elif not cap.grab():
            break
        idx += 1
    cap.release()
    hay = np.array([m[1] is not None for m in muestras])
    # quitar parpadeos de menos de medio segundo
    hay = ed.suavizar_bandera(hay, 2, 2) if len(hay) else hay
    tramos = []
    for a, b in ed.runs(list(hay)):
        ys = [m[1] for m in muestras[a:b] if m[1]]
        if not ys:
            continue
        y0 = int(np.median([y[0] for y in ys]))
        y1 = int(np.median([y[1] for y in ys]))
        fin = muestras[b][0] if b < len(muestras) else info["duracion"]
        tramos.append([round(muestras[a][0], 3), round(fin, 3), y0, y1])
    if tramos:
        ed.log(f"Franja azul de subtítulos en {len(tramos)} tramos")
    return tramos


def _tramo_mayor(flags):
    mejor, k = (0, 0, 0), 0
    while k < len(flags):
        if flags[k]:
            j = k
            while j < len(flags) and flags[j]:
                j += 1
            if j - k > mejor[0]:
                mejor = (j - k, k, j)
            k = j
        else:
            k += 1
    return mejor


def hay_titulo(frame):
    """¿Está el recuadro negro con letras blancas del título (estilo Motivacional)?"""
    H, W = frame.shape[:2]
    p = cv2.resize(frame, (W // 4, H // 4), interpolation=cv2.INTER_AREA).astype(np.int16)
    mx, mn = p.max(2), p.min(2)
    x0, x1 = int(p.shape[1] * 0.15), int(p.shape[1] * 0.85)
    negro = (mx < 45)[:, x0:x1]
    blanco = ((mn > 190) & (mx - mn < 40))[:, x0:x1]
    fr = (negro | blanco).mean(1)
    fr = np.convolve(fr, np.ones(5) / 5, mode="same")  # las letras del título no cortan el recuadro
    n, a, b = _tramo_mayor(list(fr > 0.8))
    if n * 4 < 0.06 * H:
        return False
    return negro[a:b].mean() > 0.4 and a * 4 > 0.25 * H


def detectar_titulo(video, info):
    """Hasta qué segundo dura el título del inicio (0 si el clip no tiene). Ahí no van subtítulos."""
    cap = cv2.VideoCapture(str(video))
    fps = info["fps"] or 30
    paso = max(1, int(round(fps / 4)))
    fin, idx, visto = 0.0, 0, False
    while idx / fps < 20:
        ok = cap.grab()
        if not ok:
            break
        if idx % paso == 0:
            ok, fr = cap.retrieve()
            if not ok:
                break
            if hay_titulo(fr):
                visto, fin = True, (idx + paso) / fps
            elif visto or idx / fps > 1.0:
                break
        idx += 1
    cap.release()
    if visto:
        ed.log(f"El clip ya trae título hasta {fin:.1f}s: ahí no pongo subtítulos")
    return round(fin, 3) if visto else 0.0


def analizar(args, video, pl, pl_path, trabajo):
    fps, n, W, H = ed.info_video(video)
    info = {"fps": fps, "cuadros": n, "ancho": W, "alto": H, "duracion": n / fps if fps else 0,
            "audio": ed.tiene_audio(video)}
    if not info["audio"]:
        raise SystemExit("El video no tiene audio: no hay nada que subtitular")
    ed.Progreso.paso(0.0, "Transcribiendo el audio")
    if args.transcripcion:
        palabras = ed.limpiar_transcripcion(ed.cargar_json(args.transcripcion))
    else:
        palabras = ed.transcribir(video, args.whisper_modelo, args.dispositivo)

    ed.Progreso.paso(0.5, "Revisando nombres y ortografía")
    ia = None if args.sin_ia else ed.IA(args.url_ollama, args.modelo_ollama, "none")
    contexto = ed.analizar_tema(palabras, args.titulo or "", ia)
    ed.aplicar_correcciones(palabras, contexto.get("correcciones"))
    if pl["subtitulos"].get("puntuar_con_ia", True):
        ed.Progreso.paso(0.75, "Corrigiendo la puntuación")
        palabras = ed.estilo_motivacional().puntuar_con_ia(palabras, ia)
    ed.guardar_json(trabajo / "transcripcion.json", palabras)
    if (trabajo / "subtitulos.json").exists():
        (trabajo / "subtitulos.json").unlink()

    cfg, area = medidas(pl, W, H)
    franjas = detectar_franjas(video, info, pl.get("franja_azul", {})) if pl.get("franja_azul", {}).get("activar", True) else []
    areas = {"persona": area} if area else {}
    if franjas:
        fx0, fw = pl.get("franja_azul", {}).get("x_ancho", [30, 880])
        ys0 = int(np.median([f[2] for f in franjas])); ys1 = int(np.median([f[3] for f in franjas]))
        areas["dividida"] = [int(fx0 * W / 1080), ys0, int(fw * W / 1080), ys1 - ys0]
    titulo_fin = detectar_titulo(video, info) if cfg.get("modo") == "frases" else 0.0
    plan = {
        "estilo": "solo_subtitulos",
        "titulo_fin": titulo_fin,
        "video": str(video),
        "plantilla": str(pl_path),
        "titulo": args.titulo or "",
        "info": info,
        "contexto": contexto,
        "tomas": [{"inicio": 0.0, "fin": info["duracion"], "layout": "persona"}],
        "proyeccion": [],
        "momentos": [],
        "cortes": [],
        # para el editor de subtítulos en vivo (posición y tamaño ya ajustados a este video)
        "franjas": franjas,
        "subtitulos_render": {"salida": [W, H], "areas": areas, "estilo": cfg},
    }
    ed.guardar_json(trabajo / "plan.json", plan)
    ed.log(f"Plan guardado en {trabajo / 'plan.json'}")
    ed.Progreso.paso(0.95, "Preparando el video para verlo en el navegador")
    ed.copia_navegador(video, trabajo)
    ed.Progreso.paso(1.0, "Análisis terminado")
    return trabajo


def render(args, trabajo, plan, pl):
    info = plan["info"]
    W, H, fps = info["ancho"], info["alto"], info["fps"]
    salida = Path(args.salida) if args.salida else trabajo / (Path(plan["video"]).stem + "_subtitulado.mp4")
    cfg, area = medidas(pl, W, H)
    palabras = ed.cargar_json(trabajo / "transcripcion.json") if (trabajo / "transcripcion.json").exists() else []
    grupos = ed.grupos_subtitulos(trabajo, palabras, cfg)
    frases = cfg.get("modo") == "frases"
    t_titulo = plan.get("titulo_fin", 0.0) or 0.0
    if frases and t_titulo:
        grupos = ed.estilo_motivacional().partir_en_titulo(grupos, t_titulo)
    if frases:
        subs = ed.estilo_motivacional().SubtitulosFrase(grupos, cfg, W, H)
    else:
        subs = ed.Subtitulos(grupos, cfg)

    venc = ed.codificador(args.gpu, pl["salida"].get("crf", 18))
    kbps = int(pl["salida"].get("audio_kbps", 125))
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", f"{fps}", "-i", "-",
           "-i", plan["video"], "-map", "0:v", "-map", "1:a:0?",
           "-c:a", "aac", "-b:a", f"{max(32, int(kbps * 0.96))}k",
           *venc, "-pix_fmt", "yuv420p", "-shortest", "-movflags", "+faststart", str(salida)]
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    vista = ed.VistaPrevia(trabajo, W, H, fps)

    franjas = plan.get("franjas", [])
    fx0, fw = pl.get("franja_azul", {}).get("x_ancho", [30, 880])
    fx0, fw = int(fx0 * W / 1080), int(fw * W / 1080)
    subs_franja = {}

    def franja_t(t):
        for f in franjas:
            if f[0] <= t < f[1]:
                return f
        return None

    cap = cv2.VideoCapture(plan["video"])
    idx = 0
    total = info["cuadros"] or 1
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t = idx / fps
        idx += 1
        if idx % max(1, int(fps)) == 0:
            ed.Progreso.paso(idx / total, "Poniendo los subtítulos")
        if frame.shape[1] != W or frame.shape[0] != H:
            frame = cv2.resize(frame, (W, H))
        fj = franja_t(t)
        if t < t_titulo:
            # el título del clip ocupa el lugar de los subtítulos
            vista.escribir(frame, t, "titulo")
            try:
                ff.stdin.write(frame.tobytes())
            except (BrokenPipeError, OSError):
                break
            continue
        vista.escribir(frame, t, "dividida" if fj else ("frases" if frases else "persona"))
        if frases:
            gi = subs.activo(t)
            if gi is not None:
                if fj:
                    # dentro de la franja azul: misma frase, centrada en la franja
                    clave = (fj[2], fj[3])
                    if clave not in subs_franja:
                        c2 = dict(cfg, centro=[fx0 + fw / 2, (fj[2] + fj[3]) / 2])
                        subs_franja[clave] = ed.estilo_motivacional().SubtitulosFrase(subs.grupos, c2, W, H)
                    ed.pegar(frame, subs_franja[clave].imagen(gi), 0, ed.desplazamiento_subs(subs.grupos[gi], H))
                else:
                    ed.pegar(frame, subs.imagen(gi), 0, ed.desplazamiento_subs(subs.grupos[gi], H))
        else:
            act = subs.activo(t)
            if act:
                x, y, w, h = (fx0, fj[2], fw, fj[3] - fj[2]) if fj else area
                y += ed.desplazamiento_subs(subs.grupos[act[0]], H)   # este subtítulo, subido o bajado a mano
                ed.pegar(frame, subs.imagen(act[0], act[1], w, h), x, y)
        try:
            ff.stdin.write(frame.tobytes())
        except (BrokenPipeError, OSError):  # ffmpeg se cerró (el error real sale arriba en el registro)
            break
    cap.release()
    try:
        ff.stdin.close()
    except OSError:
        pass
    if ff.wait() != 0:
        raise SystemExit("ffmpeg falló al codificar")
    vista.cerrar(salida)
    ed.Progreso.paso(1.0, "Listo")
    ed.log(f"Listo: {salida}")
    return salida
