FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir flask requests

COPY services/ .

ARG SERVICE_FILE
ENV SERVICE_FILE=${SERVICE_FILE}

CMD ["sh", "-c", "python ${SERVICE_FILE}"]
