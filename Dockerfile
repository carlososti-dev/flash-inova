# Imagem de produção: o backend (FastAPI) entrega a API e o app React num único serviço.
# Build:  docker build -t flash-inova .
# Migrações (mesma imagem): docker run --env-file prod.env flash-inova alembic upgrade head

FROM node:20-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080 \
    FRONTEND_DIST=/app/frontend-dist ALLOW_TENANT_OVERRIDE=false COOKIE_SECURE=true PUBLIC_SCHEME=https
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=frontend /frontend/dist ./frontend-dist
RUN useradd --system --uid 10001 flash && mkdir -p storage storage_private && chown -R flash storage storage_private
USER flash
EXPOSE 8080
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'
