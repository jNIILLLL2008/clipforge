# ClipForge -- one image running the API, the render workers and the scheduler.
#
# ffmpeg is the reason this cannot go on a serverless host: renders take
# minutes, need a real filesystem, and run in background threads. Any platform
# that can run a container with a persistent volume will do.

FROM python:3.12-slim

# ffmpeg does the encoding; fonts are needed because the overlay burns text in
# with libass and would otherwise fall back to nothing on a bare image.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        fonts-dejavu-core \
        fonts-liberation \
        ca-certificates \
        gosu \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first, so a code change does not reinstall them.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Storage is a volume in production; this only creates the mount points.
RUN mkdir -p /app/storage/uploads /app/storage/renders /app/storage/cache

# Renders are driven from user-supplied files, so the process must not be root
# if ffmpeg is ever made to misbehave. The container still STARTS as root so
# the entrypoint can take ownership of a freshly mounted volume, then hands
# over to this user with gosu. There is no USER line for that reason.
RUN useradd --create-home --uid 10001 clipforge \
    && chown -R clipforge:clipforge /app

COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["docker-entrypoint.sh"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request,sys; \
        port=os.environ.get('PORT','8000'); \
        sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=4).status == 200 else 1)"

# ONE web process on purpose. The render queue and the daily scheduler live
# in-process, so a second worker would mean a second scheduler and an account
# could publish twice a day. To scale, run one instance with RUN_SCHEDULER=true
# and the rest with it false.
#
# Shell form, not exec form, so ${PORT} expands. Railway, Render, Fly and
# Heroku all assign a port at runtime and route to that one; binding a
# hardcoded 8000 leaves the proxy talking to nothing and returning 502.
CMD uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000}
