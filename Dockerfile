# build.py uses stdlib only (json/re/base64/hashlib) - no uv sync needed here.
FROM python:3.13-alpine AS build
WORKDIR /src
COPY build.py .
COPY site/ site/
RUN python build.py

FROM nginx:1.29-alpine
RUN printf 'server {\n  listen 80;\n  root /usr/share/nginx/html;\n  gzip on;\n  gzip_types text/css application/javascript application/json;\n  add_header X-Content-Type-Options nosniff;\n}\n' > /etc/nginx/conf.d/default.conf
COPY --from=build /src/dist/index.html /usr/share/nginx/html/index.html
EXPOSE 80
