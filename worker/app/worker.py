"""
Worker: consome a fila e executa a inferencia.

  - retentativa com espera progressiva (backoff exponencial) e, apos
    MAX_TENTATIVAS, envio para a fila dead-letter;
  - continua o trace recebido na mensagem (gateway -> inferencia -> fila -> worker);
  - nunca registra o texto do usuario em log (LGPD);
  - se o Redis cair, o laco espera e tenta de novo em vez de encerrar.

Rodar:  python -m app.worker
Suba mais de um worker e veja a carga se dividir.
"""
import json
import logging
import time

import redis

from app import fila
from app.log_requisicoes import registrar_requisicao
from app.modelo import carregar_modelo
from app.telemetry import configurar_observabilidade, extrair

MAX_TENTATIVAS = 3
BACKOFF_BASE_SEGUNDOS = 1.0

log = logging.getLogger("worker")
tracer = configurar_observabilidade("worker")


def processar_tarefa(modelo, tarefa):
    """Executa a inferencia dentro de um span ligado ao trace da requisicao."""
    with tracer.start_as_current_span(
            "worker.processar", context=extrair(tarefa.get("trace"))) as span:
        span.set_attribute("tarefa.id", tarefa["id"])
        span.set_attribute("texto.tamanho", len(tarefa["texto"]))
        _processar_com_retentativa(modelo, tarefa, span)


def _processar_com_retentativa(modelo, tarefa, span):
    for tentativa in range(1, MAX_TENTATIVAS + 1):
        inicio = time.time()
        try:
            with tracer.start_as_current_span("worker.inferencia") as sub:
                sub.set_attribute("tentativa", tentativa)
                resultado = modelo.prever(tarefa["texto"])
            resultado["status"] = "pronto"
            resultado["tempo_ms"] = round((time.time() - inicio) * 1000, 2)

            fila.guardar_resultado(tarefa["id"], resultado)
            span.set_attribute("tentativas", tentativa)
            registrar_requisicao(
                tarefa["id"], len(tarefa["texto"]), resultado["tempo_ms"],
                origem="worker",
            )
            log.info("%s concluida em %sms (tentativa %d/%d)", tarefa["id"],
                     resultado["tempo_ms"], tentativa, MAX_TENTATIVAS)
            return

        except Exception as erro:  # noqa: BLE001
            log.warning("ERRO em %s (tentativa %d/%d): %s", tarefa["id"],
                        tentativa, MAX_TENTATIVAS, type(erro).__name__)

            if tentativa < MAX_TENTATIVAS:
                espera = BACKOFF_BASE_SEGUNDOS * (2 ** (tentativa - 1))
                log.info("tentando novamente em %.1fs...", espera)
                time.sleep(espera)
            else:
                # Esgotou as tentativas -> dead-letter. O status "falha" fica
                # consultavel via GET /resultado/{id}; a DLQ guarda so metadados.
                span.record_exception(erro)
                span.set_attribute("tentativas", tentativa)
                span.set_attribute("dead_letter", True)
                tempo_ms = round((time.time() - inicio) * 1000, 2)
                fila.guardar_resultado(
                    tarefa["id"],
                    {"status": "falha", "erro": type(erro).__name__,
                     "tentativas": tentativa},
                )
                fila.enviar_para_dead_letter(tarefa, type(erro).__name__, tentativa)
                registrar_requisicao(
                    tarefa["id"], len(tarefa["texto"]), tempo_ms,
                    origem="worker-dead-letter",
                )
                log.error("%s enviada para dead-letter apos %d tentativas",
                          tarefa["id"], tentativa)


def main():
    log.info("carregando modelo...")
    modelo = carregar_modelo()
    log.info("pronto. aguardando tarefas (Ctrl+C para sair)")

    while True:
        try:
            tarefa = fila.proxima_tarefa(timeout=5)
        except redis.RedisError as erro:
            log.error("redis indisponivel (%s); nova tentativa em 2s", type(erro).__name__)
            time.sleep(2)
            continue
        if tarefa is None:
            continue

        log.info("processando %s", tarefa["id"])
        try:
            processar_tarefa(modelo, tarefa)
        except redis.RedisError as erro:
            # Nao foi possivel gravar o resultado: devolve a tarefa a fila.
            log.error("falha ao gravar resultado de %s (%s); recolocando na fila",
                      tarefa["id"], type(erro).__name__)
            time.sleep(2)
            try:
                fila.cliente().rpush(fila.FILA_TAREFAS, json.dumps(tarefa))
            except redis.RedisError:
                log.error("tarefa %s perdida: redis segue indisponivel", tarefa["id"])


if __name__ == "__main__":
    main()
