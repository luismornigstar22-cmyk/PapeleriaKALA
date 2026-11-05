#define AppVersion "1.0.1"
#if !FileExists(SourcePath + "dist\KALA\KALA.exe")
  #error Falta dist\KALA\KALA.exe
#endif
#if !FileExists(SourcePath + "dist\Preparar_KALA\Preparar_KALA.exe")
  #error Ejecuta primero CREAR_INSTALADOR.cmd para generar el asistente de base nueva.
#endif
#if !FileExists(SourcePath + "prerrequisitos\postgresql-18-windows-x64.exe")
  #error Falta el instalador oficial de PostgreSQL indicado en LEEME_PRIMERO.md.
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
OutputBaseFilename=Instalar_KALA_Nueva_PC_{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\KALA.exe
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
InfoBeforeFile=INSTALACION_PC_NUEVA.txt
[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo a KALA en el escritorio"; GroupDescription: "Accesos directos:"
Name: "postgres"; Description: "Instalar PostgreSQL 18 (solo si esta PC todavía NO lo tiene)"; GroupDescription: "Primera instalación:"; Flags: unchecked
[Files]
Source: "dist\KALA\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "dist\Preparar_KALA\*"; DestDir: "{app}\Preparacion"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "INSTALACION_PC_NUEVA.txt"; DestDir: "{app}"
Source: "prerrequisitos\postgresql-18-windows-x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Tasks: postgres
[Icons]
Name: "{group}\Papelería KALA"; Filename: "{app}\KALA.exe"; WorkingDir: "{app}"
Name: "{userdesktop}\Papelería KALA"; Filename: "{app}\KALA.exe"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{group}\Preparar base nueva de KALA"; Filename: "{app}\Preparacion\Preparar_KALA.exe"; WorkingDir: "{app}\Preparacion"
Name: "{group}\Instrucciones de primera instalación"; Filename: "{app}\INSTALACION_PC_NUEVA.txt"
[Run]
; El asistente oficial pedirá elevación de Windows y la clave de postgres.
Filename: "{tmp}\postgresql-18-windows-x64.exe"; Flags: shellexec waituntilterminated skipifsilent; Tasks: postgres
Filename: "{app}\Preparacion\Preparar_KALA.exe"; WorkingDir: "{app}\Preparacion"; Description: "Preparar la base nueva (solo después de terminar PostgreSQL)"; Flags: postinstall nowait skipifsilent
; Sin SQL ni eliminación de datos en desinstalación.
