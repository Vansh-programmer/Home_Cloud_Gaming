FROM alpine:3.22
RUN apk add --no-cache jq
COPY configure.sh /usr/local/bin/configure.sh
RUN chmod 755 /usr/local/bin/configure.sh
ENTRYPOINT ["/usr/local/bin/configure.sh"]
