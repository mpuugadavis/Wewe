FROM caddy:2-alpine
COPY Caddyfile /etc/caddy/Caddyfile
COPY index.html app.js brand.css brand-ui.js retailer-media.js /srv/
COPY assets /srv/assets
RUN sed -i 's|name="wewe-api-base" content=""|name="wewe-api-base" content="/api/v1"|' /srv/index.html
