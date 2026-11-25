"""Inicializacao minima de OpenTelemetry com exportacao OTLP para o Collector."""
import os
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

def configurar_observabilidade(nome_servico: str):
    # Evita configurar mais de um provider no mesmo processo.
    if not getattr(configurar_observabilidade, "_configurado", False):
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
        provider = TracerProvider(
            resource=Resource.create({
                "service.name": os.getenv("OTEL_SERVICE_NAME", nome_servico),
                "deployment.environment": os.getenv("AMBIENTE", "development"),
            })
        )
        exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        configurar_observabilidade._configurado = True
    return trace.get_tracer(nome_servico)

propagador = TraceContextTextMapPropagator()
