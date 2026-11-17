"""
Ajustes que Python carga solo al arrancar (con el Python privado del Editor Vertical, en Windows).

- Los procesos que lanza la plataforma (editor.py, ffmpeg, taskkill...) no abren ventanas negras.
- Los trabajos se lanzan con python.exe (no pythonw.exe) para que su avance llegue a la interfaz.
"""
import os
import sys

if os.name == "nt":
    try:
        from pathlib import Path

        _exe = Path(sys.executable)
        if _exe.name.lower() == "pythonw.exe" and (_exe.parent / "python.exe").exists():
            sys.executable = str(_exe.parent / "python.exe")

        import subprocess

        _SIN_VENTANA = 0x08000000      # CREATE_NO_WINDOW
        _CONSOLA_NUEVA = 0x00000010    # CREATE_NEW_CONSOLE (se respeta si alguien la pide a propósito)
        _Popen_init = subprocess.Popen.__init__

        def _init_sin_ventana(self, *args, **kwargs):
            flags = kwargs.get("creationflags", 0) or 0
            if not flags & _CONSOLA_NUEVA:
                kwargs["creationflags"] = flags | _SIN_VENTANA
            _Popen_init(self, *args, **kwargs)

        subprocess.Popen.__init__ = _init_sin_ventana
    except Exception:
        pass
