FROM node:20-slim

# seekdb's Linux binding links against libaio.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libaio1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
