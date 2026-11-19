FROM python:3.12-slim
WORKDIR /cluster
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py *.sql ./
CMD ["uvicorn","server:app","--host","0.0.0.0","--port","8788","--no-access-log"]
