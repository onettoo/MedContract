[CmdletBinding()]
param(
    [string]$PythonExe = ".\venv\Scripts\python.exe",
    [string]$SpecFile = "MedContract.spec",
    [string]$AppName = "MedContract",
    [switch]$SkipTests,
    [switch]$CleanBuild,
    [switch]$SkipBuild,
    [switch]$SkipSign,
    [switch]$SignAllBinaries,
    [switch]$SkipZip,
    [string]$PfxPath = $env:MEDCONTRACT_SIGN_PFX,
    [string]$PfxPassword = $env:MEDCONTRACT_SIGN_PFX_PASSWORD,
    [string]$CertThumbprint = $env:MEDCONTRACT_SIGN_CERT_THUMBPRINT,
    [switch]$UseMachineStore,
    [string]$TimestampUrl = "https://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Get-SignToolPath {
    $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    $kit10x86 = "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe"
    $kit10x64 = "${env:ProgramFiles}\Windows Kits\10\bin\*\x64\signtool.exe"
    $kit11x86 = "${env:ProgramFiles(x86)}\Windows Kits\11\bin\*\x64\signtool.exe"
    $kit11x64 = "${env:ProgramFiles}\Windows Kits\11\bin\*\x64\signtool.exe"

    $patterns = @($kit10x86, $kit10x64, $kit11x86, $kit11x64)
    foreach ($pattern in $patterns) {
        $match = Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue |
            Sort-Object -Property FullName -Descending |
            Select-Object -First 1
        if ($match) {
            return $match.FullName
        }
    }

    return $null
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path

Push-Location $repoRoot
try {
    if (-not (Test-Path ".\main.py")) {
        throw "main.py nao encontrado. Execute este script dentro do repositorio do MedContract."
    }
    if (-not (Test-Path $SpecFile)) {
        throw "Arquivo de spec nao encontrado: $SpecFile"
    }

    if (-not (Test-Path $PythonExe)) {
        $fallbackPython = Get-Command python -ErrorAction SilentlyContinue
        if ($fallbackPython) {
            $PythonExe = $fallbackPython.Source
        } else {
            throw "Python nao encontrado. Ajuste -PythonExe ou ative o venv."
        }
    }

    if (-not $SkipTests) {
        Write-Step "Executando testes de validacao backend"
        & $PythonExe -m unittest tests.test_validation_service -v
        if ($LASTEXITCODE -ne 0) {
            throw "Os testes falharam. Build cancelado."
        }
    } else {
        Write-Step "Testes ignorados (-SkipTests)"
    }

    if (-not $SkipBuild) {
        Write-Step "Gerando build com PyInstaller"
        $buildArgs = @("-m", "PyInstaller", "--noconfirm")
        if ($CleanBuild) {
            $buildArgs += "--clean"
        }
        $buildArgs += $SpecFile

        & $PythonExe @buildArgs
        if ($LASTEXITCODE -ne 0) {
            throw "PyInstaller retornou codigo $LASTEXITCODE."
        }
    } else {
        Write-Step "Build ignorado (-SkipBuild)"
    }

    $exeCandidates = @(
        (Join-Path -Path $repoRoot -ChildPath "dist\$AppName\$AppName.exe")
        (Join-Path -Path $repoRoot -ChildPath "dist\$AppName.exe")
    ) | Where-Object { Test-Path $_ }

    $exeCandidates = @($exeCandidates)
    if ($exeCandidates.Count -eq 0) {
        throw "Nao encontrei o executavel final em dist\."
    }

    $mainExe = $exeCandidates[0]
    Write-Step "Executavel encontrado: $mainExe"

    if (-not $SkipSign) {
        if ([string]::IsNullOrWhiteSpace($PfxPath) -and [string]::IsNullOrWhiteSpace($CertThumbprint)) {
            throw "Assinatura habilitada, mas sem certificado. Informe -PfxPath (ou MEDCONTRACT_SIGN_PFX) ou -CertThumbprint."
        }

        $signtool = Get-SignToolPath
        if (-not $signtool) {
            throw "signtool.exe nao encontrado. Instale o Windows SDK (Signing Tools for Desktop Apps)."
        }

        $targets = @($mainExe)
        $mainExeDir = Split-Path -Parent $mainExe
        if ($SignAllBinaries -and (Test-Path $mainExeDir)) {
            $targets = Get-ChildItem -Path $mainExeDir -Recurse -File -Include *.exe, *.dll |
                Select-Object -ExpandProperty FullName |
                Sort-Object -Unique
        }

        Write-Step "Assinando arquivos ($($targets.Count))"

        foreach ($file in $targets) {
            if (-not (Test-Path $file)) {
                continue
            }

            $signArgs = @("sign", "/fd", "SHA256", "/td", "SHA256")
            if (-not [string]::IsNullOrWhiteSpace($TimestampUrl)) {
                $signArgs += @("/tr", $TimestampUrl)
            }

            if (-not [string]::IsNullOrWhiteSpace($PfxPath)) {
                if (-not (Test-Path $PfxPath)) {
                    throw "PFX nao encontrado: $PfxPath"
                }
                $signArgs += @("/f", $PfxPath)
                if (-not [string]::IsNullOrWhiteSpace($PfxPassword)) {
                    $signArgs += @("/p", $PfxPassword)
                }
            } else {
                $thumb = ($CertThumbprint -replace "\s", "").ToUpperInvariant()
                $signArgs += @("/sha1", $thumb)
                if ($UseMachineStore) {
                    $signArgs += "/sm"
                }
            }

            $signArgs += $file

            & $signtool @signArgs
            if ($LASTEXITCODE -ne 0) {
                throw "Falha ao assinar: $file"
            }

            & $signtool verify /pa /v $file
            if ($LASTEXITCODE -ne 0) {
                throw "Falha ao validar assinatura: $file"
            }
        }
    } else {
        Write-Step "Assinatura ignorada (-SkipSign)"
    }

    if (-not $SkipZip) {
        Write-Step "Gerando pacote zip de entrega"
        $releaseDir = Join-Path $repoRoot "releases"
        if (-not (Test-Path $releaseDir)) {
            New-Item -Path $releaseDir -ItemType Directory | Out-Null
        }

        $stamp = Get-Date -Format "yyyyMMdd-HHmm"
        $state = if ($SkipSign) { "unsigned" } else { "signed" }
        $zipName = "$AppName-$stamp-$state.zip"
        $zipPath = Join-Path $releaseDir $zipName
        if (Test-Path $zipPath) {
            Remove-Item -Force $zipPath
        }

        $appFolder = Join-Path $repoRoot "dist\$AppName"
        if (Test-Path $appFolder) {
            Compress-Archive -Path "$appFolder\*" -DestinationPath $zipPath -Force
        } else {
            Compress-Archive -Path $mainExe -DestinationPath $zipPath -Force
        }

        Write-Host "Pacote pronto: $zipPath" -ForegroundColor Green
    } else {
        Write-Step "Zip ignorado (-SkipZip)"
    }

    Write-Host ""
    Write-Host "Processo concluido com sucesso." -ForegroundColor Green
} finally {
    Pop-Location
}
