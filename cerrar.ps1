# Cierra el Editor Vertical por completo (la plataforma y lo que esté procesando).
# La próxima vez que se abra, revisa si hay actualización en GitHub.
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe' OR Name='ffmpeg.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match "EditorVertical" -or $_.ExecutablePath -match "EditorVertical" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.MessageBox]::Show("El Editor Vertical se cerró.", "Editor Vertical · El Chapucero") | Out-Null
