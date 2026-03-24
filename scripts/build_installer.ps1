[CmdletBinding()]
param(
    [string]$AppName = "MedContract",
    [string]$AppVersion = "",
    [string]$AppPublisher = "MedContract",
    [string]$AppExeName = "MedContract.exe",
    [string]$PythonExe = ".\venv\Scripts\python.exe",
    [switch]$SkipTests,
    [string]$DistDir = ".\dist\MedContract",
    [string]$InstallerScript = ".\installer\MedContract.iss",
    [string]$OutputDir = ".\releases",
    [string]$OutputBaseFilename = "",
    [string]$DatabaseUrl = "",
    [switch]$EmbedDatabaseConfig,
    [switch]$BuildAppFirst
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Resolve-ExistingPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Resolve-Path -Path $Path).Path
}

function Get-InnoCompilerPath {
    $iscc = Get-Command iscc.exe -ErrorAction SilentlyContinue
    if ($iscc) {
        return $iscc.Source
    }

    $candidates = @(
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Inno Setup 6\ISCC.exe"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    return $null
}

function Read-AppVersionFromCode {
    param([Parameter(Mandatory = $true)][string]$RepoRoot)

    $mainWindowPath = Join-Path -Path $RepoRoot -ChildPath "main_window.py"
    if (-not (Test-Path $mainWindowPath)) {
        return ""
    }

    try {
        $line = Select-String -Path $mainWindowPath -Pattern 'APP_VERSION\s*=\s*"([^"]+)"' -CaseSensitive |
            Select-Object -First 1
        if ($line -and $line.Matches.Count -gt 0) {
            return [string]$line.Matches[0].Groups[1].Value
        }
    } catch {
    }

    return ""
}

function Resolve-PythonPath {
    param([string]$Candidate)
    if ($Candidate -and (Test-Path $Candidate)) {
        return (Resolve-Path -Path $Candidate).Path
    }
    $fallbackPython = Get-Command python -ErrorAction SilentlyContinue
    if ($fallbackPython) {
        return $fallbackPython.Source
    }
    return $null
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path

Push-Location $repoRoot
try {
    if (-not (Test-Path ".\main.py")) {
        throw "main.py nao encontrado. Execute este script dentro do repositorio."
    }
    $pythonPath = Resolve-PythonPath -Candidate $PythonExe

    if (-not $SkipTests) {
        if (-not $pythonPath) {
            throw "Python nao encontrado para executar testes. Use -PythonExe ou instale Python."
        }
        Write-Step "Executando testes de validacao backend"
        & $pythonPath -m unittest tests.test_validation_service -v
        if ($LASTEXITCODE -ne 0) {
            throw "Os testes falharam. Empacotamento cancelado."
        }
    } else {
        Write-Step "Testes ignorados (-SkipTests)"
    }

    if ($BuildAppFirst) {
        $buildScript = ".\scripts\build_signed_exe.ps1"
        if (-not (Test-Path $buildScript)) {
            throw "Script de build nao encontrado: $buildScript"
        }
        if (-not $pythonPath) {
            throw "Python nao encontrado para gerar o build. Use -PythonExe ou instale Python."
        }

        Write-Step "Gerando build da aplicacao (sem assinatura)"
        powershell -ExecutionPolicy Bypass -File $buildScript -CleanBuild -SkipSign -SkipZip -SkipTests -PythonExe $pythonPath
        if ($LASTEXITCODE -ne 0) {
            throw "Falha ao gerar build da aplicacao."
        }
    }

    if (-not (Test-Path $InstallerScript)) {
        throw "Arquivo de instalador nao encontrado: $InstallerScript"
    }
    if (-not (Test-Path $DistDir)) {
        throw "Pasta dist nao encontrada: $DistDir. Rode primeiro o build da aplicacao."
    }
    if (-not (Test-Path (Join-Path -Path $DistDir -ChildPath $AppExeName))) {
        throw "Executavel nao encontrado em: $(Join-Path -Path $DistDir -ChildPath $AppExeName)"
    }
    if (-not (Test-Path $OutputDir)) {
        New-Item -Path $OutputDir -ItemType Directory | Out-Null
    }

    if ([string]::IsNullOrWhiteSpace($AppVersion)) {
        $AppVersion = Read-AppVersionFromCode -RepoRoot $repoRoot
    }
    if ([string]::IsNullOrWhiteSpace($AppVersion)) {
        $AppVersion = "2.0.0"
    }

    if ([string]::IsNullOrWhiteSpace($OutputBaseFilename)) {
        $stamp = Get-Date -Format "yyyyMMdd-HHmm"
        $OutputBaseFilename = "$AppName-Setup-$AppVersion-$stamp"
    }

    if ($EmbedDatabaseConfig -or -not [string]::IsNullOrWhiteSpace($DatabaseUrl)) {
        throw "Por seguranca, o instalador nao permite mais embutir MEDCONTRACT_DATABASE_URL/SMTP. Configure o .env manualmente apos instalar."
    }

    $isccPath = Get-InnoCompilerPath
    if (-not $isccPath) {
        throw "ISCC.exe nao encontrado. Instale o Inno Setup 6 e rode novamente."
    }

    $distAbs = Resolve-ExistingPath -Path $DistDir
    $scriptAbs = Resolve-ExistingPath -Path $InstallerScript
    $outAbs = Resolve-ExistingPath -Path $OutputDir

    Write-Step "Compilando instalador com Inno Setup"
    Write-Host "ISCC: $isccPath"
    Write-Host "Script: $scriptAbs"
    Write-Host "Fonte: $distAbs"
    Write-Host "Saida: $outAbs"

    $args = @(
        "/DMyAppName=$AppName",
        "/DMyAppVersion=$AppVersion",
        "/DMyAppPublisher=$AppPublisher",
        "/DMyAppExeName=$AppExeName",
        "/DMySourceDir=$distAbs",
        "/DMyOutputDir=$outAbs",
        "/DMyOutputBaseFilename=$OutputBaseFilename"
    )
    $args += $scriptAbs

    & $isccPath @args
    if ($LASTEXITCODE -ne 0) {
        throw "ISCC retornou codigo $LASTEXITCODE."
    }

    $setupExe = Join-Path -Path $outAbs -ChildPath "$OutputBaseFilename.exe"
    if (Test-Path $setupExe) {
        Write-Host ""
        Write-Host "Instalador pronto: $setupExe" -ForegroundColor Green
    } else {
        Write-Host ""
        Write-Host "Compilacao concluida. Verifique a pasta de saida: $outAbs" -ForegroundColor Yellow
    }
} finally {
    Pop-Location
}
