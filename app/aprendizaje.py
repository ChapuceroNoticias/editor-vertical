#!/usr/bin/env python3
"""
Aprendizaje de la plataforma: compara lo que armó sola (automático) con lo que el editor dejó al exportar, y de
esas diferencias saca REGLAS que se proponen en el panel «Lo aprendido». Solo las reglas aprobadas se usan en los
siguientes análisis. Nada se reentrena: son diccionarios, preferencias y ajustes de plantilla.

  - Subtítulos: palabras que Whisper escucha mal (nombres, términos) -> se corrigen solas y los nombres se le
    dan a Whisper como pista.
  - Imágenes: sitios cuyas fotos siempre se quitan (evitar) o se quedan (preferir), búsquedas que el editor
    escribe (ejemplos para el modelo), duración y estilo de los momentos con imagen.
  - Acomodos: corrección constante del encuadre de Nacho (más arriba/abajo, más cerca/lejos) y la pantalla que
    se elige según lo que proyecta Nacho (video, celular, documento, imagen).

Todo se guarda en la carpeta 'aprendizaje' junto al editor.
"""
import difflib
import hashlib
import json
import re
import statistics
import time
from pathlib import Path
from urllib.parse import urlparse

BASE = Path(__file__).resolve().parent
CARPETA = BASE / "aprendizaje"
ESTADOS = CARPETA / "reglas.json"           # {id_regla: "aprobada" | "descartada"}
VIDEOS = CARPETA / "videos"                 # lo observado en cada trabajo (uno por archivo)

MIN_PANTALLA = 2        # veces que debe repetirse una elección de pantalla
MIN_ENCUADRE = 3        # correcciones de encuadre para proponer un ajuste
MIN_MOMENTOS = 5        # momentos con imagen para proponer duración / estilo
MIN_SITIO_EVITAR = 2
MIN_SITIO_PREFERIR = 3
MIN_EJEMPLOS = 3


# ----------------------------------------------------------------------------
# utilidades
# ----------------------------------------------------------------------------
def _leer(p, defecto):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return defecto


def _escribir(p, datos):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def nucleo(palabra):
    """La palabra sin signos alrededor (conserva mayúsculas y acentos)."""
    return re.sub(r"^[^\wáéíóúüñÁÉÍÓÚÜÑ]+|[^\wáéíóúüñÁÉÍÓÚÜÑ]+$", "", str(palabra or ""))


def norm(palabra):
    return nucleo(palabra).lower()


def dominio(url):
    try:
        d = urlparse(str(url)).netloc.lower()
        return d[4:] if d.startswith("www.") else d
    except Exception:
        return ""


def plantilla_clave(plan):
    return Path(str(plan.get("plantilla", ""))).stem or "chapucero_vertical"


def plan_base(trabajo):
    """Cómo lo armó la plataforma sola: plan_auto.json (desde esta versión) o el respaldo más viejo del historial."""
    t = Path(trabajo)
    if (t / "plan_auto.json").exists():
        return _leer(t / "plan_auto.json", None)
    h = sorted((t / ".historial").glob("*_plan.json")) if (t / ".historial").exists() else []
    return _leer(h[0], None) if h else None


# ----------------------------------------------------------------------------
# observar un trabajo
# ----------------------------------------------------------------------------
def observar_subtitulos(trabajo):
    """Pares (lo que escuchó Whisper -> lo que dejó el editor) comparando la transcripción con los subtítulos."""
    t = Path(trabajo)
    auto = _leer(t / "transcripcion.json", [])
    grupos = _leer(t / "subtitulos.json", None)
    if not auto or not grupos:
        return []
    final = [p for g in sorted(grupos, key=lambda g: g.get("i", 0)) for p in g.get("palabras", [])]
    a_txt = [nucleo(p.get("p", "")) for p in auto]
    f_txt = [nucleo(p.get("p", "")) for p in final]
    a_n = [x.lower() for x in a_txt]
    f_n = [x.lower() for x in f_txt]
    pares = []
    sm = difflib.SequenceMatcher(a=a_n, b=f_n, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            # mismas palabras: solo cuenta si el editor corrigió mayúsculas de un nombre
            for a, f in zip(a_txt[i1:i2], f_txt[j1:j2]):
                if a and f and a != f and a.lower() == f.lower() and f[:1].isupper() and len(f) > 2:
                    pares.append([a, f])
        elif op == "replace" and 1 <= i2 - i1 <= 3 and 1 <= j2 - j1 <= 3:
            mal = " ".join(x for x in a_txt[i1:i2] if x)
            bien = " ".join(x for x in f_txt[j1:j2] if x)
            if mal and bien and mal.lower() != bien.lower():
                # que se parezcan (corrección de la misma palabra), no un renglón reescrito
                if difflib.SequenceMatcher(a=mal.lower(), b=bien.lower()).ratio() >= 0.45 or bien[:1].isupper():
                    pares.append([mal, bien])
    return pares


def _visibles(plan):
    return [m for m in (plan or {}).get("momentos", []) if m.get("imagenes") and not m.get("oculto")]


def observar_imagenes(trabajo, base, final, palabras):
    t = Path(trabajo)
    fuentes = _leer(t / "imagenes" / "fuentes.json", {})
    def dom(ruta):
        f = fuentes.get(Path(ruta).name) or {}
        return f.get("dominio") or dominio(f.get("pagina") or f.get("url"))
    b_imgs = {i for m in _visibles(base) for i in m["imagenes"]}
    f_imgs = {i for m in _visibles(final) for i in m["imagenes"]}
    sitios = {}
    for ruta in b_imgs:
        d = dom(ruta)
        if not d:
            continue
        s = sitios.setdefault(d, {"quedo": 0, "quito": 0})
        s["quedo" if ruta in f_imgs else "quito"] += 1
    for ruta in f_imgs - b_imgs:   # fotos que buscó el editor y se quedaron
        d = dom(ruta)
        if d:
            sitios.setdefault(d, {"quedo": 0, "quito": 0})["quedo"] += 1
    # búsquedas que escribió el editor (ejemplos para el modelo)
    busq_base = {str(m.get("busqueda", "")).strip().lower() for m in (base or {}).get("momentos", [])}
    ejemplos = []
    for m in _visibles(final):
        b = str(m.get("busqueda", "")).strip()
        if b and b.lower() not in busq_base:
            texto = " ".join(p["p"] for p in palabras if m["inicio"] - 0.5 <= p.get("i", 0) < m["fin"])[:240]
            if texto:
                ejemplos.append({"texto": texto, "busqueda": b})
    cortes = (final or {}).get("cortes", [])
    def ed_t(x):
        q = 0.0
        for c in sorted(cortes, key=lambda c: c["inicio"]):
            if x >= c["fin"]:
                q += c["fin"] - c["inicio"]
            elif x > c["inicio"]:
                q += x - c["inicio"]
        return x - q
    momentos = [{"dur": round(ed_t(m["fin"]) - ed_t(m["inicio"]), 2), "estilo": m.get("estilo", "dividida")}
                for m in _visibles(final)]
    return {"sitios": sitios, "ejemplos": ejemplos, "momentos": momentos,
            "subidas": sum(1 for i in f_imgs if Path(i).name.startswith("usuario_"))}


def observar_pantalla(base, final, ed, pl):
    """Elecciones de pantalla del editor que no son las que la plataforma pone sola, por clase de contenido."""
    cfg_p = pl.get("proyeccion", {})
    out = []
    for p in (final or {}).get("proyeccion", []):
        if p.get("pantalla") not in ("completa", "dividida", "nacho"):
            continue
        defecto = ed.pantalla_de({k: v for k, v in p.items() if k != "pantalla"}, cfg_p)
        if p.get("manual") or p["pantalla"] != defecto:
            out.append([ed.clase_pantalla(p), p["pantalla"]])
    return out


def observar_encuadre(final, ed, pl):
    """Cuánto movió el editor el encuadre de Nacho respecto al automático (relativo al recuadro)."""
    ajustes = (final or {}).get("encuadre_manual") or []
    if not ajustes:
        return []
    out = []
    try:
        if (final.get("estilo") or pl.get("estilo")) == "motivacional":
            moti = ed.estilo_motivacional()
            escena = lambda tt: moti.escena_en(final, pl, tt)  # noqa: E731
        else:
            ed.escalar_cajas(pl, final["info"]["ancho"], final["info"]["alto"])
            fijo = ed.fijar_plan(final, pl)
            escena = lambda tt: ed.escena_en(fijo, pl, tt)  # noqa: E731
    except Exception:
        return []
    for a in ajustes:
        tt = (a["inicio"] + a["fin"]) / 2
        try:
            e = escena(tt)
        except Exception:
            continue
        if e.get("tipo") not in ("persona", "dividida") or not e.get("auto"):
            continue
        A = [float(v) for v in e["auto"]]
        M = ed.ventana_manual([a], tt, e["region"], e["aspect"], A)
        if A[2] <= 0 or A[3] <= 0:
            continue
        out.append({"lay": e["tipo"],
                    "dy": round(((M[1] + M[3] / 2) - (A[1] + A[3] / 2)) / A[3], 4),
                    "dx": round(((M[0] + M[2] / 2) - (A[0] + A[2] / 2)) / A[2], 4),
                    "zoom": round(A[2] / max(1.0, M[2]), 4),
                    "dur": round(a["fin"] - a["inicio"], 2)})
    return out


def aprender_de(trabajo, ed):
    """Guarda lo observado en este trabajo (se reemplaza si ya se había aprendido de él). Devuelve un resumen."""
    t = Path(trabajo)
    final = _leer(t / "plan.json", None)
    if not final:
        return None
    base = plan_base(t)
    pl = ed.plantilla_plan(final)
    palabras = _leer(t / "transcripcion.json", [])
    obs = {
        "trabajo": str(t), "video": Path(str(final.get("video", ""))).name, "plantilla": plantilla_clave(final),
        "fecha": time.strftime("%Y-%m-%d %H:%M"),
        "subtitulos": observar_subtitulos(t),
        "imagenes": observar_imagenes(t, base, final, palabras) if base else {},
        "pantalla": observar_pantalla(base, final, ed, pl),
        "encuadre": observar_encuadre(final, ed, ed.plantilla_plan(final)),
    }
    VIDEOS.mkdir(parents=True, exist_ok=True)
    _escribir(VIDEOS / (hashlib.md5(str(t).encode()).hexdigest()[:16] + ".json"), obs)
    return {"subtitulos": len(obs["subtitulos"]), "pantalla": len(obs["pantalla"]),
            "encuadre": len(obs["encuadre"]), "imagenes": len((obs["imagenes"] or {}).get("ejemplos", []))}


# ----------------------------------------------------------------------------
# reglas
# ----------------------------------------------------------------------------
def observaciones():
    return [_leer(p, {}) for p in sorted(VIDEOS.glob("*.json"))] if VIDEOS.exists() else []


def reglas():
    """Todas las reglas propuestas a partir de lo observado, con su estado (propuesta / aprobada / descartada)."""
    obs = observaciones()
    estados = _leer(ESTADOS, {})
    out = []

    def agregar(rid, tipo, titulo, detalle, valor, evidencia, n_videos):
        out.append({"id": rid, "tipo": tipo, "titulo": titulo, "detalle": detalle, "valor": valor,
                    "evidencia": evidencia, "videos": n_videos, "estado": estados.get(rid, "propuesta")})

    # --- subtítulos: diccionario ---
    pares = {}
    for o in obs:
        for mal, bien in o.get("subtitulos", []):
            k = (mal, bien)
            d = pares.setdefault(k, {"n": 0, "videos": set()})
            d["n"] += 1
            d["videos"].add(o.get("video", ""))
    for (mal, bien), d in sorted(pares.items(), key=lambda kv: -kv[1]["n"]):
        agregar("sub:" + mal.lower() + "=>" + bien, "subtitulos", f"«{mal}» → «{bien}»",
                "Whisper escribe así esta palabra y tú la corriges.", {"mal": mal, "bien": bien},
                f"corregido {d['n']} vez/veces", len(d["videos"]))

    # --- imágenes: sitios ---
    sitios = {}
    for o in obs:
        for dmn, s in ((o.get("imagenes") or {}).get("sitios") or {}).items():
            x = sitios.setdefault(dmn, {"quedo": 0, "quito": 0, "videos": set()})
            x["quedo"] += s.get("quedo", 0)
            x["quito"] += s.get("quito", 0)
            x["videos"].add(o.get("video", ""))
    for dmn, s in sitios.items():
        if s["quito"] >= MIN_SITIO_EVITAR and s["quedo"] == 0:
            agregar("sitio_evitar:" + dmn, "imagenes", f"Evitar fotos de {dmn}",
                    "Siempre quitas las fotos de este sitio.", {"dominio": dmn},
                    f"quitaste {s['quito']}, dejaste 0", len(s["videos"]))
        elif s["quedo"] >= MIN_SITIO_PREFERIR and s["quito"] * 3 <= s["quedo"]:
            agregar("sitio_preferir:" + dmn, "imagenes", f"Preferir fotos de {dmn}",
                    "Las fotos de este sitio casi siempre se quedan.", {"dominio": dmn},
                    f"dejaste {s['quedo']}, quitaste {s['quito']}", len(s["videos"]))

    # --- imágenes: ejemplos de búsqueda ---
    ejemplos = [e | {"video": o.get("video", "")} for o in obs for e in (o.get("imagenes") or {}).get("ejemplos", [])]
    if len(ejemplos) >= MIN_EJEMPLOS:
        agregar("ejemplos_busqueda", "imagenes", f"Usar tus {len(ejemplos)} búsquedas como ejemplo",
                "Al elegir qué buscar, el modelo verá cómo buscas tú (frase dicha → búsqueda).",
                {"ejemplos": ejemplos[-15:]}, "; ".join(f"«{e['busqueda']}»" for e in ejemplos[-4:]),
                len({e["video"] for e in ejemplos}))

    # --- imágenes: duración y estilo de los momentos (por plantilla) ---
    por_pl = {}
    for o in obs:
        for m in (o.get("imagenes") or {}).get("momentos", []):
            por_pl.setdefault(o.get("plantilla"), []).append(m | {"video": o.get("video", "")})
    for pln, ms in por_pl.items():
        if len(ms) < MIN_MOMENTOS:
            continue
        durs = [m["dur"] for m in ms if m.get("dur", 0) > 0.5]
        if len(durs) >= MIN_MOMENTOS:
            med = statistics.median(durs)
            agregar(f"momentos_dur:{pln}", "imagenes", f"Imágenes de unos {med:.1f} s ({pln})",
                    "Así de largas dejas las imágenes.", {"plantilla": pln, "min": round(max(1.5, med - 1.5), 1),
                                                         "max": round(med + 1.5, 1)},
                    f"{len(durs)} imágenes, mediana {med:.1f} s", len({m['video'] for m in ms}))
        cuenta = {}
        for m in ms:
            cuenta[m["estilo"]] = cuenta.get(m["estilo"], 0) + 1
        est, n = max(cuenta.items(), key=lambda kv: kv[1])
        if n / len(ms) >= 0.75 and len(cuenta) >= 1:
            nombre = {"completa": "pantalla completa", "dividida": "pantalla dividida"}.get(est, est)
            agregar(f"momentos_estilo:{pln}", "imagenes", f"Imágenes en {nombre} ({pln})",
                    "Casi siempre las dejas así.", {"plantilla": pln, "estilo": est},
                    f"{n} de {len(ms)}", len({m['video'] for m in ms}))

    # --- acomodos: pantalla según lo que proyecta Nacho (por plantilla) ---
    pant = {}
    for o in obs:
        for clase, modo in o.get("pantalla", []):
            d = pant.setdefault((o.get("plantilla"), clase), {})
            x = d.setdefault(modo, {"n": 0, "videos": set()})
            x["n"] += 1
            x["videos"].add(o.get("video", ""))
    nombres_clase = {"video": "videos", "celular": "videos de celular", "documento": "documentos",
                     "imagen": "imágenes fijas (tweets, mapas)"}
    nombres_modo = {"completa": "pantalla completa", "dividida": "pantalla dividida", "nacho": "solo Nacho"}
    for (pln, clase), d in pant.items():
        total = sum(x["n"] for x in d.values())
        modo, x = max(d.items(), key=lambda kv: kv[1]["n"])
        if x["n"] >= MIN_PANTALLA and x["n"] / total >= 0.7:
            agregar(f"pantalla:{pln}:{clase}", "acomodos", f"{nombres_clase.get(clase, clase).capitalize()} en "
                    f"{nombres_modo.get(modo, modo)} ({pln})", "Lo cambias así cada vez.",
                    {"plantilla": pln, "clase": clase, "modo": modo}, f"{x['n']} de {total} veces", len(x["videos"]))

    # --- acomodos: encuadre de Nacho (por plantilla y diseño) ---
    enc = {}
    for o in obs:
        for e in o.get("encuadre", []):
            enc.setdefault((o.get("plantilla"), e["lay"]), []).append(e | {"video": o.get("video", "")})
    for (pln, lay), es in enc.items():
        if len(es) < MIN_ENCUADRE:
            continue
        dy = statistics.median(e["dy"] for e in es)
        zoom = statistics.median(e["zoom"] for e in es)
        mismo_lado = sum(1 for e in es if (e["dy"] > 0) == (dy > 0)) / len(es)
        partes = []
        if abs(dy) >= 0.03 and mismo_lado >= 0.7:
            partes.append(("más abajo" if dy > 0 else "más arriba") + f" ({abs(dy) * 100:.0f}%)")
        else:
            dy = 0.0
        if abs(zoom - 1) >= 0.05:
            partes.append(("más cerca" if zoom > 1 else "más lejos") + f" ({abs(zoom - 1) * 100:.0f}%)")
        else:
            zoom = 1.0
        if partes:
            donde = "a pantalla completa" if lay == "persona" else "en la pantalla dividida"
            agregar(f"encuadre:{pln}:{lay}", "acomodos", f"Encuadre de Nacho {donde}: " + " y ".join(partes) + f" ({pln})",
                    "Así corriges el encuadre automático casi siempre.",
                    {"plantilla": pln, "lay": lay, "dy": round(dy, 4), "zoom": round(zoom, 4)},
                    f"{len(es)} correcciones", len({e['video'] for e in es}))
    return out


def cambiar_estado(rid, estado):
    estados = _leer(ESTADOS, {})
    if estado in ("aprobada", "descartada"):
        estados[rid] = estado
    else:
        estados.pop(rid, None)
    _escribir(ESTADOS, estados)


def resumen():
    obs = observaciones()
    rs = reglas()
    return {"videos": len(obs), "reglas": rs,
            "aprobadas": sum(1 for r in rs if r["estado"] == "aprobada"),
            "propuestas": sum(1 for r in rs if r["estado"] == "propuesta")}


# ----------------------------------------------------------------------------
# lo que se aplica al analizar (solo reglas aprobadas)
# ----------------------------------------------------------------------------
def aprobado():
    """Reglas aprobadas listas para usar: diccionario, nombres para Whisper, sitios, ejemplos y parches de plantilla."""
    out = {"diccionario": [], "nombres": [], "sitios_evitar": [], "sitios_preferir": [], "ejemplos": [], "parches": {}}
    for r in reglas():
        if r["estado"] != "aprobada":
            continue
        v = r["valor"]
        if r["id"].startswith("sub:"):
            out["diccionario"].append([v["mal"], v["bien"]])
            if any(c.isupper() for c in v["bien"]):
                out["nombres"].append(v["bien"])
        elif r["id"].startswith("sitio_evitar:"):
            out["sitios_evitar"].append(v["dominio"])
        elif r["id"].startswith("sitio_preferir:"):
            out["sitios_preferir"].append(v["dominio"])
        elif r["id"] == "ejemplos_busqueda":
            out["ejemplos"] = v["ejemplos"]
        elif r["id"].startswith("momentos_dur:"):
            out["parches"].setdefault(v["plantilla"], []).extend([[["momentos", "duracion_min"], v["min"]],
                                                                 [["momentos", "duracion_max"], v["max"]]])
        elif r["id"].startswith("momentos_estilo:"):
            out["parches"].setdefault(v["plantilla"], []).append([["momentos", "estilos"], [v["estilo"]]])
        elif r["id"].startswith("pantalla:"):
            out["parches"].setdefault(v["plantilla"], []).append([["proyeccion", "aprendido_pantalla", v["clase"]], v["modo"]])
        elif r["id"].startswith("encuadre:"):
            ruta = (["encuadre", "ajuste_aprendido"] if v["plantilla"] == "tiktok_motivacional"
                    else ["layouts", v["lay"], "persona", "ajuste_aprendido"])
            out["parches"].setdefault(v["plantilla"], []).append([ruta, {"dy": v["dy"], "zoom": v["zoom"]}])
    out["nombres"] = sorted(set(out["nombres"]))[:60]
    return out


def aplicar_parche(pl, parche):
    """Escribe en la plantilla (en memoria) los valores aprendidos: [[ruta, valor], ...]."""
    for ruta, valor in parche or []:
        d = pl
        for k in ruta[:-1]:
            if not isinstance(d.get(k), dict):
                d[k] = {}
            d = d[k]
        d[ruta[-1]] = valor
    return pl
