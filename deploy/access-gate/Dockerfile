FROM golang:1.26-alpine AS build
WORKDIR /src
COPY main.go .
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /access-gate ./main.go

FROM alpine:3.22
RUN apk add --no-cache ca-certificates nftables \
    && addgroup -S accessgate \
    && adduser -S -G accessgate accessgate
COPY --from=build /access-gate /usr/local/bin/access-gate
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
EXPOSE 9080
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
