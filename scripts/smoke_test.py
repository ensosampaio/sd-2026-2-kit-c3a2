"""Teste de fumaca da plataforma, sempre pelo gateway.

Uso local:    python scripts/smoke_test.py
Uso no deploy: BASE_URL=https://seu-dominio SENHA_API=... USUARIO_API=... python scripts/smoke_test.py

Valida: saude, 401 sem token, login, fila assincrona (POST /predict -> worker ->
GET /resultado), 404 para id inexistente. Sai com codigo 1 se algo falhar.
Requer apenas: pip install requests
"""
import os
import sys
import time

import requests

BASE = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")
USUARIO = os.getenv("USUARIO_API", "admin")
SENHA = os.getenv("SENHA_API", "troque-esta-senha")
falhas = []


def checar(descricao, condicao, detalhe=""):
    print(("PASS " if condicao else "FAIL ") + descricao + (f"  [{detalhe}]" if detalhe else ""))
    if not condicao:
        falhas.append(descricao)


def main() -> int:
    r = requests.get(f"{BASE}/saude", timeout=10)
    checar("GET /saude responde 200", r.status_code == 200, r.text[:80])

    r = requests.post(f"{BASE}/predict", json={"texto": "teste"}, timeout=10)
    checar("POST /predict sem token -> 401", r.status_code == 401)

    r = requests.post(f"{BASE}/login", json={"usuario": USUARIO, "senha": "senha-errada"}, timeout=10)
    checar("login com senha errada -> 401", r.status_code == 401)

    r = requests.post(f"{BASE}/login", json={"usuario": USUARIO, "senha": SENHA}, timeout=10)
    checar("login valido -> 200 com token", r.status_code == 200 and "access_token" in r.json(), f"HTTP {r.status_code}")
    if r.status_code != 200:
        print("Sem token nao ha como continuar (confira USUARIO_API/SENHA_API).")
        return 1
    auth = {"Authorization": f"Bearer {r.json()['access_token']}"}

    r = requests.post(f"{BASE}/predict", json={"texto": "o atendimento foi excelente"}, headers=auth, timeout=10)
    checar("POST /predict autenticado -> 202 com id", r.status_code == 202 and "id" in r.json(), f"HTTP {r.status_code}")
    if r.status_code == 202:
        tarefa_id = r.json()["id"]
        resultado = {}
        for _ in range(30):
            resultado = requests.get(f"{BASE}/resultado/{tarefa_id}", headers=auth, timeout=10).json()
            if resultado.get("status") == "pronto":
                break
            time.sleep(0.5)
        checar("worker processou e GET /resultado -> pronto", resultado.get("status") == "pronto", str(resultado)[:100])
        checar("sentimento esperado (positivo)", resultado.get("sentimento") == "positivo")

    r = requests.get(f"{BASE}/resultado/id-inexistente", headers=auth, timeout=10)
    checar("GET /resultado de id inexistente -> 404", r.status_code == 404)

    print("\nFALHAS: " + (", ".join(falhas) if falhas else "nenhuma"))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
