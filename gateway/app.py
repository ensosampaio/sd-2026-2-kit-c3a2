"""
API Gateway - porta de entrada unica da plataforma.

JA PRONTO: roteamento para o servico de inferencia e log de requisicoes.
TAREFA 1: autenticacao por JWT.
TAREFA 2: limite de requisicoes por cliente (rate limit).

Rodar: uvicorn app:app --port 8000
"""
import hmac
import os
import time

import jwt
import requests
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

app = FastAPI(title="Gateway - C3.A2")
URL_INFERENCIA = os.getenv("URL_INFERENCIA", "http://localhost:8001")

JWT_SEGREDO = os.getenv("JWT_SEGREDO", "troque-este-segredo")
JWT_ALGORITMO = "HS256"
JWT_EXPIRA_MINUTOS = int(os.getenv("JWT_EXPIRA_MINUTOS", "30"))
USUARIO_API = os.getenv("USUARIO_API", "admin")
SENHA_API = os.getenv("SENHA_API", "admin")

bearer = HTTPBearer(auto_error=False)


class Entrada(BaseModel):
    texto: str


class Login(BaseModel):
    usuario: str
    senha: str


# --- TAREFA 1: JWT ---------------------------------------------------------

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


@app.middleware("http")
async def registrar(request: Request, call_next):
    inicio = time.time()
    resposta = await call_next(request)
    ms = (time.time() - inicio) * 1000
    print(f"[gateway] {request.method} {request.url.path} "
          f"-> {resposta.status_code} ({ms:.1f}ms)")
    return resposta


@app.get("/saude")
def saude():
    return {"status": "ok"}


@app.post("/predict")
def predict(entrada: Entrada, usuario: str = Depends(usuario_autenticado)):
    # JWT validado via dependencia (401 se ausente/invalido).
    try:
        r = requests.post(f"{URL_INFERENCIA}/predict",
                          json=entrada.model_dump(), timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        raise HTTPException(status_code=503,
                            detail=f"servico de inferencia indisponivel: {e}")


@app.post("/login")
def login(dados: Login):
    ok_user = hmac.compare_digest(dados.usuario.encode(), USUARIO_API.encode())
    ok_pass = hmac.compare_digest(dados.senha.encode(), SENHA_API.encode())
    if not (ok_user and ok_pass):
        raise HTTPException(status_code=401, detail="credenciais invalidas")
    return {"access_token": criar_token(dados.usuario),
            "token_type": "bearer",
            "expires_in": JWT_EXPIRA_MINUTOS * 60}
