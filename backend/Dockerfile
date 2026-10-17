FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as an unprivileged user that owns the two directories the app writes
# (logs/ holds the audit fallback sink, data/ local blobs). The Helm chart runs
# the pod as uid 1000; without this they were root-owned and unwritable.
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin kaeos \
    && mkdir -p /app/logs /app/data \
    && chown -R kaeos:kaeos /app/logs /app/data
USER 1000

# 8001 everywhere: dev compose maps 8001:8001 and health-checks :8001, the
# frontend's VITE_API_BASE targets backend:8001, and all docs say 8001. The
# previous 8000 here meant the container ran but nothing could reach it.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
