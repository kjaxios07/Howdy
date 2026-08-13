# Multi-stage: build wheels, then ship a slim runtime with no compiler on it.
FROM python:3.12-slim AS build

RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt


FROM python:3.12-slim

# Non-root from the start — uid is fixed so volume permissions are predictable.
RUN groupadd -g 10001 kip && useradd -u 10001 -g kip -m -s /usr/sbin/nologin kip

WORKDIR /srv
COPY --from=build /wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
 && rm -rf /wheels

COPY --chown=kip:kip app ./app

USER kip
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status==200 else 1)"

# Two uvicorn workers is right for a 2-vCPU box; raise with the core count.
CMD ["gunicorn", "app.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "2", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "60", \
     "--graceful-timeout", "30", \
     "--access-logfile", "-", \
     "--access-logformat", "%(h)s %(m)s %(U)s %(s)s %(M)sms"]
