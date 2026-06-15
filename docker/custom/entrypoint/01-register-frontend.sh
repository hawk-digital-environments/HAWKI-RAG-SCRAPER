#!/bin/bash
cat > /etc/supervisor/conf.d/frontend.conf << EOF
[program:frontend]
command=node /var/www/html/ui/build
directory=/var/www/html/ui
user=www-data
environment=HOME="/tmp",PORT="${NODE_SERVICE_PORT}",ORIGIN="${ORIGIN}",CRAWLER_API_BASE_URL="${CRAWLER_API_BASE_URL}",PUBLIC_API_BASE_URL="/ui",NODE_ENV="production"
autostart=true
autorestart=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
priority=20
EOF
