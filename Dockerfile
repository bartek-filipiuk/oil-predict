# build.py uses stdlib only (json/re/base64/hashlib) - no uv sync needed here.
FROM python:3.13-alpine AS build
WORKDIR /src
COPY build.py .
COPY site/ site/
RUN python build.py

FROM nginx:1.29-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/dist/index.html /src/dist/api.json /usr/share/nginx/html/
EXPOSE 80
