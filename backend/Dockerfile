FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 8001 everywhere: dev compose maps 8001:8001 and health-checks :8001, the
# frontend's VITE_API_BASE targets backend:8001, and all docs say 8001. The
# previous 8000 here meant the container ran but nothing could reach it.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
