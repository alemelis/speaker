FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY tag-organizer/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY tag-organizer/app /app/app
COPY shared/fomo.css /app/app/static/fomo.css
COPY shared/db.py /app/db.py

EXPOSE 3040

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3040"]
