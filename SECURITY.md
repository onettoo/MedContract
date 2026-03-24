# Guia de SeguranÃ§a e OtimizaÃ§Ã£o - MedContract

## ðŸ“‹ Ãndice
1. [SeguranÃ§a](#seguranÃ§a)
2. [OtimizaÃ§Ã£o](#otimizaÃ§Ã£o)
3. [Backup e RecuperaÃ§Ã£o](#backup-e-recuperaÃ§Ã£o)
4. [Monitoramento](#monitoramento)
5. [Checklist de Deploy](#checklist-de-deploy)

---

## ðŸ”’ SeguranÃ§a

### Senhas e AutenticaÃ§Ã£o

#### âœ… Implementado
- âœ“ Hash bcrypt com salt para senhas (12 rounds)
- âœ“ ValidaÃ§Ã£o de forÃ§a de senha
- âœ“ Rate limiting de login (3 tentativas)
- âœ“ Lockout temporÃ¡rio apÃ³s falhas (120 segundos)
- âœ“ Timeout de sessÃ£o (30 minutos)
- âœ“ Auditoria de tentativas de login

#### ðŸ”§ RecomendaÃ§Ãµes
1. **Altere as senhas padrÃ£o imediatamente**
   ```bash
   Admin padrao: DEFINA_UMA_SENHA_FORTE
   RecepÃ§Ã£o padrÃ£o: DEFINA_UMA_SENHA_FORTE
   ```

2. **PolÃ­tica de senhas**
   - MÃ­nimo 8 caracteres
   - Pelo menos 1 maiÃºscula
   - Pelo menos 1 minÃºscula
   - Pelo menos 1 nÃºmero
   - Evitar senhas comuns

3. **RotaÃ§Ã£o de senhas**
   - Trocar senhas a cada 90 dias
   - NÃ£o reutilizar Ãºltimas 5 senhas

### Banco de Dados

#### âœ… Implementado
- âœ“ ConexÃ£o SSL/TLS obrigatÃ³ria
- âœ“ Pool de conexÃµes otimizado
- âœ“ Prepared statements (proteÃ§Ã£o SQL injection)
- âœ“ ValidaÃ§Ã£o de entrada
- âœ“ SanitizaÃ§Ã£o de CPF/CNPJ

#### ðŸ”§ RecomendaÃ§Ãµes
1. **Credenciais**
   - Use variÃ¡veis de ambiente (.env)
   - Nunca commite .env no Git
   - Use senhas fortes (16+ caracteres)

2. **ConexÃ£o**
   ```env
   MEDCONTRACT_DB_SSLMODE=require
   MEDCONTRACT_DB_CONNECT_TIMEOUT=10
   ```

3. **Backup**
   - Backup automÃ¡tico diÃ¡rio
   - RetenÃ§Ã£o de 30 dias
   - Armazenamento criptografado

### Dados SensÃ­veis

#### âœ… Implementado
- âœ“ CPF normalizado e indexado
- âœ“ ValidaÃ§Ã£o de CPF/CNPJ
- âœ“ SanitizaÃ§Ã£o de inputs
- âœ“ Logs de auditoria

#### ðŸ”§ RecomendaÃ§Ãµes
1. **LGPD/GDPR**
   - Obter consentimento para armazenamento
   - Permitir exclusÃ£o de dados
   - Anonimizar dados em relatÃ³rios

2. **Criptografia**
   - Dados em trÃ¢nsito: TLS 1.2+
   - Dados em repouso: AES-256
   - Backups: criptografados

### Controle de Acesso

#### âœ… Implementado
- âœ“ NÃ­veis de acesso (admin, recepÃ§Ã£o)
- âœ“ Auditoria de aÃ§Ãµes
- âœ“ SessÃµes com timeout

#### ðŸ”§ RecomendaÃ§Ãµes
1. **PrincÃ­pio do menor privilÃ©gio**
   - RecepÃ§Ã£o: apenas leitura e cadastro
   - Admin: acesso completo

2. **Auditoria**
   - Revisar logs semanalmente
   - Alertas para aÃ§Ãµes suspeitas

---

## âš¡ OtimizaÃ§Ã£o

### Performance do Banco

#### âœ… Implementado
- âœ“ Ãndices em colunas crÃ­ticas
- âœ“ Pool de conexÃµes (10 conexÃµes)
- âœ“ Query timeout (30s)
- âœ“ PaginaÃ§Ã£o de resultados

#### ðŸ”§ RecomendaÃ§Ãµes
1. **Ãndices**
   ```sql
   -- JÃ¡ criados automaticamente
   idx_clientes_cpf_norm
   idx_clientes_nome
   idx_pagamentos_cliente_mes
   ```

2. **Queries**
   - Use LIMIT em listagens
   - Evite SELECT *
   - Use prepared statements

3. **ManutenÃ§Ã£o**
   ```sql
   -- Execute mensalmente
   VACUUM ANALYZE;
   REINDEX DATABASE medcontract;
   ```

### Cache

#### âœ… Implementado
- âœ“ Cache de queries (5 minutos)
- âœ“ Pool de conexÃµes reutilizÃ¡vel

#### ðŸ”§ RecomendaÃ§Ãµes
1. **Habilitar cache**
   ```env
   MEDCONTRACT_ENABLE_CACHE=1
   MEDCONTRACT_CACHE_TTL=300
   ```

2. **Limpar cache**
   - ApÃ³s alteraÃ§Ãµes em massa
   - ApÃ³s reajustes de planos

### Interface

#### âœ… Implementado
- âœ“ PaginaÃ§Ã£o (50 itens/pÃ¡gina)
- âœ“ Lazy loading de dependentes
- âœ“ Debounce em buscas

#### ðŸ”§ RecomendaÃ§Ãµes
1. **Responsividade**
   - MÃ­nimo 1200x760
   - Esconde painel lateral < 760px

2. **Carregamento**
   - Indicadores visuais
   - Timeout de 15s

---

## ðŸ’¾ Backup e RecuperaÃ§Ã£o

### EstratÃ©gia de Backup

#### âœ… Implementado
- âœ“ Backup automÃ¡tico na inicializaÃ§Ã£o
- âœ“ RetenÃ§Ã£o de 30 dias
- âœ“ Formato SQL (pg_dump)

#### ðŸ”§ RecomendaÃ§Ãµes
1. **FrequÃªncia**
   - DiÃ¡rio: automÃ¡tico
   - Semanal: manual completo
   - Mensal: arquivamento externo

2. **Armazenamento**
   ```
   Local: %LOCALAPPDATA%\\MedContract\\backups\\
   Nuvem: Google Drive, Dropbox, S3
   Externo: HD externo, NAS
   ```

3. **Teste de RestauraÃ§Ã£o**
   - Mensal: teste de restore
   - Documente o processo

### RecuperaÃ§Ã£o de Desastres

#### Procedimento
1. **Backup mais recente**
   ```bash
   # Localizar backup
   dir "%LOCALAPPDATA%\\MedContract\\backups"
   ```

2. **Restaurar**
   ```bash
   psql -U postgres -d medcontract < backup.sql
   ```

3. **Verificar integridade**
   - Contar registros
   - Testar login
   - Validar relatÃ³rios

---

## ðŸ“Š Monitoramento

### Logs

#### âœ… Implementado
- âœ“ Logs rotativos (10MB, 5 arquivos)
- âœ“ NÃ­veis: INFO, WARNING, ERROR
- âœ“ Auditoria de login

#### ðŸ”§ RecomendaÃ§Ãµes
1. **Revisar logs**
   ```bash
   # Logs da aplicaÃ§Ã£o
   tail -f logs/app.log
   
   # Erros recentes
   grep ERROR logs/app.log | tail -20
   ```

2. **Alertas**
   - MÃºltiplas falhas de login
   - Erros de banco
   - EspaÃ§o em disco baixo

### MÃ©tricas

#### Monitorar
- Tempo de resposta de queries
- Taxa de erro
- Uso de memÃ³ria
- ConexÃµes ativas no banco

---

## âœ… Checklist de Deploy

### Antes do Deploy

- [ ] Alterar senhas padrÃ£o
- [ ] Configurar .env com credenciais reais
- [ ] Testar conexÃ£o com banco
- [ ] Criar backup manual
- [ ] Revisar logs de erro
- [ ] Testar em ambiente de staging

### ConfiguraÃ§Ãµes de ProduÃ§Ã£o

```env
# .env
MEDCONTRACT_ENV=production
MEDCONTRACT_LOG_LEVEL=INFO
MEDCONTRACT_DB_SSLMODE=require
MEDCONTRACT_DB_POOL_MAX=10
MEDCONTRACT_ENABLE_CACHE=1
MEDCONTRACT_AUTO_BACKUP_ON_STARTUP=0
MEDCONTRACT_AUTO_BACKUP_ON_EXIT=0
MEDCONTRACT_ALLOW_JSON_BACKUP_FALLBACK=0
```

### ApÃ³s o Deploy

- [ ] Verificar logs de inicializaÃ§Ã£o
- [ ] Testar login admin
- [ ] Testar cadastro de cliente
- [ ] Testar registro de pagamento
- [ ] Verificar backup automÃ¡tico
- [ ] Documentar credenciais (cofre seguro)

### ManutenÃ§Ã£o ContÃ­nua

#### DiÃ¡ria
- Verificar logs de erro
- Monitorar espaÃ§o em disco

#### Semanal
- Revisar logs de auditoria
- Verificar backups

#### Mensal
- Atualizar dependÃªncias
- Testar restauraÃ§Ã£o de backup
- Revisar acessos de usuÃ¡rios
- Limpar logs antigos

#### Trimestral
- RotaÃ§Ã£o de senhas
- Auditoria de seguranÃ§a
- OtimizaÃ§Ã£o de banco
- AtualizaÃ§Ã£o de documentaÃ§Ã£o

---

## ðŸš¨ Incidentes de SeguranÃ§a

### Procedimento

1. **IdentificaÃ§Ã£o**
   - Revisar logs
   - Identificar escopo

2. **ContenÃ§Ã£o**
   - Desativar usuÃ¡rio comprometido
   - Trocar senhas
   - Bloquear IPs suspeitos

3. **ErradicaÃ§Ã£o**
   - Corrigir vulnerabilidade
   - Atualizar sistema

4. **RecuperaÃ§Ã£o**
   - Restaurar de backup limpo
   - Validar integridade

5. **LiÃ§Ãµes Aprendidas**
   - Documentar incidente
   - Atualizar procedimentos

---

## ðŸ“ž Contatos de EmergÃªncia

- **Suporte TÃ©cnico**: [seu-email]
- **DBA**: [dba-email]
- **SeguranÃ§a**: [security-email]

---

## ðŸ“š Recursos Adicionais

- [DocumentaÃ§Ã£o PostgreSQL](https://www.postgresql.org/docs/)
- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [LGPD - Lei Geral de ProteÃ§Ã£o de Dados](https://www.gov.br/cidadania/pt-br/acesso-a-informacao/lgpd)

---

**Ãšltima atualizaÃ§Ã£o**: 2024
**VersÃ£o**: 2.0.0





## Hardening Final (Desktop)

Este sistema é desktop (PySide6), então CORS e headers HTTP não se aplicam diretamente no cliente.
Esses itens só são exigidos se existir API web separada.

### Checklist de Produção (obrigatório)

- [ ] `MEDCONTRACT_ENV=production`
- [ ] `MEDCONTRACT_DB_ALLOW_SQLITE_FALLBACK=0`
- [ ] `MEDCONTRACT_DB_SSLMODE=require` (ou `verify-ca` / `verify-full`)
- [ ] `MEDCONTRACT_DEFAULT_ADMIN_PASSWORD` com valor real forte (não placeholder)
- [ ] `.env` sem credenciais reais versionáveis; segredos em `.env.local`
- [ ] `MEDCONTRACT_ALLOW_JSON_BACKUP_FALLBACK=0`
- [ ] `MEDCONTRACT_BACKUP_ENCRYPTION_KEY` definido (backup em repouso criptografado)
- [ ] `MEDCONTRACT_LOGIN_MAX_ATTEMPTS` e `MEDCONTRACT_LOGIN_LOCKOUT_SECS` configurados

### Gate de Inicialização

O app agora executa preflight de segurança no startup e bloqueia inicialização
em caso de configuração crítica insegura em produção.

### Checklist de Release Operacional

1. Rodar compilação: `python -m compileall -q .`
2. Validar import principal: `venv\\Scripts\\python.exe -c "import main_window; import database.db as db"`
3. Validar login admin e perfil recepção
4. Validar fluxo: cadastro, listagem, exportação, backup
5. Confirmar geração de arquivos em `reports` (resumo e lembrete diário)
6. Registrar hash/versão do build e guardar backup pré-release




