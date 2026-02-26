FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    libgmp-dev \
    pkg-config \
    autoconf \
    libtool \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY minimal_relay.py .

EXPOSE 6969

CMD ["python", "minimal_relay.py"]
