; Instalador .exe del Editor Vertical · El Chapucero (Inno Setup 6, gratis: https://jrsoftware.org/isdl.php)
; Para crear el .exe: abre este archivo con Inno Setup y presiona "Compile" (Ctrl+F9).
; El .exe resultante queda en la carpeta "Output" y es lo único que hay que pasar a las otras PCs.
; Al cambiar de versión, cambia también app\version.txt.

#define Version "1.1.4"

[Setup]
AppId={{5B7E2A61-3C1D-4F7A-9E2B-8D4C6A1F0E37}
AppName=Editor Vertical · El Chapucero
AppVersion={#Version}
AppPublisher=El Chapucero
DefaultDirName={localappdata}\EditorVertical\instalador
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputBaseFilename=Instalar_Editor_Vertical_{#Version}
SetupIconFile=app\icono.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
Uninstallable=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Files]
Source: "app\*"; DestDir: "{app}\app"; Flags: recursesubdirs ignoreversion; Excludes: "__pycache__\*,*.pyc,registro.log,aprendizaje\*"
Source: "instalar.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "desinstalar.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "cerrar.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Run]
; la instalación real (detecta la tarjeta, descarga e instala todo) se hace en una ventana con el avance
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\instalar.ps1"" -Origen ""{app}"""; \
  StatusMsg: "Instalando (se abrirá una ventana con el avance)..."; Flags: waituntilterminated
