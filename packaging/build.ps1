<#
Builds Spotderpy for Windows:
  dist\Spotderpy\                         the app folder (PyInstaller one-folder build)
  dist\release\Spotderpy-<ver>-Setup.exe  installer (Inno Setup)
  dist\release\Spotderpy-<ver>-portable.zip

Usage (from the repo root):  powershell -ExecutionPolicy Bypass -File packaging\build.ps1 [-SkipTests] [-SkipInstaller]
Needs: Python 3.10+ (uses .venv if present), Inno Setup 6 for the installer.
#>
param([switch]$SkipTests, [switch]$SkipInstaller)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }
function Run([string]$exe, [string[]]$arguments) {
    & $exe @arguments
    if ($LASTEXITCODE -ne 0) { throw "'$exe $arguments' failed with exit code $LASTEXITCODE" }
}

Write-Host "== Installing build dependencies" -ForegroundColor Cyan
Run $Python @("-m", "pip", "install", "--quiet", "--upgrade", "pip")
Run $Python @("-m", "pip", "install", "--quiet", "--upgrade", "-e", ".[dev]", "yt-dlp")

$Version = (& $Python -c "import spotderpy; print(spotderpy.__version__)").Trim()
Write-Host "== Building Spotderpy $Version" -ForegroundColor Cyan

if (-not $SkipTests) {
    Write-Host "== Running tests" -ForegroundColor Cyan
    Run $Python @("-m", "pytest", "-q")
}

Write-Host "== Collecting third-party licenses" -ForegroundColor Cyan
Run $Python @("scripts\collect_licenses.py")

Write-Host "== Writing version info" -ForegroundColor Cyan
New-Item -ItemType Directory -Force build | Out-Null
$parts = ($Version -split "[.-]")[0..2] + @("0") | ForEach-Object { [int]($_ -replace "\D", "0") }
$tuple = ($parts[0..3] -join ", ")
@"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($tuple), prodvers=($tuple), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Spotderpy'),
      StringStruct('FileDescription', 'Spotderpy'),
      StringStruct('FileVersion', '$Version'),
      StringStruct('InternalName', 'Spotderpy'),
      StringStruct('LegalCopyright', 'MIT License'),
      StringStruct('OriginalFilename', 'Spotderpy.exe'),
      StringStruct('ProductName', 'Spotderpy'),
      StringStruct('ProductVersion', '$Version')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"@ | Set-Content -Encoding utf8 build\version_info.txt

Write-Host "== Running PyInstaller" -ForegroundColor Cyan
Run $Python @("-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", "dist", "--workpath", "build\pyinstaller", "packaging\spotderpy.spec")

$Release = "dist\release"
New-Item -ItemType Directory -Force $Release | Out-Null
Get-ChildItem $Release -Filter "Spotderpy-*" -ErrorAction SilentlyContinue | Remove-Item -Force

Write-Host "== Creating portable zip" -ForegroundColor Cyan
$Zip = Join-Path $Release "Spotderpy-$Version-portable.zip"
Compress-Archive -Path "dist\Spotderpy" -DestinationPath $Zip -CompressionLevel Optimal

if (-not $SkipInstaller) {
    Write-Host "== Building installer" -ForegroundColor Cyan
    $Iscc = @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $Iscc) { throw "Inno Setup 6 not found. Install it (winget install JRSoftware.InnoSetup) or pass -SkipInstaller." }
    Run $Iscc @("/Qp", "/DAppVersion=$Version", "packaging\installer.iss")
}

Write-Host "== Done" -ForegroundColor Green
Get-ChildItem $Release | ForEach-Object { "{0,-40} {1,8:N1} MB" -f $_.Name, ($_.Length / 1MB) }
