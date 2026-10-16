FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# iputils-ping / iproute2 are only used by `ouster-demo doctor`.
RUN apt-get update \
 && apt-get install -y --no-install-recommends iputils-ping iproute2 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

# Sensor UDP only works with host networking (see docker-compose.yml); the UI listens on $PORT.
ENV PORT=8080
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('PORT','8080'),timeout=3)"

ENTRYPOINT ["ouster-demo"]
CMD ["serve"]
