# Roadmap Técnico 2026 - MedContract

## Objetivo
Reduzir risco operacional e acelerar evolução do produto com foco em modularização, testes e performance.

## Prioridade P0 (imediato)
1. Modularizar domínios críticos:
- `finance_payload_service` (extraído de `main_window.py`)
- próximo alvo: dashboard payload.

2. Reduzir erros silenciosos:
- substituir `except ...: pass` críticos por logs com contexto.

3. Confiabilidade de pagamentos:
- status dinâmico baseado em pagamento no mês vigente.
- normalização diária de `mes_referencia` no startup.

## Prioridade P1 (curto prazo)
1. Cobertura de testes:
- fluxos de cadastro > pagamento > dashboard > financeiro.
- testes de regressão para contas recorrentes.

2. Performance de dados:
- evitar full scan em consultas por mês.
- consolidar consultas de métricas com filtros SQL.

3. CI e qualidade:
- workflow com compile + unittest em push/PR.

## Prioridade P2 (médio prazo)
1. Dashboard service dedicado:
- extração de `_compute_dashboard_payload` para `services/dashboard_payload_service.py`.

2. Padronização visual:
- evoluir tokens e estados visuais compartilhados (QSS).

3. Runbook de produção:
- troubleshooting de banco, backup, restore e jobs automáticos.

