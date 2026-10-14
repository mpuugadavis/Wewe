FROM caddy:2-alpine AS web
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app/backend
COPY backend/requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY backend/pyproject.toml backend/alembic.ini ./
COPY backend/app ./app
COPY backend/migrations ./migrations
RUN pip install --no-cache-dir --no-deps --no-build-isolation .
COPY --from=web /usr/bin/caddy /usr/bin/caddy
# Copy without file capabilities: restricted hosts drop CAP_NET_BIND_SERVICE.
# Port 10000 does not require privileged-port capabilities.
RUN cp /usr/bin/caddy /usr/bin/caddy-nocaps && mv /usr/bin/caddy-nocaps /usr/bin/caddy
COPY frontend/index.html frontend/app.js frontend/brand.css frontend/brand-ui.js frontend/retailer-media.js /srv/
COPY frontend/assets/brand /srv/assets/brand
COPY deploy /app/deploy
RUN sed -i 's|name="wewe-api-base" content=""|name="wewe-api-base" content="/api/v1"|' /srv/index.html \
    && useradd --create-home --uid 10001 wewe && chown -R wewe:wewe /app /srv
USER wewe
EXPOSE 10000
CMD ["python", "/app/deploy/start.py"]
