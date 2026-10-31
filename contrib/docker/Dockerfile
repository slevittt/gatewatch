FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY . /src
RUN pip install --no-cache-dir .
ENV GATEWATCH_CONFIG=/config/gatewatch.ini
VOLUME ["/var/lib/gatewatch", "/config"]
EXPOSE 10813 8094
CMD ["gatewatch", "relay"]
