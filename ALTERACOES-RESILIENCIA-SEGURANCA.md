# Alterações preparadas — Resiliência e segurança

Esta versão foi preparada a partir do ZIP enviado. O deploy em nuvem não foi iniciado.

## O que foi alterado

1. **Gateway**
   - segredo JWT, usuário e senha passam a ser obrigatórios;
   - validação mínima do segredo (32 caracteres) e senha (12 caracteres);
   - limite de 5.000 caracteres para o texto de entrada;
   - timeout configurável;
   - retry com backoff somente na consulta GET;
   - Circuit Breaker com limiar e tempo de recuperação configuráveis;
   - mensagens de erro upstream sem expor detalhes internos;
   - criação de spans OpenTelemetry e propagação do trace.

2. **Inferência e Redis**
   - recebem e armazenam o contexto `traceparent` junto da tarefa;
   - criam spans no recebimento e no enfileiramento;
   - resultados expiram após 24 horas por padrão;
   - timeout de conexão e socket Redis;
   - texto não é copiado para a Dead Letter Queue.

3. **Worker**
   - mantém as três tentativas com backoff exponencial;
   - continua enviando falhas definitivas para a Dead Letter Queue;
   - retoma o contexto de trace recebido na mensagem Redis;
   - registra spans de processamento e não grava o texto nos logs.

4. **Observabilidade**
   - novo serviço OpenTelemetry Collector no Docker Compose;
   - traces OTLP recebidos na porta 4317 e exibidos nos logs do Collector pelo exporter `debug`.

5. **Documentação**
   - seção LGPD no README com dados, finalidade, retenção e logs;
   - instruções de configuração segura do `.env`;
   - limitações conhecidas e itens pendentes de validação.

## Antes de executar

- Copie `.env.example` para `.env`.
- Gere um JWT_SEGREDO aleatório com pelo menos 32 caracteres.
- Defina USUARIO_API não padrão e SENHA_API com pelo menos 12 caracteres.
- Não compartilhe nem versione o `.env`.

## Validação realizada nesta preparação

- Sintaxe dos arquivos Python verificada com `compileall`.
- Sintaxe dos arquivos YAML verificada com PyYAML.
- Não foi possível executar containers, chamadas HTTP, Redis ou o fluxo distribuído porque o Docker Desktop não está operacional neste computador.

Portanto, considere as alterações implementadas no código, mas ainda pendentes de teste de integração antes da entrega.
