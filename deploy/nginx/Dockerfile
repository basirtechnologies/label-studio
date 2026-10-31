# syntax=docker/dockerfile:1
################################################################################
# Label Studio nginx front proxy image.
#
# This is a thin layer on top of the Label Studio app image: nginx serves
# /static/ and /react-app/ straight from files baked into the app image, and
# deploy/docker-entrypoint.sh already has an "nginx" mode that:
#   - copies /etc/nginx/nginx.conf (deploy/default.conf, or a file mounted
#     over it) to $OPT_DIR/nginx/nginx.conf and runs nginx with that copy,
#   - points the upstream at $APP_HOST (default "app", i.e. app:8000),
#   - enables the 8086 SSL listener only when NGINX_SSL_CERT/NGINX_SSL_CERT_KEY
#     are set (e.g. /certs/cert.pem, /certs/cert.key).
# User (1001), workdir and entrypoint are inherited from the app image.
#
# CI builds this from the app image of the same commit:
#   --build-arg APP_IMAGE=ghcr.io/basirtechnologies/label-studio:sha-<short sha>
# Build context: deploy/nginx (nothing is copied from it).
################################################################################
ARG APP_IMAGE=ghcr.io/basirtechnologies/label-studio:develop
FROM ${APP_IMAGE}

EXPOSE 8085 8086

CMD ["nginx"]
