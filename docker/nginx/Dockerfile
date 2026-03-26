# Nginx reverse proxy for inference API
# Phase 5: Rate limiting, security headers, proxy pass

FROM nginx:1.28.1-alpine

# Remove default config
RUN rm /etc/nginx/conf.d/default.conf

# Copy custom configuration
COPY configs/nginx/nginx.conf /etc/nginx/nginx.conf
COPY src/serving/nginx/nginx.conf /etc/nginx/conf.d/api.conf

EXPOSE 80

HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
    CMD wget -q --spider http://localhost/nginx/health || exit 1
