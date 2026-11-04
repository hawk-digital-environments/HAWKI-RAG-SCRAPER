#!/bin/bash
# Registers the SvelteKit (adapter-node) frontend as a supervisor program.
# The ".mode-web" filename marker keeps the web UI out of worker/build runs.

# Derive the frontend's NODE_ENV from ENVIRONMENT the same way the neunerlei
# images derive their framework variables.
frontend_node_env="production"
if [ "${ENVIRONMENT:-production}" = "development" ] || [ "${ENVIRONMENT:-production}" = "dev" ]; then
    frontend_node_env="development"
fi

# The fallbacks below mirror the defaults in custom/env/10-service.env and
# only apply when that file is absent or leaves the variable unset.
cat > /etc/supervisor/conf.d/frontend.conf << EOF
[program:frontend]
command=node /var/www/html/ui/build
directory=/var/www/html/ui
user=www-data
environment=HOME="/tmp",PORT="${NODE_SERVICE_PORT:-3000}",ORIGIN="${ORIGIN:-http://localhost:80}",CRAWLER_API_BASE_URL="${CRAWLER_API_BASE_URL:-http://localhost:80}",PUBLIC_API_BASE_URL="${PUBLIC_API_BASE_URL:-/ui}",NODE_ENV="${frontend_node_env}"
autostart=true
autorestart=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
priority=20
EOF
