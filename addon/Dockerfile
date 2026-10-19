FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app /app/app

COPY run.sh /run.sh
RUN chmod +x /run.sh

ENV CONFIG_PATH=/data/config.json
ENV LOG_LEVEL=info

EXPOSE 8099

CMD ["/run.sh"]
