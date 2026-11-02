FROM node:24-bookworm-slim AS web
WORKDIR /build
COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/package.json
RUN npm ci
COPY apps/web apps/web
RUN npm run build

FROM denoland/deno:2.9.8 AS deno

FROM python:3.12-slim-trixie
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    MEDIA_DATA_DIR=/data MEDIA_WEB_DIR=/app/web \
    MEDIA_FFMPEG_LOCATION=/opt/media-tools \
    DENO_DIR=/tmp/deno DENO_NO_UPDATE_CHECK=1 HOME=/tmp
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 10001 media && useradd -u 10001 -g media -M media \
    && mkdir -p /data /opt/media-tools && chown media:media /data
COPY scripts/check-native.py /opt/media-tools/check-native.py
RUN python /opt/media-tools/check-native.py > /opt/media-tools/native-security.json
COPY --from=deno /usr/bin/deno /usr/local/bin/deno
WORKDIR /app
LABEL org.opencontainers.image.title="vertov-dl" org.opencontainers.image.version="0.1.0-alpha.1" org.opencontainers.image.licenses="MPL-2.0"
COPY requirements.lock pyproject.toml LICENSE NOTICE.md THIRD_PARTY_NOTICES.md ./
RUN pip install --no-cache-dir -r requirements.lock
COPY LICENSES LICENSES
COPY apps/api apps/api
RUN pip install --no-cache-dir --no-deps .
COPY scripts/ffmpeg-local.py /opt/media-tools/ffmpeg
COPY scripts/ffmpeg-local.py /opt/media-tools/ffprobe
RUN chmod 755 /opt/media-tools/ffmpeg /opt/media-tools/ffprobe
COPY --from=web /build/apps/web/dist /app/web
USER 10001:10001
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:47831/healthz', timeout=3)"
CMD ["python", "-m", "media_loader"]
