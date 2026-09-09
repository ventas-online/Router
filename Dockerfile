FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8080

WORKDIR /app
COPY . .

RUN python -m compileall -q llmrouter server.py && \
    python -m unittest discover -s tests -p 'test_*.py'

EXPOSE 8080
CMD ["python", "server.py"]
