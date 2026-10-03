# Form Finder, with the browser add-on (Chromium) included.
# Playwright's image already contains Chromium; the pinned playwright version must match its tag.
FROM mcr.microsoft.com/playwright/python:v1.56.0-noble

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt "playwright==1.56.0"

COPY app ./app

# Templates and the knowledge base. Mount a volume here to keep them across restarts.
ENV DATA_DIR=/data
VOLUME /data

# Hosting providers set PORT; 8000 locally.
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
