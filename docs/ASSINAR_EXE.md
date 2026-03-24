# Assinatura digital do EXE (Windows)

Este projeto tem um script pronto para build e assinatura:

`scripts/build_signed_exe.ps1`

Por padrao, o script executa os testes de validacao backend antes do build.

## Pre-requisitos

- Windows 10/11
- Python do projeto (venv recomendado)
- `pyinstaller` instalado no ambiente
- Certificado de Code Signing (PFX ou no repositorio de certificados do Windows)
- `signtool.exe` (Windows SDK: Signing Tools for Desktop Apps)

## Opcao A: certificado PFX

1. Defina variaveis de ambiente no PowerShell:

```powershell
$env:MEDCONTRACT_SIGN_PFX = "C:\certs\empresa-codesign.pfx"
$env:MEDCONTRACT_SIGN_PFX_PASSWORD = "SUA_SENHA_AQUI"
```

2. Rode o script:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_signed_exe.ps1 -CleanBuild -SignAllBinaries
```

## Opcao B: certificado ja instalado no Windows (thumbprint)

1. Defina o thumbprint:

```powershell
$env:MEDCONTRACT_SIGN_CERT_THUMBPRINT = "SEU_THUMBPRINT_AQUI"
```

2. Rode o script:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_signed_exe.ps1 -CleanBuild -SignAllBinaries
```

Se o certificado estiver no repositorio da maquina local (`LocalMachine\My`), acrescente:

```powershell
-UseMachineStore
```

## Saidas

- EXE/folder: `dist\`
- Pacote de entrega: `releases\MedContract-YYYYMMDD-HHmm-signed.zip`

## Teste sem assinatura (somente validar build)

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_signed_exe.ps1 -CleanBuild -SkipSign
```

Para pular os testes (nao recomendado), acrescente:

```powershell
-SkipTests
```

## Validar assinatura manualmente

```powershell
Get-AuthenticodeSignature .\dist\MedContract\MedContract.exe | Format-List Status,SignerCertificate,TimeStamperCertificate
```
