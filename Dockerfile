FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libseccomp2 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.13.4
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini institutions.json ./
RUN uv sync --frozen --no-dev --no-cache
RUN useradd --system --uid 10001 bridge && mkdir /data /fences && chown bridge /data /fences
USER bridge
EXPOSE 8000
CMD [".venv/bin/canvas-bridge", "serve"]
