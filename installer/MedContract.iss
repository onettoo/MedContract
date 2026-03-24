; Inno Setup script for MedContract
; Build with:
;   ISCC.exe /DMyAppVersion=2.0.0 /DMySourceDir="C:\repo\dist\MedContract" /DMyOutputDir="C:\repo\releases" installer\MedContract.iss

#ifndef MyAppName
  #define MyAppName "MedContract"
#endif

#ifndef MyAppVersion
  #define MyAppVersion "2.0.0"
#endif

#ifndef MyAppPublisher
  #define MyAppPublisher "MedContract"
#endif

#ifndef MyAppExeName
  #define MyAppExeName "MedContract.exe"
#endif

#ifndef MySourceDir
  #define MySourceDir "..\dist\MedContract"
#endif

#ifndef MyOutputDir
  #define MyOutputDir "..\releases"
#endif

#ifndef MyOutputBaseFilename
  #define MyOutputBaseFilename "MedContract-Setup"
#endif

[Setup]
AppId={{98A7626A-DA0D-4A30-AEBF-3BA14D86C36A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#MyOutputDir}
OutputBaseFilename={#MyOutputBaseFilename}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na area de trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "{#MySourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion; Excludes: "_internal\database\backups\*;_internal\**\__pycache__\*;_internal\**\*.pyc;**\__pycache__\*;**\*.pyc"

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; WorkingDir: "{app}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir {#MyAppName}"; Flags: nowait postinstall skipifsilent
