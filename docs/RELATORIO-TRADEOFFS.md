# Relatório de trade-offs — CAP, custo e latência

Decisões de projeto da plataforma e o que cada uma custa.

## 1. CAP: consistência ou disponibilidade?

O estado compartilhado do sistema está em **um único Redis** (fila + resultados).
Se a rede entre os serviços e o Redis é particionada (ou ele cai), é preciso escolher:

| Escolha | O que fizemos |
|---|---|
| Responder mesmo sem garantia (disponibilidade) | **Não.** Nenhuma réplica "adivinha" resultados |
| Recusar com clareza (consistência) | **Sim.** A inferência devolve `503 fila indisponivel`; o gateway devolve `502/503` sem vazar detalhes e o **circuit breaker** abre para parar de insistir |

Ou seja, em partição o sistema se comporta como **CP**: prefere falhar rápido a servir
dado incerto. Com um nó só não há réplica divergente, então um resultado gravado é lido
logo em seguida (*read-your-writes*).

- **Preço:** o Redis é ponto único de falha; durante a queda, ninguém enfileira.
- **Alternativa:** Redis com réplica (Sentinel) ganha disponibilidade, mas a replicação é
  assíncrona e, num *failover*, tarefas já confirmadas podem se perder — a consistência cai.
- **Entrega da fila:** o worker usa `BLPOP`, que remove a tarefa antes de processar
  (*at-most-once*): se o worker morrer no meio, a tarefa se perde. Retentativas e
  dead-letter cobrem falhas de **processamento**, não a morte do processo. Uma fila com
  confirmação (`BRPOPLPUSH`/Streams) daria *at-least-once* ao custo de mais código e de
  possíveis duplicatas.

## 2. Custo

- **Infraestrutura:** o alvo de implantação é uma única VM em free tier executando tudo
  (gateway, inferência, worker, Redis, coletor, Caddy) — **custo zero**. (Tentamos a Oracle
  Cloud, mas faltou capacidade gratuita; ver README.) Não usamos serviços gerenciados (Redis, API
  Gateway, tracing em SaaS), que dariam alta disponibilidade e menos operação por uma
  mensalidade.
- **Modelo:** TF-IDF + regressão logística roda em CPU, em milissegundos, sem GPU e sem
  API paga. Um LLM externo traria qualidade e custo por requisição.
- **Escala:** o worker é *stateless*; `docker compose up --scale worker=N` divide a carga
  pela fila. Não implementamos autoescalonamento (a VM tem teto fixo): pagaríamos só pelo
  uso, mas com mais componentes para operar.
- **Privacidade barata:** resultados expiram em 24 h (TTL do Redis) e logs rodam em
  rotação (3 × 10 MB), o que limita o armazenamento e a exposição de dados.

## 3. Latência

Medido localmente (Redis simulado, sem rede entre contêineres), pelo gateway:

| Operação | Tempo observado |
|---|---|
| `POST /predict` → `202` (gateway → inferência → enfileirar) | ~16 ms |
| `GET /resultado/{id}` | ~11 ms |
| Inferência dentro do worker | ~5 ms |

Em nuvem, some a latência de rede (HTTPS, até a VM). Trade-offs:

- **Assíncrono × síncrono:** o `202` volta rápido e a fila absorve picos, mas o cliente
  precisa fazer *polling* e a resposta final demora mais que um `POST` síncrono direto.
  Escolhemos o assíncrono por resiliência e desacoplamento.
- **Resiliência × latência no pior caso:** timeout de 5 s × 3 tentativas no `GET` pode
  chegar a ~15 s até um `502`. O circuit breaker compensa: depois de 5 falhas, as
  chamadas seguintes recebem `503` **imediato**. O `POST` não é retentado (não é
  idempotente: retentar duplicaria tarefas).
- **Camadas extras:** o gateway acrescenta um salto (~ms) e o JWT HS256 custa
  microssegundos. O rastreamento exporta spans em *batch*, fora do caminho da requisição.
