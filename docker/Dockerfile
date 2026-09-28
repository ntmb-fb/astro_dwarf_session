# Smartscope Session as a headless web server (e.g. on a Synology NAS).
# Build from the repository root:  docker build -f docker/Dockerfile -t smartscope-session .
FROM python:3.12-slim

# ffmpeg: live RTSP camera preview. tzdata: the scheduler runs on local time (set TZ).
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg tzdata git \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements-local.txt requirements-smartscopes.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-smartscopes.txt \
 # The Dwarf library is installed into the app folder, as upstream requires.
 && pip install --no-cache-dir --no-deps -r requirements-local.txt --target /app \
 # dwarf_python_api 3.1.1 ships one Latin-1 file that Python refuses to import;
 # convert it when needed (no-op once fixed upstream).
 && f=/app/dwarf_python_api/lib/websockets_testV2.py \
 && if [ -f "$f" ] && ! python -c "import ast,sys; ast.parse(open(sys.argv[1],'rb').read())" "$f" 2>/dev/null; then \
      iconv -f latin1 -t utf-8 "$f" > /tmp/f && mv /tmp/f "$f"; fi \
 && apt-get purge -y git && apt-get autoremove -y

COPY . /app

# Everything the app writes (device configs, Sites, program queues, logs,
# HTTPS certificates) lands in the working directory: keep it on a volume.
WORKDIR /data
VOLUME /data
ENV PYTHONUNBUFFERED=1 \
    TZ=Europe/Copenhagen \
    PORT=8765 \
    SMARTSCOPE_CERT_DIR=/data/https

EXPOSE 8765 8443
CMD ["sh", "-c", "exec python /app/astro_dwarf_ui.py --no_native --host 0.0.0.0 --port ${PORT}"]
