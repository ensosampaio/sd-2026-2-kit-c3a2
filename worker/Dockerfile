FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Treina o modelo no build para a imagem subir pronta (sem internet).
RUN python -c "from app.modelo import carregar_modelo; carregar_modelo()"

# Worker nao expoe porta: apenas consome a fila (Redis).
CMD ["python", "-m", "app.worker"]
