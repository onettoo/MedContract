# Release Notes - 2026-03-26

## Foco da entrega
- Robustez operacional.
- Menos acoplamento em regras de cliente.
- Experiência financeira mais prática (filtros e presets).

## Itens principais
1. Extração de regras de cliente para serviço dedicado.
2. Persistência de filtros do Financeiro por usuário.
3. Configuração de alertas de contas por usuário com fallback global.
4. Presets de contas a pagar (vencidas/hoje/7 dias).
5. Redução de falhas silenciosas em serviços de payload.
6. Novo painel completo de preferências por usuário (Dashboard + Financeiro + Alertas).
7. Preferências de tema e densidade de layout aplicadas nas telas principais.

## Checklist de validação
- [ ] Login e acesso ao Dashboard.
- [ ] Botão `Alertas contas` abre e salva preferência.
- [ ] Botão `Preferências` abre e salva painel completo de ajustes.
- [ ] Financeiro reaplica filtros salvos ao abrir.
- [ ] Presets de contas a pagar atualizam tabela corretamente.
- [ ] Exportações e refresh do Financeiro continuam funcionais.
- [ ] Suite de testes e `py_compile` sem erros.
