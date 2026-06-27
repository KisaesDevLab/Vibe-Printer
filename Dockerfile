# syntax=docker/dockerfile:1
# Multi-arch (arm64 Pi / amd64 NucBox). Bundles WeasyPrint native libs + fonts, libusb, CUPS.

# --- Stage 1: build the admin UI ---
FROM node:20-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm install
COPY web/ ./
RUN npm run build   # emits to /app/static via vite outDir (../app/static)

# --- Stage 2: python runtime ---
FROM python:3.12-slim-bookworm AS runtime

# WeasyPrint (pango/cairo/gdk-pixbuf), fonts, libusb, CUPS client + server.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 \
      libffi8 fonts-dejavu fonts-liberation \
      libusb-1.0-0 \
      cups cups-client libcups2 \
      && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir ".[pdf,cups,usb,access,encrypt]"

# Built UI from stage 1
COPY --from=web /app/static ./app/static

ENV VIBE_PRINT_DATA_DIR=/data
VOLUME ["/data"]
EXPOSE 8080

# CUPS binds to localhost only (P30.3); started by the entrypoint when present.
COPY deploy/cupsd.conf /etc/cups/cupsd.conf
COPY deploy/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8080/readyz').status==200 else 1)" || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", \
     "--forwarded-allow-ips", "127.0.0.1"]
