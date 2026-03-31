# Runbook Operacional - MedContract

## 1) Checklist de startup
1. Confirmar `.env.local` com `DATABASE_URL` e `sslmode=require`.
2. Iniciar app.
3. Verificar log de inicialização:
- banco inicializado
- normalização diária de `mes_referencia` (executada ou `already_ran_today`).

## 2) Verificação de status de pagamento
Regra:
- `em_dia`: existe pagamento no mês atual.
- `em_atraso`: não pagou no mês e vencimento já passou.
- `pendente`: não pagou no mês e vencimento ainda não chegou.

Validação rápida:
1. Abrir dashboard e listar clientes.
2. Confirmar contagem de atrasados.
3. Conferir 1 cliente com pagamento no mês (não pode ficar atrasado).

## 3) Contas a pagar e recorrência
Ao marcar conta recorrente como paga:
- o sistema gera automaticamente a próxima ocorrência (quando aplicável).
- evita duplicidade para o mesmo vencimento/parcela.

## 4) Alertas de vencimento (configuráveis)
Configuração padrão:
- dias: `0,3,7`.

Resumo usado no dashboard:
- vencidas
- vencem hoje
- dentro da janela configurada.

## 5) Comandos de sanidade
```powershell
.\venv\Scripts\python.exe -m py_compile database\db.py main_window.py main.py
.\venv\Scripts\python.exe -m unittest tests.test_validation_service tests.test_pagamento_status_rules tests.test_db_month_alert_helpers -v
```

## 6) Falhas comuns
1. `ModuleNotFoundError: psycopg`
- usar sempre o Python do `venv`.

2. Métricas divergentes de atraso
- rodar sincronização forçada de status no ambiente da aplicação.

