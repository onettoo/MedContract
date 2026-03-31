# Changelog - 2026-03-26

## Adicionado
- Serviço de domínio de clientes em `services/clientes_service.py`, centralizando:
  - salvar cliente,
  - excluir cliente,
  - cancelar plano,
  - renovar contrato (individual/lote),
  - aplicar reajuste.
- Persistência de preferências do Financeiro por usuário no banco:
  - `obter_preferencias_financeiro_usuario`,
  - `salvar_preferencias_financeiro_usuario`.
- Configuração de alertas de contas por usuário (com fallback global):
  - `obter_contas_alerta_config(usuario=...)`,
  - `salvar_contas_alerta_config(..., usuario=...)`.
- Botão no Dashboard para abrir configuração de alertas de contas.
- Janela de preferências de alertas (`ContasAlertaPreferencesDialog`) no `main_window.py`.
- Painel completo de preferências por usuário (`UserPreferencesDialog`) com:
  - período padrão do dashboard,
  - aplicar período ao login,
  - intervalo de auto atualização,
  - page size do Financeiro e Contas,
  - dias de alerta de contas,
  - tema visual (claro/escuro no dashboard),
  - densidade de layout (normal/compacto).
- Persistência de preferências gerais por usuário:
  - `obter_preferencias_usuario`,
  - `salvar_preferencias_usuario`.
- Presets rápidos em Contas a Pagar (somente vencidas, vencem hoje, próximos 7 dias).
- Testes novos:
  - `tests/test_clientes_service.py`,
  - `tests/test_finance_preferences_integration.py`.

## Alterado
- `main_window.py`:
  - fluxo de cliente passou a delegar para `clientes_service`,
  - filtros do Financeiro/Contas agora são salvos automaticamente por usuário,
  - ao abrir o Financeiro, filtros salvos são reaplicados.
- `services/dashboard_payload_service.py`:
  - passou a aceitar `alert_user` para carregar alertas personalizados por usuário.
- `services/finance_payload_service.py`:
  - exceções em carregamento de payload financeiro agora registram `logger.debug` (menos falha silenciosa).
- `views/financeiro_view.py`:
  - emissão correta de `query_changed_signal` sem loop com refresh remoto,
  - suporte para aplicar filtros salvos de forma programática (`apply_saved_query`, `apply_saved_contas_query`).
- `views/dashboard_view.py`:
  - botão de topo evoluiu para abrir preferências completas,
  - API de período ampliada (`current_period`, `set_period`).

## Compatibilidade
- APIs antigas continuam funcionais:
  - `obter_contas_alerta_config()` sem `usuario`,
  - `salvar_contas_alerta_config(dias)` sem `usuario`.
- Comportamento padrão permanece com dias de alerta `[0, 3, 7]` quando não houver configuração salva.
