# Works on Raspberry Pi and x86; Docker Hub provides multi-arch images
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# System deps: libevdev for python-evdev, and lsinput utilities are not required.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential \
      libevdev2 \
      curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# If you have a requirements.txt, keep this for layer caching
# (evdev, pyyaml, requests are needed for your script)
COPY requirements.txt /app/requirements.txt
RUN pip install -r requirements.txt

# If you don't keep a requirements.txt, uncomment the next line instead:
# RUN pip install evdev pyyaml requests

# Copy your daemon
COPY daemon.py /app/app.py

# Run as root to ensure read access to /dev/input (simplest).
# If you prefer non-root, you'll need to align group IDs to 'input'.
# USER appuser

CMD ["python", "app.py"]

