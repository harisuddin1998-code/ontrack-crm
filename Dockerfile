# Dockerfile
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    unixodbc \
    unixodbc-dev \
    curl \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# The Microsoft SQL Server ODBC driver, for the SJ_MIS sync.
#
# unixodbc above is only the driver manager - it ships no driver for SQL
# Server, so without this every pyodbc.connect fails with "Can't open lib
# 'ODBC Driver 17 for SQL Server' : file not found", however the
# connection is configured.
RUN curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
      | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && echo "deb [arch=amd64,armhf,arm64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
      > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y msodbcsql17 \
    && rm -rf /var/lib/apt/lists/*

# Install wkhtmltopdf
RUN wget -q https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/wkhtmltox_0.12.6.1-3.bookworm_amd64.deb \
    && dpkg -i wkhtmltox_0.12.6.1-3.bookworm_amd64.deb || true \
    && apt-get install -f -y \
    && rm wkhtmltox_0.12.6.1-3.bookworm_amd64.deb

# Copy requirements
COPY requirements/base.txt requirements/base.txt

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements/base.txt

# Copy application
COPY . .

# Create directories
RUN mkdir -p logs uploads instance

# Expose port. PORT is honoured so a host that maps a different container
# port (the platform publishes 127.0.0.1:<host>:8000) can override it.
ENV PORT=8000
EXPOSE 8000

# Migrations and the first-boot data seed run here, before the server starts.
COPY deployment/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

# Run with gunicorn (production)
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-8000} --workers 4 --threads 2 --worker-class gthread --preload --access-logfile - --error-logfile - wsgi:app"]