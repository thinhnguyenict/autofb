FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        libglib2.0-0 \
        libgl1 \
        libsm6 \
        libxext6 \
        libxrender1 \
        php-cli \
        php-curl \
        php-mbstring \
        php-xml \
        php-zip \
    && rm -rf /var/lib/apt/lists/*

COPY reqs.txt /tmp/reqs.txt
RUN pip install -r /tmp/reqs.txt

COPY . .
COPY docker-entrypoint.sh /usr/local/bin/autofb-entrypoint
RUN chmod +x /usr/local/bin/autofb-entrypoint

EXPOSE 8000

ENTRYPOINT ["autofb-entrypoint"]
