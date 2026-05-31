FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY fomo-ui/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY core /app/core
COPY fomo-ui/app /app/app

EXPOSE 3050

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3050"]
