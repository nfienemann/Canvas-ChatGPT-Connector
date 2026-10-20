#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#ifndef SourceRoot
  #define SourceRoot ".."
#endif

[Setup]
AppId={{CC5239F2-80A3-4616-84EC-67C2A8AA384A}
AppName=Canvas Bridge Demo
AppVersion={#AppVersion}
AppPublisher=Canvas Bridge project
AppPublisherURL=https://github.com/nfienemann/Canvas-ChatGPT-Connector
DefaultDirName={localappdata}\Programs\Canvas Bridge Demo
DefaultGroupName=Canvas Bridge Demo
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
DisableProgramGroupPage=yes
DisableWelcomePage=no
UninstallDisplayIcon={app}\CanvasBridgeDemo.exe
SetupIconFile={#SourceRoot}\build\icons\canvas-bridge.ico
OutputDir={#SourceRoot}\dist\installers
OutputBaseFilename=CanvasBridgeDemo-Windows-x64-Setup
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
WelcomeLabel1=Try Canvas Bridge on your computer
WelcomeLabel2=This installs the local demo with fictional courses. Python and terminal commands are not needed.%n%nThis preview does not connect to a real university or ChatGPT. Your demo data stays in your user account and is kept when you upgrade or uninstall.

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#SourceRoot}\dist\CanvasBridgeDemo\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Canvas Bridge Demo"; Filename: "{app}\CanvasBridgeDemo.exe"
Name: "{autodesktop}\Canvas Bridge Demo"; Filename: "{app}\CanvasBridgeDemo.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\CanvasBridgeDemo.exe"; Description: "Open Canvas Bridge Demo"; Flags: nowait postinstall skipifsilent

; Never remove the user's separate data directory during upgrades or uninstall.
