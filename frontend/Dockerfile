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

# Production stage
FROM nginx:alpine

# Copy built assets
COPY --from=build /app/dist /usr/share/nginx/html

# Nginx config for SPA routing
RUN echo 'server { \
    listen 80; \
    root /usr/share/nginx/html; \
    index index.html; \
    location / { \
        try_files $uri $uri/ /index.html; \
    } \
}' > /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
