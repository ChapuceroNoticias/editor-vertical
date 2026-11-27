"""
Revisión en Drive (fase 1): el editor manda su trabajo a una carpeta compartida de Google Drive para escritorio.

Carpeta compartida (la elige cada PC en la sección «Revisión»):
    <carpeta>/Trabajos/<título>__<editor>/      el trabajo completo, listo para abrirse en cualquier PC
        plan.json, transcripcion.json, subtitulos.json, imagenes/, vista_previa.mp4 ...
        base/<video>                             el video base (para el render final en calidad completa)
        recursos/                                imágenes que estaban fuera de la carpeta _trabajo
        revision.json                            estado, editor, fechas e historial
    <carpeta>/Listos para subir/                 los videos finales (fase 3)

Las rutas dentro del plan se guardan con la ruta de la PC que lo escribió («raiz» en revision.json);
al abrirlo en otra PC, localizar() las cambia a la ruta de esa PC (Drive puede estar en G:, H:, etc.).
"""
import json
import os
import shutil
import socket
import threading
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATOS = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "EditorVertical"
CONF = DATOS / "revision.json"
SUB_TRABAJOS = "Trabajos"
SUB_LISTOS = "Listos para subir"

# lo que no viaja a Drive: copias locales que se rehacen solas, temporales e historial de deshacer
EXCLUIR = {"proxy.mp4", "proxy.json", "render_edicion.log", "exportado.txt", "revision_envio.json", "miniatura.jpg",
           ".historial", ".rehacer", "_tramos", "revision.json"}

ESTADOS = {"por_revisar": "Por revisar", "en_revision": "En revisión", "regresado": "Regresado al editor",
           "renderizado": "Renderizado", "aprobado": "Listo para subir"}

_ENVIOS = {}          # carpeta _trabajo -> {"estado", "progreso", "etapa", "mensaje"}
_LOCK = threading.Lock()


# ----------------------------------------------------------------------------
# Configuración de esta PC
# ----------------------------------------------------------------------------
def config():
    try:
        c = json.loads(CONF.read_text(encoding="utf-8"))
    except Exception:
        c = {}
    return {"carpeta": c.get("carpeta", ""), "nombre": c.get("nombre", ""), "salida": c.get("salida", ""),
            "destinos": c.get("destinos", "")}


def carpeta_destinos():
    """Carpeta de Drive con las carpetas de cada programa (ej. «Mi unidad\\Clips Chapucero»)."""
    d = config()["destinos"]
    return Path(d) if d and Path(d).is_dir() else None


def lista_destinos():
    """Las subcarpetas de la carpeta de destinos (El Chapucero, Ganso Informativo, Videos Gaby...)."""
    d = carpeta_destinos()
    if not d:
        return []
    try:
        return sorted((x.name for x in d.iterdir() if x.is_dir() and not x.name.startswith(".")), key=str.lower)
    except OSError:
        return []


def ruta_destino(nombre):
    """Carpeta elegida en el desplegable (solo una de las subcarpetas de destinos)."""
    d = carpeta_destinos()
    if not d or not nombre or nombre not in lista_destinos():
        return None
    return d / nombre


def copiar_a_destino(archivo, carpeta, nombre=None):
    """Copia el video terminado a la carpeta de Drive (sin pisar otro con el mismo nombre). -> ruta final"""
    archivo, carpeta = Path(archivo), Path(carpeta)
    base = Path(nombre or archivo.name)
    destino, n = carpeta / base.name, 2
    while destino.exists():
        destino, n = carpeta / f"{base.stem} ({n}){base.suffix}", n + 1
    tmp = destino.with_name(destino.name + ".copiando")
    shutil.copyfile(archivo, tmp)
    os.replace(tmp, destino)
    return destino


def carpeta_salida():
    """Dónde deja el Revisor los videos finales (por defecto «Listos para subir» de la carpeta compartida)."""
    c = config()
    if c["salida"]:
        return Path(c["salida"])
    raiz = carpeta_lista()
    return raiz / SUB_LISTOS if raiz else None


def guardar_config(carpeta, nombre, salida=None, destinos=None):
    carpeta = (carpeta or "").strip().strip('"').strip()
    nombre = (nombre or "").strip()
    if not carpeta:
        return False, "Escribe la carpeta compartida de Drive."
    if not nombre:
        return False, "Escribe tu nombre (así se sabe quién mandó o revisa cada trabajo)."
    p = Path(carpeta)
    if not p.exists():
        return False, (f"No encuentro la carpeta «{carpeta}». Revisa que Google Drive para escritorio esté abierto "
                       "y que la carpeta compartida esté en «Mi unidad» o en la unidad compartida.")
    try:
        (p / SUB_TRABAJOS).mkdir(exist_ok=True)
        (p / SUB_LISTOS).mkdir(exist_ok=True)
    except OSError as e:
        return False, f"No pude crear las subcarpetas en Drive: {e}"
    DATOS.mkdir(parents=True, exist_ok=True)
    datos = {"carpeta": str(p), "nombre": nombre, "salida": config()["salida"], "destinos": config()["destinos"]}
    if destinos is not None:
        destinos = (destinos or "").strip().strip('"').strip()
        if destinos and not Path(destinos).is_dir():
            return False, f"No encuentro la carpeta de destinos «{destinos}»."
        datos["destinos"] = destinos
    if salida is not None:
        salida = (salida or "").strip().strip('"').strip()
        if salida and not Path(salida).exists():
            return False, f"No encuentro la carpeta de videos finales «{salida}»."
        datos["salida"] = salida
    CONF.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    return True, f"Listo: esta PC usa «{p}» como carpeta de revisión."


def carpeta_lista():
    c = config()
    p = Path(c["carpeta"]) if c["carpeta"] else None
    return p if p and p.exists() else None


# ----------------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------------
def _leer(p, defecto=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return defecto


def _escribir(p, datos):
    p = Path(p)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def _limpio(txt, n=60):
    malos = '<>:"/\\|?*\n\r\t'
    s = "".join("_" if ch in malos else ch for ch in (txt or "")).strip(" .")
    return " ".join(s.split())[:n].strip(" .") or "trabajo"


def _variantes(ruta):
    """La misma ruta escrita con / y con \\ (en los JSON de Windows aparecen las dos)."""
    s = str(ruta)
    return {s, s.replace("\\", "/"), s.replace("/", "\\")}


def _reemplazar(obj, mapa):
    """Cambia los prefijos de ruta (más largos primero) en todos los textos del JSON."""
    if isinstance(obj, dict):
        return {k: _reemplazar(v, mapa) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_reemplazar(v, mapa) for v in obj]
    if isinstance(obj, str) and len(obj) > 2:
        for viejo, nuevo in mapa:
            if obj == viejo or obj.startswith(viejo + "/") or obj.startswith(viejo + "\\"):
                resto = obj[len(viejo):].replace("\\", os.sep).replace("/", os.sep)
                return nuevo + resto
        return obj
    return obj


def _rutas_externas(obj, dentro, salida):
    """Archivos que el plan usa y que NO están dentro de la carpeta _trabajo (imágenes subidas de otro lado...)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("video", "plantilla", "video_original"):
                continue
            _rutas_externas(v, dentro, salida)
    elif isinstance(obj, list):
        for v in obj:
            _rutas_externas(v, dentro, salida)
    elif isinstance(obj, str) and len(obj) > 3 and (obj[1:3] in (":\\", ":/") or obj.startswith("/")):
        try:
            p = Path(obj)
            if p.is_file() and not str(p.resolve()).startswith(str(Path(dentro).resolve())):
                salida.add(str(p))
        except OSError:
            pass


def _copiar(src, dst, aviso=None):
    """Copia por bloques (con avance). Si ya está igual (mismo tamaño y fecha) no la vuelve a copiar."""
    src, dst = Path(src), Path(dst)
    st = src.stat()
    if dst.exists():
        d = dst.stat()
        if d.st_size == st.st_size and abs(d.st_mtime - st.st_mtime) < 2:
            if aviso:
                aviso(1.0)
            return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".copiando")
    hecho, total = 0, max(1, st.st_size)
    with open(src, "rb") as a, open(tmp, "wb") as b:
        while True:
            bloque = a.read(8 * 1024 * 1024)
            if not bloque:
                break
            b.write(bloque)
            hecho += len(bloque)
            if aviso:
                aviso(hecho / total)
    shutil.copystat(src, tmp)
    os.replace(tmp, dst)
    return True


def miniatura(carpeta, forzar=False):
    """Imagen chica del trabajo (para la cuadrícula del Revisor): un cuadro de la vista previa a un tercio del video."""
    carpeta = Path(carpeta)
    destino = carpeta / "miniatura.jpg"
    if destino.exists() and not forzar:
        return destino
    fuente = next((carpeta / n for n in ("vista_previa.mp4", "vista_navegador.mp4") if (carpeta / n).exists()), None)
    if fuente is None:
        try:
            plan = _leer(carpeta / "plan.json", {}) or {}
            v = Path(plan.get("video", ""))
            fuente = v if v.exists() else None
        except Exception:
            fuente = None
    if fuente is None:
        return None
    import subprocess
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(fuente)],
                           capture_output=True, text=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        dur = float(r.stdout.strip() or 0)
    except Exception:
        dur = 0
    tmp = carpeta / "miniatura_tmp.jpg"
    try:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{max(0.0, dur * 0.33):.2f}", "-i", str(fuente),
                        "-frames:v", "1", "-vf", "scale=360:-2", "-q:v", "4", str(tmp)],
                       capture_output=True, timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if tmp.exists():
            os.replace(tmp, destino)
            return destino
    except Exception:
        pass
    return None


def _al_dia(t):
    vp = Path(t) / "vista_previa.mp4"
    return vp.exists() and (Path(t) / "plan.json").stat().st_mtime <= vp.stat().st_mtime + 1


def _refrescar_previa(carpeta, estaba_al_dia):
    """Reescribir plan.json no debe dejar la vista previa como «desactualizada»."""
    vp = Path(carpeta) / "vista_previa.mp4"
    if estaba_al_dia and vp.exists():
        try:
            ahora = time.time() + 2
            os.utime(vp, (ahora, ahora))
        except OSError:
            pass


# ----------------------------------------------------------------------------
# Paquetes en Drive
# ----------------------------------------------------------------------------
def paquete_de(t):
    """Carpeta en Drive a la que ya se mandó este trabajo (o None)."""
    raiz = carpeta_lista()
    info = _leer(Path(t) / "revision_envio.json", {}) or {}
    if raiz and info.get("paquete"):
        p = raiz / SUB_TRABAJOS / info["paquete"]
        if (p / "revision.json").exists():
            return p
    return None


def estado_de(t):
    """Para el encabezado del trabajo: si ya se mandó y en qué va."""
    p = paquete_de(t)
    if not p:
        return None
    r = _leer(p / "revision.json", {}) or {}
    return {"estado": r.get("estado"), "texto": ESTADOS.get(r.get("estado"), r.get("estado") or ""),
            "revisa": r.get("revisa") if r.get("estado") == "en_revision" else None,
            "nota": r.get("nota", "") if r.get("estado") == "regresado" else "", "paquete": p.name}


def _nuevo_nombre(raiz, plan, nombre):
    base = f"{_limpio(plan.get('titulo') or Path(plan['video']).stem)}__{_limpio(nombre, 30)}"
    p, n = raiz / SUB_TRABAJOS / base, 2
    while p.exists():
        p, n = raiz / SUB_TRABAJOS / f"{base} ({n})", n + 1
    return p


def enviar(t, cargar_plan, armar_previa=None):
    """Arranca en segundo plano el envío del trabajo a Drive. cargar_plan(t) -> plan;
    armar_previa(t) -> (ok, detalle): arma la vista previa ligera si falta o quedó vieja (la usa el revisor)."""
    with _LOCK:
        actual = _ENVIOS.get(t)
        if actual and actual.get("estado") == "trabajando":
            return {"ok": True, "mensaje": "Ya se está mandando a revisión."}
        raiz = carpeta_lista()
        if not raiz:
            return {"ok": False, "mensaje": "Primero elige la carpeta compartida de Drive en la sección «Revisión»."}
        c = config()
        p = paquete_de(t)
        if p:
            r = _leer(p / "revision.json", {}) or {}
            if r.get("estado") == "en_revision":
                return {"ok": False, "mensaje": f"No se puede mandar de nuevo: lo está revisando "
                                                f"{r.get('revisa') or 'otra persona'}."}
        _ENVIOS[t] = {"estado": "trabajando", "progreso": 0.0, "etapa": "Preparando"}
    threading.Thread(target=_enviar, args=(t, raiz, c["nombre"], cargar_plan, armar_previa), daemon=True).start()
    return {"ok": True, "mensaje": "Mandando a revisión…"}


def estado_envio(t):
    return _ENVIOS.get(t) or {"estado": "nada"}


def _enviar(t, raiz, nombre, cargar_plan, armar_previa):
    st = _ENVIOS[t]
    try:
        t = Path(t)
        plan = cargar_plan(str(t))
        solo = "solo_subtitulos" in Path(str(plan.get("plantilla", ""))).name
        # 1) vista previa ligera al día (con ella revisa el encargado sin bajar el video pesado)
        if not solo and not _al_dia(t) and armar_previa:
            st.update(etapa="Armando la vista previa", progreso=0.02)
            ok, detalle = armar_previa(str(t))
            if not ok:
                raise RuntimeError(f"no se pudo armar la vista previa: {detalle}")
            plan = cargar_plan(str(t))
        al_dia = _al_dia(t)
        # 2) carpeta destino (si el revisor ya corrigió subtítulos o título, primero se traen esos cambios)
        if traer_cambios(t, cargar_plan):
            plan = cargar_plan(str(t))
        destino = paquete_de(t) or _nuevo_nombre(raiz, plan, nombre)
        destino.mkdir(parents=True, exist_ok=True)
        video = Path(plan["video"])
        if not video.exists():
            raise RuntimeError(f"no encuentro el video base «{video}»")
        externos = set()
        _rutas_externas(plan, t, externos)
        # 3) archivos del trabajo
        archivos = [f for f in t.rglob("*") if f.is_file() and not any(x in EXCLUIR for x in f.relative_to(t).parts)
                    and not f.name.endswith(("_tmp.mp4", ".tmp", ".copiando"))]
        total = sum(f.stat().st_size for f in archivos) + video.stat().st_size + \
            sum(Path(e).stat().st_size for e in externos) or 1
        hecho = [0]

        def copiar(src, dst, etapa):
            tam = Path(src).stat().st_size
            base = hecho[0]
            st["etapa"] = etapa

            def aviso(f):
                st["progreso"] = round(0.05 + 0.9 * (base + f * tam) / total, 3)
            _copiar(src, dst, aviso)
            hecho[0] += tam

        for f in archivos:
            copiar(f, destino / f.relative_to(t), "Copiando el trabajo")
        dest_video = destino / "base" / video.name
        copiar(video, dest_video, "Copiando el video base (puede tardar)")
        mapa_ext = []
        usados = set()
        for e in sorted(externos):
            nom, n = Path(e).name, 2
            while nom.lower() in usados:   # dos imágenes con el mismo nombre en carpetas distintas
                nom, n = f"{Path(e).stem} ({n}){Path(e).suffix}", n + 1
            usados.add(nom.lower())
            d = destino / "recursos" / nom
            copiar(e, d, "Copiando imágenes")
            mapa_ext.append((e, str(d)))
        # 4) rutas del plan -> las de la carpeta de Drive en esta PC
        st.update(etapa="Ajustando rutas", progreso=0.96)
        mapa = [(v, str(dest_video)) for v in _variantes(video)]
        for e, d in mapa_ext:
            mapa += [(v, d) for v in _variantes(e)]
        mapa += [(v, str(destino)) for v in _variantes(t)]
        mapa.sort(key=lambda x: -len(x[0]))
        for j in [destino / "plan.json", destino / "plan_auto.json"]:
            datos = _leer(j)
            if datos is None:
                continue
            datos = _reemplazar(datos, mapa)
            if datos.get("plantilla"):
                datos["plantilla"] = str(BASE / "plantillas" / Path(str(datos["plantilla"]).replace("\\", "/")).name)
            if datos.get("video_original") and not Path(datos["video_original"]).exists():
                datos.pop("video_original", None)
            _escribir(j, datos)
        _refrescar_previa(destino, al_dia)
        st.update(etapa="Miniatura", progreso=0.98)
        miniatura(destino, forzar=True)
        # 5) estado de revisión
        r = _leer(destino / "revision.json", {}) or {}
        ahora = time.strftime("%Y-%m-%d %H:%M")
        hist = r.get("historial", [])
        hist.append({"fecha": ahora, "quien": nombre, "accion": "reenviado" if r else "enviado"})
        r.update({"estado": "por_revisar", "editor": nombre, "pc": socket.gethostname(), "enviado": ahora,
                  "titulo": plan.get("titulo", ""), "estilo": Path(str(plan.get("plantilla", ""))).stem,
                  "video": video.name, "raiz": str(destino), "historial": hist[-50:]})
        r.pop("revisa", None)
        _escribir(destino / "revision.json", r)
        _escribir(t / "revision_envio.json", {"paquete": destino.name, "enviado": ahora, "marca": _marca(destino)})
        st.update(estado="listo", progreso=1.0, etapa="Listo",
                  mensaje=f"Mandado a revisión: «{destino.name}». Google Drive lo sube solo en segundo plano.")
    except Exception as e:
        st.update(estado="error", mensaje=f"No se pudo mandar a revisión: {e}")


CAMPOS_TITULO = ("titulo", "titulo_tam", "titulo_inter", "titulo_en_video")


def _marca(paquete):
    """Última vez que cambiaron los subtítulos o el plan en Drive."""
    m = 0.0
    for n in ("plan.json", "subtitulos.json"):
        f = Path(paquete) / n
        if f.exists():
            m = max(m, f.stat().st_mtime)
    return m


def traer_cambios(t, cargar_plan, respaldar=None):
    """Si en Drive el revisor corrigió subtítulos o título después del envío, se traen a la carpeta _trabajo
    del editor (así, si se lo regresan, sigue desde lo corregido y al reenviar no se pierde). -> True si trajo algo."""
    p = paquete_de(t)
    if not p:
        return False
    info = _leer(Path(t) / "revision_envio.json", {}) or {}
    marca = _marca(p)
    if marca <= float(info.get("marca") or 0) + 1:
        return False
    if respaldar:
        respaldar(str(t))
    sub = p / "subtitulos.json"
    if sub.exists():
        shutil.copy2(sub, Path(t) / "subtitulos.json")
    remoto = _leer(p / "plan.json") or {}
    plan = cargar_plan(str(t))
    for k in CAMPOS_TITULO:
        if k in remoto:
            plan[k] = remoto[k]
        else:
            plan.pop(k, None)
    _escribir(Path(t) / "plan.json", plan)
    info["marca"] = marca
    _escribir(Path(t) / "revision_envio.json", info)
    return True


# ----------------------------------------------------------------------------
# Revisor: candado, regresar, render final
# ----------------------------------------------------------------------------
LATIDO_VENCE = 10 * 60   # si la PC que lo revisa no da señales en 10 min, el candado ya no cuenta


def _yo():
    return config()["nombre"] or socket.gethostname(), socket.gethostname()


def candado_ajeno(r):
    """Quién lo tiene abierto (si es otra PC y sigue viva), o None."""
    if r.get("estado") != "en_revision":
        return None
    _, pc = _yo()
    if r.get("revisa_pc") == pc:
        return None
    if time.time() - float(r.get("latido") or 0) > LATIDO_VENCE:
        return None
    return r.get("revisa") or "otra persona"


def _historial(r, accion, nota=""):
    nombre, _ = _yo()
    h = r.get("historial", [])
    h.append({"fecha": time.strftime("%Y-%m-%d %H:%M"), "quien": nombre, "accion": accion, **({"nota": nota} if nota else {})})
    r["historial"] = h[-50:]


def abrir(carpeta, forzar=False):
    carpeta = Path(carpeta)
    r = _leer(carpeta / "revision.json")
    if r is None or not (carpeta / "plan.json").exists():
        return {"ok": False, "mensaje": "Ese trabajo ya no está en la carpeta compartida (o Drive aún no lo baja)."}
    ajeno = candado_ajeno(r)
    if ajeno and not forzar:
        return {"ok": False, "ocupado": ajeno, "mensaje": f"Lo está revisando {ajeno}."}
    localizar(carpeta)
    r = _leer(carpeta / "revision.json", {}) or {}
    nombre, pc = _yo()
    if r.get("estado") in ("por_revisar", "en_revision", None) or forzar:
        if r.get("estado") != "en_revision" or r.get("revisa_pc") != pc:
            _historial(r, "abrió")
        r.update(estado="en_revision", revisa=nombre, revisa_pc=pc, latido=time.time())
        _escribir(carpeta / "revision.json", r)
    return {"ok": True, "t": str(carpeta), "revision": r}


def latido(carpeta):
    carpeta = Path(carpeta)
    r = _leer(carpeta / "revision.json", {}) or {}
    _, pc = _yo()
    if r.get("estado") == "en_revision" and r.get("revisa_pc") == pc:
        r["latido"] = time.time()
        _escribir(carpeta / "revision.json", r)
        return True
    return False


def soltar(carpeta):
    """Al cerrar el trabajo en el Revisor sin render ni regreso: vuelve a «Por revisar»."""
    carpeta = Path(carpeta)
    r = _leer(carpeta / "revision.json", {}) or {}
    _, pc = _yo()
    if r.get("estado") == "en_revision" and r.get("revisa_pc") == pc:
        r["estado"] = "por_revisar"
        for k in ("revisa", "revisa_pc", "latido"):
            r.pop(k, None)
        _escribir(carpeta / "revision.json", r)
    return True


def regresar(carpeta, nota, aprobado=False):
    carpeta = Path(carpeta)
    r = _leer(carpeta / "revision.json", {}) or {}
    r["estado"] = "aprobado" if aprobado else "regresado"
    r["decision_id"] = str(time.time_ns())
    r["titulo"] = (_leer(carpeta / "plan.json", {}) or {}).get("titulo", r.get("titulo", ""))
    r["nota"] = (nota or "").strip()[:1000]
    for k in ("revisa_pc", "latido"):
        r.pop(k, None)
    _historial(r, "listo para subir" if aprobado else "regresó al editor", r["nota"])
    _escribir(carpeta / "revision.json", r)
    return True


def marcar_renderizado(carpeta, archivo, destino_nombre=""):
    carpeta = Path(carpeta)
    r = _leer(carpeta / "revision.json", {}) or {}
    r.update(estado="renderizado", archivo_final=str(archivo), destino=destino_nombre,
             renderizado=time.strftime("%Y-%m-%d %H:%M"))
    for k in ("revisa_pc", "latido"):
        r.pop(k, None)
    _historial(r, "render final", Path(archivo).name)
    _escribir(carpeta / "revision.json", r)


def copia_local(carpeta, destino):
    """Copia ligera del trabajo en esta PC para el render final (los temporales del render no se suben a Drive).
    El video base y los recursos se leen desde la carpeta de Drive."""
    carpeta, destino = Path(carpeta), Path(destino)
    shutil.rmtree(destino, ignore_errors=True)
    destino.mkdir(parents=True, exist_ok=True)
    fuera = {"base", "recursos", "vista_navegador.mp4", "vista_previa.mp4", ".historial", ".rehacer", "_tramos"}
    for f in carpeta.rglob("*"):
        rel = f.relative_to(carpeta)
        if f.is_file() and not any(x in fuera for x in rel.parts) and not f.name.endswith((".tmp", "_tmp.mp4")):
            (destino / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, destino / rel)
    mapa = []
    for sub in ("base", "recursos"):
        mapa += [(v, str(carpeta / sub)) for v in _variantes(carpeta / sub)]
    mapa += [(v, str(destino)) for v in _variantes(carpeta)]
    mapa.sort(key=lambda x: -len(x[0]))
    for j in [destino / "plan.json", destino / "plan_auto.json"]:
        datos = _leer(j)
        if datos is not None:
            _escribir(j, _reemplazar(datos, mapa))
    return destino


def localizar(carpeta):
    """Al abrir un trabajo de Drive en esta PC: las rutas del plan pasan a las de esta PC."""
    carpeta = Path(carpeta)
    r = _leer(carpeta / "revision.json", {}) or {}
    viejo = r.get("raiz")
    al_dia = _al_dia(carpeta)
    cambio = False
    for j in [carpeta / "plan.json", carpeta / "plan_auto.json"]:
        datos = _leer(j)
        if datos is None:
            continue
        nuevo = _reemplazar(datos, sorted([(v, str(carpeta)) for v in _variantes(viejo)], key=lambda x: -len(x[0]))) \
            if viejo and viejo != str(carpeta) else datos
        pl = Path(str(nuevo.get("plantilla", "")).replace("\\", "/")).name
        if pl and str(nuevo.get("plantilla")) != str(BASE / "plantillas" / pl):
            nuevo["plantilla"] = str(BASE / "plantillas" / pl)
        if nuevo != datos:
            _escribir(j, nuevo)
            cambio = True
    if viejo != str(carpeta):
        r["raiz"] = str(carpeta)
        _escribir(carpeta / "revision.json", r)
    if cambio:
        _refrescar_previa(carpeta, al_dia)
    return cambio


def borrar_renderizados():
    """Borra de la carpeta compartida los trabajos que ya se renderizaron (para liberar espacio en Drive).
    Los videos finales no se tocan. -> (borrados, espacio en bytes, errores)"""
    raiz = carpeta_lista()
    if not raiz:
        return 0, 0, ["no hay carpeta compartida"]
    n, tam, errores = 0, 0, []
    for d in (raiz / SUB_TRABAJOS).iterdir() if (raiz / SUB_TRABAJOS).exists() else []:
        r = _leer(d / "revision.json") if d.is_dir() else None
        if not r or r.get("estado") != "renderizado":
            continue
        try:
            peso = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
            shutil.rmtree(d)
            n, tam = n + 1, tam + peso
        except OSError as e:
            errores.append(f"{d.name}: {e}")
    return n, tam, errores


def lista():
    """Todos los trabajos de la carpeta compartida (los más recientes primero)."""
    raiz = carpeta_lista()
    if not raiz:
        return []
    salida = []
    for d in (raiz / SUB_TRABAJOS).iterdir() if (raiz / SUB_TRABAJOS).exists() else []:
        r = _leer(d / "revision.json") if d.is_dir() else None
        if not r:
            continue
        salida.append({"carpeta": str(d), "nombre": d.name, "titulo": r.get("titulo") or d.name,
                       "editor": r.get("editor", ""), "enviado": r.get("enviado", ""), "estado": r.get("estado", ""),
                       "texto": ESTADOS.get(r.get("estado"), r.get("estado", "")),
                       "revisa": r.get("revisa") if r.get("estado") == "en_revision" else None,
                       "ocupado": candado_ajeno(r), "nota": r.get("nota", ""),
                       "archivo_final": Path(r["archivo_final"]).name if r.get("archivo_final") else "",
                       "destino": r.get("destino") or (Path(r["archivo_final"]).parent.name if r.get("archivo_final") else ""),
                       "estilo": r.get("estilo", ""), "video": r.get("video", ""), "listo_video": (d / "base" / r.get("video", "")).exists(),
                       "mini_v": int((d / "miniatura.jpg").stat().st_mtime) if (d / "miniatura.jpg").exists() else 0})
    salida.sort(key=lambda x: x["enviado"], reverse=True)
    return salida
