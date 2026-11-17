# ============================================================================
#  Instalador del Editor Vertical · El Chapucero
#  - Revisa la PC y la tarjeta NVIDIA, y ajusta todo al modelo de tarjeta.
#  - Instala su propio Python, ffmpeg, Whisper (con su modelo), el lector de texto (OCR), Ollama (con su modelo)
#    y la plataforma.
#  - Crea el acceso directo en el escritorio y las carpetas «VideosEdit» y «Renders».
#  No necesita permisos de administrador.
# ============================================================================
param(
    [string]$Origen = $PSScriptRoot,
    [switch]$SinOllama
)

$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot;$env:SystemRoot\System32\Wbem;$env:SystemRoot\System32\WindowsPowerShell\v1.0;" + $env:PATH
$ErrorActionPreference = "Continue"   # los programas externos escriben avisos en stderr; los errores se revisan a mano
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Host.UI.RawUI.WindowTitle = "Instalando Editor Vertical - El Chapucero"

# --- Repositorio de GitHub de donde se actualiza solo (usuario/repositorio). Cámbialo aquí si usas otro. ---
$REPO = "ChapuceroNoticias/editor-vertical"
$RAMA = "main"

$PY_VERSION = "3.12.8"
$URL_PY     = "https://www.python.org/ftp/python/$PY_VERSION/python-$PY_VERSION-embed-amd64.zip"
$URL_GETPIP = "https://bootstrap.pypa.io/get-pip.py"
$URL_FFMPEG = @("https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
                "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
                "https://github.com/GyanD/codexffmpeg/releases/download/7.1/ffmpeg-7.1-essentials_build.zip")
$URL_OLLAMA = "https://ollama.com/download/OllamaSetup.exe"
$TOTAL = 11

$Datos = Join-Path $env:LOCALAPPDATA "EditorVertical"
$Raiz  = Join-Path $Datos "programa"
$Tmp   = Join-Path $Datos "descargas"
$Log   = Join-Path $Datos "instalacion.log"
New-Item -ItemType Directory -Force -Path $Raiz, $Tmp | Out-Null

function Escribir($texto, $color = "Gray") {
    Write-Host $texto -ForegroundColor $color
    Add-Content -Path $Log -Value ("{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $texto) -Encoding UTF8
}
$script:paso = 0
function Paso($texto) {
    $script:paso++
    Write-Host ""
    Escribir ("[{0}/{1}] {2}" -f $script:paso, $TOTAL, $texto) "Cyan"
}
function Fallar($texto) {
    Escribir ""
    Escribir "ERROR: $texto" "Red"
    Escribir "Detalles en: $Log" "Red"
    Write-Host ""
    Read-Host "Presiona Enter para cerrar"
    exit 1
}
function Preguntar($texto) {
    $r = Read-Host "$texto (S/N)"
    return $r -match '^[sSyY]'
}
function Descargar($urls, $destino) {
    # Prueba varias formas (curl sin revisar revocación de certificados, que falla en algunas redes y antivirus;
    # luego PowerShell y luego BITS) y varias direcciones si hay más de una.
    $curl = Join-Path $env:SystemRoot "System32\curl.exe"
    foreach ($url in @($urls)) {
        Escribir "   Descargando $(Split-Path $url -Leaf)..."
        for ($i = 1; $i -le 3; $i++) {
            if (Test-Path $destino) { Remove-Item $destino -Force -ErrorAction SilentlyContinue }
            if (Test-Path $curl) {
                $salida = & $curl -L --fail --ssl-no-revoke --retry 2 --retry-delay 3 --connect-timeout 30 -o $destino $url 2>&1
                if ($LASTEXITCODE -eq 0 -and (Test-Path $destino) -and (Get-Item $destino).Length -gt 1000) { return }
                Add-Content -Path $Log -Value ("   curl ({0}): {1}" -f $LASTEXITCODE, ($salida -join " ")) -Encoding UTF8
            }
            try {
                Invoke-WebRequest -Uri $url -OutFile $destino -UseBasicParsing -ErrorAction Stop
                if ((Get-Item $destino).Length -gt 1000) { return }
            } catch { Add-Content -Path $Log -Value "   Invoke-WebRequest: $_" -Encoding UTF8 }
            try {
                Start-BitsTransfer -Source $url -Destination $destino -ErrorAction Stop
                if ((Get-Item $destino).Length -gt 1000) { return }
            } catch { Add-Content -Path $Log -Value "   BITS: $_" -Encoding UTF8 }
            Escribir "   Reintentando ($i)..." "Yellow"
            Start-Sleep -Seconds 4
        }
        Escribir "   No se pudo desde $(([Uri]$url).Host); pruebo otra dirección..." "Yellow"
    }
    Fallar "No pude descargar $(Split-Path @($urls)[0] -Leaf). Revisa la conexión a internet (o el antivirus/firewall) y vuelve a ejecutar el instalador."
}
function Py { & (Join-Path $Raiz "python\python.exe") @args }

Clear-Host
Write-Host "==============================================================" -ForegroundColor Red
Write-Host "        EDITOR VERTICAL  ·  EL CHAPUCERO      (instalador)" -ForegroundColor White
Write-Host "==============================================================" -ForegroundColor Red
Escribir "Origen: $Origen"
Escribir "Se instalará en: $Raiz"

# si el editor está abierto, se cierra (para poder copiar los archivos)
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match "EditorVertical" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

# ---------------------------------------------------------------------------
Paso "Revisando la computadora"
if (-not [Environment]::Is64BitOperatingSystem) { Fallar "Se necesita Windows de 64 bits." }
$win = [Environment]::OSVersion.Version
if ($win.Major -lt 10) { Fallar "Se necesita Windows 10 u 11." }
$unidad = (Get-Item $env:LOCALAPPDATA).PSDrive
$libreGB = [math]::Round($unidad.Free / 1GB, 1)
Escribir "   Windows $($win.Major).$($win.Build) · espacio libre en ${unidad}: $libreGB GB"
if ($libreGB -lt 25) {
    if (-not (Preguntar "Hay poco espacio ($libreGB GB, se recomiendan 25 GB). ¿Continuar de todos modos?")) { exit 1 }
}

# ---------------------------------------------------------------------------
Paso "Detectando la tarjeta gráfica"
$smi = @("$env:SystemRoot\System32\nvidia-smi.exe", "$env:ProgramFiles\NVIDIA Corporation\NVSMI\nvidia-smi.exe") |
       Where-Object { Test-Path $_ } | Select-Object -First 1
$gpu = $null; $vram = 0; $driver = "0"; $cc = 0.0
if ($smi) {
    $q = & $smi --query-gpu=name,memory.total,driver_version --format=csv,noheader,nounits 2>$null | Select-Object -First 1
    if ($q) {
        $p = $q -split ",\s*"
        $gpu = $p[0].Trim(); $vram = [math]::Round([double]$p[1] / 1024, 1); $driver = $p[2].Trim()
    }
    $c = & $smi --query-gpu=compute_cap --format=csv,noheader 2>$null | Select-Object -First 1
    if ($c -match '^\d+\.\d+') { $cc = [double]$c.Trim() }
}
if (-not $gpu) {
    $v = Get-CimInstance Win32_VideoController | Where-Object { $_.Name -match "NVIDIA" } | Select-Object -First 1
    if ($v) { $gpu = $v.Name; $vram = [math]::Round($v.AdapterRAM / 1GB, 1); $driver = $v.DriverVersion }
}
if (-not $gpu) {
    Escribir "   No encontré una tarjeta NVIDIA." "Yellow"
    if (-not (Preguntar "Sin tarjeta NVIDIA todo funcionará con el procesador (mucho más lento). ¿Continuar?")) { exit 1 }
    $nvidia = $false
} else {
    $nvidia = $true
    Escribir "   Tarjeta: $gpu · $vram GB · driver $driver$(if ($cc) { " · CUDA $cc" })" "Green"
    $mayor = 0; if ($driver -match '^(\d+)') { $mayor = [int]$Matches[1] }
    if ($smi -and $mayor -gt 0 -and $mayor -lt 528) {
        Escribir "   El driver de NVIDIA es viejo ($driver). Whisper necesita la versión 528 o más nueva." "Yellow"
        if (Preguntar "¿Abrir la página de NVIDIA para actualizarlo? (después vuelve a ejecutar este instalador)") {
            Start-Process "https://www.nvidia.com/es-la/drivers/"
            exit 0
        }
    }
}

# Ajustes según la tarjeta
$whisper = "large-v3"; $compute = "float16"; $ollamaModelo = "qwen2.5:7b"
if ($nvidia) {
    if ($vram -ge 12)     { $ollamaModelo = "qwen2.5:14b" }
    elseif ($vram -lt 4)  { $whisper = "medium"; $compute = "int8_float16"; $ollamaModelo = "qwen2.5:3b" }
    elseif ($vram -lt 8)  { $compute = "int8_float16"; $ollamaModelo = "qwen2.5:3b" }
    if ($cc -gt 0 -and $cc -lt 6.1) { $compute = "float16" }   # tarjetas viejas: sin int8
    if ($cc -gt 0 -and $cc -lt 5.3) { $compute = "float32"; $whisper = "medium" }
} else {
    $whisper = "medium"; $compute = "int8"; $ollamaModelo = "qwen2.5:3b"
}
Escribir "   Whisper: $whisper ($compute) · Ollama: $ollamaModelo"

# ---------------------------------------------------------------------------
Paso "Instalando Python (privado para esta plataforma)"
$pyDir = Join-Path $Raiz "python"
if (-not (Test-Path (Join-Path $pyDir "python.exe"))) {
    $zip = Join-Path $Tmp "python.zip"
    Descargar $URL_PY $zip
    try { Expand-Archive -Path $zip -DestinationPath $pyDir -Force -ErrorAction Stop } catch { Fallar "No se pudo descomprimir Python: $_" }
    $pth = Get-ChildItem $pyDir -Filter "python*._pth" | Select-Object -First 1
    $lineas = (Get-Content $pth.FullName) -replace '^#\s*import site', 'import site'
    $lineas += "..\app"
    Set-Content -Path $pth.FullName -Value $lineas -Encoding ASCII
    $gp = Join-Path $Tmp "get-pip.py"
    Descargar $URL_GETPIP $gp
    Py $gp --no-warn-script-location 2>&1 | Out-File -Append -FilePath $Log -Encoding UTF8
    if ($LASTEXITCODE -ne 0) { Fallar "No se pudo preparar pip." }
} else { Escribir "   Ya estaba instalado." }

# ---------------------------------------------------------------------------
Paso "Copiando la plataforma"
$appDestino = Join-Path $Raiz "app"
New-Item -ItemType Directory -Force -Path $appDestino | Out-Null
if (-not (Test-Path (Join-Path $Origen "app\interfaz.py"))) { Fallar "No encuentro la carpeta 'app' junto al instalador ($Origen)." }
try { Copy-Item -Path (Join-Path $Origen "app\*") -Destination $appDestino -Recurse -Force -ErrorAction Stop }
catch { Fallar "No se pudieron copiar los archivos (¿está abierto el Editor Vertical? ciérralo y vuelve a intentar): $_" }
Get-ChildItem $appDestino -Recurse -File | Unblock-File -ErrorAction SilentlyContinue
foreach ($f in @("desinstalar.ps1", "cerrar.ps1")) { Copy-Item (Join-Path $Origen $f) $Raiz -Force -ErrorAction SilentlyContinue }

# ---------------------------------------------------------------------------
Paso "Instalando librerías (Whisper, CUDA, Gradio, OpenCV...). Puede tardar varios minutos"
Py -m pip install --upgrade pip --no-warn-script-location 2>&1 | Out-File -Append -FilePath $Log -Encoding UTF8
Py -m pip install --no-warn-script-location -r (Join-Path $appDestino "requirements.txt") 2>&1 |
    Tee-Object -Append -FilePath $Log | Where-Object { $_ -match "^(Collecting|Successfully)" } |
    ForEach-Object { Write-Host "   $_" -ForegroundColor DarkGray }
if ($LASTEXITCODE -ne 0) { Fallar "Falló la instalación de librerías." }

# ---------------------------------------------------------------------------
Paso "Instalando ffmpeg"
$ffDir = Join-Path $Raiz "ffmpeg"
if (-not (Test-Path (Join-Path $ffDir "bin\ffmpeg.exe"))) {
    $zip = Join-Path $Tmp "ffmpeg.zip"
    Descargar $URL_FFMPEG $zip
    $ext = Join-Path $Tmp "ffmpeg_ext"
    if (Test-Path $ext) { Remove-Item $ext -Recurse -Force }
    try { Expand-Archive -Path $zip -DestinationPath $ext -Force -ErrorAction Stop } catch { Fallar "No se pudo descomprimir ffmpeg: $_" }
    $bin = Get-ChildItem $ext -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
    New-Item -ItemType Directory -Force -Path (Join-Path $ffDir "bin") | Out-Null
    Copy-Item (Join-Path $bin.DirectoryName "*") (Join-Path $ffDir "bin") -Force
    Remove-Item $ext -Recurse -Force
} else { Escribir "   Ya estaba instalado." }
$env:PATH = (Join-Path $ffDir "bin") + ";" + $env:PATH
$nvencOk = $false
if ($nvidia) {
    & (Join-Path $ffDir "bin\ffmpeg.exe") -v error -f lavfi -i "color=c=black:s=256x256:d=0.2" -c:v h264_nvenc -f null - 2>$null
    $nvencOk = ($LASTEXITCODE -eq 0)
    if ($nvencOk) { Escribir "   La tarjeta puede codificar video (NVENC) ✓" "Green" }
    else { Escribir "   La tarjeta no pudo codificar video (NVENC). Se usará el procesador para esa parte." "Yellow" }
}

# ---------------------------------------------------------------------------
Paso "Descargando el modelo de Whisper ($whisper). Es grande (hasta 3 GB)"
$env:HF_HOME = Join-Path $Raiz "modelos_hf"
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"
Py -c "from huggingface_hub import snapshot_download; snapshot_download('Systran/faster-whisper-$whisper')"   # con barra de avance
if ($LASTEXITCODE -ne 0) { Fallar "No se pudo descargar el modelo de Whisper." }

# ---------------------------------------------------------------------------
Paso "Preparando el lector de texto (para difuminar los subtítulos que ya trae el video)"
$r = Py -c "from rapidocr import RapidOCR; RapidOCR(); print('OCR_OK')" 2>&1
$r | Out-File -Append -FilePath $Log -Encoding UTF8
if (($r -join "`n") -match "OCR_OK") { Escribir "   Listo ✓" "Green" }
else { Escribir "   No se pudo preparar ahora; se descarga solo la primera vez que se use." "Yellow" }

# ---------------------------------------------------------------------------
Paso "Instalando Ollama y su modelo ($ollamaModelo) para entender el tema, nombres y puntuación"
if (-not $SinOllama) {
    $ollamaExe = @("$env:LOCALAPPDATA\Programs\Ollama\ollama.exe", "$env:ProgramFiles\Ollama\ollama.exe") |
                 Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $ollamaExe) {
        $inst = Join-Path $Tmp "OllamaSetup.exe"
        Descargar $URL_OLLAMA $inst
        Escribir "   Instalando Ollama..."
        # -Wait se quedaba esperando también a "ollama app" (que se queda abierto): se espera solo al instalador
        $p = Start-Process -FilePath $inst -ArgumentList "/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES" -PassThru
        $p.WaitForExit()
        Start-Sleep -Seconds 5
        $ollamaExe = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
    } else { Escribir "   Ollama ya estaba instalado." }
    if (Test-Path $ollamaExe) {
        $vivo = $false
        try { Invoke-WebRequest "http://127.0.0.1:11434/api/tags" -UseBasicParsing -TimeoutSec 3 | Out-Null; $vivo = $true } catch { }
        if (-not $vivo) { Start-Process -FilePath $ollamaExe -ArgumentList "serve" -WindowStyle Hidden; Start-Sleep -Seconds 6 }
        Escribir "   Descargando $ollamaModelo (unos minutos)..."
        & $ollamaExe pull $ollamaModelo   # muestra la barra de avance en la ventana
        if ($LASTEXITCODE -ne 0) { Escribir "   No se pudo bajar el modelo de Ollama; el editor funcionará sin el análisis del tema." "Yellow" }
    } else { Escribir "   No se pudo instalar Ollama; el editor funcionará sin el análisis del tema." "Yellow" }
} else { Escribir "   Omitido." }

# ---------------------------------------------------------------------------
Paso "Guardando la configuración y probando la tarjeta"
$escritorio = [Environment]::GetFolderPath("Desktop")   # también si el escritorio está en OneDrive
$config = [ordered]@{
    gpu_cuda        = [bool]$nvidia
    gpu_nvenc       = [bool]($nvidia -and $nvencOk)
    gpu_nombre      = $(if ($gpu) { $gpu } else { "Procesador" })
    vram_gb         = $vram
    driver          = $driver
    whisper_modelo  = $whisper
    whisper_compute = $compute
    ollama_modelo   = $ollamaModelo
    escritorio      = $escritorio
    carpeta_videos  = (Join-Path $escritorio "VideosEdit")
    carpeta_renders = (Join-Path $escritorio "Renders")
    puerto          = 7860
    repo            = $REPO
    rama            = $RAMA
    actualizar_solo = $true
}
function GuardarConfig { [IO.File]::WriteAllText((Join-Path $Raiz "config.json"), ($config | ConvertTo-Json), (New-Object Text.UTF8Encoding $false)) }  # sin BOM
GuardarConfig
if ($nvidia) {
    $env:HF_HUB_OFFLINE = "1"
    $prueba = "import sys; sys.path.insert(0, r'$appDestino'); import editor; editor.preparar_dlls_cuda(); " +
              "from faster_whisper import WhisperModel; WhisperModel('$whisper', device='cuda', compute_type='$compute'); print('WHISPER_GPU_OK')"
    $r = Py -c $prueba 2>&1
    $r | Out-File -Append -FilePath $Log -Encoding UTF8
    if (($r -join "`n") -match "WHISPER_GPU_OK") { Escribir "   Whisper funciona con la tarjeta ✓" "Green" }
    else {
        Escribir "   Whisper no pudo usar la tarjeta (se usará el procesador para transcribir). Revisa que el driver de NVIDIA esté actualizado." "Yellow"
        $config.gpu_cuda = $false
        $config.whisper_compute = "int8"
        GuardarConfig
    }
}

# ---------------------------------------------------------------------------
Paso "Creando el acceso directo y las carpetas del escritorio"
New-Item -ItemType Directory -Force -Path (Join-Path $escritorio "VideosEdit"), (Join-Path $escritorio "Renders") | Out-Null
$ws = New-Object -ComObject WScript.Shell
$menu = [Environment]::GetFolderPath("Programs")
foreach ($destino in @((Join-Path $escritorio "Editor Vertical.lnk"), (Join-Path $menu "Editor Vertical.lnk"))) {
    $lnk = $ws.CreateShortcut($destino)
    $lnk.TargetPath = Join-Path $pyDir "pythonw.exe"
    $lnk.Arguments = "`"" + (Join-Path $appDestino "iniciar.pyw") + "`""
    $lnk.WorkingDirectory = $appDestino
    $lnk.IconLocation = (Join-Path $appDestino "icono.ico") + ",0"
    $lnk.Description = "Editor Vertical · El Chapucero"
    $lnk.Save()
}
# «Cerrar Editor Vertical» en el menú Inicio (para cerrarlo por completo; al abrirlo de nuevo busca actualizaciones)
$lnk = $ws.CreateShortcut((Join-Path $menu "Cerrar Editor Vertical.lnk"))
$lnk.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$lnk.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"" + (Join-Path $Raiz "cerrar.ps1") + "`""
$lnk.IconLocation = (Join-Path $appDestino "icono.ico") + ",0"
$lnk.Description = "Cierra el Editor Vertical"
$lnk.Save()
# entrada en "Agregar o quitar programas"
$reg = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\EditorVerticalChapucero"
New-Item -Path $reg -Force | Out-Null
Set-ItemProperty $reg -Name DisplayName -Value "Editor Vertical · El Chapucero"
Set-ItemProperty $reg -Name DisplayVersion -Value ((Get-Content (Join-Path $appDestino "version.txt")).Trim())
Set-ItemProperty $reg -Name Publisher -Value "El Chapucero"
Set-ItemProperty $reg -Name DisplayIcon -Value (Join-Path $appDestino "icono.ico")
Set-ItemProperty $reg -Name UninstallString -Value ("powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"" + (Join-Path $Raiz "desinstalar.ps1") + "`"")
Set-ItemProperty $reg -Name NoModify -Value 1 -Type DWord
Set-ItemProperty $reg -Name NoRepair -Value 1 -Type DWord

Remove-Item $Tmp -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "==============================================================" -ForegroundColor Green
Escribir "  ¡Listo! Abre «Editor Vertical» desde el escritorio." "Green"
Escribir "  Pon los videos a editar en la carpeta «VideosEdit» del escritorio." "Green"
Escribir "  Los videos exportados quedan en la carpeta «Renders» del escritorio." "Green"
Write-Host "==============================================================" -ForegroundColor Green
if (Preguntar "¿Abrir el Editor Vertical ahora?") {
    Start-Process -FilePath (Join-Path $pyDir "pythonw.exe") -ArgumentList "`"$(Join-Path $appDestino 'iniciar.pyw')`"" -WorkingDirectory $appDestino
}
