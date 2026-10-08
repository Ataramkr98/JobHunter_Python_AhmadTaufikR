FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt requirements-production.txt ./
RUN pip install --no-cache-dir -r requirements-production.txt
COPY . .
EXPOSE 8000
CMD ["python", "docker_entrypoint.py"]
