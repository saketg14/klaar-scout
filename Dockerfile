# Official Playwright Python image - Chromium + all system libraries pre-installed.
# The image tag MUST match the playwright version pinned in requirements.txt.
FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Browsers are already baked into this image at /ms-playwright,
# but this guarantees the chromium build Playwright expects is present.
RUN playwright install chromium

# Copy the rest of the app
COPY . .

# Railway injects PORT at runtime; default to 8080 for local docker runs
ENV PORT=8080
EXPOSE 8080

CMD ["python", "app.py"]
