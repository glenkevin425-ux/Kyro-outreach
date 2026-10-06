FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PYTHONUNBUFFERED=1
ENV PORT=8000
ENV DATABASE_PATH=/app/data/kyro.sqlite3
RUN mkdir -p /app/data
EXPOSE 8000
CMD ["python","server.py"]