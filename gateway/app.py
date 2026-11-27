"""
API Gateway - porta de entrada unica da plataforma.

  - JWT (Aula 16): POST /login emite o token; as demais rotas exigem Bearer.
  - Rate limit por cliente (Aula 8): janela deslizante de 60 s.
  - Resiliencia (Aula 11): tempo-limite, retentativa com espera progressiva
    (somente em GET, que e idempotente) e circuit breaker nas chamadas ao
    servico de inferencia.
  - Observabilidade (Aula 15): cada chamada gera spans OpenTelemetry e propaga
    o contexto (traceparent) ao servico de inferencia, que o repassa a fila e
    ao worker.

Rodar: uvicorn app:app --port 8000
"""
import hmac
import logging
import os
import threading
import time
from collections import defaultdict, deque

import jwt
import requests
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator

from circuit_breaker import CircuitBreaker, CircuitoAberto
from telemetry import configurar_observabilidade, injetar

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("gateway")
tracer = configurar_observabilidade("gateway")

app = FastAPI(title="Gateway - C3.A2")

AMBIENTE = os.getenv("AMBIENTE", "development")
URL_INFERENCIA = os.getenv("URL_INFERENCIA", "http://localhost:8001")

JWT_SEGREDO = os.getenv("JWT_SEGREDO", "troque-este-segredo")
JWT_ALGORITMO = "HS256"
JWT_EXPIRA_MINUTOS = int(os.getenv("JWT_EXPIRA_MINUTOS", "30"))
USUARIO_API = os.getenv("USUARIO_API", "admin")
SENHA_API = os.getenv("SENHA_API", "admin")
LIMITE_POR_MINUTO = int(os.getenv("LIMITE_POR_MINUTO", "30"))
CONFIAR_PROXY = os.getenv("CONFIAR_PROXY", "false").lower() == "true"
MAX_TEXTO = int(os.getenv("MAX_TEXTO_CARACTERES", "5000"))

TIMEOUT_INFERENCIA = float(os.getenv("TIMEOUT_INFERENCIA_SEGUNDOS", "5"))
TENTATIVAS_GET = int(os.getenv("TENTATIVAS_GET", "3"))
BACKOFF_SEGUNDOS = float(os.getenv("BACKOFF_SEGUNDOS", "0.2"))
CB_LIMITE_FALHAS = int(os.getenv("CB_LIMITE_FALHAS", "5"))
CB_ESPERA_SEGUNDOS = float(os.getenv("CB_ESPERA_SEGUNDOS", "20"))

disjuntor = CircuitBreaker(limite_falhas=CB_LIMITE_FALHAS,
                           espera_segundos=CB_ESPERA_SEGUNDOS)
bearer = HTTPBearer(auto_error=False)


# --- Configuracao segura ---------------------------------------------------

def validar_configuracao():
    """Em producao, recusa subir com segredo/senha fracos ou padrao."""
    padroes = {"", "troque-este-segredo", "troque-esta-senha", "admin"}
    problemas = []
    if JWT_SEGREDO in padroes or len(JWT_SEGREDO) < 32:
        problemas.append("JWT_SEGREDO precisa ter 32+ caracteres e nao ser o padrao")
    if SENHA_API in padroes or len(SENHA_API) < 12:
        problemas.append("SENHA_API precisa ter 12+ caracteres e nao ser o padrao")
    if USUARIO_API in padroes:
        problemas.append("USUARIO_API nao pode ser o padrao")
    if not problemas:
        return
    if AMBIENTE == "production":
        raise RuntimeError("Configuracao insegura: " + "; ".join(problemas))
    log.warning("Configuracao de desenvolvimento (NAO usar em producao): %s",
                "; ".join(problemas))


validar_configuracao()


class Entrada(BaseModel):
    texto: str = Field(min_length=1, max_length=MAX_TEXTO)

    @field_validator("texto")
    @classmethod
    def nao_vazio(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("texto vazio")
        return v


class Login(BaseModel):
    usuario: str
    senha: str


# --- JWT -------------------------------------------------------------------

def criar_token(usuario: str) -> str:
    agora = int(time.time())
    payload = {"sub": usuario, "iat": agora,
               "exp": agora + JWT_EXPIRA_MINUTOS * 60}
    return jwt.encode(payload, JWT_SEGREDO, algorithm=JWT_ALGORITMO)


def usuario_autenticado(
    cred: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> str:
    """Valida o token Bearer; 401 se ausente, invalido ou expirado."""
    if cred is None:
        raise HTTPException(status_code=401, detail="token ausente",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(cred.credentials, JWT_SEGREDO,
                             algorithms=[JWT_ALGORITMO])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="token invalido ou expirado",
                            headers={"WWW-Authenticate": "Bearer"})
    return payload["sub"]


# --- Rate limit (janela deslizante de 60s por cliente) ---------------------

_acessos: dict[str, deque] = defaultdict(deque)
_trava = threading.Lock()


def permitir(cliente: str) -> tuple[bool, int]:
    """Retorna (permitido, segundos ate liberar)."""
    agora = time.monotonic()
    with _trava:
        fila = _acessos[cliente]
        while fila and agora - fila[0] >= 60:
            fila.popleft()
        if len(fila) >= LIMITE_POR_MINUTO:
            return False, int(60 - (agora - fila[0])) + 1
        fila.append(agora)
        return True, 0


def limitar(cliente: str):
    ok, espera = permitir(cliente)
    if not ok:
        raise HTTPException(status_code=429,
                            detail="limite de requisicoes excedido",
                            headers={"Retry-After": str(espera)})


def limite_por_usuario(usuario: str = Depends(usuario_autenticado)) -> str:
    limitar(f"user:{usuario}")
    return usuario


def ip_do_cliente(request: Request) -> str:
    # Atras do proxy HTTPS (Caddy) o IP real vem em X-Forwarded-For.
    if CONFIAR_PROXY:
        encaminhado = request.headers.get("x-forwarded-for", "")
        if encaminhado:
            return encaminhado.split(",")[0].strip()
    return request.client.host if request.client else "desconhecido"


def limite_por_ip(request: Request):
    limitar(f"ip:{ip_do_cliente(request)}")


# --- Chamada protegida ao servico de inferencia -----------------------------

class ErroUpstream(Exception):
    """Resposta 5xx do servico de inferencia (conta como falha no disjuntor)."""


def _requisicao(metodo: str, caminho: str, headers: dict, corpo):
    r = requests.request(metodo, f"{URL_INFERENCIA}{caminho}", json=corpo,
                         headers=headers, timeout=TIMEOUT_INFERENCIA)
    if r.status_code >= 500:
        raise ErroUpstream(f"inferencia respondeu {r.status_code}")
    return r


def chamar_inferencia(metodo: str, caminho: str, rota: str,
                      corpo=None, tentativas: int = 1):
    """Tempo-limite + retentativa (backoff) + circuit breaker + span de trace.

    Erros viram HTTPException sem expor detalhes internos ao cliente (o detalhe
    vai para o log do servidor).
    """
    with tracer.start_as_current_span(f"gateway -> inferencia {metodo} {rota}") as span:
        span.set_attribute("peer.service", "inferencia")
        span.set_attribute("http.route", rota)
        headers = injetar({})  # traceparent: liga este span ao da inferencia
        ultimo = None
        for tentativa in range(1, tentativas + 1):
            try:
                resposta = disjuntor.chamar(_requisicao, metodo, caminho, headers, corpo)
                span.set_attribute("http.status_code", resposta.status_code)
                span.set_attribute("tentativas", tentativa)
                return resposta
            except CircuitoAberto:
                span.set_attribute("circuito", "aberto")
                log.error("circuito aberto: %s %s recusada", metodo, rota)
                raise HTTPException(
                    status_code=503,
                    detail="servico de inferencia temporariamente indisponivel",
                    headers={"Retry-After": str(int(CB_ESPERA_SEGUNDOS))})
            except (requests.RequestException, ErroUpstream) as erro:
                ultimo = erro
                log.warning("inferencia falhou (%s %s, tentativa %d/%d, circuito=%s): %s",
                            metodo, rota, tentativa, tentativas, disjuntor.estado, erro)
                if tentativa < tentativas:
                    time.sleep(BACKOFF_SEGUNDOS * (2 ** (tentativa - 1)))
        span.record_exception(ultimo)
        span.set_attribute("tentativas", tentativas)
        if isinstance(ultimo, requests.Timeout):
            raise HTTPException(status_code=504,
                                detail="tempo esgotado ao chamar o servico de inferencia")
        raise HTTPException(status_code=502,
                            detail="servico de inferencia indisponivel")


# --- Rotas -----------------------------------------------------------------

@app.middleware("http")
async def registrar(request: Request, call_next):
    inicio = time.time()
    resposta = await call_next(request)
    ms = (time.time() - inicio) * 1000
    # Nunca registra corpo, token ou texto do usuario (LGPD).
    log.info("%s %s -> %s (%.1fms)", request.method, request.url.path,
             resposta.status_code, ms)
    return resposta


@app.get("/saude")
def saude():
    return {"status": "ok", "disjuntor": disjuntor.estado}


@app.post("/login", dependencies=[Depends(limite_por_ip)])
def login(dados: Login):
    ok_user = hmac.compare_digest(dados.usuario.encode(), USUARIO_API.encode())
    ok_pass = hmac.compare_digest(dados.senha.encode(), SENHA_API.encode())
    if not (ok_user and ok_pass):
        raise HTTPException(status_code=401, detail="credenciais invalidas")
    return {"access_token": criar_token(dados.usuario),
            "token_type": "bearer",
            "expires_in": JWT_EXPIRA_MINUTOS * 60}


@app.post("/predict", status_code=202)
def predict(entrada: Entrada, usuario: str = Depends(limite_por_usuario)):
    """Enfileira a inferencia. POST nao e idempotente: sem retentativa."""
    r = chamar_inferencia("POST", "/predict", "/predict",
                          corpo=entrada.model_dump(), tentativas=1)
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code,
                            detail="requisicao recusada pelo servico de inferencia")
    return r.json()


@app.get("/resultado/{tarefa_id}")
def resultado(tarefa_id: str, usuario: str = Depends(limite_por_usuario)):
    """Consulta o resultado de uma tarefa enfileirada (GET: com retentativa)."""
    r = chamar_inferencia("GET", f"/resultado/{tarefa_id}", "/resultado/{id}",
                          tentativas=TENTATIVAS_GET)
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail="tarefa nao encontrada")
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code,
                            detail="requisicao recusada pelo servico de inferencia")
    return r.json()
