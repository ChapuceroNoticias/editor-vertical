#!/usr/bin/env python3
"""
Puente entre el editor vertical y OpenCut (ida y vuelta).

  1. En la pestaña «Edición», el botón «Abrir en OpenCut» manda la propuesta que armó la plataforma:
       - el video ya armado en vertical (encuadres, pantalla dividida, título, subtítulos) pero SIN las
         imágenes de los momentos, en la pista principal (se arma en <trabajo>\\_opencut, como un render),
       - las imágenes de los momentos en su propia pista, ya en su lugar (abajo si es dividida, todo el cuadro
         si es pantalla completa),
       - los tramos de pantalla (completa / dividida / solo Nacho / cerca / lejos) como textos en otra pista,
       - el TÍTULO (estilo motivacional) como texto.
  2. En OpenCut mueves, alargas, acortas o borras esos bloques. Para cambiar cómo se ve un tramo de pantalla,
     edita su texto (por ejemplo «DIVIDIDA» -> «PANTALLA COMPLETA»). Para quitar una imagen, bórrala u ocúltala.
     También puedes AGREGAR: una imagen nueva (se vuelve un momento con esa foto) o un texto nuevo que diga
     DIVIDIDA o PANTALLA COMPLETA (se vuelve un tramo de pantalla nuevo).
  3. «Enviar a editor vertical» (arriba en OpenCut) regresa los tiempos a plan.json. Se puede deshacer
     con «Deshacer» en la pestaña Edición, y el video final se sigue exportando con este programa
     (subtítulos, música, lectura, aprendizaje: todo igual).

Las rutas se agregan solas al servidor de interfaz.py (/oc/...). OpenCut debe estar corriendo
(por defecto en http://localhost:3000; para otra dirección: set OPENCUT_URL=http://...).
"""
import base64
import hashlib
import json
import os
import time
import unicodedata
from pathlib import Path

OPENCUT_URL = os.environ.get("OPENCUT_URL", "http://localhost:3000").rstrip("/")
CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Allow-Private-Network": "true"}

# Texto que se ve en OpenCut para cada forma de pantalla
ETIQUETAS = {"completa": "PANTALLA COMPLETA", "dividida": "DIVIDIDA", "nacho": "SOLO NACHO",
             "cerca": "NACHO CERCA", "lejos": "NACHO LEJOS"}

_ULTIMO_CAMBIO = {}   # carpeta _trabajo -> hora del último envío desde OpenCut


def _sin_acentos(txt):
    return "".join(c for c in unicodedata.normalize("NFD", str(txt)) if unicodedata.category(c) != "Mn").lower()


def leer_opcion(texto, opciones, actual):
    """Texto editado en OpenCut -> opción de pantalla. Si no se entiende, se queda como estaba."""
    t = _sin_acentos(texto)
    pruebas = [("cerca", "cerca"), ("lejos", "lejos"), ("complet", "completa"), ("divid", "dividida"),
               ("solo", "nacho"), ("nacho", "nacho")]
    for clave, op in pruebas:
        if clave in t and op in opciones:
            return op
    return actual


def firma(tramos):
    """Huella de los tramos: si el trabajo cambia mientras está abierto en OpenCut, no se mezcla."""
    base = [[x["k"], x["ini_s"], x["fin_s"], x["pantalla"]] for x in tramos.get("tramos", [])]
    return hashlib.md5(json.dumps(base).encode()).hexdigest()[:12]


# ----------------------------------------------------------------------------
# Video base vertical: el armado de la plataforma (encuadres, pantalla dividida, título, subtítulos, música)
# SIN las imágenes de los momentos; en OpenCut las imágenes van encima, en su lugar, para moverlas.
# Se arma en <trabajo>/_opencut con el mismo render del video final y se reusa mientras no cambie el plan.
# ----------------------------------------------------------------------------
_BASE_PROC = {}     # carpeta _trabajo -> proceso del render
_BASE_FALLO = {}    # carpeta _trabajo -> firma con la que falló (no se reintenta solo)


def _firma_base(I, t, plan, est):
    sin = {k: v for k, v in plan.items() if k not in ("momentos", "aprendido")}
    if est == "motivacional":
        sin.pop("titulo_fin", None)   # el título va encima en OpenCut (se puede estirar)
        sin.pop("titulo", None)
    extra = []
    for nombre in ("subtitulos.json", "transcripcion.json"):
        f = Path(t) / nombre
        extra.append(f.stat().st_mtime if f.exists() else 0)
    return hashlib.md5(json.dumps([sin, extra], sort_keys=True, default=str).encode()).hexdigest()[:12]


def base_vertical(I, t, plan, est):
    """{"listo": bool, "preparando": bool, "firma": str}. Si falta o ya no corresponde, se arma en segundo plano."""
    import shutil
    import subprocess
    import sys
    import threading
    carpeta = Path(t) / "_opencut"
    fb = _firma_base(I, t, plan, est)
    info = carpeta / "base.json"
    if info.exists() and (carpeta / "base.mp4").exists():
        try:
            if json.loads(info.read_text(encoding="utf-8")).get("firma") == fb:
                return {"listo": True, "preparando": False, "firma": fb}
        except ValueError:
            pass
    proc = _BASE_PROC.get(t)
    if proc is not None and proc.poll() is None:
        return {"listo": False, "preparando": True, "firma": fb}
    if _BASE_FALLO.get(t) == fb:
        return {"listo": False, "preparando": False, "firma": fb}

    carpeta.mkdir(exist_ok=True)
    sombra = dict(plan, momentos=[])
    if est == "motivacional":
        sombra["titulo"] = ""
    I.ed.guardar_json(carpeta / "plan.json", sombra)
    for nombre in ("subtitulos.json", "transcripcion.json"):
        origen, copia = Path(t) / nombre, carpeta / nombre
        if origen.exists():
            shutil.copy2(origen, copia)
        else:
            copia.unlink(missing_ok=True)
    tmp = carpeta / "base_tmp.mp4"
    cmd = [sys.executable, str(I.BASE / "editor.py"), "render", str(carpeta), "--salida", str(tmp)]
    try:
        if I.ed.nvenc_disponible():
            cmd.append("--gpu")
    except Exception:
        pass
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    registro = open(carpeta / "render.log", "w", encoding="utf-8")
    lanzar = getattr(I, "lanzar", subprocess.Popen)   # se puede detener con «Cancelar todo»
    proc = lanzar(cmd, cwd=str(I.BASE), env=env, stdout=registro, stderr=subprocess.STDOUT)
    _BASE_PROC[t] = proc

    def terminar():
        proc.wait()
        registro.close()
        if proc.returncode == 0 and tmp.exists():
            (carpeta / "base.mp4").unlink(missing_ok=True)
            tmp.rename(carpeta / "base.mp4")
            info.write_text(json.dumps({"firma": fb}), encoding="utf-8")
        elif not (hasattr(I, "fue_cancelado") and I.fue_cancelado(proc)):   # cancelado: se puede volver a intentar
            _BASE_FALLO[t] = fb

    threading.Thread(target=terminar, daemon=True).start()
    return {"listo": False, "preparando": True, "firma": fb}


def area_momento(pl, estilo, est):
    """Dónde va la imagen de un momento en el cuadro 1080x1920: [x, y, ancho, alto]."""
    W, H = pl["salida"]["ancho"], pl["salida"]["alto"]
    area = [0, 0, W, H]
    if estilo == "dividida" and est != "motivacional":
        area = (pl.get("layouts", {}).get("dividida", {}).get("inferior") or {}).get("area") or area
    k = 1080 / W
    return [round(v * k) for v in area]


def propuesta(I, t):
    """Todo lo que OpenCut necesita para armar el proyecto. Tiempos del video editado (sin pausas), en segundos."""
    plan, _ = I.cargar(t)
    est = I.estilo_de(plan)
    if est == "solo_subtitulos":
        return {"ok": False, "mensaje": "En «Solo subtítulos» no hay tramos que acomodar."}
    pl = I.plantilla(plan)
    base = base_vertical(I, t, plan, est)
    if base["listo"]:
        video = {"url": f"/oc/base?t={_q(t)}&v={base['firma']}", "nombre": Path(plan["video"]).stem + "_base",
                 "vertical": True}
    elif base["preparando"]:
        return {"ok": True, "listo": False, "preparando": True,
                "mensaje": "Armando la vista previa vertical para OpenCut (como un render, sin las imágenes)…"}
    else:   # el render falló: se usa la copia ligera 16:9 como antes
        px = I.estado_proxy(t, plan)
        if not px["proxy"]:
            return {"ok": True, "listo": False, "preparando": px["preparando"],
                    "mensaje": "Preparando la copia ligera del video…" if px["preparando"]
                    else "No se pudo preparar el video (revisa _opencut\\render.log en la carpeta de trabajo)."}
        video = {"url": f"/oc/proxy?t={_q(t)}&v={px['proxy']['firma']}", "nombre": Path(plan["video"]).stem,
                 "vertical": False}
    tr = I.tramos_pantalla(t)
    imagenes, pantalla = [], []
    for x in tr["tramos"]:
        k = x["k"]
        if k[0] == "m":
            i = int(k[1:])
            m = plan["momentos"][i]
            area = area_momento(pl, m.get("estilo") or "dividida", est)
            imagenes.append({"k": k, "inicio": x["ini_s"], "fin": x["fin_s"], "oculto": x["pantalla"] == "quitar",
                             "nombre": (m.get("busqueda") or f"Imagen {i + 1}")[:50], "area": area,
                             "url": f"/oc/img?t={_q(t)}&i={i}&w={area[2]}&h={area[3]}"})
        elif x["opciones"]:   # los tramos sin opciones (Nacho sin pantalla) no se mandan
            pantalla.append({"k": k, "inicio": x["ini_s"], "fin": x["fin_s"], "op": x["pantalla"],
                             "texto": ETIQUETAS.get(x["pantalla"], x["pantalla"].upper()),
                             "tipo": x["tipo"]})
    titulo = None
    if est == "motivacional" and plan.get("titulo") and plan.get("titulo_fin") is not None:
        titulo = {"k": "ti", "inicio": 0.0, "fin": round(I.ed_t(plan["titulo_fin"], plan), 3),
                  "texto": plan["titulo"]}
    return {"ok": True, "listo": True, "t": t, "firma": firma(tr), "estilo": est,
            "nombre": f"{Path(plan['video']).stem} · editor vertical",
            "duracion": tr["duracion"], "video": video,
            "imagenes": imagenes, "pantalla": pantalla, "titulo": titulo}


def aplicar(I, t, d):
    """Lo que regresa OpenCut -> plan.json (con respaldo para «Deshacer»)."""
    plan, _ = I.cargar(t)
    tr = I.tramos_pantalla(t)
    if d.get("firma") != firma(tr):
        raise ValueError("El trabajo cambió desde que lo abriste en OpenCut. Vuelve a darle «Abrir en OpenCut».")
    est = tr.get("estilo")
    dur_ed = float(tr.get("duracion") or plan["info"]["duracion"])
    elementos = {}
    repetidos = set()
    for e in d.get("elementos", []):
        k = str(e.get("k", ""))
        ini, fin = float(e["inicio"]), float(e["fin"])
        if k in elementos:   # se partió un bloque en OpenCut: se queda el pedazo más largo
            repetidos.add(k)
            if fin - ini <= elementos[k]["fin"] - elementos[k]["inicio"]:
                continue
        elementos[k] = {"inicio": max(0.0, ini), "fin": fin, "texto": e.get("texto"), "oculto": bool(e.get("oculto"))}

    cambios, movidos, quitados = [], 0, 0
    for x in tr["tramos"]:
        k, e = x["k"], elementos.get(x["k"])
        if k[0] == "n" or not x["opciones"]:
            continue
        if k[0] == "m":
            if e is None or e["oculto"]:
                if x["pantalla"] != "quitar":
                    quitados += 1
                cambios.append({"k": k, "pantalla": "quitar", **({"inicio": e["inicio"], "fin": e["fin"]} if e else {})})
                continue
            if x["pantalla"] != "quitar":
                op = x["pantalla"]
            else:   # estaba quitada y la volviste a mostrar
                op = "imagen" if est == "motivacional" else (plan["momentos"][int(k[1:])].get("estilo") or "dividida")
        else:
            if e is None:   # borraste el bloque de pantalla
                op = "nacho" if "nacho" in x["opciones"] else x["pantalla"]
                if op != x["pantalla"]:
                    movidos += 1
                    cambios.append({"k": k, "pantalla": op})
                continue
            op = leer_opcion(e["texto"] or "", x["opciones"], x["pantalla"])
        if abs(e["inicio"] - x["ini_s"]) > 0.005 or abs(e["fin"] - x["fin_s"]) > 0.005 or op != x["pantalla"]:
            movidos += 1
            cambios.append({"k": k, "pantalla": op, "inicio": round(e["inicio"], 3), "fin": round(e["fin"], 3)})
        else:
            cambios.append({"k": k, "pantalla": op})   # sin cambio: aplicar_pantalla lo deja igual

    # textos nuevos que agregaste en OpenCut con DIVIDIDA / PANTALLA COMPLETA -> tramo nuevo de pantalla
    tramos_nuevos = 0
    if est != "motivacional":
        for n in d.get("tramos_nuevos", []):
            ini, fin = max(0.0, float(n["inicio"])), min(dur_ed, float(n["fin"]))
            op = leer_opcion(n.get("texto") or "", ["completa", "dividida"], None)
            if op is None or fin - ini < 0.3:
                continue
            a0, b0 = I.orig_t(ini, plan), I.orig_t(fin, plan)
            cambios.append({"k": f"g{a0:.3f}_{b0:.3f}", "pantalla": op, "inicio": round(ini, 3), "fin": round(fin, 3)})
            tramos_nuevos += 1

    # imágenes nuevas que agregaste en OpenCut -> momentos nuevos con esa foto
    nuevas = []
    for k, n in enumerate(d.get("nuevas", []), 1):
        ini, fin = max(0.0, float(n["inicio"])), min(dur_ed, float(n["fin"]))
        if fin - ini < 0.3 or not n.get("datos"):
            continue
        nuevas.append((ini, fin, n))

    ti = elementos.get("ti")
    cambio_titulo = False
    if ti and est == "motivacional" and plan.get("titulo_fin") is not None:
        nuevo = round(I.orig_t(ti["fin"], plan), 4)
        cambio_titulo = abs(nuevo - float(plan["titulo_fin"])) > 0.01
    if not (movidos or quitados or tramos_nuevos or nuevas or cambio_titulo):
        return {"ok": True, "mensaje": "No hubo cambios.", "cambios": 0}

    I.aplicar_pantalla(t, cambios)   # guarda respaldo y plan.json (los momentos se cambian por número: va primero)
    if cambio_titulo or nuevas:
        plan, _ = I.cargar(t)
        if cambio_titulo:
            plan["titulo_fin"] = max(0.3, min(round(I.orig_t(ti["fin"], plan), 4), plan["info"]["duracion"]))
        if nuevas:
            destino = Path(t) / "imagenes"
            destino.mkdir(exist_ok=True)
            moms = plan.setdefault("momentos", [])
            for k, (ini, fin, n) in enumerate(nuevas, 1):
                ext = Path(str(n.get("nombre") or "")).suffix.lower()
                if ext not in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
                    ext = ".jpg"
                archivo = destino / f"opencut_{time.strftime('%H%M%S')}_{k}{ext}"
                archivo.write_bytes(base64.b64decode(n["datos"]))
                nombre = Path(str(n.get("nombre") or "imagen")).stem[:40]
                moms.append({"inicio": round(I.orig_t(ini, plan), 3), "fin": round(I.orig_t(fin, plan), 3),
                             "estilo": "completa" if est == "motivacional" else "dividida",
                             "busqueda": nombre, "busquedas": [], "que_mostrar": nombre, "texto": "",
                             "imagenes": [str(archivo)],
                             "prioridad": "imagen"})   # puesta a mano: se ve aunque Nacho tenga algo en pantalla
            moms.sort(key=lambda x: x["inicio"])
        I.guardar_plan(t, plan)
    _ULTIMO_CAMBIO[str(t)] = time.time()
    partes = []
    if movidos:
        partes.append(f"{movidos} bloque(s) cambiados")
    if quitados:
        partes.append(f"{quitados} imagen(es) quitadas")
    if nuevas:
        partes.append(f"{len(nuevas)} imagen(es) nuevas")
    if tramos_nuevos:
        partes.append(f"{tramos_nuevos} tramo(s) de pantalla nuevos")
    if cambio_titulo:
        partes.append("fin del título")
    msg = "Guardado en el editor vertical: " + (", ".join(partes) or "cambios") + "."
    if repetidos:
        msg += f" Partiste {len(repetidos)} bloque(s): se usó el pedazo más largo."
    return {"ok": True, "mensaje": msg, "cambios": movidos + quitados + len(nuevas) + tramos_nuevos + int(cambio_titulo)}


def _q(t):
    from urllib.parse import quote
    return quote(str(t), safe="")


def registrar(app, I):
    """Agrega las rutas /oc/... al servidor de interfaz.py. I = el módulo interfaz."""
    import cv2
    from fastapi import HTTPException, Request
    from fastapi.responses import FileResponse, JSONResponse, Response

    def validar(t):
        t = I.limpiar_ruta(t)
        if not t or not (Path(t) / "plan.json").exists():
            raise HTTPException(404, "Carpeta de trabajo no válida")
        return t

    def js(data, status=200):
        return JSONResponse(data, status_code=status, headers=CORS)

    @app.options("/oc/{resto:path}")
    def oc_preflight(resto: str):
        return Response(status_code=204, headers=CORS)

    @app.get("/oc/config")
    def oc_config():
        return js({"opencut": OPENCUT_URL})

    @app.get("/oc/propuesta")
    def oc_propuesta(t: str):
        try:
            return js(propuesta(I, validar(t)))
        except HTTPException as e:
            return js({"ok": False, "mensaje": e.detail}, e.status_code)
        except Exception as e:
            return js({"ok": False, "mensaje": f"No pude armar la propuesta: {e}"}, 500)

    @app.get("/oc/proxy")
    def oc_proxy(t: str):
        p = Path(validar(t)) / "proxy.mp4"
        if not p.exists():
            raise HTTPException(404, "Aún no está lista")
        return FileResponse(p, media_type="video/mp4", headers=CORS)

    @app.get("/oc/base")
    def oc_base(t: str):
        p = Path(validar(t)) / "_opencut" / "base.mp4"
        if not p.exists():
            raise HTTPException(404, "Aún no está lista")
        return FileResponse(p, media_type="video/mp4", headers=CORS)

    @app.get("/oc/img")
    def oc_img(t: str, i: int, w: int = 0, h: int = 0):
        """Primera imagen del momento; con w y h, ya recortada (cubriendo) al tamaño de su lugar en el cuadro."""
        plan, _ = I.cargar(validar(t))
        try:
            img = I.ed.leer_img(plan["momentos"][i]["imagenes"][0])
        except (IndexError, KeyError):
            img = None
        if img is None:
            raise HTTPException(404, "No pude leer la imagen")
        if w > 0 and h > 0:
            img = I.ed.ajustar(img, w, h, "cubrir", 0.5)
        else:
            img = I.imagen_vista(plan["momentos"][i]["imagenes"][0], 1600)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
        return Response(buf.tobytes(), media_type="image/jpeg", headers=CORS)

    @app.post("/oc/enviar")
    async def oc_enviar(request: Request):
        # llega como text/plain para que el navegador no pida permiso aparte (preflight)
        try:
            d = json.loads((await request.body()).decode("utf-8"))
            t = validar(d.get("t"))
            return js(aplicar(I, t, d))
        except HTTPException as e:
            return js({"ok": False, "mensaje": e.detail}, e.status_code)
        except (KeyError, TypeError, ValueError) as e:
            return js({"ok": False, "mensaje": str(e)}, 400)
        except Exception as e:
            return js({"ok": False, "mensaje": f"No pude guardar: {e}"}, 500)

    @app.get("/oc/estado")
    def oc_estado(t: str):
        return js({"cambio": _ULTIMO_CAMBIO.get(str(validar(t)), 0)})
