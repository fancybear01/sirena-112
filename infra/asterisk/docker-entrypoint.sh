#!/bin/sh
set -eu

export ARI_USERNAME="${ARI_USERNAME:-media}"
export ARI_PASSWORD="${ARI_PASSWORD:-change-me-ari}"
export SIP_1001_PASSWORD="${SIP_1001_PASSWORD:-change-me-1001}"
export SIP_1002_PASSWORD="${SIP_1002_PASSWORD:-change-me-1002}"
export EXTERNAL_ADDRESS="${EXTERNAL_ADDRESS:-127.0.0.1}"

envsubst '${ARI_USERNAME} ${ARI_PASSWORD} ${SIP_1001_PASSWORD} ${SIP_1002_PASSWORD} ${EXTERNAL_ADDRESS}' \
  < /etc/asterisk/templates/ari.conf.template > /etc/asterisk/ari.conf

envsubst '${SIP_1001_PASSWORD} ${SIP_1002_PASSWORD} ${EXTERNAL_ADDRESS}' \
  < /etc/asterisk/templates/pjsip.endpoints.conf.template > /etc/asterisk/pjsip.endpoints.conf

if [ -x /usr/sbin/asterisk ]; then
  AST_BIN=/usr/sbin/asterisk
elif [ -x /usr/sbin/asterisk-bin ]; then
  AST_BIN=/usr/sbin/asterisk-bin
else
  AST_BIN=$(command -v asterisk)
fi

exec "$AST_BIN" -f -U asterisk -G asterisk -vvvdddf

