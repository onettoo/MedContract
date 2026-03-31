<h1 align="center">
  <img src="assets/logo.png" alt="MedContract" width="180"/>
  <br/>
  MedContract
</h1>

<p align="center">
  Sistema desktop para gestão de contratos e pagamentos de clientes em clínicas médicas.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-blue?style=flat-square&logo=python" />
  <img src="https://img.shields.io/badge/PySide6-Qt-green?style=flat-square&logo=qt" />
  <img src="https://img.shields.io/badge/SQLite-banco%20local-lightgrey?style=flat-square&logo=sqlite" />
  <img src="https://img.shields.io/badge/status-ativo-brightgreen?style=flat-square" />
</p>

---

## 🇧🇷 Sobre o projeto

O **MedContract** é um sistema de gestão voltado para clínicas que trabalham com contratos ou mensalidades.

Ele permite registrar clientes, gerenciar dependentes, acompanhar pagamentos e visualizar informações importantes através de um dashboard centralizado — substituindo planilhas e controles manuais por uma solução simples, organizada e visual.

## 🇺🇸 About the project

**MedContract** is a desktop application designed to help clinics manage client contracts and monthly payments.

The system centralizes client records, payment tracking and financial indicators in a single dashboard, replacing spreadsheets and manual processes with a more efficient workflow.

---

## ✨ Funcionalidades

### 👤 Gestão de Clientes
- Cadastro, edição e exclusão de clientes
- Busca por nome ou CPF
- Controle de status (ativo / inativo)
- Cadastro de dependentes vinculados ao cliente

### 💳 Pagamentos
- Registro de pagamentos mensais por mês de referência
- Atualização automática do status de pagamento
- Identificação de clientes em atraso

### 📊 Dashboard
- Total de clientes ativos
- Receita mensal e estimativa de inadimplência
- Pagamentos realizados no mês
- Contratos fechados no mês
- Gráfico de receita mensal

### 📁 Exportação de Dados
- Exportação de clientes, inadimplentes e pagamentos do mês
- Arquivos gerados em planilha

### 🔒 Segurança
- Sistema de login com níveis de acesso
- Senhas criptografadas com `bcrypt`
- Preflight de segurança na inicialização

### 💾 Backup
- Backup automático do banco de dados
- Armazenamento em pasta do usuário

---

## 🛠️ Tecnologias

| Tecnologia | Uso |
|---|---|
| Python 3.11+ | Linguagem principal |
| PySide6 (Qt) | Interface gráfica |
| SQLite | Banco de dados local |
| bcrypt | Criptografia de senhas |
| PyInstaller | Geração do executável |

---

## 🚀 Como executar

### Pré-requisitos
- Python 3.11+
- pip

### Instalação

```bash
# Clone o repositório
git clone https://github.com/onettoo/MedContract.git
cd MedContract

# Instale as dependências
pip install -r requirements.txt

# Configure o ambiente
cp .env.example .env
# Edite o .env com suas configurações

# Execute o sistema
python main.py
```

---

## ⚙️ Configuração

Copie o arquivo `.env.example` para `.env` e preencha as variáveis:

```env
MEDCONTRACT_DEFAULT_ADMIN_USER=admin
MEDCONTRACT_DEFAULT_ADMIN_PASSWORD=sua_senha_forte
MEDCONTRACT_SMTP_USER=seu_email@gmail.com
MEDCONTRACT_SMTP_PASSWORD=sua_senha_de_app
```

> ⚠️ Nunca suba o arquivo `.env` para o repositório.

---

## 📄 Licença

Este projeto é de uso privado. Todos os direitos reservados.
