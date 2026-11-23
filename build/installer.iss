; DowFlow per-edition installer.
;
; build_export.py invokes ISCC with /D overrides:
;   /DAppName=DowFlow Video /DAppExe=DowFlow-Video.exe
;   /DSourceDir=<repo>\build\out\DowFlow-Video
;   /DDestDir=submenus\video /DOutputBase=DowFlow-Video-Setup
;   /DOutputDir=%USERPROFILE%\Downloads /DToolsDir=<repo>\build\tools
;   /DIconFile=<repo>\static\dowflow.ico /DAppId=DowFlow.Video

#ifndef AppName
  #define AppName "DowFlow"
#endif
#ifndef AppExe
  #define AppExe "DowFlow.exe"
#endif
#ifndef SourceDir
  #define SourceDir "..\build\out\DowFlow"
#endif
#ifndef DestDir
  #define DestDir "menu"
#endif
#ifndef OutputBase
  #define OutputBase "DowFlow-Setup"
#endif
#ifndef OutputDir
  #define OutputDir "..\..\..\Downloads"
#endif
#ifndef ToolsDir
  #define ToolsDir "..\build\tools"
#endif
#ifndef IconFile
  #define IconFile "..\static\dowflow.ico"
#endif
#ifndef AppId
  #define AppId "DowFlow.Menu"
#endif
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=DowFlow
DefaultDirName={localappdata}\DowFlow
DefaultGroupName=DowFlow
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBase}
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\{#DestDir}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
; Every edition installs into the same %LOCALAPPDATA%\DowFlow root (its own
; submenus\<edition> folder plus the shared data\ folder). Inno Setup's
; "folder already exists" prompt therefore appeared on the second edition and
; made it look like a second install of the same app; installing there is
; the normal case for this layout.
DirExistsWarning=no
MinVersion=10.0

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The runnable application for this edition.
Source: "{#SourceDir}\*"; DestDir: "{app}\{#DestDir}"; Flags: ignoreversion recursesubdirs createallsubdirs
; The whole-menu setup also installs DowFlow Music (Liner) in its own submenu,
; so one download brings the menu and the Music app the Music card opens.
#ifdef LinerDir
Source: "{#LinerDir}\*"; DestDir: "{app}\submenus\music"; Flags: ignoreversion recursesubdirs createallsubdirs
#endif
; Shared native tools, installed once for every edition and never removed by
; an edition's uninstaller.
Source: "{#ToolsDir}\ffmpeg\*"; DestDir: "{app}\data\tools\ffmpeg"; Flags: ignoreversion recursesubdirs createallsubdirs onlyifdoesntexist uninsneveruninstall
Source: "{#ToolsDir}\node\*"; DestDir: "{app}\data\tools\node"; Flags: ignoreversion recursesubdirs createallsubdirs onlyifdoesntexist uninsneveruninstall
Source: "{#ToolsDir}\chromium\*"; DestDir: "{app}\data\tools\chromium"; Flags: ignoreversion recursesubdirs createallsubdirs onlyifdoesntexist uninsneveruninstall
Source: "{#ToolsDir}\webview2\*"; DestDir: "{app}\data\tools\webview2"; Flags: ignoreversion recursesubdirs createallsubdirs onlyifdoesntexist uninsneveruninstall
Source: "{#ToolsDir}\.tools.ready"; DestDir: "{app}\data\tools"; Flags: ignoreversion onlyifdoesntexist uninsneveruninstall

[Dirs]
; The shared data folder holds config.json, dowflow.db, logs and tools.
; Keep it on uninstall so downloads, history and settings survive.
Name: "{app}\data"; Flags: uninsneveruninstall
Name: "{app}\data\tools"; Flags: uninsneveruninstall

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#DestDir}\{#AppExe}"; WorkingDir: "{app}\{#DestDir}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#DestDir}\{#AppExe}"; WorkingDir: "{app}\{#DestDir}"; Tasks: desktopicon

[Registry]
; config.py reads DataRoot so every edition (menu and submenus) shares the
; same configuration, database, logs and native tools.
Root: HKCU; Subkey: "Software\DowFlow"; ValueType: string; ValueName: "DataRoot"; ValueData: "{app}\data"

[Run]
Filename: "{app}\{#DestDir}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
function WebView2Installed(): Boolean;
var
  Version: String;
begin
  Result :=
    RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) or
    RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) or
    RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  Bootstrapper: String;
begin
  if CurStep = ssPostInstall then
  begin
    if not WebView2Installed() then
    begin
      Bootstrapper := ExpandConstant('{app}\data\tools\webview2\MicrosoftEdgeWebview2Setup.exe');
      if FileExists(Bootstrapper) then
      begin
        Exec(Bootstrapper, '/silent /install', '', SW_SHOW, ewWaitUntilTerminated, ResultCode);
      end
      else
      begin
        MsgBox('Microsoft Edge WebView2 Runtime is required to open the DowFlow window.' + #13#10 +
               'Install it from https://developer.microsoft.com/microsoft-edge/webview2/ and start DowFlow again.',
               mbInformation, MB_OK);
      end;
    end;
  end;
end;
