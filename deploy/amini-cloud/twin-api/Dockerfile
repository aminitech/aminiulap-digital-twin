# twin-api: the backend of the Ulap twin demo on Amini Cloud.
FROM python:3.13.9-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app.py seed.json ./
RUN useradd --uid 10001 --no-create-home twin
USER twin
EXPOSE 8080
CMD ["python", "app.py"]
