"""
Servico de inferencia (REST). Acessado apenas pelo gateway.

  POST /predict          -> coloca a tarefa na fila e devolve {"id"} (202)
  GET  /resultado/{id}   -> devolve o resultado, ou 404 se o id nao existir
  POST /predict-sync     -> inferencia sincrona (apoio/laboratorio)

O modelo e carregado UMA vez, na subida. O contexto de trace recebido do
gateway (traceparent) e gravado na mensagem da fila, para o worker continuar
o mesmo trace.

Rodar:  uvicorn app.api_rest:app --port 8001
"""
import logging
import time
import uuid

import redis
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from app import fila
from app.log_requisicoes import registrar_requisicao
from app.modelo import carregar_modelo
from app.telemetry import configurar_observabilidade, extrair, injetar

log = logging.getLogger("inferencia")
tracer = configurar_observabilidade("inferencia")

app = FastAPI(title="Servico de Inferencia - C3.A2", version="0.2.0")

modelo = None


class Entrada(BaseModel):
    texto: str = Field(min_length=1, max_length=5000)


@app.on_event("startup")
def _subir():
    """Carrega o modelo UMA vez. Este e o ponto-chave da Aula 6."""
    global modelo
    inicio = time.time()
    modelo = carregar_modelo()
    log.info("modelo carregado em %.3fs", time.time() - inicio)


@app.get("/saude")
def saude():
    return {"status": "ok", "modelo_carregado": modelo is not None,
            "fila": "ok" if fila.ping() else "indisponivel"}


@app.post("/predict-sync")
def predict_sync(entrada: Entrada):
    """Inferencia SINCRONA: o cliente espera a resposta."""
    if not entrada.texto.strip():
        raise HTTPException(status_code=400, detail="texto vazio")
    inicio = time.time()
    resultado = modelo.prever(entrada.texto)
    resultado["tempo_ms"] = round((time.time() - inicio) * 1000, 2)
    registrar_requisicao(
        str(uuid.uuid4()), len(entrada.texto), resultado["tempo_ms"],
        origem="rest-sync",
    )
    return resultado


@app.post("/predict", status_code=202)
def predict(entrada: Entrada, request: Request):
    inicio = time.time()
    if not entrada.texto.strip():
        raise HTTPException(status_code=400, detail="texto vazio")
    with tracer.start_as_current_span(
            "inferencia.enfileirar", context=extrair(request.headers)) as span:
        span.set_attribute("texto.tamanho", len(entrada.texto))
        try:
            # injetar(): o contexto atual (este span) viaja na mensagem da fila.
            tarefa_id = fila.enfileirar(entrada.texto, injetar({}))
        except redis.RedisError as erro:
            span.record_exception(erro)
            log.error("fila indisponivel: %s", erro)
            raise HTTPException(status_code=503, detail="fila indisponivel")
        span.set_attribute("tarefa.id", tarefa_id)
    registrar_requisicao(
        tarefa_id, len(entrada.texto),
        round((time.time() - inicio) * 1000, 2),
        origem="rest-async-submissao",
    )
    return {"id": tarefa_id}


@app.get("/resultado/{tarefa_id}")
def resultado(tarefa_id: str, request: Request):
    inicio = time.time()
    with tracer.start_as_current_span(
            "inferencia.consultar_resultado", context=extrair(request.headers)) as span:
        span.set_attribute("tarefa.id", tarefa_id)
        try:
            res = fila.buscar_resultado(tarefa_id)
        except redis.RedisError as erro:
            span.record_exception(erro)
            log.error("fila indisponivel: %s", erro)
            raise HTTPException(status_code=503, detail="fila indisponivel")
    registrar_requisicao(
        tarefa_id, 0, round((time.time() - inicio) * 1000, 2),
        origem="rest-async-consulta",
    )
    if res is None:
        raise HTTPException(status_code=404, detail="Tarefa nao encontrada")
    return res
