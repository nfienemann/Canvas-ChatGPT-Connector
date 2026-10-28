FROM python:3.14-slim@sha256:35caba83af2fe6da9a5d922f9b0156f21d1246a48278c58a08bd253303ba42e8
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libseccomp2 libtesseract5 tesseract-ocr-eng && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.13.4
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini institutions.json ./
RUN uv sync --locked --no-dev --no-cache
RUN useradd --system --uid 10001 bridge && mkdir /data /fences && mkdir -m 700 /opt/canvas-parser && chown bridge /data /fences /opt/canvas-parser
USER bridge
RUN .venv/bin/python -c "from pathlib import Path; from canvas_bridge.linux_sandbox import ensure_runtime; root = Path('/opt/canvas-parser'); ensure_runtime(root); ensure_runtime(root, Path('/usr/share/tesseract-ocr/5'))"
ENV BRIDGE_PARSER_RUNTIME_ROOT=/opt/canvas-parser BRIDGE_OCR_ROOT=/usr/share/tesseract-ocr/5
EXPOSE 8000
CMD [".venv/bin/canvas-bridge", "serve"]
