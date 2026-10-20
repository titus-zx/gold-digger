FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd -r -u 10001 app
COPY forecaster.py .
COPY idx_monitor ./idx_monitor
RUN mkdir -p /app/results/gold && chown -R app:app /app/results
USER app
EXPOSE 8080
CMD ["python", "-m", "idx_monitor.web"]
