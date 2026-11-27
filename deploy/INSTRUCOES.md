# Deploy em nuvem (free tier) com HTTPS

A plataforma inteira (gateway, inferência, worker, Redis, coletor de traces) roda
com o mesmo `docker-compose.yml`, numa única VM gratuita. O **Caddy** (perfil
`https`) obtém e renova sozinho o certificado Let's Encrypt.

## 1. VM e domínio

1. Crie uma VM Ubuntu 22.04 num free tier (Oracle Cloud *Always Free*, AWS EC2
   `t2.micro`/`t3.micro` ou GCP `e2-micro`). Prefira 1 GB de RAM ou mais.
2. No firewall/security group da nuvem, libere **22, 80 e 443**. Não libere 8000.
3. Crie um subdomínio gratuito em [duckdns.org](https://www.duckdns.org) apontando
   para o **IP público** da VM (ex.: `minha-plataforma.duckdns.org`).

## Atalho: tudo em um comando (recomendado)

Com a VM criada, as portas 22/80/443 liberadas e o DuckDNS apontando para o IP dela,
conecte por SSH (ou pelo terminal no navegador da nuvem) e rode:

```bash
curl -fsSL https://raw.githubusercontent.com/ensosampaio/sd-2026-2-kit-c3a2/main/deploy/vm_setup.sh | bash -s -- minha-plataforma.duckdns.org
```

O script instala o Docker, cria swap, clona o repositório, **gera segredos fortes**,
escreve o `.env` de produção, sobe tudo com HTTPS e roda o teste de fumaca. Usuário e
senha da API ficam em `~/credenciais_api.txt` (`cat ~/credenciais_api.txt`).
Os passos 2 e 3 abaixo são o mesmo processo, feito à mão.

## 2. Instalar e configurar (na VM)

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker

# VM com pouca RAM: crie 2 GB de swap para o build do scikit-learn
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile

git clone https://github.com/ensosampaio/sd-2026-2-kit-c3a2.git
cd sd-2026-2-kit-c3a2
cp .env.example .env
nano .env
```

No `.env`, defina **obrigatoriamente**:

```
AMBIENTE=production
JWT_SEGREDO=<saida de: openssl rand -hex 32>
USUARIO_API=<um usuario que nao seja "admin">
SENHA_API=<senha com 12+ caracteres>
DOMINIO=minha-plataforma.duckdns.org
GATEWAY_BIND=127.0.0.1
CONFIAR_PROXY=true
```

Com `AMBIENTE=production` o gateway **recusa subir** se o segredo/senha forem
fracos ou padrão. `GATEWAY_BIND=127.0.0.1` garante que só o Caddy fale com o
gateway (assim ninguém falsifica `X-Forwarded-For` para burlar o rate limit).

## 3. Subir

```bash
docker compose --profile https up --build -d
docker compose ps            # tudo "healthy"/"running"
```

## 4. Validar

De qualquer máquina:

```bash
pip install requests
BASE_URL=https://minha-plataforma.duckdns.org USUARIO_API=<usuario> SENHA_API=<senha> \
  python scripts/smoke_test.py
```

O teste confere HTTPS, 401 sem token, login, fila assíncrona (gateway → inferência →
Redis → worker) e 404. Depois **escreva a URL pública no README**.

Para ver o rastreamento distribuído: `docker compose logs otel-collector`.

## Alternativas

Render/Railway/Fly publicam bem o gateway, mas o worker e o Redis precisam de
serviços adicionais (muitas vezes pagos). A VM única mantém a arquitetura idêntica
à do `docker compose` local.
