FROM andrius/asterisk:20

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends gettext-base curl \
    && rm -rf /var/lib/apt/lists/*

COPY config/logger.conf /etc/asterisk/logger.conf
COPY config/extensions.conf /etc/asterisk/extensions.conf
COPY config/http.conf /etc/asterisk/http.conf
COPY config/modules.conf /etc/asterisk/modules.conf
COPY config/pjsip.conf /etc/asterisk/pjsip.conf
COPY config/rtp.conf /etc/asterisk/rtp.conf
COPY templates/ /etc/asterisk/templates/
COPY docker-entrypoint.sh /docker-entrypoint.sh

RUN chmod +x /docker-entrypoint.sh

EXPOSE 5060/udp 5060/tcp 8088/tcp 10000-10100/udp

ENTRYPOINT ["/docker-entrypoint.sh"]
