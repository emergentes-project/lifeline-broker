#!/usr/bin/env bash
set -euo pipefail
cd /opt/lifeline-broker
set -a
source .env
set +a
case "${BROKER_FQDN:-}" in
  ""|*[!a-zA-Z0-9.-]*) echo 'Configure BROKER_FQDN with a DNS name.' >&2; exit 1 ;;
esac
if [[ ! "${BROKER_KEYSTORE_PASSWORD:-}" =~ ^[0-9a-fA-F]{64}$ ]]; then
  echo 'Invalid keystore password format.' >&2
  exit 1
fi
umask 077
mkdir -p tls
openssl pkcs12 -export -name lifeline-broker \
  -in "/etc/letsencrypt/live/$BROKER_FQDN/fullchain.pem" \
  -inkey "/etc/letsencrypt/live/$BROKER_FQDN/privkey.pem" \
  -out tls/broker.p12.new -passout env:BROKER_KEYSTORE_PASSWORD
broker_uid=$(docker run --rm --entrypoint id apache/activemq-artemis:2.40.0 -u)
broker_gid=$(docker run --rm --entrypoint id apache/activemq-artemis:2.40.0 -g)
chown "$broker_uid:$broker_gid" tls tls/broker.p12.new
chmod 700 tls
chmod 600 tls/broker.p12.new
mv -f tls/broker.p12.new tls/broker.p12
echo 'TLS keystore exported.'
