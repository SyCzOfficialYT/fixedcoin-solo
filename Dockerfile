FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates wget tar \
    && rm -rf /var/lib/apt/lists/*

ARG FIX_VER=29.1.3
RUN mkdir -p /opt/fixedcoin \
 && curl -fsSL -o /tmp/fix.tgz \
    "https://github.com/Fixed-Blockchain/fixedcoin/releases/download/v${FIX_VER}/fixedcoin-${FIX_VER}-x86_64-linux-gnu.tar.gz" \
 && tar -xzf /tmp/fix.tgz -C /opt/fixedcoin --strip-components=1 \
 && rm /tmp/fix.tgz \
 && ln -sf /opt/fixedcoin/bin/fixedcoind /usr/local/bin/fixedcoind \
 && ln -sf /opt/fixedcoin/bin/fixedcoin-cli /usr/local/bin/fixedcoin-cli

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app
RUN chmod +x /app/docker/entrypoint.sh

ENV FIX_DATADIR=/data/fixedcoin
EXPOSE 3333 5050 24768
ENTRYPOINT ["/app/docker/entrypoint.sh"]
