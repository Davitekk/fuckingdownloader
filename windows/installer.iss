#define AppVersion GetEnv("FDL_VERSION")
#if AppVersion == ""
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId=FuckinDownloader.Windows
AppName=FuckinDownloader
AppVersion={#AppVersion}
AppPublisher=FuckinDownloader contributors
AppPublisherURL=https://github.com/Davitekk/fuckingdownloader
DefaultDirName={localappdata}\Programs\FuckinDownloader
DefaultGroupName=FuckinDownloader
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
UninstallDisplayIcon={app}\fuckindownloader.exe
LicenseFile=..\LICENSE
OutputDir=dist
OutputBaseFilename=FuckinDownloader-Setup-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "target\release\fuckindownloader.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

Source: "..\browser-extension\manifest.json"; DestDir: "{app}\browser-extension"; Flags: ignoreversion
Source: "..\browser-extension\popup.html"; DestDir: "{app}\browser-extension"; Flags: ignoreversion
Source: "..\browser-extension\popup.css"; DestDir: "{app}\browser-extension"; Flags: ignoreversion
Source: "..\browser-extension\popup.mjs"; DestDir: "{app}\browser-extension"; Flags: ignoreversion
Source: "..\browser-extension\cookies.mjs"; DestDir: "{app}\browser-extension"; Flags: ignoreversion
Source: "..\browser-extension\README.md"; DestDir: "{app}\browser-extension"; Flags: ignoreversion

[Icons]
Name: "{userprograms}\FuckinDownloader"; Filename: "{app}\fuckindownloader.exe"

[Run]
Filename: "{app}\fuckindownloader.exe"; Description: "Open FuckinDownloader"; Flags: nowait postinstall skipifsilent
