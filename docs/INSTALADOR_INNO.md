# Instalador sem certificado (Inno Setup)

## O que este fluxo faz

- Empacota a pasta `dist\MedContract` em um instalador `.exe`.
- Nao exige certificado digital.
- Instala em `{localappdata}\MedContract` (sem exigir admin por padrao).

## Pre-requisitos

- Inno Setup 6 instalado (ISCC.exe)
- Build da aplicacao pronto em `dist\MedContract`

## 1) Gerar build da aplicacao (se ainda nao gerou)

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_signed_exe.ps1 -CleanBuild -SkipSign -SkipZip
```

## 2) Gerar instalador

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_installer.ps1
```

Observacao: por padrao, o script executa os testes de validacao backend antes de empacotar.

Opcional: gerar build + instalador em uma vez:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_installer.ps1 -BuildAppFirst
```

Para pular os testes (nao recomendado):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_installer.ps1 -SkipTests
```

## 3) Configuracao de ambiente (seguranca)

Por seguranca, o instalador nao embute mais credenciais de banco/SMTP.

Depois da instalacao:

1. Crie um arquivo `.env` no diretorio do aplicativo instalado.
2. Preencha as variaveis com base no `.env.example`.
3. Nunca distribua esse `.env` junto com o instalador.

## Saida

- Instalador em `releases\MedContract-Setup-<versao>-<data>.exe`

## Arquivos envolvidos

- Script Inno: `installer\MedContract.iss`
- Automacao PowerShell: `scripts\build_installer.ps1`
