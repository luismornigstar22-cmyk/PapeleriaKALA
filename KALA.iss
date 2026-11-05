; Coloca este archivo en la raiz de PapeleriaKALA, junto a iniciar_kala.py.
; Compila con Inno Setup 6.3 o posterior, despues de generar dist\KALA.
#define AppVersion "1.0.0"
#if !FileExists(SourcePath + "dist\KALA\KALA.exe")
  #error No se encontro dist\KALA\KALA.exe. Coloca KALA.iss en la raiz del proyecto y genera primero el ejecutable.
#endif

[Setup]
AppId={{CCF3FB6A-EFE6-4D7A-90C5-1C0139153EBC}
AppName=Papelería KALA
AppVersion={#AppVersion}
AppPublisher=Papelería KALA
DefaultDirName={localappdata}\Programs\PapeleriaKALA
DefaultGroupName=Papelería KALA
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
MinVersion=10.0
OutputDir=instalador_salida
OutputBaseFilename=Instalar_KALA_{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\KALA.exe
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
InfoBeforeFile=ANTES_DE_INSTALAR.txt

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"

[Files]
; Incluye todo el resultado de PyInstaller, sin copiar el proyecto ni sus secretos.
Source: "dist\KALA\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "ANTES_DE_INSTALAR.txt"; DestDir: "{app}"

[Icons]
Name: "{group}\Papelería KALA"; Filename: "{app}\KALA.exe"; WorkingDir: "{app}"
Name: "{userdesktop}\Papelería KALA"; Filename: "{app}\KALA.exe"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{group}\Información de instalación"; Filename: "{app}\ANTES_DE_INSTALAR.txt"

[Run]
Filename: "{app}\KALA.exe"; WorkingDir: "{app}"; Description: "Abrir KALA (requiere la base local configurada)"; Flags: nowait postinstall skipifsilent unchecked

; No borrar bases, respaldos ni credenciales al desinstalar.
; No ejecutar SQL ni reinstalar PostgreSQL en las actualizaciones.
