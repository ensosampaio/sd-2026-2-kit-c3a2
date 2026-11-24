# Worker de fila

Vem do C1.A2: consome a fila `tarefas` do Redis, roda o modelo, grava o
resultado e usa retentativa com backoff exponencial + dead-letter.
Execucao: `python -m app.worker`.
