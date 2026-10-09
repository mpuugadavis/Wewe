FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LOG_LEVEL=INFO
WORKDIR /app/backend
COPY pyproject.toml ./
COPY app ./app
COPY tests ./tests
COPY scripts ./scripts
COPY migrations ./migrations
COPY alembic.ini ./
RUN pip install --no-cache-dir ".[test]"
RUN useradd --create-home --uid 10001 wewe && chown -R wewe:wewe /app
USER wewe
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
