#!/usr/bin/env python3
"""
Interfaz del editor vertical.

    python interfaz.py

Se abre en el navegador (http://127.0.0.1:7860). Desde ahí:
  - Procesas un video nuevo o cargas una carpeta _trabajo ya hecha.
  - Pestaña Subtítulos: tabla con todos los subtítulos; editas el texto o los tiempos y guardas.
  - Pestaña Imágenes: por cada momento eliges estilo, tiempos, imagen, encuadre (clic sobre la foto),
    y el movimiento con dos marcos (inicio y final) y vista previa animada; buscas o subes imágenes.
  - Pestaña Título y cortes: cambias el título o quitas un tramo del video.
  - Renderizas de nuevo con un botón.
"""
import inspect
import json
import os
import shutil
import string
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import quote

import cv2
import gradio as gr
import numpy as np

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import editor as ed  # noqa: E402
import aprendizaje  # noqa: E402
import montaje  # noqa: E402

# compatibilidad Gradio 5 y 6
_TEMA_EN_BLOCKS = "theme" in inspect.signature(gr.Blocks.__init__).parameters

URL_OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434")
# Carpetas en el escritorio: «VideosEdit» (videos a editar y sus carpetas _trabajo) y «Renders» (videos exportados).
# El instalador pone las rutas reales (el escritorio puede estar en OneDrive) en config.json -> iniciar.pyw.
ESCRITORIO = Path(os.environ.get("ESCRITORIO") or (Path.home() / "Desktop"))
CARPETA_VIDEOS = Path(os.environ.get("CARPETA_VIDEOS") or (ESCRITORIO / "VideosEdit"))
CARPETA_RENDERS = Path(os.environ.get("CARPETA_RENDERS") or (ESCRITORIO / "Renders"))
# «Solo tarjeta gráfica» marcado de inicio (en PCs sin tarjeta NVIDIA el instalador lo apaga)
GPU_INICIAL = os.environ.get("EDITOR_SIN_GPU") != "1"
EXT_VIDEO = [".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mts", ".flv", ".wmv"]


def buscar_video(nombre):
    """Busca el video en la carpeta fija. Sin extensión, primero .mp4 y luego los demás formatos."""
    nombre = limpiar_ruta(nombre)
    if not nombre:
        return None
    p = Path(nombre)
    if p.is_absolute() and p.exists():
        return p
    base = CARPETA_VIDEOS / nombre
    if base.suffix.lower() in EXT_VIDEO and base.exists():
        return base
    for ext in EXT_VIDEO:
        candidato = base.with_name(base.name + ext)
        if candidato.exists():
            return candidato
    # sin importar mayúsculas en la extensión
    if CARPETA_VIDEOS.exists():
        stem = Path(nombre).stem.lower() if Path(nombre).suffix.lower() in EXT_VIDEO else nombre.lower()
        for f in CARPETA_VIDEOS.iterdir():
            if f.suffix.lower() in EXT_VIDEO and f.stem.lower() == stem:
                return f
    return None
_IA = None

EFECTOS = {
    "Acercar": "zoom_in",
    "Alejar": "zoom_out",
    "Paneo a la derecha": "paneo_der",
    "Paneo a la izquierda": "paneo_izq",
    "Paneo hacia arriba": "paneo_arriba",
    "Paneo hacia abajo": "paneo_abajo",
    "Sin movimiento": "ninguno",
}
EFECTO_NOMBRE = {v: k for k, v in EFECTOS.items()}


def ia():
    global _IA
    if _IA is None:
        _IA = ed.IA(URL_OLLAMA)
    return _IA


# ----------------------------------------------------------------------------
# Archivos del trabajo
# ----------------------------------------------------------------------------
def limpiar_ruta(txt):
    return (txt or "").strip().strip('"').strip()


def cargar(trabajo):
    t = Path(trabajo)
    plan = ed.cargar_json(t / "plan.json")
    palabras = ed.cargar_json(t / "transcripcion.json") if (t / "transcripcion.json").exists() else []
    return plan, palabras


ESTILOS = {
    "Clips Chapuceros": "plantillas/chapucero_vertical.json",
    "Tiktoks Motivacionales": "plantillas/tiktok_motivacional.json",
    "Tiktoks Yair": "plantillas/tiktok_yair.json",
    "Tiktoks Gaby": "plantillas/tiktok_gaby.json",
    "Clips Fuera": "plantillas/clips_fuera.json",
    "Solo subtítulos (Chapucero)": "plantillas/solo_subtitulos_chapucero.json",
}


def plantilla(plan):
    return ed.plantilla_plan(plan)   # con lo aprendido que se le aplicó al analizarlo


def grupos_actuales(trabajo, plan, palabras):
    return ed.grupos_subtitulos(trabajo, palabras, plantilla(plan)["subtitulos"])


_CONTADOR_FOTO = [0]


def _foto(trabajo, carpeta):
    """Guarda el estado actual (plan + subtítulos) en la carpeta de historial indicada."""
    t = Path(trabajo)
    h = t / carpeta
    h.mkdir(exist_ok=True)
    _CONTADOR_FOTO[0] += 1
    marca = time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}_{_CONTADOR_FOTO[0] % 1000:03d}"
    shutil.copy2(t / "plan.json", h / f"{marca}_plan.json")
    sub = t / "subtitulos.json"
    if sub.exists():
        shutil.copy2(sub, h / f"{marca}_subtitulos.json")
    else:
        (h / f"{marca}_subtitulos.json").write_text("null", encoding="utf-8")
    if (t / "transcripcion.json").exists():   # el montaje (mover segmentos del video) también la cambia
        shutil.copy2(t / "transcripcion.json", h / f"{marca}_transcripcion.json")


def _restaurar(trabajo, carpeta):
    """Regresa al estado más reciente guardado en la carpeta (y lo quita de ahí). False si no hay."""
    h = Path(trabajo) / carpeta
    planes = sorted(h.glob("*_plan.json")) if h.exists() else []
    if not planes:
        return False
    ultimo = planes[-1]
    marca = ultimo.name[: -len("_plan.json")]
    shutil.copy2(ultimo, Path(trabajo) / "plan.json")
    sub = h / f"{marca}_subtitulos.json"
    destino = Path(trabajo) / "subtitulos.json"
    if sub.exists():
        if sub.read_text(encoding="utf-8").strip() == "null":
            if destino.exists():
                destino.unlink()
        else:
            shutil.copy2(sub, destino)
        sub.unlink()
    tr = h / f"{marca}_transcripcion.json"
    if tr.exists():
        shutil.copy2(tr, Path(trabajo) / "transcripcion.json")
        tr.unlink()
    ultimo.unlink()
    return True


def respaldar(trabajo):
    """Antes de cada cambio: guarda el estado para «Deshacer». Un cambio nuevo borra lo que se podía «Rehacer»."""
    _foto(trabajo, ".historial")
    shutil.rmtree(Path(trabajo) / ".rehacer", ignore_errors=True)


def deshacer(trabajo):
    h = Path(trabajo) / ".historial"
    if not (h.exists() and any(h.glob("*_plan.json"))):
        return False
    _foto(trabajo, ".rehacer")
    return _restaurar(trabajo, ".historial")


def rehacer(trabajo):
    h = Path(trabajo) / ".rehacer"
    if not (h.exists() and any(h.glob("*_plan.json"))):
        return False
    _foto(trabajo, ".historial")
    return _restaurar(trabajo, ".rehacer")


PANTALLAS = {"completa": "Pantalla completa", "dividida": "Dividida (Nacho arriba)", "nacho": "Solo Nacho"}
TIPOS = {"video": "Video", "imagen": "Imagen", "lectura": "Documento (lectura)"}


def tabla_pantalla(trabajo):
    """Tramos en que se ve lo que Nacho muestra en pantalla, con cómo se ven (editable)."""
    if not trabajo:
        return []
    plan, _ = cargar(trabajo)
    pl = plantilla(plan)
    filas = []
    for p in plan.get("proyeccion", []):
        tipo = TIPOS.get(p["tipo"], p["tipo"])
        if p.get("documento"):
            tipo = "Documento"
        elif p.get("vertical") or (p["tipo"] == "video" and p.get("caja") and p["caja"][3] > p["caja"][2] * 1.2):
            tipo = "Video de celular"
        filas.append([mmss(ed_t(p["inicio"], plan)), mmss(ed_t(p["fin"], plan)), tipo,
                      PANTALLAS[ed.pantalla_de(p, pl.get("proyeccion", {}))]])
    return filas


def guardar_pantalla(trabajo, tabla):
    plan, _ = cargar(trabajo)
    proy = plan.get("proyeccion", [])
    inverso = {v: k for k, v in PANTALLAS.items()}
    for p, fila in zip(proy, filas_de(tabla)):
        if len(fila) < 4:
            continue
        txt = str(fila[3]).strip().lower()
        modo = inverso.get(str(fila[3]).strip()) or next((k for k in ("completa", "dividida", "nacho") if k in txt), None)
        if modo:
            p["pantalla"] = modo
        ini, fin = seg(fila[0]), seg(fila[1])
        if ini is not None and mmss(ini) != mmss(ed_t(p["inicio"], plan)):
            p["inicio"] = round(orig_t(ini, plan), 3)
        if fin is not None and mmss(fin) != mmss(ed_t(p["fin"], plan)):
            p["fin"] = round(orig_t(fin, plan), 3)
    proy.sort(key=lambda x: x["inicio"])
    respaldar(trabajo)
    guardar_plan(trabajo, plan)
    return len(proy)


# ----------------------------------------------------------------------------
# Línea de tiempo de pantalla (todos los estilos menos Solo subtítulos)
# ----------------------------------------------------------------------------
NOMBRES_OP = {"completa": "Pantalla completa", "dividida": "Dividida", "nacho": "Solo Nacho",
              "cerca": "Nacho cerca", "lejos": "Nacho lejos", "imagen": "Imagen", "arriba": "Arriba (en lugar de Nacho)", "ganso": "Dividida Ganso", "quitar": "Quitar"}


def estilo_de(plan):
    pl = plantilla(plan)
    return plan.get("estilo") or pl.get("estilo") or "chapucero"


def tramos_pantalla(t):
    """Todo el video en tramos, cada uno con cómo se ve y qué opciones tiene. Tiempos del video editado."""
    plan, _ = cargar(t)
    pl = plantilla(plan)
    est = estilo_de(plan)
    dur = plan["info"]["duracion"]
    fin_ed = ed_t(dur, plan)
    out = []

    def add(k, a, b, tipo, pantalla, opciones):
        a_e, b_e = ed_t(max(0.0, a), plan), ed_t(min(dur, b), plan)
        if b_e - a_e < 0.09:
            return
        out.append({"k": k, "inicio": mmss(a_e), "fin": mmss(b_e), "ini_s": round(a_e, 3), "fin_s": round(b_e, 3),
                    "tipo": tipo, "pantalla": pantalla, "opciones": opciones})

    if est == "solo_subtitulos":
        return {"tramos": [], "duracion": fin_ed, "mensaje": "En «Solo subtítulos» el video no se reacomoda."}

    if est == "motivacional":
        for i, e in enumerate(plan.get("encuadres", [])):
            add(f"e{i}", e["inicio"], e["fin"], "Nacho", e.get("zoom", "cerca"), ["cerca", "lejos"])
        for i, m in enumerate(plan.get("momentos", [])):
            if m.get("imagenes") and not m.get("entrada"):   # la de la entrada dura lo que el título
                add(f"m{i}", m["inicio"], m["fin"], "Imagen: " + (m.get("busqueda") or "")[:40],
                    "quitar" if m.get("oculto") else "imagen", ["imagen", "quitar"])
    else:
        cfg_p = pl.get("proyeccion", {})
        proy = plan.get("proyeccion", [])
        # «Dividida Ganso» solo si la plantilla trae ese acomodo
        ops_p = ["completa", "dividida", "nacho", "916"] + (["ganso"] if "ganso" in pl.get("layouts", {}) else [])
        for i, p in enumerate(proy):
            tipo = TIPOS.get(p["tipo"], p["tipo"])
            if p.get("documento"):
                tipo = "Documento"
            elif p.get("vertical") or (p["tipo"] == "video" and p.get("caja") and p["caja"][3] > p["caja"][2] * 1.2):
                tipo = "Video de celular"
            if p.get("habla_otro"):
                tipo += " (habla la persona del video)"
            add(f"p{i}", p["inicio"], p["fin"], tipo, ed.pantalla_de(p, cfg_p), ops_p)
        # ratos de pantalla partida donde no se usa lo que Nacho proyecta (sale solo Nacho)
        for i, sg in enumerate(plan.get("tomas", [])):
            if sg.get("layout") != "dividida":
                # aunque la plataforma no viera pantalla partida aquí, se puede poner a mano (dividida, completa o
                # 9:16); los ratos que ya tienen su tramo de pantalla (p. ej. un «9:16») no se repiten
                libres_n = [(sg["inicio"], sg["fin"])]
                for p in proy:
                    nuevos = []
                    for a, b in libres_n:
                        if p["fin"] <= a or p["inicio"] >= b:
                            nuevos.append((a, b))
                            continue
                        if p["inicio"] > a:
                            nuevos.append((a, p["inicio"]))
                        if p["fin"] < b:
                            nuevos.append((p["fin"], b))
                    libres_n = nuevos
                for a, b in libres_n:
                    add(f"n{i}" if len(libres_n) == 1 else f"n{i}@{a:.3f}", a, b, "Nacho (sin pantalla)", "nacho",
                        ops_p)
                continue
            libres = [(sg["inicio"], sg["fin"])]
            for p in proy:
                nuevos = []
                for a, b in libres:
                    if p["fin"] <= a or p["inicio"] >= b:
                        nuevos.append((a, b))
                        continue
                    if p["inicio"] > a:
                        nuevos.append((a, p["inicio"]))
                    if p["fin"] < b:
                        nuevos.append((p["fin"], b))
                libres = nuevos
            for a, b in libres:
                if b - a >= 1.0:
                    add(f"g{a:.3f}_{b:.3f}", a, b, "Lo que proyecta (no se está usando)", "nacho",
                        ops_p)
        for i, m in enumerate(plan.get("momentos", [])):
            if m.get("imagenes"):
                add(f"m{i}", m["inicio"], m["fin"], "Imagen de internet: " + (m.get("busqueda") or "")[:40],
                    "quitar" if m.get("oculto") else (m.get("estilo") or "dividida"), ["completa", "dividida", "arriba", "quitar"])
    out.sort(key=lambda x: (x["ini_s"], x["k"][0] != "m"))
    return {"tramos": out, "duracion": round(fin_ed, 3), "estilo": est}


def pista_cara_en(video, caja, a, b):
    """Pista de la cara más grande dentro de la caja entre a y b (para encuadrar un video a pantalla completa)."""
    try:
        det = ed.DetectorCara()
    except Exception:
        return []
    cap = cv2.VideoCapture(str(video))
    x, y, w, h = [int(v) for v in caja]
    pista = []
    for tt in np.arange(a, b, 0.5):
        cap.set(cv2.CAP_PROP_POS_MSEC, tt * 1000)
        ok, fr = cap.read()
        if not ok:
            break
        c = det.mayor(fr[y:y + h, x:x + w])
        if c and c[3] > 40:
            pista.append([round(float(tt), 3), x + c[0] + c[2] / 2, y + c[1] + c[3] / 2, c[3]])
    cap.release()
    return pista if len(pista) >= 2 else []


def caja_proyeccion(pl_px, plan):
    """Recuadro de la pantalla de Nacho según la plantilla (en px del video); si la plantilla no lo trae
    (Tiktoks Motivacionales / Yair), todo el cuadro."""
    b = (pl_px.get("fuente_16x9") or {}).get("proyeccion")
    if b:
        return [int(v) for v in b]
    return [0, 0, int(plan["info"]["ancho"]), int(plan["info"]["alto"])]


def aplicar_pantalla(t, cambios):
    """Guarda lo elegido en la línea de tiempo de pantalla."""
    plan, _ = cargar(t)
    pl = plantilla(plan)
    respaldar(t)
    proy = plan.setdefault("proyeccion", [])
    nuevos_proy = []
    tomas_partidas = {}   # índice de toma -> tomas que la reemplazan (para no mover los índices mientras se recorre)
    pl_px = json.loads(json.dumps(pl))
    ed.escalar_cajas(pl_px, plan["info"]["ancho"], plan["info"]["alto"])   # recuadros en píxeles de este video

    def tiempos(c, ini0, fin0):
        a, b = seg(c.get("inicio")), seg(c.get("fin"))
        a = orig_t(a, plan) if a is not None and mmss(a) != mmss(ed_t(ini0, plan)) else ini0
        b = orig_t(b, plan) if b is not None and mmss(b) != mmss(ed_t(fin0, plan)) else fin0
        return round(a, 3), round(max(b, a + 0.1), 3)

    for c in cambios:
        k, op = str(c.get("k", "")), c.get("pantalla")
        if k.startswith("p") and k[1:].isdigit() and int(k[1:]) < len(proy):
            p = proy[int(k[1:])]
            if op in ("completa", "dividida", "nacho", "916", "ganso"):
                p["pantalla"] = op
            p["inicio"], p["fin"] = tiempos(c, p["inicio"], p["fin"])
        elif k.startswith("g"):
            try:
                a0, b0 = [float(x) for x in k[1:].split("_")]
            except ValueError:
                continue
            if op not in ("completa", "dividida", "916", "ganso"):
                continue
            a, b = tiempos(c, a0, b0)
            # misma caja que el tramo de proyección más cercano (o la de la plantilla)
            cerca = sorted(proy, key=lambda p: min(abs(p["inicio"] - b), abs(p["fin"] - a)))
            caja = (cerca[0].get("caja") if cerca else None) or caja_proyeccion(pl_px, plan)
            item = {"tipo": "video", "inicio": a, "fin": b, "caja": caja, "pantalla": op, "manual": True}
            cara = pista_cara_en(plan["video"], caja, a, b) if op != "916" else None   # 9:16 no la necesita
            if cara:
                item["cara"] = cara
            nuevos_proy.append(item)
        elif k.startswith("n") and k[1:].split("@")[0].isdigit():
            # rato que la plataforma tomó como «solo Nacho»: se vuelve pantalla partida con lo que proyecta Nacho
            tomas = plan.get("tomas", [])
            i = int(k[1:].split("@")[0])
            if i >= len(tomas) or op not in ("completa", "dividida", "916", "ganso"):
                continue
            sg = tomas[i]
            a, b = tiempos(c, sg["inicio"], sg["fin"])
            a, b = max(a, sg["inicio"]), min(b, sg["fin"])
            if b - a < 0.099:
                continue
            partes = []
            if a - sg["inicio"] >= 0.05:
                partes.append(dict(sg, fin=a))
            partes.append(dict(sg, inicio=a, fin=b, layout=sg.get("layout") if op == "916" else "dividida", manual=True))
            if sg["fin"] - b >= 0.05:
                partes.append(dict(sg, inicio=b))
            tomas_partidas[i] = partes
            caja = caja_proyeccion(pl_px, plan)
            item = {"tipo": "video", "inicio": a, "fin": b, "caja": caja, "pantalla": op, "manual": True}
            cara = pista_cara_en(plan["video"], caja, a, b) if op != "916" else None   # 9:16 no la necesita
            if cara:
                item["cara"] = cara
            nuevos_proy.append(item)
        elif k.startswith("e") and k[1:].isdigit():
            enc = plan.get("encuadres", [])
            i = int(k[1:])
            if i < len(enc):
                if op in ("cerca", "lejos"):
                    enc[i]["zoom"] = op
                enc[i]["inicio"], enc[i]["fin"] = tiempos(c, enc[i]["inicio"], enc[i]["fin"])
        elif k.startswith("m") and k[1:].isdigit():
            moms = plan.get("momentos", [])
            i = int(k[1:])
            if i < len(moms):
                m = moms[i]
                m["oculto"] = op == "quitar"
                if op in ("completa", "dividida", "arriba"):
                    m["estilo"] = op
                m["inicio"], m["fin"] = tiempos(c, m["inicio"], m["fin"])
    proy.extend(nuevos_proy)
    proy.sort(key=lambda x: x["inicio"])
    if tomas_partidas:
        tomas = []
        for i, sg in enumerate(plan.get("tomas", [])):
            tomas.extend(tomas_partidas.get(i, [sg]))
        plan["tomas"] = sorted(tomas, key=lambda x: x["inicio"])
    guardar_plan(t, plan)
    return len(cambios)


def guardar_plan(trabajo, plan):
    ed.guardar_json(Path(trabajo) / "plan.json", plan)


def ruta_export(trabajo):
    """Dónde queda el video final al exportar: carpeta «Renders» del escritorio, con el TÍTULO del cuadro «Título»
    como nombre (sin título: nombre del video). Si ya hay otro video con ese nombre, se le agrega (2), (3)..."""
    plan, _ = cargar(trabajo)
    titulo = (plan.get("titulo") or "").strip()
    if titulo:
        base = nombre_archivo(titulo)
    else:
        base = Path(plan["video"]).stem + ("_subtitulado" if estilo_de(plan) == "solo_subtitulos" else "_vertical")
    p, k = CARPETA_RENDERS / f"{base}.mp4", 2
    while p.exists() and str(p) != exportado_de(trabajo):
        p = CARPETA_RENDERS / f"{base} ({k}).mp4"
        k += 1
    return p


def exportado_de(trabajo):
    """Último video exportado de este trabajo (se anota aparte para no tocar plan.json)."""
    try:
        return (Path(trabajo) / "exportado.txt").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def video_salida(trabajo):
    """Video final exportado (en «Renders»; los trabajos viejos lo tienen en su carpeta _trabajo)."""
    if not trabajo:
        return None
    plan, _ = cargar(trabajo)
    ex = exportado_de(trabajo)
    if ex and Path(ex).exists():
        return ex
    for fin in ("_vertical.mp4", "_subtitulado.mp4"):
        p = Path(trabajo) / (Path(plan["video"]).stem + fin)
        if p.exists():
            return str(p)
    return None


def mmss(t):
    """Segundos -> 'MM:SS:CC' (minutos : segundos : centésimas)."""
    cc = int(round(max(0.0, float(t)) * 100))
    return f"{cc // 6000:02d}:{cc // 100 % 60:02d}:{cc % 100:02d}"


def seg(valor):
    """'MM:SS:CC', 'MM:SS' o segundos ('75.5') -> segundos. None si está vacío o no se entiende."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    txt = str(valor).strip().replace(",", ".").replace(";", ":").replace(" ", "")
    if not txt or txt.lower() == "nan":
        return None
    try:
        partes = txt.split(":")
        if len(partes) == 1:
            return float(partes[0])
        if len(partes) == 2:
            return int(partes[0] or 0) * 60 + float(partes[1] or 0)
        if len(partes) == 3:
            cc = partes[2] or "0"
            return int(partes[0] or 0) * 60 + int(partes[1] or 0) + int(cc.ljust(2, "0")[:2]) / 100
    except ValueError:
        return None
    return None


# ----------------------------------------------------------------------------
# Subtítulos
# ----------------------------------------------------------------------------
def ed_t(t, plan):
    """Tiempo original -> tiempo en el video ya editado (lo que ve el usuario)."""
    return ed.a_editado(t, plan.get("cortes", []))


def orig_t(te, plan):
    """Tiempo que escribe el usuario (video editado) -> tiempo del video original."""
    return ed.a_original(te, plan.get("cortes", []))


def tabla_subtitulos(trabajo):
    """Los tiempos se muestran como aparecen en el video ya editado."""
    if not trabajo:
        return []
    plan, palabras = cargar(trabajo)
    return [[mmss(ed_t(g["i"], plan)), mmss(ed_t(g["f"], plan)), " ".join(p["p"] for p in g["palabras"])]
            for g in grupos_actuales(trabajo, plan, palabras)]


def filas_de(tabla):
    """Acepta lista de listas o DataFrame de pandas."""
    if tabla is None:
        return []
    if hasattr(tabla, "values"):
        return tabla.values.tolist()
    return list(tabla)


def texto_con_saltos(palabras):
    """Texto del subtítulo con los saltos de línea que puso el usuario (Shift+Enter en el editor)."""
    out = ""
    for k, p in enumerate(palabras):
        out += p["p"]
        if k + 1 < len(palabras):
            out += "\n" if p.get("salto") else " "
    return out


def leer_saltos(texto):
    """'a Donald Trump\na un proyecto' -> (['a','Donald','Trump','a','un','proyecto'], {2})."""
    palabras, saltos = [], set()
    for linea in str(texto).replace("\r", "").split("\n"):
        ws = linea.split()
        if not ws:
            continue
        if palabras:
            saltos.add(len(palabras) - 1)
        palabras += ws
    return palabras, saltos


def fuera_de_cortes(a_o, b_o, cortes):
    """Tiempo (original) de una palabra escrita a mano, siempre FUERA de los tramos quitados: si cruza uno, se queda
    del lado donde dura más (antes se quedaba del lado donde empezaba aunque fuera por 2 milésimas, y quedaba casi
    toda dentro del tramo quitado: se ocultaba al guardar, p. ej. «Santiago» en «de parte de Santiago Peña»)."""
    b_o = max(a_o + 0.02, b_o)
    for c in cortes:
        if a_o < c["fin"] and b_o > c["inicio"]:   # se enciman
            antes, despues = c["inicio"] - a_o, b_o - c["fin"]
            if antes >= despues and antes >= 0.02:
                b_o = c["inicio"] - 0.001
            else:
                a_o = c["fin"] + 0.001
                b_o = max(b_o, a_o + 0.02)
    return round(a_o, 3), round(b_o, 3)


def guardar_subtitulos(trabajo, tabla, cortes=None):
    """Los tiempos de la tabla son del video editado. 'cortes' = los tramos quitados con los que la pestaña
    calculó esos tiempos (si en Edición se quitó o restauró algo después, se convierten con los de entonces)."""
    plan, palabras = cargar(trabajo)
    if cortes is not None:
        plan = dict(plan, cortes=cortes)
    cortes_u = ed.cortes_quitados(plan.get("cortes", []))
    viejos = grupos_actuales(trabajo, plan, palabras)
    usados = set()
    nuevos = []
    for n, fila in enumerate(filas_de(tabla)):
        if len(fila) < 3:
            continue
        ini_e, fin_e = seg(fila[0]), seg(fila[1])
        if ini_e is None or fin_e is None:
            continue
        texto = str(fila[2] or "").strip()
        if not texto or texto.lower() == "nan":
            continue  # fila vacía = subtítulo quitado
        palabras_nuevas, saltos = leer_saltos(texto)
        if not palabras_nuevas:
            continue
        # la fila puede traer el número del subtítulo original (el editor en vivo lo manda; -1 = nuevo)
        ref = n
        if len(fila) >= 4 and str(fila[3]).lstrip("-").isdigit():
            ref = int(fila[3])
        viejo = viejos[ref] if 0 <= ref < len(viejos) else None
        if viejo is not None:
            usados.add(ref)
        try:   # altura de ESTE subtítulo (px de un video de 1920 de alto; negativo = más arriba)
            dy = max(-1800, min(1800, int(round(float(fila[4]))))) if len(fila) >= 5 else int((viejo or {}).get("dy", 0))
        except (TypeError, ValueError):
            dy = int((viejo or {}).get("dy", 0) or 0)
        # se compara con lo que se veía (sin las palabras de tramos quitados): si no cambió, se conserva entero
        vis = [p for p in viejo["palabras"] if not ed.palabra_cortada(p, cortes_u)] if viejo else []
        saltos_viejos = {k for k, p in enumerate(vis) if p.get("salto") and k < len(vis) - 1}
        if viejo and [p["p"] for p in vis] == palabras_nuevas and saltos_viejos == saltos and \
                mmss(ed_t(viejo["i"], plan)) == mmss(ini_e) and mmss(ed_t(viejo["f"], plan)) == mmss(fin_e):
            igual = {k: v for k, v in viejo.items() if k != "dy"}
            if dy:
                igual["dy"] = dy
            nuevos.append(igual)
            continue
        # los tiempos de la tabla son del video editado; se guardan en tiempo del original. Las palabras se reparten
        # en el tiempo EDITADO y luego se pasan al original, así ninguna cae dentro de una pausa recortada
        # (antes una palabra agregada podía quedar ahí y desaparecer al guardar)
        if fin_e <= ini_e:
            fin_e = ini_e + 0.5
        ini, fin = orig_t(ini_e, plan), orig_t(fin_e, plan)
        if viejo and mmss(ed_t(viejo["i"], plan)) == mmss(ini_e):
            ini = viejo["i"]
        if viejo and mmss(ed_t(viejo["f"], plan)) == mmss(fin_e):
            fin = viejo["f"]
        if fin <= ini:
            fin = ini + 0.5

        def a_orig(te):
            return round(orig_t(te, plan), 3)
        if vis and len(vis) == len(palabras_nuevas):
            # mismo número de palabras: conserva el ritmo que tenían, ajustado a los tiempos nuevos
            vi, vf = ed_t(vis[0]["i"], plan), ed_t(vis[-1]["f"], plan)
            esc = (fin_e - ini_e) / max(0.05, vf - vi)
            tiempos = [(ini_e + (ed_t(p["i"], plan) - vi) * esc, ini_e + (ed_t(p["f"], plan) - vi) * esc) for p in vis]
        else:
            paso = (fin_e - ini_e) / len(palabras_nuevas)
            tiempos = [(ini_e + k * paso, ini_e + (k + 1) * paso) for k in range(len(palabras_nuevas))]
        pal = []
        todos_cortes = ed.unir_cortes(plan.get("cortes", []))
        for txt, (a_e, b_e) in zip(palabras_nuevas, tiempos):
            a_o, b_o = fuera_de_cortes(a_orig(a_e + 0.001), a_orig(max(a_e + 0.002, b_e - 0.001)), todos_cortes)
            pal.append({"p": txt, "i": a_o, "f": b_o})
        for k in saltos:
            if k < len(pal) - 1:
                pal[k]["salto"] = True
        nuevo = {"i": round(ini, 3), "f": round(fin, 3), "palabras": pal}
        if dy:
            nuevo["dy"] = dy
        nuevos.append(nuevo)
    # los que no se veían por estar todos en un tramo quitado se guardan tal cual (vuelven si se restaura)
    for n, g in enumerate(viejos):
        if n not in usados and g.get("palabras") and all(ed.palabra_cortada(p, cortes_u) for p in g["palabras"]):
            nuevos.append(g)
    nuevos = ed.sanear_grupos(nuevos, plan.get("cortes", []))
    respaldar(trabajo)
    ed.guardar_json(Path(trabajo) / "subtitulos.json", nuevos)
    return len(nuevos)


# ----------------------------------------------------------------------------
# Momentos e imágenes
# ----------------------------------------------------------------------------
def opciones_momentos(plan):
    return [f"{i} · {mmss(ed_t(m['inicio'], plan))}–{mmss(ed_t(m['fin'], plan))} · {m.get('busqueda', '')[:40]}"
            + ("" if m.get("imagenes") else " (sin imágenes)")
            for i, m in enumerate(plan.get("momentos", []), 1)]


def num_momento(etiqueta):
    try:
        return int(str(etiqueta).split("·")[0].strip())
    except (ValueError, IndexError):
        return None


def area_de(plan, estilo):
    pl = plantilla(plan)
    if estilo == "completa" or "dividida" not in pl.get("layouts", {}):
        return pl["salida"]["ancho"], pl["salida"]["alto"]
    a = pl["layouts"]["dividida"]["inferior"]["area"]
    return a[2], a[3]


def imagen_vista(ruta_img, max_lado=900):
    img = ed.leer_img(ruta_img)
    if img is None:
        return None
    h, w = img.shape[:2]
    esc = min(1.0, max_lado / max(h, w))
    return cv2.resize(img, (int(w * esc), int(h * esc)), interpolation=cv2.INTER_AREA) if esc < 1 else img


def datos_momento(t, n):
    """Datos para el editor de movimiento: marcos de inicio/final de cada imagen del momento n."""
    plan, _ = cargar(t)
    pl = plantilla(plan)
    m = plan["momentos"][n - 1]
    w, h = area_de(plan, m.get("estilo", "dividida"))
    con_imgs = [x for x in plan.get("momentos", []) if x.get("imagenes")]
    lista = m.get("encuadres") or []
    imgs = []
    for k, ruta_img in enumerate(m.get("imagenes", [])):
        img = ed.leer_img(ruta_img)
        if img is None:
            continue
        ih, iw = img.shape[:2]
        guardado = k < len(lista) and isinstance(lista[k], dict) and bool(lista[k].get("inicio"))
        idx = (con_imgs.index(m) if m in con_imgs else 0) * 3 + k
        e = ed.encuadre_de(m, k, idx, pl["momentos"], img)
        a, b, suav = ed.marcos(e, iw, ih, w, h)
        imgs.append({"k": k, "url": f"/mov/img?t={quote(t)}&n={n}&k={k}&v={int(time.time())}",
                     "inicio": a, "fin": b, "suavizado": suav if guardado else "suave", "guardado": guardado})
    dur = (m["fin"] - m["inicio"]) / max(1, len(m.get("imagenes", [])))
    return {"estilo": m.get("estilo", "dividida"), "area": [w, h], "duracion_img": dur, "imagenes": imgs}


def iframe_editor(t, n):
    if not t or not n:
        return "<div style='padding:20px;color:#888'>Selecciona un momento.</div>"
    url = f"/mov/editor?t={quote(t)}&n={n}&v={int(time.time() * 1000)}"
    return (f'<iframe src="{url}" style="width:100%;height:760px;border:0;border-radius:12px"></iframe>'
            f'<div style="text-align:right;font-size:13px"><a href="{url}" target="_blank">Abrir el editor en otra ventana ↗</a></div>')


def iframe_subs(t):
    if not t:
        return "<div style='padding:20px;color:#888'>Carga o procesa un video para editar sus subtítulos.</div>"
    url = f"/sub/editor?t={quote(t)}&v={int(time.time() * 1000)}"
    return (f'<iframe src="{url}" style="width:100%;height:820px;border:0;border-radius:12px"></iframe>'
            f'<div style="text-align:right;font-size:13px"><a href="{url}" target="_blank">Abrir en otra ventana ↗</a></div>')


def iframe_pant(t):
    if not t:
        return "<div style='padding:20px;color:#888'>Carga o procesa un video.</div>"
    url = f"/pant/editor?t={quote(t)}&v={int(time.time() * 1000)}"
    return (f'<iframe src="{url}" style="width:100%;height:820px;border:0;border-radius:12px"></iframe>'
            f'<div style="text-align:right;font-size:13px"><a href="{url}" target="_blank">Abrir en otra ventana ↗</a></div>')


def iframe_enc(t):
    if not t:
        return "<div style='padding:20px;color:#888'>Carga o procesa un video para corregir el encuadre.</div>"
    url = f"/enc/editor?t={quote(t)}&v={int(time.time() * 1000)}"
    return (f'<iframe src="{url}" style="width:100%;height:900px;border:0;border-radius:12px"></iframe>'
            f'<div style="text-align:right;font-size:13px"><a href="{url}" target="_blank">Abrir en otra ventana ↗</a></div>')


TIPOS_ESCENA = {"persona": 0, "dividida": 1, "video": 2, "imagen": 3, "contenida": 4}
_CACHE_ENC = {}


def encajables(plan):
    """Tramos (tiempo original) con un video vertical que puede ir completo bajo el título o recortado:
    [inicio, fin, encajado ahora (1/0), 'toma' | 'pantalla']."""
    out = []
    for v in plan.get("verticales") or []:
        out.append([v["inicio"], v["fin"], 0 if v.get("encajar") is False else 1, "toma"])
    for p in plan.get("proyeccion", []):
        if ed.encajar_pv(dict(p, encajar=None)):
            out.append([p["inicio"], p["fin"], 0 if p.get("encajar") is False else 1, "pantalla"])
    return out


def guardar_encajar(t, momento, valor):
    """«Encajar completo» (True) o «Recortar» (False) para la toma o el video de la pantalla que se ve en 'momento'."""
    plan, _ = cargar(t)
    tt = float(momento)
    respaldar(t)
    hecho = None
    for p in plan.get("proyeccion", []):
        if p["inicio"] <= tt < p["fin"] and ed.encajar_pv(dict(p, encajar=None)):
            p["encajar"], hecho = bool(valor), "pantalla"
            break
    if not hecho:
        for v in plan.get("verticales") or []:
            if v["inicio"] <= tt < v["fin"]:
                v["encajar"], hecho = bool(valor), "toma"
                break
    if not hecho:
        return {"ok": False, "mensaje": "Aquí no hay un video vertical que encajar."}
    guardar_plan(t, plan)
    return {"ok": True, "mensaje": "Se ve completo bajo el título." if valor else "Se recorta para llenar la pantalla."}


def datos_encuadre(t):
    """Para el editor de encuadre: qué ventana del video original usa el armado automático cada 0.2 s,
    los tramos ya corregidos a mano y los cortes de pausas."""
    p_plan = Path(t) / "plan.json"
    plan, _ = cargar(t)
    pl = plantilla(plan)
    estilo = plan.get("estilo") or pl.get("estilo") or "chapucero"
    if estilo == "solo_subtitulos":
        return {"soportado": False, "motivo": "En «Solo subtítulos» no se recorta el video, no hay encuadre que corregir."}
    plan = ed.asegurar_util(t, plan, pl)   # tomas que son un video vertical con barras negras (una sola vez)
    info = plan["info"]
    # las muestras no cambian si solo cambian los ajustes a mano
    firma = json.dumps({k: plan.get(k) for k in ("tomas", "proyeccion", "momentos", "cortes", "encuadres", "cara",
                                                 "titulo", "titulo_fin", "plantilla", "transiciones_camara", "verticales")}, sort_keys=True, default=str)
    clave = (str(p_plan), hash(firma))
    if clave not in _CACHE_ENC:
        if estilo == "motivacional":
            moti = ed.estilo_motivacional()
            plan = dict(plan)
            plan["_pista_fija"] = moti.pista_fija_moti(plan, pl, plan.get("cara") or [[0.0, info["ancho"] / 2,
                                                       info["alto"] * 0.35, info["alto"] * 0.25, info["alto"] * 0.33]])
            escena = lambda tt: moti.escena_en(plan, pl, tt)  # noqa: E731
        else:
            ed.escalar_cajas(pl, info["ancho"], info["alto"])
            plan_fijo = ed.fijar_plan(plan, pl)
            escena = lambda tt: ed.escena_en(plan_fijo, pl, tt)  # noqa: E731
        # cambios de escena exactos: las muestras van cada 0.2 s y la vista previa cambiaba de escena hasta
        # 0.2 s tarde (se veía la escena anterior con el encuadre de la siguiente); se busca el cuadro del cambio
        def llave(e):
            return (e["tipo"], e.get("mom", -1), e.get("pv", -1), e.get("arr", -1), bool(e.get("ganso")),
                    bool(e.get("encajar")), tuple(round(v) for v in e.get("region") or ()))
        paso = 0.2
        muestras, extra, pvwin, arriba, ganso = [], [], [], [], []
        llaves = []
        n = int(info["duracion"] / paso) + 1
        for i in range(n):
            tt = round(i * paso, 3)
            e = escena(tt)
            llaves.append(llave(e))
            fila = [tt, TIPOS_ESCENA[e["tipo"]]]
            arriba.append(e.get("arr", -1))
            ganso.append(1 if e.get("ganso") else 0)
            if "auto" in e:
                fila += [round(v, 1) for v in e["region"]] + [round(e["aspect"], 5)] + [round(v, 1) for v in e["auto"]]
            muestras.append(fila)
            # para la vista previa armada (subtítulos): qué imagen o qué parte de la pantalla de Nacho se ve
            ex = [e.get("mom", -1), e.get("pv", -1)]
            if e["tipo"] == "contenida":
                ex += [round(v, 1) for v in e["region"]] + [1 if e.get("lay") == "dividida" else 0,
                                                            1 if e.get("encajar") else 0]
            extra.append(ex)
            # recuadro de lo que proyecta Nacho (abajo en la dividida o imagen fija a pantalla completa)
            pw = e.get("pv_ventana")
            pvwin.append([round(v, 1) for v in pw["region"]] + [round(pw["aspect"], 5)] +
                         [round(v, 1) for v in pw["auto"]] if pw else 0)
        cambios, fps_v = {}, float(info.get("fps") or 30.0)
        for i in range(n - 1):
            if llaves[i] != llaves[i + 1]:
                a_, b_ = i * paso, (i + 1) * paso
                while b_ - a_ > 0.5 / fps_v:
                    m_ = (a_ + b_) / 2
                    if llave(escena(m_)) == llaves[i]:
                        a_ = m_
                    else:
                        b_ = m_
                cambios[i] = round(b_, 4)
        W, H = pl["salida"]["ancho"], pl["salida"]["alto"]
        areas = {"persona": [0, 0, W, H], "video": [0, 0, W, H]}
        if "layouts" in pl:
            areas["persona"] = pl["layouts"]["persona"]["persona"]["area"]
            if "dividida" in pl["layouts"]:   # «Tiktoks Gaby» no tiene pantalla dividida
                areas["dividida"] = pl["layouts"]["dividida"]["persona"]["area"]
            if "ganso" in pl["layouts"]:
                areas["ganso"] = pl["layouts"]["ganso"]["persona"]["area"]
        _CACHE_ENC.clear()
        _CACHE_ENC[clave] = {"paso": paso, "muestras": muestras, "extra": extra, "pvwin": pvwin, "cambios": cambios,
                             "arriba": arriba if any(a >= 0 for a in arriba) else None,
                             "ganso": ganso if any(ganso) else None,
                             "salida": [W, H], "areas": areas,
                             "armado": datos_armado(plan, pl)}
    base = _CACHE_ENC[clave]
    return {"soportado": True, "estilo": estilo, **base,
            "video": {"ancho": info["ancho"], "alto": info["alto"], "duracion": info["duracion"], "fps": info["fps"],
                      "archivo": Path(plan["video"]).name},
            "ajustes": plan.get("encuadre_manual") or [],
            "ajustes_pantalla": plan.get("encuadre_pantalla") or [],
            "encajables": encajables(plan),
            "audio_tramos": plan.get("audio_tramos") or [],   # secciones de audio con su volumen (0 = silencio)
            # dónde puede ir el recuadro de la pantalla de Nacho (de su cámara a la orilla derecha, de arriba a abajo)
            "zona_pantalla": zona_de(plan),
            # franjas desenfocadas sobre los subtítulos que ya trae el video de Nacho (tiempo y px del original)
            "difuminar": plan.get("difuminar") or [],
            "difuminar_busqueda": estado_difuminar(t),
            # stickers animados (tiempo del original; posición y tamaño relativos al video vertical)
            "stickers": plan.get("stickers") or [],
            "catalogo_stickers": [{"tipo": a, "nombre": b, "color": c, "tam": d} for a, b, c, d in ed.CATALOGO_STICKERS
                                  if (ed.DIR_STICKERS / f"{a}.png").exists()],
            "meta_stickers": ed.meta_stickers(),
            **estado_proxy(t, plan),
            "cortes": [{"inicio": c["inicio"], "fin": c["fin"]} for c in ed.unir_cortes(plan.get("cortes", []))],
            # cada corte tal cual (pausas que quitó el automático y tramos quitados a mano), para verlos y ajustarlos
            "cortes_detalle": [{"inicio": c["inicio"], "fin": c["fin"], "manual": bool(c.get("manual")),
                                "hasta_final": bool(c.get("hasta_final"))}
                               for c in sorted(plan.get("cortes", []), key=lambda c: c["inicio"])],
            "titulo": bool(plan.get("titulo")) and (estilo == "motivacional" or bool(pl.get("titulo", {}).get("barra")))}


_CACHE_MARCOS = {}


def marcos_momento(m, plan, pl):
    """Movimiento de cada foto del momento, igual que en el render: [[marco_inicio, marco_final, suavizado], ...]
    con marcos normalizados [x, y, ancho, alto] de la foto."""
    if not m.get("imagenes"):
        return []
    W, H = pl["salida"]["ancho"], pl["salida"]["alto"]
    moti = (plan.get("estilo") or pl.get("estilo")) == "motivacional"
    if moti or m.get("estilo") == "completa" or "layouts" not in pl:
        w, h = W, H
    elif m.get("estilo") == "arriba":   # en el lugar de Nacho, debajo de la barra del título
        ax_, ay_, w, h = pl["layouts"]["dividida"]["persona"]["area"]
        h -= max(0, min(h - 40, ed.tope_imagen_arriba(plan, pl) - ay_))
    else:
        w, h = pl["layouts"]["dividida"]["inferior"]["area"][2:4]
    cfg_m = pl.get("momentos", {})
    visibles = [x for x in plan.get("momentos", []) if x.get("imagenes") and not x.get("oculto")]
    pos = next((i for i, x in enumerate(visibles) if x is m), 0)
    out = []
    for k, ruta_img in enumerate(m["imagenes"]):
        clave = (ruta_img, Path(ruta_img).stat().st_mtime if Path(ruta_img).exists() else 0)
        if clave not in _CACHE_MARCOS:
            img = ed.leer_img(ruta_img)
            _CACHE_MARCOS[clave] = (img.shape[1], img.shape[0], ed.foco_auto(img)) if img is not None else None
        dat = _CACHE_MARCOS[clave]
        if dat is None:
            out.append(None)
            continue
        iw, ih, foco = dat
        e = ed.encuadre_de(m, k, 0 if moti else pos * 3 + k, cfg_m)   # mismo orden que el render
        lista = m.get("encuadres") or []
        if not (k < len(lista) and isinstance(lista[k], dict) and "fx" in lista[k]):
            e["fx"], e["fy"] = foco   # el render centra en lo importante de la foto
        a, b, suav = ed.marcos(e, iw, ih, w, h)
        out.append([[round(v, 5) for v in a], [round(v, 5) for v in b], suav])
    return out


_COPIA_LOCK = threading.Lock()   # copia H.264 de «Solo subtítulos» (una a la vez)
_PROXY_TRABAJOS = {}   # carpeta de trabajo -> proceso que está preparando su vista previa fluida
_PROXY_FALLO = {}

# ----------------------------------------------------------------------------
# Cancelar todo: cada proceso que arranca la interfaz se registra aquí para poder detenerlo
# (junto con lo que él abrió: ffmpeg, Whisper…) con el botón «⛔ Cancelar todo».
# ----------------------------------------------------------------------------
import signal  # noqa: E402

_ACTIVOS = set()
_ACTIVOS_LOCK = threading.Lock()
_CANCELADO = [0.0]   # hora del último «Cancelar todo»


def lanzar(cmd, **kw):
    """subprocess.Popen que se puede cancelar. En su propio grupo para detener también a sus hijos."""
    if os.name == "nt":
        kw.setdefault("creationflags", subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        kw.setdefault("start_new_session", True)
    proc = subprocess.Popen(cmd, **kw)
    proc._inicio = time.time()
    with _ACTIVOS_LOCK:
        for x in [x for x in _ACTIVOS if x.poll() is not None]:
            _ACTIVOS.discard(x)
        _ACTIVOS.add(proc)
    return proc


def fue_cancelado(proc):
    """True si «Cancelar todo» se presionó mientras este proceso trabajaba."""
    return _CANCELADO[0] >= getattr(proc, "_inicio", time.time())


def _matar(proc):
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":   # /T = con todo lo que abrió (ffmpeg, etc.)
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass


# ----------------------------------------------------------------------------
# «Renderizar de nuevo» desde la pestaña Edición: arma otra vez el video con la edición actual (imágenes, pantalla
# dividida, encuadres, cortes) para que la pestaña Subtítulos tenga el acomodo nuevo. Corre en segundo plano.
# ----------------------------------------------------------------------------
_RENDER_EDI = {}   # carpeta _trabajo -> {"proc", "log"}


def renderizar_de_nuevo(t):
    actual = _RENDER_EDI.get(t)
    if actual and actual["proc"].poll() is None:
        return {"ok": True, "mensaje": "Ya se está renderizando."}
    try:
        gpu = ed.nvenc_disponible()
    except Exception:
        gpu = False
    # --previa: solo la vista previa ligera (mitad de tamaño, 15 cps), sin el video final: mucho más rápido
    cmd = [sys.executable, str(BASE / "editor.py"), "render", t, "--previa"] + (["--gpu", "--solo-gpu"] if gpu else [])
    log = Path(t) / "render_edicion.log"
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    f = open(log, "w", encoding="utf-8")
    proc = lanzar(cmd, cwd=str(BASE), env=env, stdout=f, stderr=subprocess.STDOUT)
    _RENDER_EDI[t] = {"proc": proc, "log": log, "archivo": f}
    registrar("─" * 60)
    registrar(f"▶ Vista previa ligera (desde Edición): {Path(t).name}")
    return {"ok": True, "mensaje": "Armando la vista previa con la edición actual…"}


def estado_render_edicion(t):
    r = _RENDER_EDI.get(t)
    if not r:
        return {"estado": "nada"}
    proc, log = r["proc"], r["log"]
    lineas = log.read_text(encoding="utf-8", errors="ignore").splitlines() if log.exists() else []
    prog, etapa = 0.0, "Preparando"
    for ln in reversed(lineas):
        if ln.startswith("@@PROGRESO@@"):
            try:
                v, etapa = ln.split(" ", 1)[1].split("|", 1)
                prog = float(v)
            except ValueError:
                pass
            break
    if proc.poll() is None:
        return {"estado": "trabajando", "progreso": round(prog, 3), "etapa": etapa}
    try:
        r["archivo"].close()
    except Exception:
        pass
    if proc.returncode == 0:
        if not r.get("avisado"):
            r["avisado"] = True
            registrar("✔ Vista previa lista: Subtítulos ya tiene el acomodo nuevo")
        return {"estado": "listo"}
    if fue_cancelado(proc):
        return {"estado": "cancelado"}
    utiles = [x for x in lineas if x.strip() and not x.startswith("@@")][-4:]
    if not r.get("avisado"):
        r["avisado"] = True
        registrar("✖ Falló la vista previa desde Edición: " + " | ".join(utiles)[-300:])
    return {"estado": "error", "detalle": "\n".join(utiles)[-600:]}


# ----------------------------------------------------------------------------
# Difuminar los subtítulos que ya trae el video de Nacho
# ----------------------------------------------------------------------------
_DIF_PROC = {}


def guardar_difuminar(t, lista):
    plan, _ = cargar(t)
    W, H = plan["info"]["ancho"], plan["info"]["alto"]
    dur = plan["info"]["duracion"]
    limpios = []
    for d in lista or []:
        try:
            a, b = max(0.0, float(d["inicio"])), min(dur, float(d["fin"]))
            x, y, w, h = [float(v) for v in d["caja"]]
        except (KeyError, TypeError, ValueError):
            continue
        x, y = max(0.0, min(x, W - 8)), max(0.0, min(y, H - 8))
        w, h = max(8.0, min(w, W - x)), max(8.0, min(h, H - y))
        if b - a < 0.099:
            continue
        limpios.append({"inicio": round(a, 3), "fin": round(b, 3), "caja": [int(x), int(y), int(w), int(h)],
                        "auto": bool(d.get("auto"))})
    limpios.sort(key=lambda d: d["inicio"])
    respaldar(t)
    plan["difuminar"] = limpios
    guardar_plan(t, plan)
    return limpios


def guardar_stickers(t, lista):
    plan, _ = cargar(t)
    dur = plan["info"]["duracion"]
    tipos = {a: c for a, _, c, _ in ed.CATALOGO_STICKERS}
    limpios = []
    for d in lista or []:
        try:
            tipo = str(d["tipo"])
            a, b = max(0.0, float(d["inicio"])), min(dur, float(d["fin"]))
            x, y = float(d.get("x", 0.5)), float(d.get("y", 0.5))
            tam = float(d.get("tam", 0.35))
            rot = float(d.get("rot", 0) or 0)
        except (KeyError, TypeError, ValueError):
            continue
        if tipo not in tipos or b - a < 0.099:
            continue
        color = str(d.get("color") or tipos[tipo])
        if not (len(color) == 7 and color.startswith("#") and all(ch in "0123456789abcdefABCDEF" for ch in color[1:])):
            color = tipos[tipo]
        limpios.append({"tipo": tipo, "inicio": round(a, 3), "fin": round(b, 3),
                        "x": round(max(-0.2, min(1.2, x)), 4), "y": round(max(-0.2, min(1.2, y)), 4),
                        "tam": round(max(0.04, min(1.5, tam)), 4), "prop": ed.prop_sticker(d),
                        "rot": round(((rot + 180) % 360) - 180, 1),
                        "color": color.lower(), "espejo": bool(d.get("espejo"))})
    limpios.sort(key=lambda d: d["inicio"])
    # los stickers se dibujan en vivo en la vista previa: cambiarlos no la deja «desactualizada»
    vpm = Path(t) / "vista_previa.mp4"
    al_dia = vpm.exists() and (Path(t) / "plan.json").stat().st_mtime <= vpm.stat().st_mtime + 1
    respaldar(t)
    plan["stickers"] = limpios
    guardar_plan(t, plan)
    if al_dia:
        try:
            os.utime(vpm, None)
        except OSError:
            pass
    return limpios


def buscar_difuminar(t):
    proc = _DIF_PROC.get(t)
    if proc is not None and proc.poll() is None:
        return {"ok": True, "mensaje": "Ya se está buscando."}
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    respaldar(t)
    _DIF_PROC[t] = lanzar([sys.executable, str(BASE / "editor.py"), "difuminar", t], cwd=str(BASE), env=env,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    registrar(f"▶ Buscando subtítulos en los videos de Nacho: {Path(t).name}")
    return {"ok": True, "mensaje": "Buscando los subtítulos que trae el video de Nacho…"}


def estado_difuminar(t):
    proc = _DIF_PROC.get(t)
    if proc is None:
        return "nada"
    if proc.poll() is None:
        return "buscando"
    if proc.returncode == 0:
        return "listo"
    return "cancelado" if fue_cancelado(proc) else "error"


def soltar_otros(t):
    """Al abrir otro trabajo: se detienen las vistas previas, copias ligeras y difuminados que seguían trabajando
    para los trabajos anteriores (le quitaban procesador al actual). La exportación y el video largo no se tocan."""
    t = str(t or "")
    n = 0
    for reg in (_PROXY_TRABAJOS, _DIF_PROC, _RENDER_EDI):
        for k in list(reg):
            v = reg[k]
            proc = v.get("proc") if isinstance(v, dict) else v
            if str(k) == t or proc is None:
                continue
            if proc.poll() is None:
                _matar(proc); n += 1
            reg.pop(k, None)
    if n:
        registrar(f"🧹 Se detuvieron {n} proceso(s) que seguían trabajando para otro trabajo")
    return n


def cancelar_todo():
    """Detiene todo lo que esté trabajando: análisis, exportación, conversión, vistas previas,
    búsqueda de clips del video largo y la cola de fragmentos pendientes."""
    _CANCELADO[0] = time.time()
    en_cola = 0
    while True:   # los fragmentos que esperaban en la cola ya no se hacen
        try:
            nombre, fids, _gpu = _COLA.get_nowait()
        except queue.Empty:
            break
        try:
            for fid in (fids if isinstance(fids, (list, tuple)) else [fids]):
                actualizar_frag(carpeta_frag(nombre)[1], fid, estado="cancelado", detalle="Cancelado")
        except Exception:
            pass
        _COLA.task_done()
        en_cola += 1
    with _ACTIVOS_LOCK:
        vivos = [x for x in _ACTIVOS if x.poll() is None]
    for x in vivos:
        _matar(x)
    _PROXY_FALLO.clear()   # lo cancelado se puede volver a intentar solo
    registrar("─" * 60)
    registrar(f"⛔ Cancelado: {len(vivos)} proceso(s) detenidos" + (f", {en_cola} fragmento(s) sacados de la cola" if en_cola else ""))
    return len(vivos), en_cola


def estado_proxy(t, plan=None, arrancar=True):
    """{"proxy": {...} o None, "preparando": bool}. Si la copia ligera falta o ya no corresponde a las pausas
    actuales, se prepara sola en segundo plano."""
    plan = plan or cargar(t)[0]
    if estilo_de(plan) == "solo_subtitulos":
        return {"proxy": None, "preparando": False}
    firma = ed.firma_cortes(plan)
    pj, pm = Path(t) / "proxy.json", Path(t) / "proxy.mp4"
    if pj.exists() and pm.exists():
        info = ed.cargar_json(pj)
        if info.get("firma") == firma:
            return {"proxy": {"firma": firma, "ancho": info["ancho"], "alto": info["alto"]}, "preparando": False}
    proc = _PROXY_TRABAJOS.get(t)
    if proc is not None and proc.poll() is None:
        return {"proxy": None, "preparando": True}
    if proc is not None and proc.returncode != 0 and _PROXY_FALLO.get(t) == firma:
        return {"proxy": None, "preparando": False}   # ya falló con estas mismas pausas: no se reintenta solo
    if proc is not None and proc.returncode != 0:
        _PROXY_FALLO[t] = firma
        return {"proxy": None, "preparando": False}
    if arrancar:
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        _PROXY_TRABAJOS[t] = lanzar([sys.executable, str(BASE / "editor.py"), "proxy", t], cwd=str(BASE), env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"proxy": None, "preparando": True}
    return {"proxy": None, "preparando": False}


_CORTINILLA = {}


def info_cortinilla(pl):
    """Datos de la cortinilla limpia para las vistas previas (None si el estilo no la usa)."""
    cfg = pl.get("transicion_camara") or {}
    if not cfg.get("activar"):
        return None
    clave = str(cfg.get("video"))
    if clave not in _CORTINILLA:
        it = ed.info_transicion(cfg)
        _CORTINILLA[clave] = {"n": it["cuadros"], "fps": it["fps"], "duracion": it["duracion"], "w": 270, "h": 480} if it else None
    return _CORTINILLA[clave]


def sprite_cortinilla(pl):
    """Todos los cuadros de la cortinilla limpia en una sola imagen (uno debajo de otro), en chico."""
    cfg = pl.get("transicion_camara") or {}
    it = ed.info_transicion(cfg)
    if not it:
        return None
    cap = cv2.VideoCapture(it["ruta"])
    cuadros = []
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        cuadros.append(cv2.resize(fr, (270, 480), interpolation=cv2.INTER_AREA))
    cap.release()
    ok, buf = cv2.imencode(".jpg", np.vstack(cuadros), [cv2.IMWRITE_JPEG_QUALITY, 88])
    return buf.tobytes() if ok else None


def accion_transiciones(t, d):
    """Pestaña Edición: agregar / quitar una transición de cámara en un momento, o volver a buscarlas."""
    plan, _ = cargar(t)
    pl = plantilla(plan)
    cfg = pl.get("transicion_camara") or {}
    if not cfg.get("activar"):
        raise ValueError("Este estilo no usa la cortinilla de cambio de cámara")
    trans = list(plan.get("transiciones_camara") or [])
    acc = d.get("accion")
    respaldar(t)
    if acc == "buscar":
        trans = ed.detectar_transiciones(plan["video"], plan["info"], cfg)
        msg = f"{len(trans)} transición(es) encontradas."
    elif acc == "agregar":
        it = ed.info_transicion(cfg)
        a = max(0.0, float(d["t_orig"]))
        trans = [x for x in trans if not (x["inicio"] - 0.01 <= a < x["fin"])]
        trans.append({"inicio": round(a, 4), "fin": round(min(plan["info"]["duracion"], a + it["duracion"]), 4), "manual": True})
        msg = "Transición agregada aquí."
    elif acc == "quitar":
        a = float(d["t_orig"])
        antes = len(trans)
        trans = [x for x in trans if not (x["inicio"] - 0.05 <= a < x["fin"] + 0.05)]
        msg = "Transición quitada." if len(trans) < antes else "Aquí no hay transición."
    else:
        raise ValueError("Acción desconocida")
    trans.sort(key=lambda x: x["inicio"])
    plan["transiciones_camara"] = trans
    # que las pausas recortadas solas no se coman la cortinilla (los tramos quitados a mano se respetan)
    auto = [c for c in plan.get("cortes", []) if not c.get("manual")]
    man = [c for c in plan.get("cortes", []) if c.get("manual")]
    plan["cortes"] = sorted(ed.respetar_transiciones(auto, trans) + man, key=lambda c: c["inicio"])
    guardar_plan(t, plan)
    return msg, len(trans)


def datos_armado(plan, pl):
    """Lo que necesita la vista previa armada en vivo (pestaña Subtítulos): diseño de la plantilla,
    tramos de la pantalla de Nacho e imágenes de los momentos."""
    cfg_p = pl.get("proyeccion", {})
    L = pl.get("layouts", {})
    div = L.get("dividida", {})

    def acomodo(d):
        return {"persona": d.get("persona", {}).get("area"), "franja": d.get("franja", {}).get("area"),
                "franja_fondo": bool(d.get("franja", {}).get("fondo")), "inferior": d.get("inferior", {}).get("area")}
    return {
        "tope_arriba": ed.tope_imagen_arriba(plan, pl),   # la imagen «arriba» empieza debajo del título
        "dividida": acomodo(div),
        **({"ganso": acomodo(L["ganso"])} if "ganso" in L else {}),
        "contener": {k: L.get("persona", {}).get("persona", {}).get(k, v)
                     for k, v in (("ancho_panel", 0.593), ("margen_sup_panel", 110), ("desenfoque", 22),
                                  ("oscurecer_fondo", 0.85))},
        "zoom_imagen": cfg_p.get("zoom_imagen", 1.5),
        "imagen_izquierda": bool(cfg_p.get("imagen_izquierda")),
        "proyeccion": [{"inicio": p["inicio"], "fin": p["fin"], "caja": [float(v) for v in (p.get("caja") or [0, 0, 1, 1])],
                        "tipo": p["tipo"], "documento": bool(p.get("documento")), "vertical": bool(p.get("vertical"))}
                       for p in plan.get("proyeccion", [])],
        "momentos": [{"inicio": m["inicio"], "fin": m["fin"], "estilo": m.get("estilo", "dividida"),
                      "n": len(m.get("imagenes") or []), "marcos": marcos_momento(m, plan, pl)}
                     for m in plan.get("momentos", [])],
        "titulo_fin": plan.get("titulo_fin", 3.0) if plan.get("titulo") else 0,
        # transiciones de cambio de cámara de Nacho (tiempo original) y la cortinilla limpia que las tapa
        "transiciones": [[t_["inicio"], t_["fin"]] for t_ in plan.get("transiciones_camara") or []],
        "cortinilla": info_cortinilla(pl),
        # «Tiktoks Gaby»: video de fondo en movimiento detrás de la franja de la persona
        "fondo": bool((pl.get("fondo") or {}).get("video")),
    }


# ----------------------------------------------------------------------------
# Área de Edición (editor unificado: pantalla, imágenes, encuadre, cortes y título)
# ----------------------------------------------------------------------------
def poner_imagenes(m, nuevas, reemplazar=False):
    if not reemplazar:
        previas = list(m.get("imagenes", []))
        enc = list(m.get("encuadres") or [])
        enc += [{}] * (len(previas) - len(enc))
        m["imagenes"] = previas + nuevas
        m["encuadres"] = enc[:len(previas)] + [{}] * len(nuevas)
    else:
        m["imagenes"] = nuevas
        m["encuadres"] = []


def buscar_para(t, plan, busqueda, prefijo):
    ed.cargar_aprendido()   # sitios a evitar / preferir aprobados
    pl = plantilla(plan)
    cfg = pl.get("momentos", {})
    return ed.buscar_imagenes([busqueda], cfg.get("imagenes_por_momento", 2), Path(t) / "imagenes", prefijo, ia(),
                              busqueda, cfg.get("max_candidatos", 8), cfg.get("puntaje_min", 7), usar_mejor=True)


def datos_edicion(t):
    """Lo que el editor unificado necesita además del armado: título, momentos y tramos quitados a mano."""
    plan, palabras = cargar(t)
    # silencios entre frases de Nacho (tiempo editado): ahí un corte se ve natural (el «imán» de la línea de tiempo)
    pausas = []
    for w1, w2 in zip(palabras, palabras[1:]):
        try:
            hueco = float(w2["i"]) - float(w1["f"])
        except (KeyError, TypeError, ValueError):
            continue
        if hueco >= 0.12:
            pausas.append(round(ed_t((float(w1["f"]) + float(w2["i"])) / 2, plan), 3))
    momentos = []
    for i, m in enumerate(plan.get("momentos", [])):
        momentos.append({"i": i, "inicio": m["inicio"], "fin": m["fin"], "estilo": m.get("estilo", "dividida"),
                         "oculto": bool(m.get("oculto")), "busqueda": m.get("busqueda", ""),
                         "prioridad": m.get("prioridad", "pantalla"),
                         # todo lo necesario para copiar y pegar el momento (Ctrl+C / Ctrl+V)
                         "datos": {k: m.get(k) for k in ("imagenes", "encuadres", "estilo", "prioridad", "busqueda",
                                                         "busquedas", "que_mostrar") if m.get(k) is not None},
                         "n": len(m.get("imagenes") or [])})
    manuales = [{"i": k, "inicio": c["inicio"], "fin": c["fin"]} for k, c in enumerate(plan.get("cortes", []))
                if c.get("manual")]
    vp = Path(t) / "vista_previa.json"
    previa_vieja = estilo_de(plan) != "solo_subtitulos" and (
        not vp.exists() or bool(ed.cargar_json(vp).get("provisional"))
        or (Path(t) / "plan.json").stat().st_mtime > vp.stat().st_mtime + 1)
    return {"titulo": plan.get("titulo", ""), "momentos": momentos, "cortes_manuales": manuales, "version": ed.VERSION,
            "previa_vieja": previa_vieja, "render": estado_render_edicion(t),
            "titulo_fin": plan.get("titulo_fin") if estilo_de(plan) == "motivacional" and plan.get("titulo")
            and not ed.estilo_motivacional().es_gaby(plantilla(plan)) else None,   # «Tiktoks Gaby»: el título va todo el video
            "pausas": pausas,
            "audio": datos_audio(plan),
            "portapapeles": montaje.portapapeles(t),
            "montaje": len(plan.get("montaje") or []) > 1 or bool(plan.get("montaje_n")),
            "estilo": estilo_de(plan), "historial": len(list((Path(t) / ".historial").glob("*_plan.json")))
            if (Path(t) / ".historial").exists() else 0}


def musica_de(plan):
    """Archivo de la música de fondo de la plantilla del trabajo (o None)."""
    try:
        m = (plantilla(plan).get("audio") or {}).get("musica")
    except Exception:
        return None
    p = ed.ruta(m) if m else None
    return p if p and Path(p).exists() else None


def datos_audio(plan):
    pl_a = (plantilla(plan).get("audio") or {}) if estilo_de(plan) != "solo_subtitulos" else {}
    return {"musica": bool(musica_de(plan)) and estilo_de(plan) != "solo_subtitulos",
            "base": pl_a.get("volumen_musica", 0.5), "mezcla": ed.mezcla_de(plan)}


def guardar_audio(t, musica, voz):
    plan, _ = cargar(t)
    respaldar(t)
    mez = {"musica": round(min(3.0, max(0.0, float(musica))), 3), "voz": round(min(3.0, max(0.0, float(voz))), 3)}
    if mez == {"musica": 1.0, "voz": 1.0}:
        plan.pop("audio_mezcla", None)
    else:
        plan["audio_mezcla"] = mez
    guardar_plan(t, plan)
    return mez


def accion_momento_http(t, d):
    """Cambios de los momentos con imagen. Tiempos que llegan: segundos del video ORIGINAL."""
    plan, _ = cargar(t)
    moms = plan.setdefault("momentos", [])
    acc = d.get("accion")
    if acc == "agregar":
        ini, fin = float(d["inicio"]), float(d["fin"])
        if fin - ini < 0.099:
            raise ValueError("El momento es muy corto")
        busq = (d.get("busqueda") or "").strip()
        m = {"inicio": round(ini, 3), "fin": round(fin, 3),
             "estilo": d.get("estilo") if d.get("estilo") in ("dividida", "completa", "arriba") else "dividida",
             "busqueda": busq, "busquedas": [busq] if busq else [], "que_mostrar": busq, "texto": "", "imagenes": [],
             "prioridad": "imagen"}   # puesta a mano: se ve aunque Nacho tenga algo en pantalla
        if busq:
            m["imagenes"] = buscar_para(t, plan, busq, f"momento_nuevo_{time.strftime('%H%M%S')}")
        respaldar(t)
        moms.append(m)
        moms.sort(key=lambda x: x["inicio"])
        guardar_plan(t, plan)
        return {"ok": True, "i": moms.index(m), "imagenes": len(m["imagenes"]),
                "mensaje": "Momento agregado." if m["imagenes"] or not busq else
                "Momento agregado, pero no encontré imágenes que sirvan: súbelas o busca otra cosa."}
    if acc == "pegar":
        # momento copiado (Ctrl+V): mismas fotos, movimiento y estilo, en otro lugar
        datos = d.get("datos") or {}
        ini, fin = float(d["inicio"]), float(d["fin"])
        if fin - ini < 0.099:
            raise ValueError("El momento es muy corto")
        imgs = [str(x) for x in (datos.get("imagenes") or []) if Path(str(x)).exists()]
        m = {k: json.loads(json.dumps(v)) for k, v in datos.items()
             if k in ("encuadres", "estilo", "prioridad", "busqueda", "busquedas", "que_mostrar")}
        m.update(inicio=round(ini, 3), fin=round(fin, 3), imagenes=imgs, texto="")
        m.setdefault("estilo", "dividida")
        m.setdefault("prioridad", "imagen")
        respaldar(t)
        moms.append(m)
        moms.sort(key=lambda x: x["inicio"])
        guardar_plan(t, plan)
        return {"ok": True, "i": moms.index(m), "mensaje": "Imagen pegada."}
    i = int(d["i"])
    if not 0 <= i < len(moms):
        raise ValueError("Ese momento no existe")
    m = moms[i]
    if acc == "dividir":
        # partir el momento en dos en el tiempo t (Ctrl+B)
        tc = float(d["t_corte"])
        if not (m["inicio"] + 0.099 <= tc <= m["fin"] - 0.099):
            raise ValueError("Pon el cursor dentro de la imagen (no tan cerca de sus orillas) para partirla")
        respaldar(t)
        m2 = json.loads(json.dumps(m))
        m["fin"], m2["inicio"] = round(tc, 3), round(tc, 3)
        moms.append(m2)
        moms.sort(key=lambda x: x["inicio"])
        guardar_plan(t, plan)
        return {"ok": True, "i": i, "mensaje": "Imagen partida en dos."}
    if acc == "guardar":
        if d.get("estilo") in ("dividida", "completa", "arriba"):
            m["estilo"] = d["estilo"]
            m["oculto"] = False
        if d.get("estilo") == "quitar":
            m["oculto"] = True
        if d.get("prioridad") in ("imagen", "pantalla"):
            m["prioridad"] = d["prioridad"]
        if d.get("inicio") is not None and d.get("fin") is not None and float(d["fin"]) - float(d["inicio"]) >= 0.3:
            m["inicio"], m["fin"] = round(float(d["inicio"]), 3), round(float(d["fin"]), 3)
        respaldar(t)
        moms.sort(key=lambda x: x["inicio"])
        guardar_plan(t, plan)
        return {"ok": True, "i": moms.index(m), "mensaje": "Imagen guardada."}
    if acc == "eliminar":
        respaldar(t)
        moms.pop(i)
        guardar_plan(t, plan)
        return {"ok": True, "i": -1, "mensaje": "Momento eliminado."}
    if acc == "buscar":
        busq = (d.get("busqueda") or "").strip()
        if not busq:
            raise ValueError("Escribe qué buscar")
        imgs = buscar_para(t, plan, busq, f"momento{i + 1:02d}_{time.strftime('%H%M%S')}")
        if not imgs:
            return {"ok": False, "i": i, "mensaje": f"No encontré imágenes que sirvan para «{busq}»."}
        respaldar(t)
        m.update(busqueda=busq, busquedas=[busq])
        poner_imagenes(m, imgs, bool(d.get("reemplazar")))
        guardar_plan(t, plan)
        return {"ok": True, "i": i, "mensaje": f"{len(imgs)} imágenes nuevas (ahora tiene {len(m['imagenes'])})."}
    raise ValueError("Acción desconocida")


def dividir_pantalla(t, i, tc):
    """Parte en dos un tramo de lo que proyecta Nacho en el tiempo tc (original), para que cada parte se vea distinto."""
    plan, _ = cargar(t)
    proy = plan.get("proyeccion", [])
    if not 0 <= i < len(proy):
        raise ValueError("Ese tramo no existe")
    p = proy[i]
    if not (p["inicio"] + 0.099 <= tc <= p["fin"] - 0.099):
        raise ValueError("Pon el cursor dentro del tramo (no tan cerca de sus orillas) para partirlo")
    respaldar(t)
    p2 = json.loads(json.dumps(p))
    p["fin"], p2["inicio"] = round(tc, 3), round(tc, 3)
    proy.append(p2)
    proy.sort(key=lambda x: x["inicio"])
    guardar_plan(t, plan)


def partir_escena(t, i, tc):
    """Parte en dos un tramo de Nacho (cerca/lejos) del estilo motivacional en el tiempo tc (original)."""
    plan, _ = cargar(t)
    es = plan.get("encuadres", [])
    if not 0 <= i < len(es):
        raise ValueError("Ese tramo no existe")
    e = es[i]
    if not (e["inicio"] + 0.099 <= tc <= e["fin"] - 0.099):
        raise ValueError("Pon el cursor dentro del tramo (cada parte de al menos 0.10 s) para partirlo")
    respaldar(t)
    e2 = json.loads(json.dumps(e))
    e["fin"], e2["inicio"] = round(tc, 3), round(tc, 3)
    es.insert(i + 1, e2)
    guardar_plan(t, plan)


def partir_toma(t, tc):
    """Parte en dos el bloque gris (la toma) en el tiempo tc (original), para mover o cambiar cada parte por separado."""
    plan, _ = cargar(t)
    tomas = plan.get("tomas", [])
    for k, sg in enumerate(tomas):
        if sg["inicio"] + 0.099 <= tc <= sg["fin"] - 0.099:
            respaldar(t)
            s2 = json.loads(json.dumps(sg))
            sg["fin"], s2["inicio"] = round(tc, 3), round(tc, 3)
            tomas.insert(k + 1, s2)
            guardar_plan(t, plan)
            return
    raise ValueError("Pon el cursor dentro del bloque (no tan cerca de sus orillas) para partirlo")


def guardar_audio_tramos(t, tramos):
    """Secciones del audio separadas en Edición, cada una con su volumen (0 = silenciada, 1 = normal)."""
    plan, _ = cargar(t)
    dur = float(plan["info"]["duracion"])
    limpios = []
    for x in tramos or []:
        try:
            a, b = max(0.0, float(x["inicio"])), min(dur, float(x["fin"]))
            g = max(0.0, min(4.0, float(x.get("ganancia", 1.0))))
        except (TypeError, ValueError, KeyError):
            continue
        if b - a >= 0.02:
            limpios.append({"inicio": round(a, 3), "fin": round(b, 3), "ganancia": round(g, 3)})
    limpios.sort(key=lambda x: x["inicio"])
    respaldar(t)
    plan["audio_tramos"] = limpios
    guardar_plan(t, plan)
    return len(limpios)


def mover_frontera_toma(t, de, a):
    """Recorre el punto donde se partió un bloque gris (la orilla entre dos tomas seguidas). Tiempos del original."""
    plan, _ = cargar(t)
    tomas = plan.get("tomas", [])
    for k in range(len(tomas) - 1):
        if abs(tomas[k]["fin"] - de) < 0.08 and abs(tomas[k + 1]["inicio"] - de) < 0.08:
            a = min(max(a, tomas[k]["inicio"] + 0.1), tomas[k + 1]["fin"] - 0.1)
            respaldar(t)
            tomas[k]["fin"] = tomas[k + 1]["inicio"] = round(a, 3)
            guardar_plan(t, plan)
            return
    raise ValueError("Ahí no hay un corte entre dos bloques para mover")


def guardar_subidas(t, i, archivos, reemplazar):
    plan, _ = cargar(t)
    moms = plan.get("momentos", [])
    if not 0 <= i < len(moms):
        raise ValueError("Ese momento no existe")
    destino = Path(t) / "imagenes"
    destino.mkdir(exist_ok=True)
    nuevas = []
    for k, (nombre, datos) in enumerate(archivos, 1):
        ext = Path(nombre).suffix.lower() or ".jpg"
        if ext not in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
            continue
        p = destino / f"usuario_m{i + 1:02d}_{time.strftime('%H%M%S')}_{k}{ext}"
        p.write_bytes(datos)
        nuevas.append(str(p))
    if not nuevas:
        raise ValueError("No llegó ninguna imagen válida")
    respaldar(t)
    poner_imagenes(moms[i], nuevas, reemplazar)
    guardar_plan(t, plan)
    return {"ok": True, "i": i, "mensaje": f"Ahora tiene {len(moms[i]['imagenes'])} imagen(es)."}


def captura_pantalla(t, d):
    """📸 Captura de TODO el cuadro del video horizontal (calidad completa) en el punto donde va la reproducción;
    con el recuadro de la imagen se elige qué parte se usa. Se agrega al momento con imagen de ese punto, o crea uno nuevo."""
    plan, _ = cargar(t)
    tiempo = max(0.0, min(float(d["tiempo"]), float(plan["info"]["duracion"]) - 0.05))
    W, H = int(plan["info"]["ancho"]), int(plan["info"]["alto"])
    # todo el cuadro del video: ya con el recuadro de la imagen se elige qué parte se ve
    caja = d.get("caja") or [0, 0, W, H]
    x, y, w, h = [float(v) for v in caja]
    x, y = max(0, int(x)), max(0, int(y))
    w, h = int(min(w, W - x)), int(min(h, H - y))
    w, h = w - w % 2, h - h % 2
    if w < 40 or h < 40:
        raise ValueError("No encontré la pantalla de Nacho en este punto")
    destino = Path(t) / "imagenes"
    destino.mkdir(exist_ok=True)
    tmp = destino / f"captura_{time.strftime('%H%M%S')}_{int(time.time() * 1000) % 1000:03d}.png"
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{tiempo:.3f}", "-i", str(plan["video"]),
                        "-frames:v", "1", "-vf", f"crop={w}:{h}:{x}:{y}", str(tmp)], capture_output=True, text=True)
    if r.returncode != 0 or not tmp.exists():
        raise ValueError("No se pudo tomar la captura: " + (r.stderr or "")[-200:])
    datos = tmp.read_bytes()
    tmp.unlink(missing_ok=True)
    i = d.get("i")
    nuevo = i is None or int(i) < 0
    if nuevo:
        i = accion_momento_http(t, {"accion": "agregar", "inicio": d["inicio"], "fin": d["fin"],
                                    "estilo": d.get("estilo") or "dividida", "busqueda": ""})["i"]
    try:
        guardar_subidas(t, int(i), [("captura.png", datos)], False)
    except Exception:
        if nuevo:
            accion_momento_http(t, {"accion": "eliminar", "i": int(i)})
        raise
    return {"ok": True, "i": int(i), "mensaje": "📸 Captura agregada como imagen. Muévela o estírala en la línea de tiempo."
            if nuevo else "📸 Captura agregada a las fotos de esta imagen."}


def limpiar_titulo(titulo):
    """Quita espacios sobrantes y deja hasta tres renglones (Enter = otro renglón)."""
    return "\n".join(ed.lineas_titulo(titulo, 3))


def guardar_titulo_ajuste(t, tam=None, inter=None):
    """Tamaño de la letra del título (None = automático) y su interlineado (-100…+100 %, 0 = el normal)."""
    plan, _ = cargar(t)
    respaldar(t)
    if tam in (None, "", 0, "auto"):
        plan.pop("titulo_tam", None)
    else:
        plan["titulo_tam"] = max(12, min(600, int(float(tam))))
    if inter is not None:
        v = max(-100, min(100, int(round(float(inter)))))
        if v:
            plan["titulo_inter"] = v
        else:
            plan.pop("titulo_inter", None)
    guardar_plan(t, plan)
    return info_titulo(t)


def info_titulo(t):
    """Tamaño de letra con que sale hoy el título (para mostrarlo en los controles) y los ajustes guardados."""
    plan, _ = cargar(t)
    pl = plantilla(plan)
    usado = None
    try:
        cfg = pl.get("titulo")
        if isinstance(cfg, dict) and plan.get("titulo"):
            cfg = dict(cfg)
            pl2 = dict(pl, titulo=cfg)
            if estilo_de(plan) == "motivacional":
                ed.estilo_motivacional().capa_titulo(cfg, plan["titulo"], pl["salida"]["ancho"], pl["salida"]["alto"])
            else:
                ed.capa_titulo(pl2, plan["titulo"], 1080, 1920)
            usado = cfg.get("_usado")
    except Exception:
        usado = None
    return {"tam": plan.get("titulo_tam"), "inter": plan.get("titulo_inter", 0), "usado": usado}


def guardar_titulo(t, titulo, en_video=None):
    plan, _ = cargar(t)
    respaldar(t)
    plan["titulo"] = limpiar_titulo(titulo)
    if en_video is not None:   # «Solo subtítulos»: poner o no la barra del título encima del clip
        plan["titulo_en_video"] = bool(en_video)
    guardar_plan(t, plan)


def quitar_tramo(t, a, b, al_final=False):
    """Quita del video un tramo (a, b en segundos del video ORIGINAL). al_final / un «hasta» en el último cuadro:
    se quita todo lo que sigue (no se cuela el último cuadro)."""
    plan, _ = cargar(t)
    if b - a < 0.005:
        raise ValueError("El tramo es muy corto")
    fps = plan["info"]["fps"]
    dur = float(plan["info"]["duracion"])
    # al cuadro más cercano; un tramo de centésimas siempre quita al menos un cuadro
    ca = int(round(float(a) * fps))
    cb = max(int(round(float(b) * fps)), ca + 1)
    a2, b2 = round(ca / fps, 4), round(cb / fps, 4)
    corte = {"inicio": a2, "fin": b2, "manual": True}
    if al_final or b2 >= dur - 1.5 / fps:
        corte.update(fin=round(dur, 4), hasta_final=True)
    respaldar(t)
    plan.setdefault("cortes", []).append(corte)
    plan["cortes"].sort(key=lambda c: c["inicio"])
    guardar_plan(t, plan)


def ajustar_corte(t, inicio0, fin0, inicio=None, fin=None, recuperar=False):
    """Cambia un corte (pausa quitada por el automático o tramo quitado a mano), encontrado por sus tiempos de antes
    (segundos del video ORIGINAL). recuperar=True o si queda de menos de 2 centésimas: se quita el corte (vuelve todo)."""
    plan, _ = cargar(t)
    cs = plan.get("cortes", [])
    k = next((n for n, c in enumerate(cs) if abs(c["inicio"] - inicio0) < 0.003 and abs(c["fin"] - fin0) < 0.003), None)
    if k is None:
        raise ValueError("Ese corte ya no existe (recarga la pestaña)")
    respaldar(t)
    if recuperar:
        cs.pop(k)
        guardar_plan(t, plan)
        return {"ok": True, "mensaje": "Corte recuperado: ese pedazo vuelve al video."}
    dur = float(plan["info"]["duracion"])
    otros = sorted([c for n, c in enumerate(cs) if n != k], key=lambda c: c["inicio"])
    antes = max([c["fin"] for c in otros if c["fin"] <= inicio0 + 1e-6] or [0.0])
    despues = min([c["inicio"] for c in otros if c["inicio"] >= fin0 - 1e-6] or [dur])
    a = max(antes, min(float(inicio), dur))
    b = min(despues, max(float(fin), 0.0))
    if b - a < 0.02:
        cs.pop(k)
        guardar_plan(t, plan)
        return {"ok": True, "mensaje": "Corte recuperado: ese pedazo vuelve al video."}
    cs[k]["inicio"], cs[k]["fin"] = round(a, 4), round(b, 4)
    if cs[k].get("hasta_final") and b < dur - 0.01:
        cs[k].pop("hasta_final", None)
    guardar_plan(t, plan)
    return {"ok": True, "mensaje": f"Corte ajustado: ahora quita {b - a:.2f} s."}


_ONDA_LOCK = threading.Lock()


def onda_de(video, cache, pps=None):
    """Onda del audio de un video: un pico (0-255) cada 1/pps s, en base64. Se guarda en 'cache' y se reusa
    mientras el video no cambie. Videos largos: menos picos por segundo (sigue viéndose bien y pesa poco)."""
    import base64
    v = Path(video)
    st = v.stat()
    firma = f"{v.name}-{st.st_size}-{int(st.st_mtime)}"
    try:
        d = ed.cargar_json(cache)
        if d.get("firma") == firma and d.get("b64") is not None:
            return d
    except Exception:
        pass
    with _ONDA_LOCK:
        if pps is None:
            pps = 100 if ed.duracion_video(v) <= 900 else 25
        sr = 8000
        n = sr // pps
        pr = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(v), "-map", "0:a:0?", "-ac", "1", "-ar", str(sr),
                               "-f", "s16le", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        partes, resto = [], np.zeros(0, np.int16)
        while True:   # por pedazos: un video de 2 horas no se carga entero en memoria
            buf = pr.stdout.read(n * 2 * 4000)
            if not buf:
                break
            a = np.concatenate([resto, np.frombuffer(buf[:len(buf) // 2 * 2], np.int16)])
            k = len(a) // n
            if k:
                partes.append(np.abs(a[:k * n].astype(np.int32).reshape(k, n)).max(axis=1))
            resto = a[k * n:]
        pr.wait()
        pk = np.concatenate(partes).astype(np.float32) if partes else np.zeros(0, np.float32)
        if len(pk):
            ref = max(1.0, float(np.percentile(pk, 99.5)))
            picos = np.clip(np.sqrt(pk / ref) * 255, 0, 255).astype(np.uint8)   # raíz: se ven también las partes bajas
        else:
            picos = np.zeros(0, np.uint8)
        d = {"firma": firma, "pps": pps, "b64": base64.b64encode(picos.tobytes()).decode()}
        try:
            Path(cache).parent.mkdir(parents=True, exist_ok=True)
            ed.guardar_json(cache, d)
        except OSError:
            pass
        return d


def onda_audio(t):
    """Onda del video del trabajo (pestaña Edición)."""
    plan, _ = cargar(t)
    return onda_de(plan["video"], Path(t) / "onda.json", 100)


def restaurar_tramo(t, i):
    plan, _ = cargar(t)
    cs = plan.get("cortes", [])
    if not 0 <= i < len(cs) or not cs[i].get("manual"):
        raise ValueError("Ese tramo no existe")
    respaldar(t)
    cs.pop(i)
    guardar_plan(t, plan)


# ----------------------------------------------------------------------------
# Video largo: fragmentos, sugerencias y cola para mandar a editar
# ----------------------------------------------------------------------------
import queue  # noqa: E402
import re as _re  # noqa: E402

_COLA = queue.Queue()
_COLA_LOCK = threading.RLock()
_SUGERIR = {}      # carpeta -> proceso de sugerencias
_TRABAJADOR = [None]


def carpeta_frag(nombre):
    v = buscar_video(nombre)
    if not v:
        raise ValueError(f"No encuentro «{nombre}» en {CARPETA_VIDEOS}")
    return v, v.with_name(v.stem + "_fragmentos")


def leer_frag(d):
    p = Path(d) / "fragmentos.json"
    with _COLA_LOCK:
        return ed.cargar_json(p) if p.exists() else {"fragmentos": [], "siguiente": 1}


def _escribir_atomico(p, datos):
    """Escribe en un archivo temporal y lo pone en su lugar. Crea la carpeta si no existe (la primera vez que se
    marca un fragmento de un video) y reintenta si Windows tiene el archivo ocupado un instante."""
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    ed.guardar_json(tmp, datos)
    for intento in range(8):
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            if intento == 7:
                raise
            time.sleep(0.15)


def escribir_frag(d, datos):
    with _COLA_LOCK:
        Path(d).mkdir(parents=True, exist_ok=True)
        _escribir_atomico(Path(d) / "fragmentos.json", datos)


def actualizar_frag(d, fid, **cambios):
    with _COLA_LOCK:
        datos = leer_frag(d)
        for f in datos["fragmentos"]:
            if f["id"] == fid:
                f.update(cambios)
        _escribir_atomico(Path(d) / "fragmentos.json", datos)


def estado_sugerir(d):
    proc = _SUGERIR.get(str(d))
    log = Path(d) / "sugerir.log"
    etapa, frac = "", None
    if log.exists():
        for linea in reversed(log.read_text(encoding="utf-8", errors="ignore").splitlines()[-200:]):
            if linea.startswith("@@PROGRESO@@"):
                try:
                    v, etapa = linea.split(" ", 1)[1].split("|", 1)
                    frac = float(v)
                except ValueError:
                    pass
                break
    if proc is not None and proc.poll() is None:
        return {"estado": "trabajando", "etapa": etapa, "avance": frac}
    if proc is not None and proc.returncode not in (0, None) and fue_cancelado(proc):
        return {"estado": "error", "etapa": "Cancelado"}
    if proc is not None and proc.returncode not in (0, None):
        ult = [x for x in log.read_text(encoding="utf-8", errors="ignore").splitlines() if x.strip() and not x.startswith("@@")][-3:] \
            if log.exists() else []
        return {"estado": "error", "etapa": " ".join(ult)[-300:]}
    return {"estado": "listo" if (Path(d) / "sugerencias.json").exists() else "nada", "etapa": etapa}


def integrar_sugerencias(d):
    """Pasa las sugerencias nuevas a la lista de fragmentos (una sola vez)."""
    sp = Path(d) / "sugerencias.json"
    if not sp.exists():
        return
    sug = ed.cargar_json(sp)
    with _COLA_LOCK:
        datos = leer_frag(d)
        if datos.get("sugerencias_fecha") == sug.get("fecha"):
            return
        hist = datos.setdefault("sugeridas_historial", [])   # para «Lo aprendido»: qué sugirió la IA
        for c in sug.get("clips", []):
            hist.append({"inicio": c["inicio"], "fin": c["fin"], "titulo": c.get("titulo") or "", "tema": c.get("tema", "")})
            datos["fragmentos"].append({"id": datos.get("siguiente", 1), "inicio": c["inicio"], "fin": c["fin"],
                                        "titulo": c.get("titulo") or "", "tema": c.get("tema", ""), "estilo": datos.get("estilo", "Clips Chapuceros"),
                                        "estado": "pendiente", "sugerido": True, "marcado": True})
            datos["siguiente"] = datos.get("siguiente", 1) + 1
        datos["fragmentos"].sort(key=lambda f: f["inicio"])
        datos["sugerencias_fecha"] = sug.get("fecha")
        _escribir_atomico(Path(d) / "fragmentos.json", datos)


def datos_frag(nombre):
    v, d = carpeta_frag(nombre)
    integrar_sugerencias(d)
    datos = leer_frag(d)
    tp = d / "transcripcion.json"
    pausas = []
    if tp.exists():
        pal = ed.cargar_json(tp)
        pausas = [round((a["f"] + b["i"]) / 2, 2) for a, b in zip(pal, pal[1:]) if b["i"] - a["f"] >= 0.35]
    return {"video": v.name, "mp4": v.suffix.lower() in (".mp4", ".webm", ".m4v"), "duracion": ed.duracion_video(v),
            "fragmentos": datos["fragmentos"], "estilo": datos.get("estilo", "Clips Chapuceros"),
            "estilos": list(ESTILOS), "pausas": pausas, "transcrito": tp.exists(), "sugerir": estado_sugerir(d),
            "gpu": GPU_INICIAL}


def guardar_frag(nombre, lista, estilo=None):
    """Guarda lo que editó el usuario (inicio, fin, título, estilo, marcado). El estado lo maneja la cola."""
    v, d = carpeta_frag(nombre)
    with _COLA_LOCK:
        datos = leer_frag(d)
        previos = {f["id"]: f for f in datos["fragmentos"]}
        nuevos = []
        for f in lista:
            fid = f.get("id")
            if not isinstance(fid, int) or fid <= 0:
                fid = datos.get("siguiente", 1)
                datos["siguiente"] = fid + 1
            base = previos.get(fid, {"estado": "pendiente"})
            a, b = float(f["inicio"]), float(f["fin"])
            if b - a < 1.0:
                continue
            g = f.get("grupo")
            nuevos.append({**base, "id": fid, "inicio": round(a, 3), "fin": round(b, 3),
                           "titulo": str(f.get("titulo", ""))[:120], "estilo": f.get("estilo") or base.get("estilo") or "Clips Chapuceros",
                           "marcado": bool(f.get("marcado", True)), "sugerido": bool(f.get("sugerido", base.get("sugerido", False))),
                           "grupo": int(g) if isinstance(g, (int, float)) and g > 0 else None})
            if not nuevos[-1]["grupo"]:
                nuevos[-1].pop("grupo")
        # un grupo de un solo fragmento ya no es grupo
        cuenta = {}
        for x in nuevos:
            if x.get("grupo"):
                cuenta[x["grupo"]] = cuenta.get(x["grupo"], 0) + 1
        for x in nuevos:
            if x.get("grupo") and cuenta[x["grupo"]] < 2:
                x.pop("grupo")
        datos["fragmentos"] = sorted(nuevos, key=lambda x: x["inicio"])
        if estilo in ESTILOS:
            datos["estilo"] = estilo
        _escribir_atomico(d / "fragmentos.json", datos)
    return datos


def slug(txt, n=40):
    import unicodedata
    t = unicodedata.normalize("NFKD", txt or "").encode("ascii", "ignore").decode()
    t = _re.sub(r"[^A-Za-z0-9]+", "_", t).strip("_")
    return t[:n] or "clip"


def nombre_archivo(titulo, n=100):
    """Título -> nombre de archivo válido en Windows (conserva espacios y acentos)."""
    t = _re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", str(titulo or ""))
    t = _re.sub(r"\s+", " ", t).strip().rstrip(". ")
    return t[:n].rstrip(". ") or "clip"


def ruta_fragmento(titulo):
    """Archivo del clip en VideosEdit con el TÍTULO como nombre (si ya existe otro, se le agrega (2), (3)...)."""
    base = nombre_archivo(titulo)
    salida, k = CARPETA_VIDEOS / f"{base}.mp4", 2
    while salida.exists() or salida.with_name(salida.stem + "_trabajo").exists():
        salida = CARPETA_VIDEOS / f"{base} ({k}).mp4"
        k += 1
    return salida


def _estado_varios(d, fids, **cambios):
    for fid in fids:
        actualizar_frag(d, fid, **cambios)


def trabajador_cola():
    """Corta y analiza los fragmentos en cola, uno tras otro (en segundo plano). Un GRUPO de fragmentos
    (Ctrl+G en Video largo) se une en un solo video, en orden, y se analiza como uno solo."""
    while True:
        nombre, fids, gpu = _COLA.get()
        fids = list(fids) if isinstance(fids, (list, tuple)) else [fids]
        d = None
        try:
            v, d = carpeta_frag(nombre)
            todos = {x["id"]: x for x in leer_frag(d)["fragmentos"]}
            partes = sorted([todos[i] for i in fids if i in todos], key=lambda x: x["inicio"])
            if not partes:
                continue
            titulo = (next((p.get("titulo") for p in partes if (p.get("titulo") or "").strip()), "") or "").strip()
            estilo = partes[0].get("estilo")
            registrar("─" * 60)
            registrar(f"▶ Video largo «{v.name}»: " + (f"grupo de {len(partes)} fragmentos" if len(partes) > 1
                                                     else f"fragmento {partes[0]['id']}") + f" «{titulo}»")
            _estado_varios(d, fids, estado="cortando", detalle="")
            salida = ruta_fragmento(titulo or f"{v.stem} parte {partes[0]['id']:02d}")
            if len(partes) == 1:
                ed.cortar_fragmento(v, partes[0]["inicio"], partes[0]["fin"], salida)
            else:
                ed.unir_fragmentos(v, [(p["inicio"], p["fin"]) for p in partes], salida)
            registrar(f"   cortado: {salida.name}")
            # la transcripción del video largo se reutiliza (no se vuelve a transcribir); en un grupo, cada pedazo
            # se recorre a su lugar en el video unido
            cmd_extra = []
            tp = d / "transcripcion.json"
            if tp.exists():
                todas = ed.cargar_json(tp)
                pal, desp = [], 0.0
                for p in partes:
                    pal += [{"p": w["p"], "i": round(w["i"] - p["inicio"] + desp, 3), "f": round(w["f"] - p["inicio"] + desp, 3)}
                            for w in todas if p["inicio"] - 0.05 <= w["i"] and w["f"] <= p["fin"] + 0.05]
                    desp += p["fin"] - p["inicio"]
                tf = d / f"parte{partes[0]['id']:02d}_transcripcion.json"
                ed.guardar_json(tf, pal)
                cmd_extra = ["--transcripcion", str(tf)]
            _estado_varios(d, fids, estado="analizando", salida=str(salida))
            plantilla_est = str(BASE / ESTILOS.get(estilo, ESTILOS["Clips Chapuceros"]))
            # sin pre-acomodo: solo limpieza de pausas y subtítulos (Nacho y la pantalla se acomodan a mano)
            cmd = [sys.executable, str(BASE / "editor.py"), "analizar", str(salida), "--titulo", titulo,
                   "--plantilla", plantilla_est, "--vista-previa", "--ligero", *cmd_extra] + \
                  (["--solo-gpu", "--dispositivo", "cuda"] if gpu else [])
            final = None
            for _html, fin in correr(cmd):
                if fin is not None:
                    final = fin
            if final and final.get("ok"):
                try:   # de dónde salió (para «Lo aprendido»)
                    pt = Path(final["trabajo"]) / "plan.json"
                    plan = ed.cargar_json(pt)
                    plan["origen_video_largo"] = {"video": v.name, "tramos": [[p["inicio"], p["fin"]] for p in partes]}
                    ed.guardar_json(pt, plan)
                except Exception:
                    pass
                _estado_varios(d, fids, estado="listo", trabajo=final.get("trabajo"), detalle="")
            elif final and final.get("cancelado"):
                _estado_varios(d, fids, estado="cancelado", detalle="Cancelado")
            else:
                _estado_varios(d, fids, estado="error", detalle="El análisis falló (mira el Registro)")
        except Exception as e:
            try:
                if d is not None:
                    _estado_varios(d, fids, estado="error", detalle=str(e)[:300])
            except Exception:
                pass
            registrar(f"✖ Fragmento(s) {fids}: {e}")
        finally:
            _COLA.task_done()


def mandar_a_editar(nombre, ids, gpu):
    """Manda a la cola los fragmentos marcados. Los de un mismo grupo van juntos como UN solo video."""
    v, d = carpeta_frag(nombre)
    if _TRABAJADOR[0] is None or not _TRABAJADOR[0].is_alive():
        _TRABAJADOR[0] = threading.Thread(target=trabajador_cola, daemon=True)
        _TRABAJADOR[0].start()
    frs = leer_frag(d)["fragmentos"]
    ocupados = ("en cola", "cortando", "analizando")
    trabajos, vistos = [], set()
    for f in sorted(frs, key=lambda x: x["inicio"]):
        if f["id"] not in ids or f["id"] in vistos or f.get("estado") in ocupados:
            continue
        if f.get("grupo"):
            miembros = [x["id"] for x in frs if x.get("grupo") == f["grupo"] and x.get("estado") not in ocupados]
        else:
            miembros = [f["id"]]
        vistos.update(miembros)
        trabajos.append(miembros)
    for miembros in trabajos:
        _estado_varios(d, miembros, estado="en cola", detalle="")
        _COLA.put((nombre, tuple(miembros), gpu))
    try:   # lo que se eligió y lo que se descartó (para «Lo aprendido»)
        aprendizaje.observar_video_largo(d, v.name, ed)
    except Exception as e:
        registrar(f"⚠ No pude aprender de este video largo: {e}")
    return len(trabajos)


def zona_de(plan):
    try:
        pl = plantilla(plan)
        ed.escalar_cajas(pl, plan["info"]["ancho"], plan["info"]["alto"])
        return ed.zona_pantalla(pl, plan["info"])
    except Exception:
        return [0.0, 0.0, float(plan["info"]["ancho"]), float(plan["info"]["alto"])]


def guardar_encuadre(t, ajustes, clave="encuadre_manual"):
    plan, _ = cargar(t)
    dur = plan["info"]["duracion"]
    limpios = []
    for a in ajustes:
        ini, fin = max(0.0, float(a["inicio"])), min(dur, float(a["fin"]))
        if fin - ini < 0.05:
            continue
        if a.get("modo") == "libre" and a.get("r") and len(a["r"]) == 4:
            # recuadro de forma libre (pantalla de Nacho): se guarda tal cual, con su recuadro final si se mueve
            e = {"inicio": round(ini, 3), "fin": round(fin, 3), "modo": "libre",
                 "r": [round(float(v), 1) for v in a["r"]]}
            if a.get("region") and len(a["region"]) == 4:
                e["region"] = [round(float(v), 1) for v in a["region"]]
            if isinstance(a.get("final"), dict) and a["final"].get("r") and len(a["final"]["r"]) == 4:
                e["final"] = {"r": [round(float(v), 1) for v in a["final"]["r"]]}
                e["suavizado"] = "lineal" if a.get("suavizado") == "lineal" else "suave"
            limpios.append(e)
            continue
        e = {"inicio": round(ini, 3), "fin": round(fin, 3), "modo": "ajuste" if a.get("modo") == "ajuste" else "fijo",
             "zoom": round(min(8.0, max(0.2, float(a.get("zoom", 1.0)))), 4)}
        if e["modo"] == "ajuste":
            e["dx"], e["dy"] = round(float(a.get("dx", 0)), 1), round(float(a.get("dy", 0)), 1)
        else:
            e["cx"], e["cy"] = round(float(a["cx"]), 1), round(float(a["cy"]), 1)
        if a.get("region") and len(a["region"]) == 4:   # dónde puede moverse (libre = todo el cuadro)
            e["region"] = [round(float(v), 1) for v in a["region"]]
        if isinstance(a.get("final"), dict) and e["modo"] == "fijo":   # movimiento: recuadro final
            fz = a["final"]
            e["final"] = {"cx": round(float(fz["cx"]), 1), "cy": round(float(fz["cy"]), 1),
                          "zoom": round(min(8.0, max(0.2, float(fz.get("zoom", 1.0)))), 4)}
            e["suavizado"] = "lineal" if a.get("suavizado") == "lineal" else "suave"
        limpios.append(e)
    limpios.sort(key=lambda e: e["inicio"])
    # sin encimarse: el que empieza después manda
    for a, b in zip(limpios, limpios[1:]):
        a["fin"] = min(a["fin"], b["inicio"])
    limpios = [e for e in limpios if e["fin"] - e["inicio"] >= 0.05]
    respaldar(t)
    if limpios:
        plan[clave] = limpios
    else:
        plan.pop(clave, None)
    guardar_plan(t, plan)
    return limpios


def datos_subtitulos(t):
    """Todo lo que necesita el editor de subtítulos en vivo (tiempos ya en el video editado)."""
    plan, palabras = cargar(t)
    pl = plantilla(plan)
    cfg = pl["subtitulos"]
    cs = plan.get("cortes", [])
    grupos = []
    cortes_u = ed.cortes_quitados(cs)
    for n, g in enumerate(grupos_actuales(t, plan, palabras)):
        # las palabras que quedaron en un tramo quitado (en Edición) no se ven; si se quitó todo, el subtítulo no sale
        vis = [p for p in g["palabras"] if not ed.palabra_cortada(p, cortes_u)]
        if not vis:
            continue
        grupos.append({"id": n, "i": round(ed_t(g["i"], plan), 3), "f": round(ed_t(g["f"], plan), 3),
                       "texto": texto_con_saltos(vis), "dy": int(g.get("dy", 0) or 0),
                       "palabras": [{"p": p["p"], "i": round(ed.a_editado(p["i"], cs), 3),
                                     "f": round(ed.a_editado(p["f"], cs), 3), "salto": bool(p.get("salto"))}
                                    for p in vis]})
    vp = Path(t) / "vista_previa.json"
    diseno = ed.cargar_json(vp)["diseno"] if vp.exists() else []
    areas = {k: v["subtitulos"]["area"] for k, v in pl.get("layouts", {}).items() if "subtitulos" in v}
    salida = [pl["salida"].get("ancho", 1080), pl["salida"].get("alto", 1920)]
    if plan.get("subtitulos_render"):  # solo subtítulos: medidas del video real
        sr = plan["subtitulos_render"]
        cfg, areas, salida = sr["estilo"], sr["areas"], sr["salida"]
    modo = cfg.get("modo", "palabras")
    solo = estilo_de(plan) == "solo_subtitulos" and Path(plan["video"]).exists()
    if solo:
        # se ve el clip original con los subtítulos encima, en vivo, sin renderizar.
        # Diseño por tiempo: título al inicio (si lo tiene), franja azul donde se detectó, normal en lo demás.
        normal = "frases" if modo == "frases" else "persona"
        cambios = []
        if modo == "frases" and float(plan.get("titulo_fin") or 0) > 0:
            cambios.append([0.0, "titulo"])
            cambios.append([round(float(plan["titulo_fin"]), 3), normal])
        else:
            cambios.append([0.0, normal])
        for f in sorted(plan.get("franjas", []), key=lambda x: x[0]):
            cambios.append([round(float(f[0]), 3), "dividida"])
            cambios.append([round(float(f[1]), 3), normal])
        cambios.sort(key=lambda x: x[0])
        diseno = []
        for te, lay in cambios:
            if diseno and abs(diseno[-1][0] - te) < 1e-6:
                diseno[-1][1] = lay
            elif not diseno or diseno[-1][1] != lay:
                diseno.append([te, lay])
    return {
        "grupos": grupos, "modo": modo, "diseno": diseno, "areas": areas,
        # con qué tramos quitados se calcularon estos tiempos (si cambian en Edición, la pestaña se pone al día)
        "cortes": [{"inicio": c["inicio"], "fin": c["fin"], **({"manual": True} if c.get("manual") else {})} for c in cs],
        "firma_cortes": ed.firma_cortes(plan),
        # si cambia el título en Edición, esta pestaña vuelve a pedir su imagen
        "titulo_firma": json.dumps([plan.get("titulo", ""), plan.get("titulo_en_video"), plan.get("titulo_fin")]),
        "previa_v": round(vp.stat().st_mtime, 2) if vp.exists() else 0,
        "salida": salida,
        "estilo": {k: cfg.get(k) for k in ("tam", "tam_min", "max_lineas", "color", "contorno", "color_contorno",
                                            "color_resalte", "espacio", "mayusculas", "centro", "ancho_max",
                                            "interlineado", "sombra", "sombra_opacidad")},
        "limpia": solo or (Path(t) / "vista_previa.mp4").exists(),
        "provisional": not solo and vp.exists() and bool(ed.cargar_json(vp).get("provisional")),
        # el plan cambió después del último render (encuadre, pantalla, imágenes, cortes...)
        "desactualizada": not solo and (Path(t) / "vista_previa.mp4").exists() and
                          (Path(t) / "plan.json").stat().st_mtime > (Path(t) / "vista_previa.mp4").stat().st_mtime + 1,
        "hay_video": solo or (Path(t) / "vista_previa.mp4").exists() or bool(video_salida(t)),
        # «Solo subtítulos»: el título se escribe aquí mismo (con él se nombra el video al exportar)
        "solo": solo, "titulo_texto": plan.get("titulo", "") or "", "titulo_en_video": plan.get("titulo_en_video"),   # None = nunca se ha elegido
        "nombre_sin_titulo": Path(plan["video"]).stem + "_subtitulado.mp4",
        # stickers (se dibujan en vivo encima de la vista previa; tiempos del video editado)
        "stickers": [dict(s_, i=round(ed_t(s_["inicio"], plan), 3), f=round(ed_t(s_["fin"], plan), 3))
                     for s_ in plan.get("stickers") or []],
        "meta_stickers": ed.meta_stickers(),
        # para que los stickers queden debajo de la franja azul y del título (en px del video vertical)
        "franja_area": (pl.get("layouts", {}).get("dividida", {}).get("franja") or {}).get("area"),
        "franja_areas": {k: v["franja"]["area"] for k, v in pl.get("layouts", {}).items() if (v.get("franja") or {}).get("area")},
        "titulo": bool(plan.get("titulo")) and (estilo_de(plan) == "motivacional" or bool(pl.get("titulo", {}).get("barra"))),
        "titulo_fin": round(ed_t(float(plan.get("titulo_fin", 3.0)), plan), 3) if estilo_de(plan) == "motivacional" else None,
    }


def crear_app():
    from fastapi import Body, FastAPI, HTTPException, Request
    from fastapi.responses import FileResponse, JSONResponse, Response

    app = FastAPI()

    def validar(t):
        t = limpiar_ruta(t)
        if not t or not (Path(t) / "plan.json").exists():
            raise HTTPException(404, "Carpeta de trabajo no válida")
        return t

    @app.get("/mov/editor")
    def pagina():
        return FileResponse(BASE / "web" / "movimiento.html", headers={"Cache-Control": "no-store"})

    @app.get("/mov/datos")
    def datos(t: str, n: int):
        return JSONResponse(datos_momento(validar(t), n))

    @app.get("/mov/img")
    def imagen(t: str, n: int, k: int):
        plan, _ = cargar(validar(t))
        img = imagen_vista(plan["momentos"][n - 1]["imagenes"][k], 1400)
        if img is None:
            raise HTTPException(404, "No pude leer la imagen")
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
        return Response(buf.tobytes(), media_type="image/jpeg")

    @app.post("/mov/guardar")
    def guardar(d: dict = Body(...)):
        t = validar(d.get("t"))
        n, k = int(d["n"]), int(d["k"])
        plan, _ = cargar(t)
        respaldar(t)
        m = plan["momentos"][n - 1]
        lista = m.get("encuadres") or []
        while len(lista) < len(m["imagenes"]):
            lista.append({})
        lista[k] = {"inicio": [round(float(v), 5) for v in d["inicio"]],
                    "fin": [round(float(v), 5) for v in d["fin"]],
                    "suavizado": "lineal" if d.get("suavizado") == "lineal" else "suave"}
        m["encuadres"] = lista
        guardar_plan(t, plan)
        return {"ok": True}

    @app.post("/mov/quitar_imagen")
    def quitar_imagen(d: dict = Body(...)):
        t = validar(d.get("t"))
        n, k = int(d["n"]), int(d["k"])
        plan, _ = cargar(t)
        m = plan["momentos"][n - 1]
        if not 0 <= k < len(m.get("imagenes", [])):
            raise HTTPException(400, "Esa imagen no existe")
        respaldar(t)
        m["imagenes"].pop(k)
        enc = m.get("encuadres") or []
        if k < len(enc):
            enc.pop(k)
        m["encuadres"] = enc
        guardar_plan(t, plan)
        return {"ok": True, "quedan": len(m["imagenes"])}

    @app.post("/mov/restablecer")
    def restablecer(d: dict = Body(...)):
        t = validar(d.get("t"))
        n, k = int(d["n"]), int(d["k"])
        plan, _ = cargar(t)
        respaldar(t)
        m = plan["momentos"][n - 1]
        lista = m.get("encuadres") or []
        if k < len(lista):
            lista[k] = {}
        m["encuadres"] = lista
        guardar_plan(t, plan)
        return next(i for i in datos_momento(t, n)["imagenes"] if i["k"] == k)

    # ---------------- subtítulos en vivo ----------------
    @app.get("/sub/editor")
    def sub_pagina():
        return FileResponse(BASE / "web" / "subtitulos.html", headers={"Cache-Control": "no-store"})

    @app.get("/sub/datos")
    def sub_datos(t: str):
        return JSONResponse(datos_subtitulos(validar(t)))

    @app.get("/sub/video")
    def sub_video(t: str):
        t = validar(t)
        plan, _ = cargar(t)
        if estilo_de(plan) == "solo_subtitulos" and Path(plan["video"]).exists():
            # «Solo subtítulos»: el video limpio es el mismo clip que se subtitula (no hay que armar nada).
            # Se ve una copia en H.264 porque el navegador no reproduce HEVC (TikTok) en muchos equipos.
            with _COPIA_LOCK:
                try:
                    copia = ed.copia_navegador(plan["video"], t)
                except Exception as e:
                    registrar(f"⚠ No pude preparar la copia para el navegador: {e}")
                    copia = None
            return FileResponse(str(copia or plan["video"]), media_type="video/mp4", headers={"Cache-Control": "no-store"})
        p = Path(t) / "vista_previa.mp4"
        if not p.exists():
            v = video_salida(t)
            if not v:
                raise HTTPException(404, "Aún no hay video")
            p = Path(v)
        return FileResponse(p, media_type="video/mp4", headers={"Cache-Control": "no-store"})

    @app.get("/sub/fuente")
    def sub_fuente(t: str):
        plan, _ = cargar(validar(t))
        f = ed.ruta(plantilla(plan)["subtitulos"]["fuente"])
        return FileResponse(f, media_type="font/otf" if str(f).lower().endswith(".otf") else "font/ttf")

    @app.post("/sub/guardar")
    def sub_guardar(d: dict = Body(...)):
        t = validar(d.get("t"))
        filas = [[str(f.get("i", "")), str(f.get("f", "")), str(f.get("texto", "")), str(f.get("id", -1)),
                  str(f.get("dy", 0))] for f in d.get("filas", [])]
        n = guardar_subtitulos(t, filas, d.get("cortes"))
        return {"ok": True, "n": n, "datos": datos_subtitulos(t)}

    # ---------------- pantalla por tramo ----------------
    @app.get("/pant/editor")
    def pant_pagina():
        return FileResponse(BASE / "web" / "pantalla.html", headers={"Cache-Control": "no-store"})

    @app.get("/pant/datos")
    def pant_datos(t: str):
        return JSONResponse(tramos_pantalla(validar(t)))

    @app.get("/pant/cuadro")
    def pant_cuadro(t: str, k: str):
        t = validar(t)
        plan, _ = cargar(t)
        img = None
        if k.startswith("m") and k[1:].isdigit():
            m = plan["momentos"][int(k[1:])]
            img = imagen_vista(m["imagenes"][0], 360) if m.get("imagenes") else None
        else:
            if k.startswith("p") and k[1:].isdigit():
                p = plan["proyeccion"][int(k[1:])]
                a, b, caja = p["inicio"], p["fin"], p.get("caja")
            elif k.startswith("g"):
                a, b = [float(x) for x in k[1:].split("_")]
                caja = caja_proyeccion(plantilla(plan), plan)
            elif k.startswith("e") and k[1:].isdigit():
                e = plan["encuadres"][int(k[1:])]
                a, b, caja = e["inicio"], min(e["fin"], plan["info"]["duracion"]), None
            else:
                raise HTTPException(404, "Tramo no válido")
            cap = cv2.VideoCapture(plan["video"])
            cap.set(cv2.CAP_PROP_POS_MSEC, (a + min(1.5, (b - a) / 2)) * 1000)
            ok, fr = cap.read()
            cap.release()
            if ok:
                x, y, w, h = [int(v) for v in caja or [0, 0, fr.shape[1], fr.shape[0]]]
                img = fr[y:y + h, x:x + w]
                esc = 360 / max(img.shape[:2])
                img = cv2.resize(img, (max(1, int(img.shape[1] * esc)), max(1, int(img.shape[0] * esc))))
        if img is None:
            raise HTTPException(404, "No pude leer el cuadro")
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return Response(buf.tobytes(), media_type="image/jpeg", headers={"Cache-Control": "max-age=600"})

    @app.post("/pant/guardar")
    def pant_guardar(d: dict = Body(...)):
        t = validar(d.get("t"))
        n = aplicar_pantalla(t, d.get("cambios", []))
        return {"ok": True, "n": n}

    # ---------------- encuadre corregido a mano ----------------
    @app.get("/enc/editor")
    def enc_pagina():
        return FileResponse(BASE / "web" / "encuadre.html", headers={"Cache-Control": "no-store"})

    @app.get("/enc/datos")
    def enc_datos(t: str):
        return JSONResponse(datos_encuadre(validar(t)))

    @app.get("/enc/video")
    def enc_video(t: str):
        plan, _ = cargar(validar(t))
        p = Path(plan["video"])
        if not p.exists():
            raise HTTPException(404, "No encuentro el video original")
        return FileResponse(p, media_type="video/mp4")

    @app.get("/enc/proxy")
    def enc_proxy(t: str):
        """Copia ligera sin pausas (vista previa fluida)."""
        p = Path(validar(t)) / "proxy.mp4"
        if not p.exists():
            raise HTTPException(404, "Aún no está lista")
        return FileResponse(p, media_type="video/mp4")

    @app.get("/enc/proxy_estado")
    def enc_proxy_estado(t: str):
        return estado_proxy(validar(t))

    @app.get("/enc/titulo")
    def enc_titulo(t: str):
        """Capa del título (PNG transparente del tamaño de la salida) para la vista previa."""
        plan, _ = cargar(validar(t))
        pl = plantilla(plan)
        solo = estilo_de(plan) == "solo_subtitulos"
        W, H = (plan["info"]["ancho"], plan["info"]["alto"]) if solo else (pl["salida"]["ancho"], pl["salida"]["alto"])
        try:
            moti = ed.estilo_motivacional()
            if solo:   # «Solo subtítulos»: la barra del título encima del clip, si se pidió
                sup = ed.estilo_solo_subtitulos().titulo_del_plan(plan, pl)
            elif estilo_de(plan) == "motivacional" and moti.es_yair(pl) and plan.get("titulo"):
                sup = moti.capa_vista_previa_yair(plan, pl, W, H)   # cuadros del título + imagen de la entrada
            elif estilo_de(plan) == "motivacional":   # recuadro negro del estilo motivacional
                sup = moti.capa_titulo(pl["titulo"], plan.get("titulo", ""), W, H)
            else:
                sup = ed.capa_titulo(pl, plan.get("titulo", ""), W, H)
        except Exception:
            sup = None
        if sup is None:
            raise HTTPException(404, "Sin título")
        bgr, alpha, (x0, y0, x1, y1) = sup
        capa = np.zeros((H, W, 4), np.uint8)
        capa[y0:y1, x0:x1, :3] = bgr.astype(np.uint8)
        capa[y0:y1, x0:x1, 3] = (alpha[:, :, 0] * 255).astype(np.uint8)
        capa = cv2.resize(capa, (W // 2, H // 2), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".png", capa)
        return Response(buf.tobytes(), media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.get("/enc/fondo")
    def enc_fondo(t: str):
        """Video de fondo del estilo («Tiktoks Gaby») para la vista previa en vivo."""
        plan, _ = cargar(validar(t))
        f = (plantilla(plan).get("fondo") or {}).get("video")
        if not f or not ed.ruta(f).exists():
            raise HTTPException(404, "Sin video de fondo")
        return FileResponse(ed.ruta(f), media_type="video/mp4", headers={"Cache-Control": "max-age=86400"})

    @app.get("/enc/franja")
    def enc_franja(t: str, lay: str = "dividida"):
        plan, _ = cargar(validar(t))
        lay = lay if lay in ("dividida", "ganso") else "dividida"
        f = plantilla(plan).get("layouts", {}).get(lay, {}).get("franja", {}).get("fondo")
        if not f or not ed.ruta(f).exists():
            raise HTTPException(404, "Sin franja")
        return FileResponse(ed.ruta(f))

    # ---------------- área de Edición (editor unificado) ----------------
    @app.get("/edi/editor")
    def edi_pagina():
        return FileResponse(BASE / "web" / "edicion.html", headers={"Cache-Control": "no-store"})

    @app.get("/edi/datos")
    def edi_datos(t: str):
        return JSONResponse(datos_edicion(validar(t)))

    @app.post("/edi/audio_tramos")
    def edi_audio_tramos(d: dict = Body(...)):
        t = validar(d.get("t"))
        _ok(lambda: guardar_audio_tramos(t, d.get("tramos")))
        return {"ok": True}

    @app.post("/edi/titulo_ajuste")
    def edi_titulo_ajuste(d: dict = Body(...)):
        t = validar(d.get("t"))
        try:
            return {"ok": True, **guardar_titulo_ajuste(t, d.get("tam"), d.get("inter"))}
        except Exception as e:
            return {"ok": False, "mensaje": str(e)}

    @app.get("/edi/titulo_info")
    def edi_titulo_info(t: str):
        return info_titulo(validar(t))

    @app.post("/edi/partir_escena")
    def edi_partir_escena(d: dict = Body(...)):
        t = validar(d.get("t"))
        _ok(lambda: partir_escena(t, int(d["i"]), float(d["t_corte"])))
        return {"ok": True}

    @app.post("/edi/mover_toma")
    def edi_mover_toma(d: dict = Body(...)):
        t = validar(d.get("t"))
        _ok(lambda: mover_frontera_toma(t, float(d["de"]), float(d["a"])))
        return {"ok": True, "mensaje": "Corte recorrido."}

    @app.post("/edi/partir_toma")
    def edi_partir_toma(d: dict = Body(...)):
        t = validar(d.get("t"))
        _ok(lambda: partir_toma(t, float(d["t_corte"])))
        return {"ok": True, "mensaje": "Bloque partido en dos."}

    @app.post("/edi/montaje")
    def edi_montaje(d: dict = Body(...)):
        """Cortar / copiar / pegar / mover / duplicar segmentos del video (tiempos del video actual, sin quitar
        pausas)."""
        t = validar(d.get("t"))
        acc = d.get("accion")
        _I = sys.modules[__name__]   # este mismo módulo (cargar, respaldar, lanzar...)

        def hacer():
            if acc == "copiar":
                dur = montaje.copiar(t, float(d["a"]), float(d["b"]), _I)
                return f"Segmento copiado ({dur:.1f} s). Pégalo con Ctrl+V donde esté el cursor."
            if acc == "cortar":
                return montaje.cortar(t, float(d["a"]), float(d["b"]), _I, ed)
            if acc == "pegar":
                return montaje.pegar(t, float(d["p"]), _I, ed)
            if acc == "mover":
                return montaje.mover(t, float(d["a"]), float(d["b"]), float(d["p"]), _I, ed)
            if acc == "copiar_en":   # Ctrl + arrastrar: copia el pedazo y la pega en p
                montaje.copiar(t, float(d["a"]), float(d["b"]), _I)
                return montaje.pegar(t, float(d["p"]), _I, ed).replace("pegado", "copiado ahí")
            if acc == "duplicar":
                return montaje.duplicar(t, float(d["a"]), float(d["b"]), _I, ed)
            raise ValueError("Acción desconocida")
        def seguro():
            try:
                return hacer()
            except RuntimeError as e:
                raise ValueError(str(e))
        msg = _ok(seguro)
        registrar(f"✂ Montaje ({acc}): {msg}")
        return {"ok": True, "mensaje": msg}

    @app.get("/app/grafito.css")
    def app_grafito():
        return FileResponse(BASE / "web" / "grafito.css", media_type="text/css", headers={"Cache-Control": "no-store"})

    @app.get("/app/fuentes/{nombre}")
    def app_fuente(nombre: str):
        p = BASE / "web" / "fuentes" / Path(nombre).name
        if p.suffix != ".woff2" or not p.exists():
            raise HTTPException(404)
        return FileResponse(p, media_type="font/woff2", headers={"Cache-Control": "max-age=604800"})

    @app.get("/app/stickers_gen.js")
    def app_stickers_gen():
        return FileResponse(BASE / "web" / "stickers_gen.js", media_type="text/javascript", headers={"Cache-Control": "no-store"})

    @app.get("/app/notificacion.mp3")
    def app_notificacion():
        return FileResponse(BASE / "web" / "notificacion.mp3", media_type="audio/mpeg")

    @app.post("/app/cerrar")
    def app_cerrar():
        """Botón «Cerrar»: detiene todos los procesos de la plataforma y la apaga."""
        try:
            cancelar_todo()
        except Exception:
            pass
        for proc in list(_SUGERIR.values()) + list(_PROXY_TRABAJOS.values()):
            try:
                if proc.poll() is None:
                    _matar(proc)
            except Exception:
                pass
        registrar("⏻ Editor cerrado desde el botón «Cerrar»")
        threading.Timer(0.8, lambda: os._exit(0)).start()
        return {"ok": True}

    @app.get("/enc/cortinilla")
    def enc_cortinilla(t: str):
        plan, _ = cargar(validar(t))
        img = sprite_cortinilla(plantilla(plan))
        if not img:
            raise HTTPException(404, "Sin cortinilla")
        return Response(img, media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})

    @app.post("/edi/transiciones")
    def edi_transiciones(d: dict = Body(...)):
        t = validar(d.get("t"))
        msg, n = _ok(lambda: accion_transiciones(t, d))
        return {"ok": True, "mensaje": msg, "n": n}

    @app.get("/edi/musica")
    def edi_musica(t: str):
        plan, _ = cargar(validar(t))
        m = musica_de(plan)
        if not m:
            raise HTTPException(404, "Este estilo no lleva música de fondo")
        return FileResponse(m, media_type="audio/mpeg")

    @app.post("/edi/audio")
    def edi_audio(d: dict = Body(...)):
        t = validar(d.get("t"))
        return {"ok": True, "mezcla": guardar_audio(t, d.get("musica", 1.0), d.get("voz", 1.0))}

    def _ok(fn):
        try:
            return fn()
        except (KeyError, TypeError, ValueError) as e:
            raise HTTPException(400, str(e))

    @app.post("/edi/momento")
    def edi_momento(d: dict = Body(...)):
        t = validar(d.get("t"))
        return _ok(lambda: accion_momento_http(t, d))

    @app.post("/edi/subir")
    async def edi_subir(request: Request):
        form = await request.form()
        t = validar(form.get("t"))
        archivos = [(f.filename, await f.read()) for f in form.getlist("archivos") if hasattr(f, "read")]
        return _ok(lambda: guardar_subidas(t, int(form.get("i")), archivos, form.get("reemplazar") == "1"))

    @app.post("/edi/captura")
    def edi_captura(d: dict = Body(...)):
        t = validar(d.get("t"))
        return _ok(lambda: captura_pantalla(t, d))

    @app.post("/edi/encajar")
    def edi_encajar(d: dict = Body(...)):
        t = validar(d.get("t"))
        return _ok(lambda: guardar_encajar(t, d["momento"], d.get("valor")))

    @app.post("/edi/titulo")
    def edi_titulo(d: dict = Body(...)):
        t = validar(d.get("t"))
        guardar_titulo(t, d.get("titulo"), d.get("en_video"))
        return {"ok": True}

    @app.post("/edi/titulo_fin")
    def edi_titulo_fin(d: dict = Body(...)):
        """Hasta cuándo se ve el título (estilo motivacional). Tiempo del video original."""
        t = validar(d.get("t"))
        plan, _ = cargar(t)
        fin = max(0.3, min(float(d["fin"]), plan["info"]["duracion"]))
        respaldar(t)
        plan["titulo_fin"] = round(fin, 4)
        for m in plan.get("momentos", []):   # «Tiktoks Yair»: la imagen de la entrada dura lo mismo que el título
            if m.get("entrada"):
                m["fin"] = round(fin, 4)
        guardar_plan(t, plan)
        return {"ok": True, "mensaje": "El título ahora se quita en ese punto."}

    @app.post("/edi/cortar")
    def edi_cortar(d: dict = Body(...)):
        t = validar(d.get("t"))
        _ok(lambda: quitar_tramo(t, float(d["inicio"]), float(d["fin"]), bool(d.get("al_final"))))
        return {"ok": True}

    @app.get("/edi/onda")
    def edi_onda(t: str):
        return JSONResponse(onda_audio(validar(t)), headers={"Cache-Control": "no-store"})

    @app.post("/edi/corte")
    def edi_corte(d: dict = Body(...)):
        t = validar(d.get("t"))
        return _ok(lambda: ajustar_corte(t, float(d["inicio0"]), float(d["fin0"]), d.get("inicio"), d.get("fin"),
                                         bool(d.get("recuperar"))))

    @app.post("/edi/restaurar")
    def edi_restaurar(d: dict = Body(...)):
        t = validar(d.get("t"))
        _ok(lambda: restaurar_tramo(t, int(d["i"])))
        return {"ok": True}

    @app.post("/edi/deshacer")
    def edi_deshacer(d: dict = Body(...)):
        t = validar(d.get("t"))
        return {"ok": deshacer(t)}

    @app.post("/edi/rehacer")
    def edi_rehacer(d: dict = Body(...)):
        t = validar(d.get("t"))
        ok = rehacer(t)
        return {"ok": ok, "mensaje": "Rehice el cambio." if ok else "No hay nada que rehacer."}

    @app.post("/edi/dividir_pantalla")
    def edi_dividir_pantalla(d: dict = Body(...)):
        t = validar(d.get("t"))
        _ok(lambda: dividir_pantalla(t, int(d["i"]), float(d["t_corte"])))
        return {"ok": True, "mensaje": "Tramo partido en dos."}

    # ---------------- video largo ----------------
    @app.get("/frag/editor")
    def frag_pagina():
        return FileResponse(BASE / "web" / "fragmentos.html", headers={"Cache-Control": "no-store"})

    @app.get("/frag/videos")
    def frag_videos():
        out = []
        for etiqueta, nombre in opciones_videos():
            v = buscar_video(nombre)
            out.append({"nombre": nombre, "etiqueta": etiqueta,
                        "fragmentado": bool(v and (v.with_name(v.stem + "_fragmentos") / "fragmentos.json").exists()),
                        "duracion": ed.duracion_video(v) if v else 0})
        return out

    @app.get("/frag/datos")
    def frag_datos(v: str):
        return _ok(lambda: JSONResponse(datos_frag(v)))

    @app.get("/frag/video")
    def frag_video(v: str):
        vid = buscar_video(v)
        if not vid:
            raise HTTPException(404, "No encuentro el video")
        return FileResponse(vid, media_type="video/mp4")

    @app.get("/frag/onda")
    def frag_onda(v: str):
        video, d = carpeta_frag(v)
        return JSONResponse(onda_de(video, d / "onda.json"), headers={"Cache-Control": "no-store"})

    @app.post("/frag/guardar")
    def frag_guardar(d: dict = Body(...)):
        datos = _ok(lambda: guardar_frag(d["v"], d.get("fragmentos", []), d.get("estilo")))
        return {"ok": True, "fragmentos": datos["fragmentos"]}

    @app.post("/frag/sugerir")
    def frag_sugerir(d: dict = Body(...)):
        v, carpeta = _ok(lambda: carpeta_frag(d["v"]))
        carpeta.mkdir(parents=True, exist_ok=True)
        proc = _SUGERIR.get(str(carpeta))
        if proc is not None and proc.poll() is None:
            return {"ok": True, "mensaje": "Ya está trabajando"}
        (carpeta / "sugerencias.json").unlink(missing_ok=True)
        cmd = [sys.executable, str(BASE / "editor.py"), "sugerir", str(v), "--carpeta", str(carpeta),
               "--min-seg", str(d.get("min_seg", 30)), "--max-seg", str(d.get("max_seg", 120))] + \
              (["--solo-gpu", "--dispositivo", "cuda"] if d.get("gpu") else [])
        log = open(carpeta / "sugerir.log", "w", encoding="utf-8")
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        _SUGERIR[str(carpeta)] = lanzar(cmd, cwd=str(BASE), env=env, stdout=log, stderr=subprocess.STDOUT)
        registrar(f"▶ Video largo «{v.name}»: buscando clips (transcripción + temas)")
        return {"ok": True}

    @app.post("/frag/mandar")
    def frag_mandar(d: dict = Body(...)):
        n = _ok(lambda: mandar_a_editar(d["v"], [int(x) for x in d.get("ids", [])], bool(d.get("gpu", True))))
        return {"ok": True, "n": n}

    # ---------------- lo aprendido ----------------
    @app.get("/apr/editor")
    def apr_pagina():
        return FileResponse(BASE / "web" / "aprendido.html", headers={"Cache-Control": "no-store"})

    @app.get("/apr/datos")
    def apr_datos():
        return JSONResponse(aprendizaje.resumen())

    @app.post("/apr/estado")
    def apr_estado(d: dict = Body(...)):
        ids = d.get("ids") or [d.get("id")]
        for rid in ids:
            if rid:
                aprendizaje.cambiar_estado(rid, d.get("estado"))
        return {"ok": True}

    @app.post("/apr/aprender_todo")
    def apr_aprender_todo():
        """Aprende de todos los trabajos de la carpeta de videos (los que ya se corrigieron)."""
        n = 0
        if CARPETA_VIDEOS.exists():
            for dtr in CARPETA_VIDEOS.iterdir():
                if dtr.is_dir() and dtr.name.endswith("_trabajo") and (dtr / "plan.json").exists():
                    try:
                        if aprendizaje.aprender_de(dtr, ed):
                            n += 1
                    except Exception as e:
                        registrar(f"⚠ No pude aprender de {dtr.name}: {e}")
        return {"ok": True, "n": n}

    @app.post("/enc/guardar_pantalla")
    def enc_guardar_pantalla(d: dict = Body(...)):
        """Recuadro de lo que proyecta Nacho, acomodado a mano."""
        t = validar(d.get("t"))
        try:
            ajustes = guardar_encuadre(t, d.get("ajustes", []), "encuadre_pantalla")
        except (KeyError, TypeError, ValueError) as e:
            raise HTTPException(400, f"Datos no válidos: {e}")
        return {"ok": True, "ajustes": ajustes}

    @app.post("/enc/guardar")
    def enc_guardar(d: dict = Body(...)):
        t = validar(d.get("t"))
        try:
            ajustes = guardar_encuadre(t, d.get("ajustes", []))
        except (KeyError, TypeError, ValueError) as e:
            raise HTTPException(400, f"Datos no válidos: {e}")
        return {"ok": True, "ajustes": ajustes}

    @app.post("/edi/difuminar")
    def edi_difuminar(d: dict = Body(...)):
        t = validar(d.get("t"))
        lista = guardar_difuminar(t, d.get("lista"))
        return {"ok": True, "n": len(lista)}   # el mensaje lo pone la pestaña Edición según lo que se hizo

    @app.post("/edi/stickers")
    def edi_stickers(d: dict = Body(...)):
        t = validar(d.get("t"))
        lista = guardar_stickers(t, d.get("lista"))
        return {"ok": True, "n": len(lista)}

    @app.get("/stk/hoja")
    def stk_hoja(tipo: str, prop: float = 1.0, t: str = ""):
        """Hoja del sticker; con prop y trabajo, la hecha a la medida (si ya está; si no, la base)."""
        if tipo not in {a for a, *_ in ed.CATALOGO_STICKERS}:
            raise HTTPException(404)
        trabajo = validar(t) if t else None
        p = ed.hoja_sticker(tipo, ed.prop_sticker({"prop": prop}), trabajo)
        return FileResponse(p, media_type="image/png",
                            headers={"Cache-Control": "max-age=86400" if p.parent == ed.DIR_STICKERS else "no-store"})

    @app.post("/stk/hoja_trabajo")
    def stk_hoja_trabajo(d: dict = Body(...)):
        """La pestaña Edición manda la hoja de un sticker de línea estirado (dibujado a la medida)."""
        t = validar(d.get("t"))
        tipo = str(d.get("tipo"))
        if tipo not in ed.STICKERS_LINEA:
            raise HTTPException(400, "Ese sticker no se dibuja a la medida")
        prop = ed.prop_sticker(d)
        datos = str(d.get("png") or "")
        if "," in datos:
            datos = datos.split(",", 1)[1]
        import base64
        crudo = base64.b64decode(datos)
        if not crudo.startswith(b"\x89PNG"):
            raise HTTPException(400, "No es una imagen PNG")
        carpeta = Path(t) / "stickers"
        carpeta.mkdir(exist_ok=True)
        (carpeta / f"{tipo}_{prop:.2f}.png").write_bytes(crudo)
        return {"ok": True}

    @app.post("/edi/difuminar_buscar")
    def edi_difuminar_buscar(d: dict = Body(...)):
        return buscar_difuminar(validar(d.get("t")))

    @app.get("/edi/difuminar_estado")
    def edi_difuminar_estado(t: str):
        return {"estado": estado_difuminar(validar(t))}

    @app.post("/edi/renderizar")
    def edi_renderizar(d: dict = Body(...)):
        return renderizar_de_nuevo(validar(d.get("t")))

    @app.get("/edi/render_estado")
    def edi_render_estado(t: str):
        return estado_render_edicion(validar(t))

    @app.post("/proc/cancelar")
    def proc_cancelar():
        n, cola = cancelar_todo()
        return {"ok": True, "procesos": n, "cola": cola}

    return app


# ----------------------------------------------------------------------------
# Procesos largos con barra de progreso
# ----------------------------------------------------------------------------
def sonido_aviso():
    """Sonido de «terminó» (web/notificacion.mp3) para la barra de progreso."""
    return f'<audio autoplay src="/app/notificacion.mp3?v={int(time.time() * 1000)}" style="display:none"></audio>'


def barra(frac=None, etapa="", estado="trabajando", detalle=""):
    """HTML de la barra de progreso que va arriba del video."""
    if frac is None:
        return ""
    pct = int(round(100 * min(1.0, max(0.0, frac))))
    color = {"trabajando": "#EDEDF0", "listo": "#3DD68C", "error": "#FF6B6F"}[estado]
    texto = f"{etapa}… <span style=\"font-family:'Geist Mono',monospace;color:#9A9AA3\">{pct}%</span>" \
        if estado == "trabajando" else etapa
    extra = (f'<div style="margin-top:6px;font-size:12px;color:#FF8C8F;white-space:pre-wrap">{detalle}</div>'
             if detalle else "")
    return (f'<div class="barra-prog" style="padding:2px 0;font-family:Geist,system-ui,sans-serif">'
            f'<div style="font-weight:500;font-size:13.5px;margin-bottom:8px;color:{color}">{texto}</div>'
            f'<div style="background:#1D1D22;border-radius:999px;height:6px;overflow:hidden">'
            f'<div style="width:{pct}%;height:100%;background:{color};border-radius:999px;transition:width .4s"></div>'
            f'</div>{extra}</div>')


# Registro: todo lo que va haciendo la plataforma (para ver cómo trabaja). Se guarda también en registro.log
REGISTRO = []
REGISTRO_MAX = 4000
ARCHIVO_REGISTRO = BASE / "registro.log"
_reg_lock = threading.Lock()


def registrar(linea):
    linea = f"{time.strftime('%H:%M:%S')}  {linea}"
    with _reg_lock:
        REGISTRO.append(linea)
        _REG_N[0] += 1
        if len(REGISTRO) > REGISTRO_MAX:
            del REGISTRO[:len(REGISTRO) - REGISTRO_MAX]
        try:
            with open(ARCHIVO_REGISTRO, "a", encoding="utf-8") as f:
                f.write(linea + "\n")
        except OSError:
            pass


_REG_N = [0]   # cuántas veces cambió el registro (para no mandar el texto si no hay nada nuevo)


def texto_registro():
    with _reg_lock:
        return "\n".join(REGISTRO[-1500:]) or "Aquí aparece lo que va haciendo la plataforma cuando procesas un video."


def tick_registro(visto):
    """Cada 2 s: solo manda el registro si hay algo nuevo (antes mandaba hasta 1500 líneas cada vez, todo el día)."""
    n = _REG_N[0]
    if n == visto:
        return gr.update(), visto
    return texto_registro(), n


_GPU_CACHE = {"t": 0, "datos": None}


def estado_gpu():
    """Temperatura, uso y si la tarjeta NVIDIA está bajando su velocidad por calor (se consulta cada 15 s)."""
    if time.time() - _GPU_CACHE["t"] < 15:
        return _GPU_CACHE["datos"]
    _GPU_CACHE["t"] = time.time()
    datos = None
    smi = shutil.which("nvidia-smi")
    if smi:
        base = "name,temperature.gpu,utilization.gpu,memory.used,memory.total"
        for calor in ("clocks_event_reasons.sw_thermal_slowdown,clocks_event_reasons.hw_thermal_slowdown",
                      "clocks_throttle_reasons.sw_thermal_slowdown,clocks_throttle_reasons.hw_thermal_slowdown", ""):
            try:
                q = base + ("," + calor if calor else "")
                r = subprocess.run([smi, f"--query-gpu={q}", "--format=csv,noheader,nounits"], capture_output=True,
                                   text=True, timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if r.returncode != 0 or not r.stdout.strip():
                    continue
                v = [x.strip() for x in r.stdout.strip().splitlines()[0].split(",")]
                datos = {"nombre": v[0], "temp": float(v[1]), "uso": float(v[2]), "mem": float(v[3]), "mem_total": float(v[4]),
                         "calor": any(x.lower() == "active" for x in v[5:])}
                break
            except Exception:
                continue
    _GPU_CACHE["datos"] = datos
    return datos


def estado_equipo():
    """Recuadro de «Registro»: memoria, disco, procesos de la plataforma y calor, para saber por qué se alenta."""
    filas, alertas = [], []
    try:
        import psutil
    except Exception:
        psutil = None
    if psutil:
        try:
            yo = psutil.Process()
            hijos = yo.children(recursive=True)
            mem = yo.memory_info().rss
            for h in hijos:
                try:
                    mem += h.memory_info().rss
                except Exception:
                    pass
            vm = psutil.virtual_memory()
            filas.append(("Memoria de la plataforma", f"{mem / 2**30:.1f} GB"))
            filas.append(("Memoria del equipo", f"{vm.percent:.0f}% ocupada ({vm.available / 2**30:.1f} GB libres)"))
            if vm.percent >= 90:
                alertas.append("La memoria del equipo está casi llena: cierra pestañas de Chrome o reinicia la plataforma.")
            cpu = psutil.cpu_percent(interval=None)
            filas.append(("Procesador", f"{cpu:.0f}% en uso"))
            try:
                temps = psutil.sensors_temperatures() if hasattr(psutil, "sensors_temperatures") else {}
                maxt = max((x.current for v in temps.values() for x in v if x.current), default=None)
                if maxt:
                    filas.append(("Temperatura del procesador", f"{maxt:.0f} °C"))
                    if maxt >= 90:
                        alertas.append("El procesador está muy caliente: baja su velocidad solo para protegerse.")
            except Exception:
                pass
        except Exception:
            pass
    try:
        du = shutil.disk_usage(CARPETA_VIDEOS if Path(CARPETA_VIDEOS).exists() else BASE)
        pct = du.used / du.total * 100
        filas.append(("Disco de los videos", f"{du.free / 2**30:.0f} GB libres ({pct:.0f}% ocupado)"))
        if pct >= 90 or du.free < 15 * 2**30:
            alertas.append("Queda poco espacio en disco: borra trabajos viejos o exportados que ya no uses.")
    except Exception:
        pass
    g = estado_gpu()
    if g:
        filas.append(("Tarjeta gráfica", f"{g['nombre']} · {g['temp']:.0f} °C · {g['uso']:.0f}% en uso · "
                                          f"{g['mem'] / 1024:.1f} de {g['mem_total'] / 1024:.0f} GB"))
        if g["calor"] or g["temp"] >= 85:
            alertas.append("La tarjeta gráfica está caliente y bajó su velocidad: por eso el render va más lento. "
                           "Revisa que tenga ventilación.")
    with _ACTIVOS_LOCK:
        vivos = [x for x in _ACTIVOS if x.poll() is None]
    nombres = []
    for x in vivos:
        try:
            args = x.args if isinstance(x.args, (list, tuple)) else [str(x.args)]
            que = next((a for a in args[2:3]), Path(str(args[0])).name)
            que = {"proxy": "copia ligera", "render": "render", "difuminar": "difuminado", "analizar": "análisis",
                   "exportar": "exportación"}.get(str(que), str(que))
            mins = (time.time() - getattr(x, "_inicio", time.time())) / 60
            nombres.append(f"{que} ({mins:.0f} min)")
        except Exception:
            pass
    filas.append(("Procesos trabajando", ", ".join(nombres) if nombres else "ninguno"))
    if any(getattr(x, "_inicio", time.time()) < time.time() - 3600 for x in vivos):
        alertas.append("Hay un proceso trabajando desde hace más de una hora: si no esperas nada, usa «Cancelar todo».")
    html = "".join(f"<div class='est-f'><span>{k}</span><b>{v}</b></div>" for k, v in filas)
    html += "".join(f"<div class='est-a'>⚠ {a}</div>" for a in alertas) or "<div class='est-ok'>Todo en orden.</div>"
    return f"<div id='estado_equipo'><div class='est-t'>Estado del equipo</div>{html}</div>"


def limpiar_registro():
    with _reg_lock:
        REGISTRO.clear()
        _REG_N[0] += 1
    return texto_registro()


def correr(cmd):
    """Corre editor.py y va devolviendo (html_barra, resultado_final_o_None)."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    proc = lanzar(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=str(BASE), env=env)
    lineas, avisos = [], []
    nombres = {"todo": "Analizar y armar", "render": "Renderizar", "convertir": "Convertir a MP4", "analizar": "Analizar"}
    registrar("─" * 60)
    registrar(f"▶ {nombres.get(cmd[2] if len(cmd) > 2 else '', 'Proceso')}: {Path(cmd[3]).name if len(cmd) > 3 else ''}")
    inicio = time.time()
    etapa_ant = None
    yield barra(0.0, "Preparando"), None
    for raw in iter(proc.stdout.readline, b""):
        linea = raw.decode("utf-8", errors="replace").rstrip()
        if linea.startswith("@@AVISO@@"):
            avisos.append("⚠ " + linea.split(" ", 1)[1])
            registrar("⚠ " + linea.split(" ", 1)[1])
            continue
        if linea.startswith("@@PROGRESO@@"):
            try:
                valor, etapa = linea.split(" ", 1)[1].split("|", 1)
                if etapa != etapa_ant:
                    registrar(f"● {etapa}")
                    etapa_ant = etapa
                yield barra(float(valor), etapa), None
            except ValueError:
                pass
            continue
        if "WARN" in linea and "dnn" in linea:
            continue
        lineas.append(linea)
        if linea.strip():
            registrar("   " + linea.replace("[editor] ", ""))
    proc.wait()
    seg = int(time.time() - inicio)
    if proc.returncode != 0 and fue_cancelado(proc):
        registrar(f"⛔ Cancelado a los {seg // 60} min {seg % 60} s")
        yield barra(1.0, "⛔ Cancelado. Puedes corregir y volver a empezar.", "error"), {"ok": False, "cancelado": True}
        return
    registrar(f"{'✔ Terminó' if proc.returncode == 0 else '✖ Falló'} en {seg // 60} min {seg % 60} s")
    final = None
    for linea in reversed(lineas):
        if linea.startswith("{"):
            try:
                final = json.loads(linea)
            except json.JSONDecodeError:
                pass
            break
    if proc.returncode == 0 and final and final.get("ok"):
        # aviso con sonido al terminar (análisis o exportación)
        yield barra(1.0, "Listo ✓", "listo", "\n".join(avisos).replace("<", "&lt;")) + sonido_aviso(), final
    else:
        utiles = [x for x in lineas if x.strip() and not x.startswith("[editor]")][-6:] or lineas[-6:]
        detalle = "\n".join(utiles).replace("<", "&lt;")
        yield barra(1.0, "Algo falló. Esto fue lo último que pasó:", "error", detalle), {"ok": False}


def unidades():
    if os.name == "nt":
        return [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
    return ["/"]


# ----------------------------------------------------------------------------
# Interfaz
# ----------------------------------------------------------------------------
def iframe_edi(t):
    if not t:
        return ("<div class='vacio-editor'>Elige un video y presiona <b>Analizar video</b>, "
                "o abre un trabajo que ya exista.</div>")
    url = f"/edi/editor?t={quote(t)}&v={int(time.time() * 1000)}"
    return (f'<iframe src="{url}" style="width:100%;height:1080px;border:0;border-radius:12px;background:#0b0b0d"></iframe>'
            f'<div style="text-align:right;font-size:13px"><a href="{url}" target="_blank">Abrir en otra ventana ↗</a></div>')


def opciones_videos():
    """Videos de la carpeta VideosEdit para el desplegable: (etiqueta, nombre). «Editado» si ya tiene su _trabajo."""
    if not CARPETA_VIDEOS.exists():
        return []
    por_nombre = {}
    for f in CARPETA_VIDEOS.iterdir():
        if not f.is_file() or f.suffix.lower() not in EXT_VIDEO:
            continue
        previo = por_nombre.get(f.stem)
        # si existe el original y su MP4 convertido, se muestra uno solo (el MP4)
        if previo is None or f.suffix.lower() == ".mp4":
            por_nombre[f.stem] = f
    out = []
    for stem, f in sorted(por_nombre.items(), key=lambda kv: kv[0].lower()):
        editado = (CARPETA_VIDEOS / f"{stem}_trabajo" / "plan.json").exists()
        out.append((f"{f.name}   ·   ✔ Editado" if editado else f.name, f.name))
    return out


def opciones_trabajos():
    """Carpetas _trabajo de VideosEdit (las más recientes primero)."""
    if not CARPETA_VIDEOS.exists():
        return []
    dirs = [d for d in CARPETA_VIDEOS.iterdir() if d.is_dir() and d.name.endswith("_trabajo") and (d / "plan.json").exists()]
    dirs.sort(key=lambda d: (d / "plan.json").stat().st_mtime, reverse=True)
    return [(d.name[: -len("_trabajo")], str(d)) for d in dirs]


TEMA_CSS = """
@font-face { font-family: "Geist"; src: url("/app/fuentes/Geist-Variable.woff2") format("woff2"); font-weight: 100 900; font-display: swap; }
@font-face { font-family: "Geist Mono"; src: url("/app/fuentes/GeistMono-Variable.woff2") format("woff2"); font-weight: 100 900; font-display: swap; }
:root, .dark { --color-accent: #E5252A; --font: "Geist", system-ui, sans-serif; --font-mono: "Geist Mono", monospace; }
body, .gradio-container { background: #0B0B0D !important; font-family: "Geist", system-ui, sans-serif !important; }
.gradio-container { max-width: 100% !important; padding: 0 !important; }
.gradio-container > .main, .gradio-container .wrap.main { padding: 0 !important; }
footer { display: none !important; }
#marco { gap: 0 !important; min-height: 100vh; flex-wrap: nowrap !important; }
/* menú lateral */
#nav { flex: 0 0 232px !important; max-width: 232px; min-width: 232px !important; border-right: 1px solid #1D1D22; padding: 22px 14px !important;
  gap: 4px !important; background: #0B0B0D; position: sticky; top: 0; align-self: flex-start; min-height: 100vh; }
#nav .marca { display: flex; align-items: center; gap: 10px; padding: 4px 10px 22px; font: 600 15px "Geist", sans-serif; color: #EDEDF0; letter-spacing: -0.01em; }
#nav .marca i { width: 26px; height: 26px; border-radius: 7px; background: #E5252A; display: inline-flex; align-items: center; justify-content: center; }
#nav .marca i span { width: 9px; height: 14px; border: 1.8px solid #fff; border-radius: 2px; display: block; }
#nav button.nav { justify-content: flex-start !important; height: 38px; padding: 0 10px !important; border-radius: 8px !important; border: 0 !important;
  background: transparent !important; color: #C9C9CF !important; font: 400 14px "Geist", sans-serif !important; box-shadow: none !important; min-width: 0 !important; }
#nav button.nav:hover { background: #141417 !important; color: #fff !important; }
#nav button.nav.activo { background: #1D1D22 !important; color: #fff !important; font-weight: 500 !important; }
#nav .relleno { flex: 1 1 auto; min-height: 40px; }
#nav > *:has(.relleno) { flex: 1 1 auto !important; display: flex; flex-direction: column; justify-content: flex-end; }
#nav > *:has(.relleno) > * { flex: 1 1 auto; display: flex; flex-direction: column; justify-content: flex-end; }
#nav .carpeta { padding: 10px; font-size: 12px; color: #6E6E78; line-height: 1.5; word-break: break-all; }
#nav .carpeta b { display: block; font: 400 11.5px "Geist Mono", monospace; color: #9A9AA3; }
#btn_cerrar { justify-content: flex-start !important; height: 38px; padding: 0 10px !important; border: 0 !important; background: transparent !important;
  color: #9A9AA3 !important; font: 400 14px "Geist", sans-serif !important; box-shadow: none !important; }
#btn_cerrar:hover { color: #FF8C8F !important; background: rgba(229,37,42,.08) !important; }
/* menú lateral plegable (solo iconos), como el de ChatGPT */
#nav { transition: flex-basis .18s ease, min-width .18s ease, max-width .18s ease, padding .18s ease; overflow: hidden; }
#nav .marca { position: relative; padding-right: 40px; white-space: nowrap; }
#nav .plegar { position: absolute; right: 2px; top: 0; width: 30px; height: 30px; border: 0; border-radius: 7px; background: transparent; cursor: pointer; }
#nav .plegar::before { content: ''; position: absolute; inset: 6px; background: #9A9AA3; -webkit-mask: url("data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20viewBox='0%200%2024%2024'%20fill='none'%20stroke='black'%20stroke-width='1.8'%20stroke-linecap='round'%20stroke-linejoin='round'%3E%3Crect%20x='3'%20y='4'%20width='18'%20height='16'%20rx='2.5'/%3E%3Cpath%20d='M9%204v16'/%3E%3C/svg%3E") center / contain no-repeat; mask: url("data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20viewBox='0%200%2024%2024'%20fill='none'%20stroke='black'%20stroke-width='1.8'%20stroke-linecap='round'%20stroke-linejoin='round'%3E%3Crect%20x='3'%20y='4'%20width='18'%20height='16'%20rx='2.5'/%3E%3Cpath%20d='M9%204v16'/%3E%3C/svg%3E") center / contain no-repeat; }
#nav .plegar:hover { background: #141417; } #nav .plegar:hover::before { background: #fff; }
#nav_editor::before { -webkit-mask-image: url("data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20viewBox='0%200%2024%2024'%20fill='none'%20stroke='black'%20stroke-width='1.8'%20stroke-linecap='round'%20stroke-linejoin='round'%3E%3Cpath%20d='M4%2020h4L19%209l-4-4L4%2016v4z'/%3E%3Cpath%20d='M13.5%206.5l4%204'/%3E%3C/svg%3E"); mask-image: url("data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20viewBox='0%200%2024%2024'%20fill='none'%20stroke='black'%20stroke-width='1.8'%20stroke-linecap='round'%20stroke-linejoin='round'%3E%3Cpath%20d='M4%2020h4L19%209l-4-4L4%2016v4z'/%3E%3Cpath%20d='M13.5%206.5l4%204'/%3E%3C/svg%3E"); }
#nav_largo::before { -webkit-mask-image: url("data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20viewBox='0%200%2024%2024'%20fill='none'%20stroke='black'%20stroke-width='1.8'%20stroke-linecap='round'%20stroke-linejoin='round'%3E%3Crect%20x='3'%20y='5'%20width='18'%20height='14'%20rx='2'/%3E%3Cpath%20d='M7%205v14M17%205v14M3%209.5h4M3%2014.5h4M17%209.5h4M17%2014.5h4'/%3E%3C/svg%3E"); mask-image: url("data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20viewBox='0%200%2024%2024'%20fill='none'%20stroke='black'%20stroke-width='1.8'%20stroke-linecap='round'%20stroke-linejoin='round'%3E%3Crect%20x='3'%20y='5'%20width='18'%20height='14'%20rx='2'/%3E%3Cpath%20d='M7%205v14M17%205v14M3%209.5h4M3%2014.5h4M17%209.5h4M17%2014.5h4'/%3E%3C/svg%3E"); }
#nav_aprendido::before { -webkit-mask-image: url("data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20viewBox='0%200%2024%2024'%20fill='none'%20stroke='black'%20stroke-width='1.8'%20stroke-linecap='round'%20stroke-linejoin='round'%3E%3Cpath%20d='M9%2018h6M10%2021h4'/%3E%3Cpath%20d='M12%203a6%206%200%200%200-3.5%2010.9c.6.5%201%201.2%201%202.1h5c0-.9.4-1.6%201-2.1A6%206%200%200%200%2012%203z'/%3E%3C/svg%3E"); mask-image: url("data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20viewBox='0%200%2024%2024'%20fill='none'%20stroke='black'%20stroke-width='1.8'%20stroke-linecap='round'%20stroke-linejoin='round'%3E%3Cpath%20d='M9%2018h6M10%2021h4'/%3E%3Cpath%20d='M12%203a6%206%200%200%200-3.5%2010.9c.6.5%201%201.2%201%202.1h5c0-.9.4-1.6%201-2.1A6%206%200%200%200%2012%203z'/%3E%3C/svg%3E"); }
#nav_registro::before { -webkit-mask-image: url("data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20viewBox='0%200%2024%2024'%20fill='none'%20stroke='black'%20stroke-width='1.8'%20stroke-linecap='round'%20stroke-linejoin='round'%3E%3Cpath%20d='M8%206h12M8%2012h12M8%2018h12'/%3E%3Ccircle%20cx='4'%20cy='6'%20r='.6'/%3E%3Ccircle%20cx='4'%20cy='12'%20r='.6'/%3E%3Ccircle%20cx='4'%20cy='18'%20r='.6'/%3E%3C/svg%3E"); mask-image: url("data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20viewBox='0%200%2024%2024'%20fill='none'%20stroke='black'%20stroke-width='1.8'%20stroke-linecap='round'%20stroke-linejoin='round'%3E%3Cpath%20d='M8%206h12M8%2012h12M8%2018h12'/%3E%3Ccircle%20cx='4'%20cy='6'%20r='.6'/%3E%3Ccircle%20cx='4'%20cy='12'%20r='.6'/%3E%3Ccircle%20cx='4'%20cy='18'%20r='.6'/%3E%3C/svg%3E"); }
#btn_cerrar::before { -webkit-mask-image: url("data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20viewBox='0%200%2024%2024'%20fill='none'%20stroke='black'%20stroke-width='1.8'%20stroke-linecap='round'%20stroke-linejoin='round'%3E%3Cpath%20d='M12%203v8'/%3E%3Cpath%20d='M6.3%206.8a8%208%200%201%200%2011.4%200'/%3E%3C/svg%3E"); mask-image: url("data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20viewBox='0%200%2024%2024'%20fill='none'%20stroke='black'%20stroke-width='1.8'%20stroke-linecap='round'%20stroke-linejoin='round'%3E%3Cpath%20d='M12%203v8'/%3E%3Cpath%20d='M6.3%206.8a8%208%200%201%200%2011.4%200'/%3E%3C/svg%3E"); }
#nav button.nav::before, #btn_cerrar::before { content: ''; flex: 0 0 18px; width: 18px; height: 18px; margin-right: 10px; background: currentColor; -webkit-mask-size: contain; mask-size: contain; -webkit-mask-repeat: no-repeat; mask-repeat: no-repeat; -webkit-mask-position: center; mask-position: center; }
#nav button.nav, #btn_cerrar { white-space: nowrap; overflow: hidden; }
#nav.mini { flex-basis: 64px !important; max-width: 64px !important; min-width: 64px !important; padding: 22px 10px !important; }
#nav.mini .marca { padding: 4px 0 22px 6px; font-size: 0; }
#nav.mini .marca i { display: none; }
#nav.mini .plegar { position: relative; right: auto; top: auto; display: block; margin: 0 auto; }
#nav.mini .marca { padding: 4px 0 22px 0; gap: 0; justify-content: center; }
#nav.mini button.nav, #nav.mini #btn_cerrar { font-size: 0 !important; justify-content: center !important; padding: 0 !important; }
#nav.mini button.nav::before, #nav.mini #btn_cerrar::before { margin-right: 0; }
#nav.mini .carpeta { display: none; }

/* estado del equipo (Registro) */
#estado_equipo { border: 1px solid #2A2A30; border-radius: 12px; background: #141417; padding: 14px 16px; margin-bottom: 14px; }
#estado_equipo .est-t { font: 600 13px "Geist", sans-serif; color: #EDEDF0; margin-bottom: 8px; }
#estado_equipo .est-f { display: flex; justify-content: space-between; gap: 16px; padding: 5px 0; border-top: 1px solid #1D1D22; font-size: 13px; }
#estado_equipo .est-f span { color: #9A9AA3; } #estado_equipo .est-f b { color: #EDEDF0; font-weight: 500; text-align: right; }
#estado_equipo .est-a { margin-top: 8px; padding: 8px 10px; border-radius: 8px; background: rgba(242,163,58,.1); color: #F2A33A; font-size: 13px; }
#estado_equipo .est-ok { margin-top: 8px; color: #3DD68C; font-size: 13px; }
/* contenido */
#contenido { padding: 0 !important; min-width: 0 !important; gap: 0 !important; }
#secciones > .tab-wrapper { display: none !important; }
#secciones, #secciones > .tabitem { padding: 0 !important; border: 0 !important; background: transparent !important; }
.seccion { padding: 36px 44px !important; gap: 26px !important; }
.titulo-sec h1 { margin: 0; font: 600 28px/1.1 "Geist", sans-serif; letter-spacing: -0.02em; color: #EDEDF0; }
.titulo-sec p { margin: 6px 0 0; color: #9A9AA3; font-size: 14px; }
.etiqueta, .etiqueta * { font: 500 11px "Geist", sans-serif !important; letter-spacing: .12em !important; text-transform: uppercase; color: #9A9AA3 !important; }
#progreso_caja { padding: 14px 44px !important; border-bottom: 1px solid #1D1D22; align-items: center !important; gap: 16px !important; }
#progreso_caja:not(:has(.barra-prog)) { display: none !important; }
#progreso_caja .block { background: transparent !important; border: 0 !important; padding: 0 !important; }
/* bloques de Gradio más planos */
.block, .form { border-color: #2A2A30 !important; }
#inicio .block, #inicio .form { background: transparent !important; border: 0 !important; box-shadow: none !important; padding: 0 !important; }
#inicio label > span[data-testid="block-info"], #inicio [data-testid="block-info"] { font: 500 11px "Geist", sans-serif !important;
  letter-spacing: .12em; text-transform: uppercase; color: #9A9AA3 !important; margin-bottom: 8px; }
#inicio input[type=text], #inicio textarea { background: #0B0B0D !important; border: 1px solid #2A2A30 !important; border-radius: 10px !important;
  min-height: 44px; font-size: 15px !important; padding: 10px 14px !important; }
#inicio .wrap-inner, #inicio .secondary-wrap { background: #141417 !important; border-radius: 10px !important; }
/* estilos de edición como tarjetas */
#estilo .wrap { display: grid !important; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px !important; }
#estilo .wrap label { position: relative; display: flex !important; flex-direction: column; align-items: flex-start !important; gap: 10px !important; padding: 12px !important;
  border-radius: 10px !important; border: 1px solid #2A2A30 !important; background: transparent !important; color: #C9C9CF !important;
  font: 500 13px "Geist", sans-serif !important; min-height: 104px; cursor: pointer; box-shadow: none !important; }
#estilo .wrap label:hover { border-color: #3A3A42 !important; color: #fff !important; }
#estilo .wrap label.selected { border: 1.5px solid #E5252A !important; background: #141417 !important; color: #fff !important; }
#estilo .wrap label input { position: absolute; opacity: 0; pointer-events: none; }
#estilo .wrap label::before { content: ""; width: 34px; height: 56px; border-radius: 5px; background: #4A4A54; display: block; }
#estilo .wrap label:nth-child(1)::before { background: linear-gradient(#4A4A54 0 52%, #3B82F6 52% 60%, #2A2A30 60%); }
#estilo .wrap label:nth-child(2)::before { background: linear-gradient(#4A4A54 0 74%, #fff 74% 80%, #4A4A54 80%); background-size: 22px 100%; background-repeat: no-repeat; background-position: center; background-color: #4A4A54; }
#estilo .wrap label:nth-child(3)::before { background: linear-gradient(#4A4A54 0 12%, #F2A33A 12% 20%, #4A4A54 20% 25%, #fff 25% 31%, #4A4A54 31%); }
#estilo .wrap label:nth-child(4)::before { background: linear-gradient(#1F3A4A 0 10%, #FAE24A 10% 15%, #1F3A4A 15% 20%, #4A4A54 20% 78%, #1F3A4A 78%); }
#estilo .wrap label:nth-child(5)::before { background: linear-gradient(#4A4A54 0 50%, #3A3A42 50%); }
#estilo .wrap label:nth-child(6)::before { background: linear-gradient(#4A4A54 0 47%, #fff 47% 53%, #4A4A54 53%); background-size: 22px 100%; background-repeat: no-repeat; background-position: center; background-color: #4A4A54; }
/* botones */
button.primary, button.lg.primary { background: #E5252A !important; border: 0 !important; font-weight: 600 !important; border-radius: 10px !important; }
button.primary:hover { background: #F23B40 !important; }
button.secondary { background: #1D1D22 !important; border: 1px solid #2A2A30 !important; border-radius: 8px !important; font-weight: 500 !important; }
#btn_procesar { min-height: 46px; font-size: 15px !important; }
#fila_procesar { align-items: center !important; border-top: 1px solid #1D1D22; padding-top: 16px !important; }
/* recientes */
#recientes .wrap { display: flex !important; flex-direction: column; gap: 0 !important; border-top: 1px solid #1D1D22; }
#recientes .wrap label { border: 0 !important; border-bottom: 1px solid #1D1D22 !important; border-radius: 0 !important; background: transparent !important;
  padding: 14px 6px !important; box-shadow: none !important; color: #EDEDF0 !important; font: 400 14px "Geist", sans-serif !important; cursor: pointer; }
#recientes .wrap label:hover { background: #141417 !important; }
#recientes .wrap label input { display: none; }
#otro_trabajo { border: 0 !important; background: transparent !important; }
/* área de trabajo */
#cabeza_trabajo { align-items: center !important; gap: 12px !important; padding: 12px 20px !important; border-bottom: 1px solid #1D1D22; flex-wrap: wrap !important; }
#btn_volver { max-width: 40px; min-width: 40px !important; height: 36px; padding: 0 !important; background: transparent !important; border: 1px solid #2A2A30 !important; }
#trabajo_actual { color: #EDEDF0; font-size: 14px; }
#trabajo_actual p { margin: 0; }
#btn_cancelar { background: transparent !important; border: 1px solid #2A2A30 !important; color: #9A9AA3 !important; }
#btn_cancelar:hover { color: #FF8C8F !important; border-color: #4A2326 !important; }
#btn_exportar { min-height: 36px; }
#pasos > .tab-wrapper { padding: 10px 20px 0; border: 0 !important; }
#pasos [role=tablist] { display: inline-flex !important; width: fit-content !important; flex: 0 0 auto !important; padding: 3px; background: #141417; border: 1px solid #2A2A30; border-radius: 9px; gap: 2px; }
#pasos [role=tablist] button { height: 30px; padding: 0 16px !important; border-radius: 6px !important; color: #9A9AA3 !important; border: 0 !important; font: 500 13px "Geist", sans-serif !important; }
#pasos [role=tablist] button.selected { background: #2A2A30 !important; color: #fff !important; }
#pasos [role=tablist] button.selected::after, #pasos [role=tablist] button::after { display: none !important; }
#pasos > .tabitem { padding: 10px 0 0 !important; border: 0 !important; }
.vacio-editor { padding: 60px 20px; text-align: center; color: #9A9AA3; border: 1px dashed #2A2A30; border-radius: 12px; }
#aviso_video { margin: 16px 44px 0 !important; padding: 18px 20px !important; border: 1px solid #5A4520 !important; border-radius: 12px !important;
  background: #17140D !important; gap: 12px !important; }
#aviso_video p { margin: 0 0 4px; color: #EDEDF0; }
#caja_registro textarea { font: 12.5px/1.5 "Geist Mono", monospace !important; background: #0B0B0D !important; }
"""

TEMA_JS = """() => {
  document.body.classList.add('dark');
  // menú lateral plegable: se recuerda en este navegador
  let MINI = false;
  const poner = (mini) => {
    MINI = mini;
    const n = document.getElementById('nav'); if (n) n.classList.toggle('mini', mini);
    document.querySelectorAll('#nav button.nav, #btn_cerrar').forEach(b => { b.title = mini ? b.textContent.trim() : ''; });
    const p = document.querySelector('#nav .plegar'); if (p) p.title = mini ? 'Mostrar menú' : 'Ocultar menú';
  };
  let mini = false; try { mini = localStorage.getItem('nav_mini') === '1'; } catch (e) {}
  poner(mini);
  // por si la página vuelve a dibujar el menú
  setInterval(() => { const n = document.getElementById('nav'); if (n && n.classList.contains('mini') !== MINI) poner(MINI); }, 700);
  document.addEventListener('click', (ev) => {
    if (!ev.target.closest('#nav .plegar')) return;
    const m = !MINI; poner(m);
    try { localStorage.setItem('nav_mini', m ? '1' : '0'); } catch (e) {}
  });
}"""

JS_CERRAR = """() => {
  if (!confirm('¿Cerrar el Editor Vertical? Se detiene todo lo que esté trabajando (análisis, exportación, vistas previas, video largo).')) return;
  fetch('/app/cerrar', {method: 'POST'}).catch(() => {});
  document.body.innerHTML = '<div style="font:600 20px Geist,system-ui;color:#EDEDF0;background:#0B0B0D;height:100vh;display:flex;' +
    'flex-direction:column;align-items:center;justify-content:center;gap:10px"><div>El Editor Vertical se cerró.</div>' +
    '<div style="font-weight:400;font-size:14px;color:#9A9AA3">Puedes cerrar esta pestaña. Para volver a usarlo, abre «Editor Vertical» desde el escritorio.</div></div>';
  setTimeout(() => { try { window.close(); } catch (e) {} }, 300);
}"""


def tema():
    t = gr.themes.Base(primary_hue=gr.themes.colors.red, secondary_hue=gr.themes.colors.red,
                       neutral_hue=gr.themes.colors.zinc, radius_size=gr.themes.sizes.radius_md,
                       font=["Geist", "system-ui", "sans-serif"], font_mono=["Geist Mono", "monospace"])
    oscuro = dict(body_background_fill="#0B0B0D", background_fill_primary="#141417", background_fill_secondary="#0B0B0D",
                  block_background_fill="#141417", block_border_color="#2A2A30", border_color_primary="#2A2A30",
                  input_background_fill="#0B0B0D", body_text_color="#EDEDF0", block_label_text_color="#9A9AA3",
                  block_title_text_color="#EDEDF0", button_primary_background_fill="#E5252A",
                  button_primary_background_fill_hover="#F23B40", button_primary_text_color="#ffffff",
                  button_secondary_background_fill="#1D1D22", button_secondary_text_color="#EDEDF0",
                  button_secondary_border_color="#2A2A30", checkbox_background_color_selected="#EDEDF0",
                  checkbox_border_color_selected="#EDEDF0", color_accent_soft="#1D1D22", loader_color="#E5252A",
                  slider_color="#EDEDF0", body_text_color_subdued="#9A9AA3")
    return t.set(**oscuro, **{k + "_dark": v for k, v in oscuro.items()})


def hace_cuanto(ts):
    d = time.time() - ts
    if d < 3600:
        return f"hace {max(1, int(d // 60))} min"
    if d < 86400:
        return f"hace {int(d // 3600)} h"
    if d < 2 * 86400:
        return "ayer"
    return time.strftime("%d/%m", time.localtime(ts))


def opciones_recientes(n=8):
    """Los trabajos más recientes para la lista de inicio: (etiqueta, ruta)."""
    nombres = {Path(v).name: k for k, v in ESTILOS.items()}
    out = []
    for nombre, ruta in opciones_trabajos()[:n]:
        p = Path(ruta) / "plan.json"
        try:
            plan = ed.cargar_json(p)
            est = nombres.get(Path(str(plan.get("plantilla", ""))).name, "")
            est = est.replace(" (Chapucero)", "")
            titulo = " ".join((plan.get("titulo") or "").split())
        except Exception:
            est, titulo = "", ""
        listo = " · exportado" if exportado_de(ruta) else ""
        out.append((f"{titulo or nombre}   ·   {est or 'trabajo'} · {hace_cuanto(p.stat().st_mtime)}{listo}", ruta))
    return out


NAV = (("editor", "Editor"), ("largo", "Video largo"), ("aprendido", "Lo aprendido"), ("registro", "Registro"))


def construir():
    extra = {"theme": tema(), "css": TEMA_CSS, "js": TEMA_JS} if _TEMA_EN_BLOCKS else {}
    with gr.Blocks(title="Editor vertical · El Chapucero", fill_width=True, **extra) as demo:
        trabajo = gr.State("")
        with gr.Row(elem_id="marco", equal_height=False):
            # ======================== menú lateral ========================
            with gr.Column(elem_id="nav", scale=0, min_width=232):
                gr.HTML('<div class="marca"><i><span></span></i>Editor Vertical'
                        '<button class="plegar" type="button" title="Ocultar menú"></button></div>')
                botones_nav = [gr.Button(txt, elem_id=f"nav_{k}", elem_classes=["nav"] + (["activo"] if k == "editor" else []),
                                         size="sm") for k, txt in NAV]
                gr.HTML(f'<div class="relleno"></div><div class="carpeta">Carpeta<b>{CARPETA_VIDEOS}</b></div>')
                btn_cerrar = gr.Button("Cerrar", elem_id="btn_cerrar", size="sm")
            # Cerrar: detiene todo lo que esté trabajando, apaga la plataforma y deja la pestaña en blanco
            btn_cerrar.click(None, None, None, js=JS_CERRAR)

            # ======================== contenido ========================
            with gr.Column(elem_id="contenido", scale=1):
                with gr.Row(elem_id="progreso_caja", equal_height=True):
                    progreso = gr.HTML(elem_id="progreso")
                    btn_cancelar = gr.Button("Cancelar todo", elem_id="btn_cancelar", scale=0, min_width=130)
                # «Solo subtítulos»: el video cambió (o ya tenía subtítulos): ¿mismos subtítulos o transcribir de nuevo?
                aviso_t = gr.State("")
                with gr.Column(visible=False, elem_id="aviso_video") as col_aviso:
                    aviso_txt = gr.Markdown()
                    with gr.Row():
                        btn_mismos = gr.Button("Usar los mismos subtítulos", variant="primary", scale=0, min_width=230)
                        btn_transcribir = gr.Button("Transcribir de nuevo", scale=0, min_width=190)
                        btn_aviso_no = gr.Button("Cancelar", scale=0, min_width=110)
                with gr.Tabs(elem_id="secciones", selected="editor") as secciones:
                    # ---------- Editor ----------
                    with gr.Tab("Editor", id="editor"):
                        with gr.Column(elem_id="inicio", elem_classes=["seccion"]) as col_inicio:
                            gr.HTML('<div class="titulo-sec"><h1>Nuevo video</h1>'
                                    '<p>Elige el video, ponle título y la plataforma lo arma en vertical.</p></div>')
                            with gr.Row(equal_height=False):
                                with gr.Column(scale=3):
                                    with gr.Row(equal_height=True):
                                        ruta_video = gr.Dropdown(label="Video", choices=opciones_videos(), value=None,
                                                                 allow_custom_value=True, filterable=True, scale=5)
                                        btn_refrescar = gr.Button("↻", scale=0, min_width=48)
                                    titulo_nuevo = gr.Textbox(label="Título  ·  Shift+Enter = otro renglón (hasta 3)", lines=1, max_lines=3,
                                                              placeholder="En «Tiktoks Yair»: arriba – abajo (en «Solo subtítulos» no hace falta)")
                                    estilo_edicion = gr.Radio(list(ESTILOS), value="Clips Chapuceros", label="Estilo de edición",
                                                              elem_id="estilo")
                                    with gr.Row(elem_id="fila_procesar", equal_height=True):
                                        usar_gpu = gr.Checkbox(label="Solo tarjeta gráfica · no usa el procesador", value=GPU_INICIAL)
                                        btn_procesar = gr.Button("Analizar video  →", variant="primary", elem_id="btn_procesar",
                                                                 scale=0, min_width=200)
                                with gr.Column(scale=2):
                                    gr.HTML('<div class="etiqueta">Trabajos recientes</div>')
                                    recientes = gr.Radio(choices=opciones_recientes(), value=None, show_label=False,
                                                         elem_id="recientes")
                                    with gr.Accordion("Abrir otro trabajo", open=False, elem_id="otro_trabajo"):
                                        ruta_trabajo = gr.Dropdown(label="Carpeta _trabajo", choices=opciones_trabajos(), value=None,
                                                                   allow_custom_value=True, filterable=True)
                                        btn_cargar = gr.Button("Abrir", variant="secondary")
                        with gr.Column(visible=False, elem_id="area") as col_area:
                            with gr.Row(elem_id="cabeza_trabajo", equal_height=True):
                                btn_volver = gr.Button("←", elem_id="btn_volver", scale=0, min_width=40)
                                actual = gr.Markdown(elem_id="trabajo_actual")
                                btn_exportar = gr.Button("Exportar", variant="primary", elem_id="btn_exportar", scale=0, min_width=120)
                            with gr.Tabs(elem_id="pasos", selected="edicion") as pasos:
                                with gr.Tab("Edición", id="edicion"):
                                    editor_edi = gr.HTML(iframe_edi(None))
                                with gr.Tab("Subtítulos", id="subtitulos"):
                                    editor_subs = gr.HTML(iframe_subs(None))
                                with gr.Tab("Exportar", id="exportar"):
                                    with gr.Column(elem_classes=["seccion"]):
                                        gr.Markdown("Arma el video final (MP4 1080×1920) cuando termines de revisar **Edición** y "
                                                    "**Subtítulos**. Mientras revisas no hace falta: las vistas previas ya muestran "
                                                    f"cómo queda. Queda en la carpeta `{CARPETA_RENDERS}`.")
                                        btn_render = gr.Button("Exportar video final", variant="primary", scale=0)
                                        video = gr.Video(label="Video final", height=620, interactive=False)

                    # ---------- Video largo ----------
                    with gr.Tab("Video largo", id="largo"):
                        gr.HTML('<iframe src="/frag/editor" style="width:100%;height:1750px;border:0;'
                                'background:#0B0B0D"></iframe>')

                    # ---------- Lo aprendido ----------
                    with gr.Tab("Lo aprendido", id="aprendido"):
                        gr.HTML('<iframe src="/apr/editor" style="width:100%;height:1300px;border:0;'
                                'background:#0B0B0D"></iframe>')

                    # ---------- Registro ----------
                    with gr.Tab("Registro", id="registro"):
                        with gr.Column(elem_classes=["seccion"]):
                            gr.HTML('<div class="titulo-sec"><h1>Registro</h1><p>Lo que va haciendo la plataforma paso a paso '
                                    f'(se actualiza solo). También se guarda en {ARCHIVO_REGISTRO.name} dentro de la carpeta '
                                    'del editor.</p></div>')
                            caja_estado = gr.HTML(estado_equipo)
                            caja_registro = gr.Textbox(value=texto_registro, show_label=False, lines=28, max_lines=28,
                                                       interactive=False, autoscroll=True, elem_id="caja_registro")
                            with gr.Row():
                                btn_reg_act = gr.Button("Actualizar", scale=0, min_width=130)
                                btn_reg_limpiar = gr.Button("Limpiar", scale=0, min_width=130)

        # menú lateral: cambia de sección y marca el botón activo
        def ir_a(clave):
            return [gr.Tabs(selected=clave)] + [gr.Button(elem_classes=["nav"] + (["activo"] if k == clave else []))
                                                for k, _ in NAV]
        for (k, _), b in zip(NAV, botones_nav):
            b.click(lambda k=k: ir_a(k), None, [secciones] + botones_nav, queue=False)

        btn_reg_act.click(texto_registro, None, caja_registro)
        btn_reg_act.click(estado_equipo, None, caja_estado)
        btn_reg_limpiar.click(limpiar_registro, None, caja_registro)
        if hasattr(gr, "Timer"):
            reg_visto = gr.State(-1)
            gr.Timer(2.0).tick(tick_registro, reg_visto, [caja_registro, reg_visto], show_progress="hidden")
            gr.Timer(6.0).tick(estado_equipo, None, caja_estado, show_progress="hidden")

        # ======================== lógica ========================
        def refrescar_listas():
            return (gr.update(choices=opciones_videos()), gr.update(choices=opciones_trabajos()),
                    gr.update(choices=opciones_recientes(), value=None))

        btn_refrescar.click(refrescar_listas, None, [ruta_video, ruta_trabajo, recientes])

        def al_elegir_video(nombre):
            """Si el video ya tiene su carpeta _trabajo, se propone abrirla y se llena el título."""
            v = buscar_video(nombre) if nombre else None
            if not v:
                return gr.update(), gr.update()
            t = v.with_name(v.stem + "_trabajo")
            if (t / "plan.json").exists():
                plan, _ = cargar(str(t))
                return gr.update(choices=opciones_trabajos(), value=str(t)), plan.get("titulo", "")
            return gr.update(), gr.update()

        ruta_video.change(al_elegir_video, ruta_video, [ruta_trabajo, titulo_nuevo])

        def nombre_trabajo(t):
            plan, _ = cargar(t)
            final = video_salida(t)
            nombres = {Path(v).name: k for k, v in ESTILOS.items()}
            est = nombres.get(Path(str(plan.get("plantilla", ""))).name, "")
            return (f"**{plan.get('titulo') or Path(plan['video']).stem}**  \n"
                    f"<span style='color:#9A9AA3;font-size:12.5px'>{Path(plan['video']).name}"
                    f"{' · ' + est if est else ''}{' · exportado' if final else ''}</span>")

        def todo_ui(t):
            """Valores para refrescar la interfaz con el trabajo t."""
            soltar_otros(t)
            return (t, iframe_edi(t), iframe_subs(t), video_salida(t), nombre_trabajo(t),
                    gr.Column(visible=False), gr.Column(visible=True))

        salidas_ui = [trabajo, editor_edi, editor_subs, video, actual, col_inicio, col_area]
        sin_aviso = (gr.update(),) * 3   # col_aviso, aviso_txt, aviso_t
        salidas_aviso = [col_aviso, aviso_txt, aviso_t]

        def accion_cargar(ruta):
            t = limpiar_ruta(ruta)
            if not t or not (Path(t) / "plan.json").exists():
                gr.Warning("Esa carpeta no tiene plan.json")
                return ("", iframe_edi(None), iframe_subs(None), None, "", gr.update(), gr.update(), "", *sin_aviso)
            try:
                r = revisar_solo_subs(t, False)
            except Exception as e:
                registrar(f"⚠ No pude revisar si el video cambió: {e}")
                r = None
            if r and r != "mismo":   # cambió la duración: se abre y se pregunta qué hacer
                return (*todo_ui(t), "", gr.Column(visible=True), r, t)
            return (*todo_ui(t), "", gr.Column(visible=False), "", "")

        btn_cargar.click(accion_cargar, ruta_trabajo, salidas_ui + [progreso] + salidas_aviso)

        def abrir_reciente(ruta):
            if not ruta:
                return (*(gr.update(),) * (len(salidas_ui) + 4), gr.update())
            return (*accion_cargar(ruta), gr.update(value=None))

        recientes.input(abrir_reciente, recientes, salidas_ui + [progreso] + salidas_aviso + [recientes])

        def volver():
            return gr.Column(visible=True), gr.Column(visible=False), gr.update(choices=opciones_recientes(), value=None)

        btn_volver.click(volver, None, [col_inicio, col_area, recientes], queue=False)


        def texto_aviso(t, est_v):
            nombre = Path(cargar(t)[0]["video"]).name
            if est_v is None:
                return (f"**{nombre}** ya tiene sus subtítulos de «Solo subtítulos» (el video no ha cambiado). "
                        "Si lo analizas de nuevo se transcribe otra vez y **se pierden las correcciones**.")
            return (f"**El video {nombre} cambió y su duración es distinta**: antes {est_v['antes']:.2f} s, ahora "
                    f"{est_v['ahora']:.2f} s ({est_v['ahora'] - est_v['antes']:+.2f} s). ¿Usar los mismos subtítulos "
                    "(los que queden después del final se quitan) o transcribir de nuevo?")

        def revisar_solo_subs(t, al_analizar):
            """Para «Solo subtítulos»: None = seguir normal; "mismo" = se refrescó solo (dura lo mismo);
            o el texto del aviso para preguntar."""
            plan, _ = cargar(t)
            if estilo_de(plan) != "solo_subtitulos":
                return None
            est_v = ed.estilo_solo_subtitulos().estado_video(t)
            if est_v is None:
                return texto_aviso(t, None) if al_analizar else None
            if est_v["igual"]:
                ed.estilo_solo_subtitulos().refrescar_video(t)
                registrar(f"● El video de {Path(t).name} cambió y dura lo mismo: se usan los mismos subtítulos")
                gr.Info("El video cambió y dura lo mismo: se conservaron los subtítulos.")
                return "mismo"
            return texto_aviso(t, est_v)

        def accion_procesar(ruta, tit, gpu, est):
            nada = (gr.update(),) * len(salidas_ui)
            encontrado = buscar_video(ruta)
            if encontrado and est.startswith("Solo subtítulos"):
                t_ex = encontrado.with_name(encontrado.stem + "_trabajo")
                if (t_ex / "plan.json").exists() and ((t_ex / "subtitulos.json").exists() or (t_ex / "transcripcion.json").exists()):
                    r = revisar_solo_subs(str(t_ex), True)
                    if r == "mismo":
                        yield (*todo_ui(str(t_ex)), "", *sin_aviso)
                        return
                    if r:
                        yield (*nada, "", gr.Column(visible=True), r, str(t_ex))
                        return
            yield from ((*x, *sin_aviso) for x in analizar_video(encontrado, ruta, tit, gpu, est))

        def analizar_video(encontrado, ruta, tit, gpu, est, plantilla_ruta=None):
            nada = (gr.update(),) * len(salidas_ui)
            if not encontrado:
                gr.Warning(f"No encuentro «{limpiar_ruta(ruta)}» en {CARPETA_VIDEOS}")
                yield (*nada, barra(1.0, f"No encontré «{limpiar_ruta(ruta)}» en {CARPETA_VIDEOS}", "error"))
                return
            v = str(encontrado)
            if not (tit or "").strip() and not est.startswith("Solo subtítulos"):
                gr.Warning("Escribe un título")
                yield (*nada, "")
                return
            if encontrado.suffix.lower() != ".mp4":
                # primero convertir (solo cuando el video no es MP4)
                convertido = None
                for html, final in correr([sys.executable, str(BASE / "editor.py"), "convertir", v] + (["--solo-gpu"] if gpu else [])):
                    if final is not None and final.get("ok"):
                        convertido = final["video"]
                    elif final is not None:
                        yield (*nada, html)
                        return
                    else:
                        yield (*nada, html)
                v = convertido
            plantilla_est = plantilla_ruta or str(BASE / ESTILOS.get(est, ESTILOS["Clips Chapuceros"]))
            # solo análisis: la revisión se hace con las vistas previas en vivo; el video final se exporta al terminar
            cmd = [sys.executable, str(BASE / "editor.py"), "analizar", v, "--titulo", limpiar_titulo(tit),
                   "--plantilla", plantilla_est, "--vista-previa"] + (["--solo-gpu", "--dispositivo", "cuda"] if gpu else [])
            for html, final in correr(cmd):
                if final is not None and final.get("ok"):
                    gr.Info("Análisis listo. Revisa en Edición y Subtítulos; al terminar, Exportar.")
                    yield (*todo_ui(final["trabajo"]), html)
                else:
                    yield (*nada, html)

        ev_procesar = btn_procesar.click(accion_procesar, [ruta_video, titulo_nuevo, usar_gpu, estilo_edicion],
                                         salidas_ui + [progreso] + salidas_aviso)

        # respuestas del aviso de «Solo subtítulos»
        def usar_mismos(t):
            if not t:
                return (*(gr.update(),) * len(salidas_ui), "", gr.Column(visible=False), "", "")
            r = ed.estilo_solo_subtitulos().refrescar_video(t)
            registrar(f"● {Path(t).name}: se usan los mismos subtítulos con el video nuevo ({r['duracion']:.2f} s)")
            gr.Info("Listo: el video nuevo quedó con los mismos subtítulos." +
                    (f" {r['quitados']} subtítulo(s) quedaban después del final y se quitaron." if r["quitados"] else ""))
            return (*todo_ui(t), "", gr.Column(visible=False), "", "")

        def transcribir_otra_vez(t, gpu):
            if not t:
                yield (*(gr.update(),) * len(salidas_ui), "", gr.Column(visible=False), "", "")
                return
            plan, _ = cargar(t)
            v = Path(plan["video"])
            yield (*(gr.update(),) * len(salidas_ui), gr.update(), gr.Column(visible=False), "", "")
            yield from ((*x, *sin_aviso) for x in analizar_video(v, str(v), plan.get("titulo", ""), gpu,
                                                                  "Solo subtítulos (Chapucero)", str(ed.ruta(plan["plantilla"]))))

        btn_mismos.click(usar_mismos, aviso_t, salidas_ui + [progreso] + salidas_aviso)
        ev_transcribir = btn_transcribir.click(transcribir_otra_vez, [aviso_t, usar_gpu], salidas_ui + [progreso] + salidas_aviso)
        ev_transcribir.then(refrescar_listas, None, [ruta_video, ruta_trabajo, recientes])
        btn_aviso_no.click(lambda: (gr.Column(visible=False), "", ""), None, salidas_aviso, queue=False)
        ev_procesar.then(refrescar_listas, None, [ruta_video, ruta_trabajo, recientes])

        def accion_render(t, gpu):
            if not t:
                gr.Warning("Primero procesa o abre un video")
                yield gr.update(), "", gr.update()
                return
            destino = ruta_export(t)   # el video final queda en «Renders» del escritorio
            try:
                destino.parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
            cmd = [sys.executable, str(BASE / "editor.py"), "render", t, "--salida", str(destino)] + \
                (["--gpu", "--solo-gpu"] if gpu else [])
            for html, final in correr(cmd):
                if final is not None and final.get("ok"):
                    try:   # el video exportado de este trabajo (si cambia el título, el siguiente sale con el nombre nuevo)
                        viejo = exportado_de(t)
                        (Path(t) / "exportado.txt").write_text(str(destino), encoding="utf-8")
                        if viejo and viejo != str(destino) and Path(viejo).exists():
                            registrar(f"   (el export anterior sigue en {viejo})")
                    except Exception:
                        pass
                    try:   # lo que corregiste en este video queda como propuesta en «Lo aprendido»
                        r = aprendizaje.aprender_de(t, ed)
                        if r:
                            registrar(f"● Aprendí de este video: {r['subtitulos']} correcciones de subtítulos, "
                                      f"{r['pantalla']} de pantalla, {r['encuadre']} de encuadre, {r['imagenes']} búsquedas")
                    except Exception as e:
                        registrar(f"⚠ No pude aprender de este video: {e}")
                    yield video_salida(t), html, nombre_trabajo(t)
                elif final is not None and final.get("cancelado"):
                    a_medias = video_salida(t)
                    if a_medias:
                        Path(a_medias).unlink(missing_ok=True)   # quedó incompleto
                    (Path(t) / "vista_previa_tmp.mp4").unlink(missing_ok=True)
                    yield None, html, gr.update()
                else:
                    yield gr.update(), html, gr.update()

        ev_render = btn_render.click(accion_render, [trabajo, usar_gpu], [video, progreso, actual])
        # «Exportar» de arriba: lleva a la pestaña Exportar y arma el video final
        ev_exportar = btn_exportar.click(lambda: gr.Tabs(selected="exportar"), None, pasos, queue=False).then(
            accion_render, [trabajo, usar_gpu], [video, progreso, actual])

        def accion_cancelar():
            n, cola = cancelar_todo()
            if not n and not cola:
                return barra(1.0, "No había nada trabajando.", "listo")
            return barra(1.0, f"⛔ Cancelado: se detuvo lo que estaba trabajando ({n} proceso(s)"
                              + (f", {cola} en cola" if cola else "") + ").", "error")

        btn_cancelar.click(accion_cancelar, None, progreso, cancels=[ev_procesar, ev_render, ev_exportar, ev_transcribir], queue=False)
    return demo


def main():
    import uvicorn
    try:
        CARPETA_VIDEOS.mkdir(parents=True, exist_ok=True)
        CARPETA_RENDERS.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    demo = construir().queue()
    opciones = {"allowed_paths": unidades()}
    params = inspect.signature(gr.mount_gradio_app).parameters
    if not _TEMA_EN_BLOCKS:
        for k, v in (("theme", tema()), ("css", TEMA_CSS), ("js", TEMA_JS)):
            if k in params:
                opciones[k] = v
    app = gr.mount_gradio_app(crear_app(), demo, path="/", **opciones)
    puerto = int(os.environ.get("PUERTO", "7860"))
    url = f"http://127.0.0.1:{puerto}"
    print(f"Interfaz en {url}  (Ctrl+C para cerrar)")
    if os.environ.get("NO_NAVEGADOR") != "1":
        threading.Timer(2.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=puerto, log_level="warning")


if __name__ == "__main__":
    main()
