$ErrorActionPreference = "Stop"
$AppRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $AppRoot "..\..")).Path
$VenvRoot = Join-Path $AppRoot ".venv"
$VenvPython = Join-Path $VenvRoot "Scripts\python.exe"
$ProjectPython = Join-Path $ProjectRoot ".cache\t10-ocr-venv\Scripts\python.exe"
$Python = $null

function Test-AppRuntime {
    param([string]$Candidate)
    if (-not $Candidate -or -not (Test-Path -LiteralPath $Candidate)) {
        return $false
    }
    try {
        & $Candidate -c "import sys; import PIL; assert sys.version_info >= (3, 11)" 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

if (Test-AppRuntime $VenvPython) {
    $Python = $VenvPython
}
elseif (Test-AppRuntime $ProjectPython) {
    $Python = $ProjectPython
    Write-Host "Using the project's existing Python environment: $ProjectPython"
}
else {
    $BootstrapPython = $null

    if (Test-Path -LiteralPath $ProjectPython) {
        $BootstrapPython = $ProjectPython
    }

    if (-not $BootstrapPython) {
        $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if ($PythonCommand -and $PythonCommand.Source -notlike "*WindowsApps*") {
            $BootstrapPython = $PythonCommand.Source
        }
    }

    if (-not $BootstrapPython) {
        foreach ($Version in @("3.13", "3.12", "3.11")) {
            try {
                $DetectedPython = & py "-$Version" -c "import sys; print(sys.executable)" 2>$null
                if ($LASTEXITCODE -eq 0) {
                    $BootstrapPython = $DetectedPython.Trim()
                    break
                }
            }
            catch {
                continue
            }
        }
    }

    if (-not $BootstrapPython) {
        throw "Python 3.11 or newer was not found. Install Python and run run.ps1 again."
    }

    $VersionText = & $BootstrapPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    $VersionParts = $VersionText.Trim().Split(".")
    if ([int]$VersionParts[0] -lt 3 -or ([int]$VersionParts[0] -eq 3 -and [int]$VersionParts[1] -lt 11)) {
        throw "Python $VersionText is not supported; Python 3.11 or newer is required."
    }

    Write-Host "Creating a Python environment with $BootstrapPython (Python $VersionText)..."
    & $BootstrapPython -m venv $VenvRoot
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $VenvPython)) {
        throw "Could not create a Python environment at $VenvRoot."
    }

    Write-Host "Installing application dependencies..."
    & $VenvPython -m pip install -r (Join-Path $AppRoot "requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency installation failed. Check the network connection and run run.ps1 again."
    }
    $Python = $VenvPython
}

& $Python (Join-Path $AppRoot "server.py")
