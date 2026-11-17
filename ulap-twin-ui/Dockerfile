# twin-web: the frontend of the Ulap twin demo on Amini Cloud.
# Standard library only. data.js (licence-restricted footprints) is left out on purpose:
# the viewer's data comes from twin-api.
FROM python:3.13.9-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY server.py twin-status.js index.html scene.html app.js scene.js anime.min.js three.min.js \
     OrbitControls.js BufferGeometryUtils.js icon-white.svg wordmark-white.svg ./
RUN useradd --uid 10001 --no-create-home twin
USER twin
EXPOSE 8080
CMD ["python", "server.py"]
