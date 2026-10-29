FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 OPTIFLOW_DB=/data/tasks.sqlite3
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
# Build only from the sanitized delivery archive, never from a local credential file.
COPY dist/OptiFlow-platform.zip /tmp/platform.zip
RUN python -c "import zipfile; zipfile.ZipFile('/tmp/platform.zip').extractall('/tmp/platform')" \
    && cp -a /tmp/platform/OptiFlow/. /app/ \
    && rm -rf /tmp/platform /tmp/platform.zip \
    && useradd --uid 10001 --create-home optiflow \
    && mkdir -p /data && chown -R optiflow:optiflow /app /data
USER optiflow
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4)"
CMD ["python", "run_experiment.py", "--study-server", "--workbench-host", "0.0.0.0"]
