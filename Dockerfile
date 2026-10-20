FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN pip install --no-cache-dir uv==0.13.4
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-cache
COPY migrations ./migrations
COPY alembic.ini institutions.json ./
RUN useradd --system --uid 10001 bridge && mkdir /data /fences && chown bridge /data /fences
USER bridge
EXPOSE 8000
CMD [".venv/bin/canvas-bridge", "serve"]
