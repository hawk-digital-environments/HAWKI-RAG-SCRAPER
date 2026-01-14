# Deployment Guide

This guide covers deploying the Crawl4AI FastAPI service in production environments.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Docker Deployment](#docker-deployment)
- [Systemd Service](#systemd-service)
- [Reverse Proxy (Nginx)](#reverse-proxy-nginx)
- [SSL/TLS Configuration](#ssltls-configuration)
- [Kubernetes Deployment](#kubernetes-deployment)
- [Monitoring & Logging](#monitoring--logging)
- [Backup Strategy](#backup-strategy)
- [Security Hardening](#security-hardening)

---

## Prerequisites

### System Requirements

**Minimum**:
- CPU: 2 cores
- RAM: 4 GB
- Disk: 20 GB SSD
- OS: Linux (Ubuntu 20.04+, CentOS 8+) or macOS

**Recommended**:
- CPU: 4+ cores
- RAM: 8+ GB
- Disk: 100+ GB SSD
- OS: Linux (Ubuntu 22.04 LTS)

### Software Requirements

- Python 3.9+
- Docker & Docker Compose (for containerized deployment)
- Nginx (for reverse proxy)
- Playwright browsers

---

## Docker Deployment

### Using Docker Compose (Recommended)

#### 1. Project Structure

```
crawler/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── main.py
├── models.py
├── crawler_service.py
└── .env
```

#### 2. Create .env File

```bash
# .env
CRAWL4AI_API_TOKEN=your_secure_token_here
MAX_CONCURRENT_TASKS=5
LOG_LEVEL=INFO
```

#### 3. Docker Compose Configuration

```yaml
# docker-compose.yml
version: '3.8'

services:
  crawler:
    build: .
    container_name: crawl4ai-service
    ports:
      - "8000:8000"
    volumes:
      - ./output:/app/output
      - ./logs:/app/logs
    environment:
      - CRAWL4AI_API_TOKEN=${CRAWL4AI_API_TOKEN}
      - MAX_CONCURRENT_TASKS=${MAX_CONCURRENT_TASKS}
      - LOG_LEVEL=${LOG_LEVEL}
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
```

#### 4. Build and Run

```bash
# Build the image
docker-compose build

# Start the service
docker-compose up -d

# View logs
docker-compose logs -f

# Stop the service
docker-compose down
```

#### 5. Verify Deployment

```bash
# Check if container is running
docker-compose ps

# Test health endpoint
curl http://localhost:8000/health

# Test API
curl -X POST http://localhost:8000/crawl \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "max_pages": 5}'
```

### Production Dockerfile

```dockerfile
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    ca-certificates \
    procps \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libdbus-1-3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium
RUN playwright install-deps chromium

# Copy application code
COPY main.py models.py crawler_service.py ./

# Create output directory
RUN mkdir -p /app/output

# Create non-root user
RUN useradd -m -u 1000 crawler && \
    chown -R crawler:crawler /app

# Switch to non-root user
USER crawler

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Run application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

---

## Systemd Service

### 1. Create Service File

```bash
sudo nano /etc/systemd/system/crawler.service
```

```ini
[Unit]
Description=Crawl4AI FastAPI Service
After=network.target

[Service]
Type=simple
User=crawler
Group=crawler
WorkingDirectory=/opt/crawler
Environment="PATH=/opt/crawler/env/bin"
ExecStart=/opt/crawler/env/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
Restart=always
RestartSec=10
StandardOutput=append:/var/log/crawler/access.log
StandardError=append:/var/log/crawler/error.log

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/crawler/output /var/log/crawler

[Install]
WantedBy=multi-user.target
```

### 2. Setup Deployment

```bash
# Create user
sudo useradd -r -s /bin/false crawler

# Create directories
sudo mkdir -p /opt/crawler
sudo mkdir -p /var/log/crawler

# Copy application files
sudo cp -r /path/to/your/crawler/* /opt/crawler/

# Set permissions
sudo chown -R crawler:crawler /opt/crawler
sudo chown -R crawler:crawler /var/log/crawler
sudo chmod 750 /opt/crawler

# Create virtual environment
sudo -u crawler python3 -m venv /opt/crawler/env
sudo -u crawler /opt/crawler/env/bin/pip install -r /opt/crawler/requirements.txt
sudo -u crawler /opt/crawler/env/bin/playwright install chromium
```

### 3. Start Service

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable service (start on boot)
sudo systemctl enable crawler.service

# Start service
sudo systemctl start crawler.service

# Check status
sudo systemctl status crawler.service

# View logs
sudo journalctl -u crawler.service -f
```

### 4. Service Management

```bash
# Stop service
sudo systemctl stop crawler.service

# Restart service
sudo systemctl restart crawler.service

# Reload configuration
sudo systemctl reload crawler.service

# Disable service
sudo systemctl disable crawler.service
```

---

## Reverse Proxy (Nginx)

### 1. Install Nginx

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install nginx

# CentOS/RHEL
sudo yum install nginx
```

### 2. Configure Nginx

```bash
sudo nano /etc/nginx/sites-available/crawler
```

```nginx
# /etc/nginx/sites-available/crawler

upstream crawler_backend {
    server localhost:8000;
    # Add more servers for load balancing
    # server localhost:8001;
    # server localhost:8002;
}

# Rate limiting zone
limit_req_zone $binary_remote_addr zone=crawler_limit:10m rate=10r/s;

server {
    listen 80;
    server_name crawler.example.com;

    # Redirect to HTTPS (after SSL setup)
    # return 301 https://$server_name$request_uri;

    # Client request limits
    client_max_body_size 10M;
    client_body_timeout 30s;
    client_header_timeout 30s;

    # Logging
    access_log /var/log/nginx/crawler-access.log;
    error_log /var/log/nginx/crawler-error.log;

    location / {
        # Rate limiting
        limit_req zone=crawler_limit burst=20 nodelay;

        # Proxy headers
        proxy_pass http://crawler_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 300s;  # Long timeout for crawl jobs
    }

    # Health check endpoint (no rate limiting)
    location /health {
        proxy_pass http://crawler_backend;
        access_log off;
    }

    # API documentation (optional: restrict access)
    location /docs {
        # Allow only specific IPs
        # allow 192.168.1.0/24;
        # deny all;

        proxy_pass http://crawler_backend;
    }
}
```

### 3. Enable Site

```bash
# Create symlink
sudo ln -s /etc/nginx/sites-available/crawler /etc/nginx/sites-enabled/

# Test configuration
sudo nginx -t

# Reload Nginx
sudo systemctl reload nginx
```

---

## SSL/TLS Configuration

### Using Let's Encrypt (Certbot)

#### 1. Install Certbot

```bash
# Ubuntu/Debian
sudo apt-get install certbot python3-certbot-nginx

# CentOS/RHEL
sudo yum install certbot python3-certbot-nginx
```

#### 2. Obtain Certificate

```bash
sudo certbot --nginx -d crawler.example.com
```

#### 3. Updated Nginx Configuration (After SSL)

Certbot automatically updates the configuration. Verify:

```nginx
server {
    listen 443 ssl http2;
    server_name crawler.example.com;

    # SSL certificates (managed by Certbot)
    ssl_certificate /etc/letsencrypt/live/crawler.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/crawler.example.com/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # Rest of configuration...
    location / {
        proxy_pass http://crawler_backend;
        # ... proxy settings
    }
}

# HTTP to HTTPS redirect
server {
    listen 80;
    server_name crawler.example.com;
    return 301 https://$server_name$request_uri;
}
```

#### 4. Auto-Renewal

Certbot installs a cron job or systemd timer for auto-renewal. Verify:

```bash
# Test renewal
sudo certbot renew --dry-run

# Check timer (systemd)
sudo systemctl status certbot.timer
```

---

## Kubernetes Deployment

### 1. Deployment YAML

```yaml
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: crawler-deployment
  labels:
    app: crawler
spec:
  replicas: 3
  selector:
    matchLabels:
      app: crawler
  template:
    metadata:
      labels:
        app: crawler
    spec:
      containers:
      - name: crawler
        image: your-registry/crawler:latest
        ports:
        - containerPort: 8000
        env:
        - name: CRAWL4AI_API_TOKEN
          valueFrom:
            secretKeyRef:
              name: crawler-secrets
              key: api-token
        - name: MAX_CONCURRENT_TASKS
          value: "5"
        - name: LOG_LEVEL
          value: "INFO"
        resources:
          requests:
            memory: "2Gi"
            cpu: "1000m"
          limits:
            memory: "4Gi"
            cpu: "2000m"
        volumeMounts:
        - name: output
          mountPath: /app/output
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 20
          periodSeconds: 5
      volumes:
      - name: output
        persistentVolumeClaim:
          claimName: crawler-pvc
---
apiVersion: v1
kind: Service
metadata:
  name: crawler-service
spec:
  selector:
    app: crawler
  ports:
  - protocol: TCP
    port: 80
    targetPort: 8000
  type: LoadBalancer
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: crawler-pvc
spec:
  accessModes:
  - ReadWriteMany
  resources:
    requests:
      storage: 100Gi
---
apiVersion: v1
kind: Secret
metadata:
  name: crawler-secrets
type: Opaque
stringData:
  api-token: your_secure_token_here
```

### 2. Deploy to Kubernetes

```bash
# Apply configuration
kubectl apply -f deployment.yaml

# Check deployment
kubectl get deployments
kubectl get pods
kubectl get services

# View logs
kubectl logs -f deployment/crawler-deployment

# Scale deployment
kubectl scale deployment/crawler-deployment --replicas=5
```

---

## Monitoring & Logging

### 1. Application Logging

Add structured logging to the application:

```python
# Add to main.py
import logging
from logging.handlers import RotatingFileHandler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(
            'crawler.log',
            maxBytes=10485760,  # 10MB
            backupCount=5
        ),
        logging.StreamHandler()
    ]
)
```

### 2. Prometheus Metrics

Install prometheus-fastapi-instrumentator:

```bash
pip install prometheus-fastapi-instrumentator
```

```python
# Add to main.py
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(...)

# Add Prometheus metrics
Instrumentator().instrument(app).expose(app)
```

### 3. Health Monitoring

Use monitoring tools:

```bash
# Basic monitoring with cron
*/5 * * * * curl -f http://localhost:8000/health || echo "Service down" | mail -s "Crawler Alert" admin@example.com
```

### 4. Log Aggregation (ELK Stack)

Configure Filebeat to ship logs to Elasticsearch:

```yaml
# filebeat.yml
filebeat.inputs:
- type: log
  enabled: true
  paths:
    - /var/log/crawler/*.log
  fields:
    service: crawler

output.elasticsearch:
  hosts: ["localhost:9200"]
```

---

## Backup Strategy

### 1. Output Data Backup

```bash
#!/bin/bash
# backup.sh

BACKUP_DIR="/backups/crawler"
OUTPUT_DIR="/opt/crawler/output"
DATE=$(date +%Y%m%d_%H%M%S)

# Create backup
tar -czf "${BACKUP_DIR}/crawler_output_${DATE}.tar.gz" "${OUTPUT_DIR}"

# Remove backups older than 30 days
find "${BACKUP_DIR}" -name "crawler_output_*.tar.gz" -mtime +30 -delete
```

Schedule with cron:

```bash
# Daily backup at 2 AM
0 2 * * * /opt/crawler/backup.sh
```

### 2. Database Backup (If Extended)

```bash
# PostgreSQL backup
pg_dump crawler_db > /backups/crawler_db_$(date +%Y%m%d).sql

```

---

## Security Hardening

### 1. Firewall Configuration

```bash
# UFW (Ubuntu)
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP
sudo ufw allow 443/tcp   # HTTPS
sudo ufw enable

# Deny direct access to application port
sudo ufw deny 8000/tcp
```

### 2. SELinux (CentOS/RHEL)

```bash
# Allow Nginx to connect to network
sudo setsebool -P httpd_can_network_connect 1
```

### 3. Fail2Ban

```bash
# Install Fail2Ban
sudo apt-get install fail2ban

# Configure jail for Nginx
sudo nano /etc/fail2ban/jail.local
```

```ini
[nginx-crawler]
enabled = true
port = http,https
filter = nginx-crawler
logpath = /var/log/nginx/crawler-error.log
maxretry = 5
bantime = 3600
```

### 4. API Authentication (Recommended)

Add API key authentication:

```python
# Add to main.py
from fastapi import Security, HTTPException
from fastapi.security.api_key import APIKeyHeader

API_KEY = os.getenv("API_KEY", "your-secret-key")
api_key_header = APIKeyHeader(name="X-API-Key")

def verify_api_key(api_key: str = Security(api_key_header)):
    if api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return api_key

@app.post("/crawl")
async def crawl(config: CrawlConfig, api_key: str = Security(verify_api_key)):
    # ... existing code
```

---

## Troubleshooting

### Common Issues

1. **Playwright installation fails**
   ```bash
   playwright install-deps chromium
   ```

2. **Permission denied errors**
   ```bash
   sudo chown -R crawler:crawler /opt/crawler
   sudo chmod -R 755 /opt/crawler/output
   ```

3. **Out of memory**
   - Reduce `max_concurrency`
   - Add swap space
   - Increase server RAM

4. **Service won't start**
   ```bash
   sudo journalctl -u crawler.service -n 50
   ```

---

## Deployment Checklist

- [ ] System requirements met
- [ ] Python dependencies installed
- [ ] Playwright browsers installed
- [ ] Environment variables configured
- [ ] Output directories created with correct permissions
- [ ] Service configured (Docker/systemd)
- [ ] Reverse proxy configured (Nginx)
- [ ] SSL/TLS certificates installed
- [ ] Firewall rules configured
- [ ] Monitoring setup
- [ ] Backup strategy implemented
- [ ] Health checks verified
- [ ] Security hardening applied
- [ ] Documentation reviewed

---

## Production Ready Configuration

Example production `docker-compose.yml`:

```yaml
version: '3.8'

services:
  crawler:
    build: .
    container_name: crawl4ai-service
    ports:
      - "127.0.0.1:8000:8000"  # Bind to localhost only
    volumes:
      - ./output:/app/output:rw
      - ./logs:/app/logs:rw
    environment:
      - CRAWL4AI_API_TOKEN=${CRAWL4AI_API_TOKEN}
      - MAX_CONCURRENT_TASKS=5
      - LOG_LEVEL=INFO
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: '4'
          memory: 8G
        reservations:
          cpus: '2'
          memory: 4G
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

Your service is now ready for production deployment!
