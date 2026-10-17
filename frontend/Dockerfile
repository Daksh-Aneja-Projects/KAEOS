# Build stage
FROM node:20-slim AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# Vite bakes env vars at BUILD time — a runtime `environment:` entry in compose
# does nothing for this static build. The URL must be reachable from the USER'S
# BROWSER (localhost:8001), not the Docker network name (backend:8001).
ARG VITE_API_BASE=http://localhost:8001/api/v1
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build

# Production stage: nginx that runs as a non-root user and listens on 8080, so
# it starts under the Helm chart's runAsNonRoot pod security context.
FROM nginxinc/nginx-unprivileged:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
# SPA routing, security headers and noindex for app routes (see nginx.conf).
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
