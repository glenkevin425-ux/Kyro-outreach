FROM python:3.13-slim
WORKDIR /app
COPY server.py ./server.py
COPY public ./public
RUN mkdir -p /app/data && useradd --system --uid 10001 kyro && chown -R kyro:kyro /app
USER kyro
ENV HOST=0.0.0.0 \
    PORT=8000 \
    DATABASE_PATH=/app/data/kyro.sqlite3 \
    KYRO_DEMO_ENABLED=false \
    COOKIE_SECURE=true
EXPOSE 8000
CMD ["python", "server.py"]
