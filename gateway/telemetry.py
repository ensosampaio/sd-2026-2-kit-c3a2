"""OpenTelemetry: rastreamento distribuido (gateway -> inferencia -> fila -> worker).

OTEL_TRACES_EXPORTER: "otlp" (padrao, envia ao Collector), "console" (imprime
os spans no stdout, util para desenvolvimento) ou "none" (desliga).
"""
import os

from opentelemetry import propagate, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor


def configurar_observabilidade(nome_servico: str):
    # Evita configurar mais de um provider no mesmo processo.
    if not getattr(configurar_observabilidade, "_configurado", False):
        provider = TracerProvider(
            resource=Resource.create({
                "service.name": os.getenv("OTEL_SERVICE_NAME", nome_servico),
                "deployment.environment": os.getenv("AMBIENTE", "development"),
            })
        )
        modo = os.getenv("OTEL_TRACES_EXPORTER", "otlp").lower()
        if modo == "otlp":
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True)))
        elif modo == "console":
            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        trace.set_tracer_provider(provider)
        configurar_observabilidade._configurado = True
    return trace.get_tracer(nome_servico)


def injetar(carrier: dict) -> dict:
    """Escreve o contexto de trace atual (W3C traceparent) em `carrier`."""
    propagate.inject(carrier)
    return carrier


def extrair(carrier):
    """Le o contexto de trace de `carrier` (headers HTTP ou dict da mensagem)."""
    return propagate.extract(carrier or {})
