#!/bin/sh
set -eu

: "${PSH_PROTO_MODE:=https}"
export PSH_PROTO_MODE

envsubst '${PSH_PROTO_MODE}' < /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf

exec nginx -g 'daemon off;'
