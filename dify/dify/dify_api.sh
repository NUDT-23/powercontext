#!/bin/bash
# Dify console helper (Dify 1.11 cookie + CSRF auth)
# 凭据从环境变量读：DIFY_ADMIN_EMAIL / DIFY_ADMIN_PASSWORD（本地部署时自设，勿提交真实值）
# usage: dify_api.sh <get|post-file|post-json|del> <path> [body]
set -e
BASE=http://localhost/console/api
EMAIL="${DIFY_ADMIN_EMAIL:-admin@example.com}"
PASS="${DIFY_ADMIN_PASSWORD:-change-me}"
JAR=$(mktemp)
curl -s -c "$JAR" -X POST $BASE/login -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\"}" > /dev/null
TOK=$(grep -w access_token "$JAR" | awk '{print $NF}')
CSRF=$(grep -w csrf_token "$JAR" | awk '{print $NF}')
[ -n "$TOK" ] || { echo "login failed"; rm -f "$JAR"; exit 1; }
H1="Authorization: Bearer $TOK"
H2="X-CSRF-Token: $CSRF"
case "$1" in
  get)       curl -s -b "$JAR" -H "$H1" -H "$H2" "$BASE$2" ;;
  post-file) curl -s -b "$JAR" -X POST -H "$H1" -H "$H2" -H "Content-Type: application/json" --data-binary @"$3" "$BASE$2" ;;
  post-json) curl -s -b "$JAR" -X POST -H "$H1" -H "$H2" -H "Content-Type: application/json" -d "$3" "$BASE$2" ;;
  del)       curl -s -b "$JAR" -X DELETE -H "$H1" -H "$H2" "$BASE$2" ;;
  *) echo "usage: dify_api.sh get|post-file|post-json|del <path> [body]"; exit 1 ;;
esac
rm -f "$JAR"
