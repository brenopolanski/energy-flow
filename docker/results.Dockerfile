FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

EXPOSE 8003

CMD ["uvicorn", "results_service.app:app", "--host", "0.0.0.0", "--port", "8003", "--no-access-log"]
