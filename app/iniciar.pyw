"""
Arranque del Editor Vertical (lo abre el acceso directo del escritorio, sin ventana negra).
1) Prepara el entorno (ffmpeg, modelos, tarjeta gráfica, carpetas del escritorio).
2) Revisa en GitHub si hay versión nueva y, si la hay, se actualiza sola.
3) Se asegura de que Ollama esté corriendo.
4) Inicia la plataforma (si ya estaba abierta, solo abre el navegador) y abre el navegador.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
import zipfile
from pathlib import Path

APP = Path(__file__).resolve().parent
RAIZ = APP.parent
CONFIG = json.loads((RAIZ / "config.json").read_text(encoding="utf-8-sig")) if (RAIZ / "config.json").exists() else {}
PUERTO = int(CONFIG.get("puerto", 7860))
URL = f"http://127.0.0.1:{PUERTO}"
DATOS = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "EditorVertical"
DATOS.mkdir(parents=True, exist_ok=True)
LOG = DATOS / "arranque.log"
SIN_VENTANA = 0x08000000 if os.name == "nt" else 0
CONSOLA_NUEVA = 0x00000010 if os.name == "nt" else 0


def log(txt):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S  ") + txt + "\n")
    except OSError:
        pass


def aviso(texto, titulo="Editor Vertical"):
    log("AVISO: " + texto)
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, texto, titulo, 0x40)
        except Exception:
            pass


def vivo(url, timeout=1.5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def python_consola():
    """python.exe del Python privado (para pip)."""
    exe = Path(sys.executable)
    return str(exe.with_name("python.exe")) if exe.name.lower() == "pythonw.exe" else str(exe)


def preparar_entorno():
    ffbin = RAIZ / "ffmpeg" / "bin"
    sr = os.environ.get("SystemRoot", r"C:\Windows")
    sistema = [os.path.join(sr, "System32"), sr, os.path.join(sr, "System32", "Wbem")]  # por si el PATH está dañado
    os.environ["PATH"] = os.pathsep.join([str(ffbin)] + sistema + [os.environ.get("PATH", "")])
    os.environ["HF_HOME"] = str(RAIZ / "modelos_hf")
    os.environ["HF_HUB_OFFLINE"] = "1"   # el modelo de Whisper ya se descargó al instalar
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    os.environ["PUERTO"] = str(PUERTO)
    os.environ["NO_NAVEGADOR"] = "1"     # el navegador lo abre este arranque cuando la plataforma ya responde
    escritorio = CONFIG.get("escritorio") or str(Path.home() / "Desktop")
    os.environ["ESCRITORIO"] = escritorio
    os.environ["CARPETA_VIDEOS"] = CONFIG.get("carpeta_videos") or str(Path(escritorio) / "VideosEdit")
    os.environ["CARPETA_RENDERS"] = CONFIG.get("carpeta_renders") or str(Path(escritorio) / "Renders")
    for k in ("CARPETA_VIDEOS", "CARPETA_RENDERS"):
        try:
            Path(os.environ[k]).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    if CONFIG.get("whisper_modelo"):
        os.environ["WHISPER_MODELO"] = CONFIG["whisper_modelo"]
    if CONFIG.get("whisper_compute"):
        os.environ["WHISPER_COMPUTE"] = CONFIG["whisper_compute"]
    if not CONFIG.get("gpu_cuda", True) or not CONFIG.get("gpu_nvenc", True):
        os.environ["EDITOR_SIN_GPU"] = "1"   # «Solo tarjeta gráfica» desmarcado de inicio
    if CONFIG.get("ollama_url"):
        os.environ["OLLAMA_URL"] = CONFIG["ollama_url"]


def _version(txt):
    try:
        return tuple(int(x) for x in txt.strip().split("."))
    except ValueError:
        return (0,)


def _huella(p):
    return hashlib.md5(p.read_bytes()).hexdigest() if p.exists() else ""


def actualizar():
    """Si config.json trae 'repo' (usuario/repositorio de GitHub), compara app/version.txt con el de GitHub y,
    si allá hay una versión mayor, baja el repositorio y copia su carpeta «app» encima de la instalada."""
    repo = (CONFIG.get("repo") or "").strip().strip("/")
    if not repo or not CONFIG.get("actualizar_solo", True):
        return
    rama = CONFIG.get("rama") or "main"
    try:
        actual = (APP / "version.txt").read_text(encoding="utf-8").strip()
        url_v = f"https://raw.githubusercontent.com/{repo}/{rama}/app/version.txt?t={int(time.time())}"
        with urllib.request.urlopen(url_v, timeout=8) as r:
            nueva = r.read().decode("utf-8").strip()
        if not nueva or _version(nueva) <= _version(actual):
            return
        log(f"Actualizando {actual} -> {nueva}")
        req_antes = _huella(APP / "requirements.txt")
        tmp = Path(tempfile.mkdtemp())
        urllib.request.urlretrieve(f"https://codeload.github.com/{repo}/zip/refs/heads/{rama}", tmp / "repo.zip")
        with zipfile.ZipFile(tmp / "repo.zip") as z:
            z.extractall(tmp / "nuevo")
        raices = [d for d in (tmp / "nuevo").iterdir() if d.is_dir()]
        origen = next((d / "app" for d in raices if (d / "app" / "interfaz.py").exists()), None)
        if origen is None:
            raise RuntimeError("el repositorio no trae la carpeta «app»")
        for p in origen.rglob("*"):
            if p.is_file():
                dest = APP / p.relative_to(origen)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, dest)
        # instalador / desinstalador actualizados (por si cambian)
        for nombre in ("desinstalar.ps1",):
            for d in raices:
                if (d / nombre).exists():
                    shutil.copy2(d / nombre, RAIZ / nombre)
        shutil.rmtree(tmp, ignore_errors=True)
        if _huella(APP / "requirements.txt") != req_antes:
            # librerías nuevas: se instalan en una ventana para que se vea el avance
            log("Instalando librerías nuevas de la actualización")
            subprocess.run([python_consola(), "-m", "pip", "install", "--no-warn-script-location", "-r",
                            str(APP / "requirements.txt")], creationflags=CONSOLA_NUEVA)
        log("Actualización lista")
    except Exception as e:
        log(f"No se pudo actualizar (sigo con la versión instalada): {e}")


def asegurar_ollama():
    if vivo("http://127.0.0.1:11434/api/tags"):
        return
    candidatos = [Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
                  Path(os.environ.get("ProgramFiles", "")) / "Ollama" / "ollama.exe"]
    exe = next((c for c in candidatos if c.exists()), None)
    try:
        subprocess.Popen([str(exe) if exe else "ollama", "serve"], creationflags=SIN_VENTANA,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log("Ollama iniciado")
    except Exception as e:
        log(f"No pude iniciar Ollama: {e} (el editor funciona igual, sin el análisis del tema)")


def abrir_navegador():
    for _ in range(240):
        if vivo(URL + "/"):
            webbrowser.open(URL)
            return
        time.sleep(0.5)
    aviso("El Editor Vertical tardó demasiado en arrancar. Revisa el archivo:\n" + str(DATOS / "servidor.log"))


def main():
    if vivo(URL + "/"):
        webbrowser.open(URL)   # ya estaba abierto
        return
    preparar_entorno()
    actualizar()
    threading.Thread(target=asegurar_ollama, daemon=True).start()
    threading.Thread(target=abrir_navegador, daemon=True).start()
    # salida de errores a un archivo (pythonw no tiene consola)
    sys.stdout = sys.stderr = open(DATOS / "servidor.log", "a", encoding="utf-8", buffering=1)
    log("Arrancando en " + URL)
    sys.path.insert(0, str(APP))
    os.chdir(APP)
    try:
        import interfaz
        interfaz.main()
    except Exception as e:
        import traceback
        log(traceback.format_exc())
        aviso(f"El Editor Vertical no pudo arrancar:\n{e}\n\nDetalles en:\n{DATOS / 'servidor.log'}")


if __name__ == "__main__":
    main()
