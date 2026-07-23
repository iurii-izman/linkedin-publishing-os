FROM python:3.12.10-slim@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

RUN useradd --create-home --uid 10001 publisher
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN pip install --no-cache-dir uv==0.9.30 \
    && uv sync --frozen --no-dev --no-editable
RUN mkdir -p /var/lib/publisher/stage0 && chown -R publisher:publisher /var/lib/publisher

USER publisher
EXPOSE 8000
CMD ["uvicorn", "publisher_api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
