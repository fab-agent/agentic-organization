# workspace-controller (ADR-0018 §1): small, single-purpose, no user-facing endpoints.
# Needs the docker CLI and access to a Docker API (a verb-filtering socket proxy in
# production). Build from the repo root:
#   docker build -f workspace-controller/Dockerfile -t fab-workspace-controller .
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends docker.io \
    && rm -rf /var/lib/apt/lists/* && pip install --no-cache-dir fastapi==0.141.1 uvicorn==0.52.4 starlette==1.6.0
WORKDIR /app
COPY workspace-controller/app.py workspace-controller/docker_ops.py workspace-controller/fileio.py /app/
USER nobody
EXPOSE 8090
CMD ["uvicorn", "--factory", "app:build_app", "--host", "0.0.0.0", "--port", "8090"]
