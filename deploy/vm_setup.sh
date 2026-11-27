#!/usr/bin/env bash
# Deploy em uma VM Ubuntu nova, em um comando:
#   bash deploy/vm_setup.sh meu-dominio.duckdns.org
# (ou, sem clonar antes:  curl -fsSL <url-raw-deste-arquivo> | bash -s -- meu-dominio.duckdns.org)
#
# Faz: instala Docker, cria swap, clona o repositorio, gera segredos fortes,
# escreve o .env de producao, sobe a plataforma com HTTPS (Caddy) e roda o
# teste de fumaca. As credenciais da API ficam em ~/credenciais_api.txt.
set -euo pipefail

DOMINIO="${1:?Uso: bash deploy/vm_setup.sh <dominio>   (ex.: minha-plataforma.duckdns.org)}"
REPO_URL="${REPO_URL:-https://github.com/ensosampaio/sd-2026-2-kit-c3a2.git}"
PASTA="${PASTA:-$HOME/plataforma}"

echo ">> 1/6 Docker"
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sudo sh
fi
sudo apt-get install -y -qq git openssl python3-requests >/dev/null

echo ">> 2/6 Swap (o build do scikit-learn pede memoria)"
if ! swapon --show | grep -q .; then
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
  sudo mkswap /swapfile >/dev/null && sudo swapon /swapfile
fi

echo ">> 3/6 Codigo"
if [ -d "$PASTA/.git" ]; then
  git -C "$PASTA" pull --ff-only
else
  git clone "$REPO_URL" "$PASTA"
fi
cd "$PASTA"

echo ">> 4/6 Configuracao (.env de producao)"
definir() { sed -i "s|^$1=.*|$1=$2|" .env; }
if [ ! -f .env ]; then
  cp .env.example .env
  JWT="$(openssl rand -hex 32)"
  SENHA="$(openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | cut -c1-20)"
  USUARIO="operador"
  definir AMBIENTE production
  definir JWT_SEGREDO "$JWT"
  definir USUARIO_API "$USUARIO"
  definir SENHA_API "$SENHA"
  definir DOMINIO "$DOMINIO"
  definir GATEWAY_BIND 127.0.0.1
  definir CONFIAR_PROXY true
  umask 077
  printf 'URL:     https://%s\nUSUARIO: %s\nSENHA:   %s\n' "$DOMINIO" "$USUARIO" "$SENHA" > "$HOME/credenciais_api.txt"
  echo "   .env criado. Credenciais da API salvas em ~/credenciais_api.txt"
else
  echo "   .env ja existe: mantido."
fi

echo ">> 5/6 Subindo a plataforma (o primeiro build leva alguns minutos)"
sudo docker compose --profile https up --build -d

echo "   aguardando o gateway ficar saudavel..."
for _ in $(seq 1 90); do
  if curl -fsS http://127.0.0.1:8000/saude >/dev/null 2>&1; then break; fi
  sleep 5
done
sudo docker compose ps

echo ">> 6/6 Teste de fumaca (local, direto no gateway)"
if [ -f scripts/smoke_test.py ]; then
  USUARIO_API="$(grep '^USUARIO_API=' .env | cut -d= -f2)" \
  SENHA_API="$(grep '^SENHA_API=' .env | cut -d= -f2)" \
  BASE_URL=http://127.0.0.1:8000 python3 scripts/smoke_test.py \
    || echo "   (o teste de fumaca reportou falhas; veja acima e: sudo docker compose logs)"
else
  echo "   scripts/smoke_test.py ainda nao esta no repositorio: etapa ignorada."
fi

echo
echo "HTTPS publico (precisa do DNS apontando para esta VM e das portas 80/443 abertas):"
if curl -fsS "https://$DOMINIO/saude"; then
  echo
  echo "OK: https://$DOMINIO esta no ar. Coloque essa URL no README."
else
  echo "Ainda sem resposta em https://$DOMINIO. Confira o DNS do DuckDNS e o firewall (80/443)"
  echo "e veja o certificado com: sudo docker compose logs caddy"
fi
echo "Credenciais da API: cat ~/credenciais_api.txt"
