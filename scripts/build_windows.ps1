# Build the Windows application with PyInstaller.
#
# PyInstaller cannot cross-compile: run this on Windows 10/11 with the project
# environment already created (Python 3.13 + PySide6 + mediapipe).
#
#   py -3.13 -m venv .venv
#   .\.venv\Scripts\python.exe -m pip install -e ".[test]"
#   pyinstaller --version      # must be installed for this step
#   pwsh .\scripts\build_windows.ps1
#
# Output: dist\PinchCursor\PinchCursor.exe (onedir, no console window).

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$Python = if ($env:PYTHON) { $env:PYTHON } else { Join-Path $Root ".venv\Scripts\python.exe" }

if (-not (Test-Path $Python)) {
    Write-Error "Project environment is missing: $Python`nCreate it with:`n  py -3.13 -m venv .venv`n  .\.venv\Scripts\python.exe -m pip install -e '.[test]' 'pyinstaller==6.22.3'"
}

if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }

# The shared spec owns the module list, Qt excludes, and data files.
$env:PYTHONPATH = ""
& $Python -m PyInstaller --noconfirm --clean "PinchCursor.spec"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$ExePath = Join-Path $Root "dist\PinchCursor\PinchCursor.exe"
if (-not (Test-Path $ExePath)) {
    Write-Error "Build failed: $ExePath was not produced."
}

Write-Host "Built: $ExePath"
