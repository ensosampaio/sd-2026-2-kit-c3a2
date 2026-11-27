# TAREFAS - Trabalho C3.A2 (Plataforma de IA como Servico)

Este e o projeto integrador. Reaproveite o que voce fez em C1.A2 e C2.A2.

## Nucleo obrigatorio

- [x] **1. Autenticacao JWT no gateway** - `gateway/app.py`
      Rota de login que emite o token e protecao das demais rotas (401 sem token). (Aula 16)

- [x] **2. Rate limit no gateway** - `gateway/app.py`
      Limitar requisicoes por cliente por minuto. (Aula 8)

- [x] **3. Dockerfile de cada servico**
      Um Dockerfile por servico: `gateway/`, `inferencia/`, `worker/`. (Aula 13)

- [x] **4. docker-compose completo**
      Sobe o sistema inteiro com `docker compose up --build`: gateway, inferencia, worker,
      Redis e coletor de traces (Caddy no perfil `https`). (Aula 14)

- [ ] **5. Deploy em nuvem (free tier)**
      Pronto para publicar (`deploy/INSTRUCOES.md`). FALTA: criar a VM, subir e colocar a
      URL publica no README.

- [x] **6. Resiliencia**
      Tempo-limite, retentativa com espera progressiva e circuit breaker no gateway;
      retentativa + dead-letter no worker. (Aula 11)

- [x] **7. Observabilidade**
      OpenTelemetry: um unico trace cobre gateway -> inferencia -> fila -> worker. (Aula 15)

- [ ] **8. HTTPS** no servico publicado. (Aula 16)
      Configurado (Caddy + Let's Encrypt, `docker compose --profile https`). FALTA: ativar
      no deploy real.

- [x] **9. Secao de conformidade no README**
      Secao "Conformidade (LGPD)": dados, finalidade e retencao.

- [x] **10. Relatorio de trade-offs**
      `docs/RELATORIO-TRADEOFFS.md` (CAP, custo e latencia).

## Extensoes opcionais

- [ ] Autoescalonamento de workers conforme o tamanho da fila
- [ ] Componente serverless ou na borda
- [ ] CI/CD publicando automaticamente a cada commit
- [ ] Painel de metricas
- [ ] Manifests de Kubernetes

## Antes de entregar

- [ ] Clone em OUTRA maquina e rode o comando unico (`docker compose up --build`) - funciona?
- [ ] A URL publica esta no ar e no README? (`BASE_URL=https://... python scripts/smoke_test.py`)
- [x] Toda configuracao esta em variavel de ambiente (nada fixo no codigo)?
- [x] Os logs estao livres de dados pessoais? (verificado: sem texto, token ou senha)
