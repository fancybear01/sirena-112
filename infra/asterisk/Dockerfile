FROM andrius/asterisk:20@sha256:c202cdf0f0348ab75e6dee49967418ce8c08853644b8a5c00de91f6b4aca4dd1

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends gettext-base curl \
    && rm -rf /var/lib/apt/lists/*

COPY infra/asterisk/config/logger.conf /etc/asterisk/logger.conf
COPY infra/asterisk/config/extensions.conf /etc/asterisk/extensions.conf
COPY infra/asterisk/config/http.conf /etc/asterisk/http.conf
COPY infra/asterisk/config/modules.conf /etc/asterisk/modules.conf
COPY infra/asterisk/config/pjsip.conf /etc/asterisk/pjsip.conf
COPY infra/asterisk/config/pjsip.smoke.conf /etc/asterisk/pjsip.smoke.conf
COPY infra/asterisk/config/rtp.conf /etc/asterisk/rtp.conf
COPY infra/asterisk/templates/ /etc/asterisk/templates/
COPY services/ai/tests/fixtures/voice/operator-01-address.wav /var/lib/asterisk/sounds/smoke-address.wav16
COPY infra/asterisk/docker-entrypoint.sh /docker-entrypoint.sh

RUN sed -i 's/\r$//' /docker-entrypoint.sh && chmod +x /docker-entrypoint.sh

EXPOSE 5060/udp 5060/tcp 8088/tcp 10000-10100/udp

ENTRYPOINT ["/docker-entrypoint.sh"]
