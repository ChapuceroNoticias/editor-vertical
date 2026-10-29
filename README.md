# Editor Vertical · El Chapucero

Convierte videos 16:9 en videos verticales 9:16 con plantillas de edición (Clips Chapuceros, Clips Fuera,
Tiktoks Motivacionales, Tiktoks Yair y Solo subtítulos).

- **Instalar en una PC:** descarga el repositorio (Code → Download ZIP), descomprímelo y abre `Instalar.bat`.
  Detalles en [`LEEME.txt`](LEEME.txt).
- **Carpetas en el escritorio:** `VideosEdit` (videos a editar) y `Renders` (videos exportados).
- **Actualizar todas las PCs:** sube los archivos cambiados de `app/` y sube el número de `app/version.txt`.
  Cada PC se actualiza sola la próxima vez que abra el editor.
- **Manual de la plataforma:** [`app/LEEME.md`](app/LEEME.md).

| Carpeta / archivo | Qué es |
|---|---|
| `app/` | La plataforma (lo que se actualiza desde GitHub) |
| `app/version.txt` | Versión publicada: súbela para que las PCs se actualicen |
| `Instalar.bat`, `instalar.ps1` | Instalador (Python privado, ffmpeg, Whisper, OCR, Ollama, accesos directos) |
| `EditorVertical.iss` | Para crear un solo `.exe` de instalación con Inno Setup |
| `cerrar.ps1`, `desinstalar.ps1` | Cerrar por completo / quitar de la PC |
