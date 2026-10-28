#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#ifndef SourceRoot
  #define SourceRoot ".."
#endif
#ifndef BundleRoot
  #define BundleRoot SourceRoot + "\dist"
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
OutputDir={#BundleRoot}\installers
OutputBaseFilename=CanvasBridgeDemo-Windows-x64-Setup
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
#ifdef SignedRelease
SignTool=bridge-sign
SignedUninstaller=yes
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
WelcomeLabel1=Set up Canvas Bridge on your computer
WelcomeLabel2=Choose offline academic tools or a synthetic demonstration after installation. Python and terminal commands are not needed.%n%nInstitution access requires an independently approved hosted service. This installer cannot enable it. Upgrades preserve your separate data; uninstall offers an explicit removal option.

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#BundleRoot}\CanvasBridgeDemo\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Canvas Bridge Demo"; Filename: "{app}\CanvasBridgeDemo.exe"
Name: "{autodesktop}\Canvas Bridge Demo"; Filename: "{app}\CanvasBridgeDemo.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\CanvasBridgeDemo.exe"; Description: "Open Canvas Bridge Demo"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\CanvasBridgeDemo.exe"; Parameters: "--uninstall-data"; RunOnceId: "ReviewLocalData"; Check: OfferLocalDataRemoval

; Silent uninstall and updates preserve data. The native dialog defaults to keeping it.

[Code]
function OfferLocalDataRemoval: Boolean;
begin
  Result := not UninstallSilent;
end;
