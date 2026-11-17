# Desinstala el Editor Vertical · El Chapucero (no borra las carpetas «VideosEdit» ni «Renders» ni Ollama, salvo que lo pidas)
$ErrorActionPreference = "Continue"
$Datos = Join-Path $env:LOCALAPPDATA "EditorVertical"
Add-Type -AssemblyName System.Windows.Forms
$r = [System.Windows.Forms.MessageBox]::Show("¿Quitar el Editor Vertical de esta computadora?`n`nTus carpetas «VideosEdit» y «Renders» del escritorio no se borran.", "Editor Vertical · El Chapucero", "YesNo", "Question")
if ($r -ne "Yes") { exit 0 }
# cerrar la plataforma si está abierta
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe' OR Name='ffmpeg.exe'" |
    Where-Object { $_.CommandLine -match "EditorVertical" -or $_.ExecutablePath -match "EditorVertical" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 1
$menu = [Environment]::GetFolderPath("Programs")
Remove-Item (Join-Path ([Environment]::GetFolderPath("Desktop")) "Editor Vertical.lnk") -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $menu "Editor Vertical.lnk") -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $menu "Cerrar Editor Vertical.lnk") -Force -ErrorAction SilentlyContinue
Remove-Item "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\EditorVerticalChapucero" -Recurse -Force -ErrorAction SilentlyContinue
$q = [System.Windows.Forms.MessageBox]::Show("¿Quitar también Ollama y sus modelos? (Elige No si otra aplicación lo usa, por ejemplo el Subtitulador)", "Editor Vertical · El Chapucero", "YesNo", "Question")
if ($q -eq "Yes") {
    $u = Get-ChildItem "$env:LOCALAPPDATA\Programs\Ollama" -Filter "unins*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($u) { Start-Process $u.FullName -ArgumentList "/VERYSILENT" -Wait }
}
# se borra a sí mismo al final
Start-Process "$env:SystemRoot\System32\cmd.exe" -ArgumentList "/c timeout /t 2 >nul & rmdir /s /q `"$Datos`"" -WindowStyle Hidden
[System.Windows.Forms.MessageBox]::Show("Listo, el Editor Vertical se quitó.", "Editor Vertical · El Chapucero") | Out-Null
