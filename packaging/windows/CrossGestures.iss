; CrossGestures per-user Windows installer
#define ScriptDir ExtractFilePath(__PATHFILENAME__)
#define RepoRoot ScriptDir + "..\.."
#define BuildDir RepoRoot + "\WGestures.App\bin\Release"
#define AppExe BuildDir + "\CrossGestures.exe"

#ifnexist AppExe
  #error "Build the CrossGestures Windows application in Release mode before compiling the installer."
#endif

#define AppVersion GetVersionNumbersString(AppExe)

[Setup]
AppId={{1B31E2EC-F8C5-447E-81DD-AEB121781308}
AppName=CrossGestures
AppVersion={#AppVersion}
AppPublisher=YingDev contributors
AppPublisherURL=https://github.com/jtl520/WGestures-Linux
AppSupportURL=https://github.com/jtl520/WGestures-Linux/issues
AppUpdatesURL=https://github.com/jtl520/WGestures-Linux/releases/latest
DefaultDirName={localappdata}\Programs\CrossGestures
DefaultGroupName=CrossGestures
DisableProgramGroupPage=yes
LicenseFile={#RepoRoot}\LICENSE
OutputDir={#RepoRoot}\build\windows
OutputBaseFilename=CrossGestures-{#AppVersion}-Windows-Setup
SetupIconFile={#RepoRoot}\WGestures.App\Resources\icon.ico
UninstallDisplayIcon={app}\CrossGestures.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
MinVersion=6.1sp1
CloseApplications=yes
RestartApplications=no
AppMutex=com.jtl520.CrossGestures

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式："; Flags: unchecked

[Files]
Source: "{#BuildDir}\*"; DestDir: "{app}"; Excludes: "WGestures.exe,WGestures.exe.config,*.pdb,*.xml"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: files; Name: "{app}\WGestures.exe"
Type: files; Name: "{app}\WGestures.exe.config"

[UninstallDelete]
Type: files; Name: "{userstartup}\com.jtl520.CrossGestures.lnk"

[Icons]
Name: "{group}\CrossGestures 设置"; Filename: "{app}\CrossGestures.exe"; Parameters: "--settings"; WorkingDir: "{app}"
Name: "{group}\卸载 CrossGestures"; Filename: "{uninstallexe}"
Name: "{autodesktop}\CrossGestures"; Filename: "{app}\CrossGestures.exe"; Parameters: "--settings"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\CrossGestures.exe"; Parameters: "--settings"; Description: "启动 CrossGestures 并打开设置"; Flags: nowait postinstall skipifsilent

[Code]
function IsDotNet48Installed(): Boolean;
var
  Release: Cardinal;
begin
  Result :=
    (RegQueryDWordValue(HKLM64,
      'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full',
      'Release', Release) and (Release >= 528040)) or
    (RegQueryDWordValue(HKLM32,
      'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full',
      'Release', Release) and (Release >= 528040));
end;

function InitializeSetup(): Boolean;
var
  ErrorCode: Integer;
begin
  Result := IsDotNet48Installed();
  if Result then
    exit;

  MsgBox('CrossGestures 需要 Microsoft .NET Framework 4.8。安装完成后请重新运行本安装程序。',
    mbInformation, MB_OK);
  ShellExec('open',
    'https://dotnet.microsoft.com/download/dotnet-framework/net48',
    '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
end;
