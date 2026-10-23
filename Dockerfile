# Linux single-instance runtime. Override these with reviewed image digests
# before a release; no image was pulled or built during template validation.
ARG NODE_IMAGE=node:24-bookworm-slim
ARG PYTHON_IMAGE=python:3.13-slim-bookworm

FROM ${NODE_IMAGE} AS frontend-build
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM ${PYTHON_IMAGE} AS app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHON_DOTENV_DISABLED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.lock.txt ./
RUN python -m pip install --no-cache-dir --require-hashes --only-binary=:all: -r requirements.lock.txt \
    && groupadd --gid 10001 sprite \
    && useradd --uid 10001 --gid 10001 --no-create-home sprite \
    && mkdir -p /var/lib/knowledge-sprite /var/backups/knowledge-sprite \
    && chown 10001:10001 /var/lib/knowledge-sprite /var/backups/knowledge-sprite
COPY backend/ ./backend/
COPY --from=frontend-build /build/frontend/dist/ ./frontend/dist/
COPY deploy/app-entrypoint.py deploy/app-healthcheck.py deploy/app-backup.py ./deploy/
USER 10001:10001
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "/app/deploy/app-healthcheck.py"]
ENTRYPOINT ["python", "/app/deploy/app-entrypoint.py"]
