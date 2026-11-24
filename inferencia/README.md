# Servico de inferencia

Vem do C1.A2: API REST (`app/api_rest.py`) que enfileira tarefas no Redis
(`POST /predict` -> `{"id"}`) e permite consultar o resultado
(`GET /resultado/{id}`). Rota sincrona de apoio: `POST /predict-sync`.
Acesso externo apenas pelo gateway.
