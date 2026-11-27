"""
Auxiliares de fila (Redis).

A fila guarda tarefas pendentes e os resultados prontos.
Conceito da Aula 8: quem pede nao espera; um worker processa depois.

Este arquivo existe identico em inferencia/app e worker/app (cada servico e
uma imagem independente): se alterar um, altere o outro.

LGPD: o texto enviado pelo usuario fica no Redis so ate ser processado e o
resultado expira sozinho (RESULTADO_TTL_SEGUNDOS, padrao 24 h). O texto NAO e
copiado para a dead-letter.
"""
import json
import os
import uuid

import redis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
FILA_TAREFAS = "tarefas"
FILA_DEAD_LETTER = "tarefas:dead_letter"
PREFIXO_RESULTADO = "resultado:"
RESULTADO_TTL_SEGUNDOS = int(os.getenv("RESULTADO_TTL_SEGUNDOS", "86400"))
# Deve ser maior que o timeout do BLPOP do worker (5 s).
REDIS_SOCKET_TIMEOUT = float(os.getenv("REDIS_SOCKET_TIMEOUT", "10"))
REDIS_CONNECT_TIMEOUT = float(os.getenv("REDIS_CONNECT_TIMEOUT", "3"))

_cliente = None


def cliente():
    global _cliente
    if _cliente is None:
        _cliente = redis.from_url(
            REDIS_URL, decode_responses=True,
            socket_connect_timeout=REDIS_CONNECT_TIMEOUT,
            socket_timeout=REDIS_SOCKET_TIMEOUT,
        )
    return _cliente


def enfileirar(texto: str, contexto_trace: dict | None = None) -> str:
    """Coloca uma tarefa na fila e devolve o id para consulta posterior.

    `contexto_trace` (traceparent) viaja na mensagem para o worker continuar
    o mesmo trace (rastreamento distribuido atraves da fila).
    """
    tarefa_id = str(uuid.uuid4())
    tarefa = {"id": tarefa_id, "texto": texto, "trace": contexto_trace or {}}
    cliente().set(PREFIXO_RESULTADO + tarefa_id,
                  json.dumps({"status": "na_fila"}), ex=RESULTADO_TTL_SEGUNDOS)
    cliente().rpush(FILA_TAREFAS, json.dumps(tarefa))
    return tarefa_id


def proxima_tarefa(timeout: int = 5):
    """Bloqueia ate chegar tarefa (ou timeout). Usado pelo worker."""
    item = cliente().blpop(FILA_TAREFAS, timeout=timeout)
    if item is None:
        return None
    return json.loads(item[1])


def guardar_resultado(tarefa_id: str, resultado: dict) -> None:
    cliente().set(PREFIXO_RESULTADO + tarefa_id, json.dumps(resultado),
                  ex=RESULTADO_TTL_SEGUNDOS)


def buscar_resultado(tarefa_id: str):
    bruto = cliente().get(PREFIXO_RESULTADO + tarefa_id)
    return json.loads(bruto) if bruto else None


def enviar_para_dead_letter(tarefa: dict, erro: str, tentativas: int) -> None:
    """Grava a falha definitiva numa fila de descarte dedicada, para inspecao.

    Guarda so id, erro e tentativas: o texto do usuario nao e retido (LGPD).
    """
    cliente().rpush(
        FILA_DEAD_LETTER,
        json.dumps({"id": tarefa["id"], "erro": erro, "tentativas": tentativas}),
    )


def tamanho_dead_letter() -> int:
    return cliente().llen(FILA_DEAD_LETTER)


def ping() -> bool:
    try:
        return bool(cliente().ping())
    except redis.RedisError:
        return False
