FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LOG_LEVEL=INFO \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10
WORKDIR /app/backend
COPY pyproject.toml ./
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel --retries 10 --timeout 120 \
    && python -m pip install --no-cache-dir --no-build-isolation . --retries 10 --timeout 120
RUN useradd --create-home --uid 10001 wewe && chown -R wewe:wewe /app
USER wewe
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
