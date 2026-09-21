# syntax=docker/dockerfile:1

FROM golang:1.26.5-alpine AS build
WORKDIR /src
RUN apk add --no-cache git ca-certificates
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o /out/media ./cmd/media

FROM alpine:3.20
RUN apk add --no-cache ca-certificates
WORKDIR /app
COPY --from=build /out/media /app/media
EXPOSE 8091 18000-18099/udp
USER nobody
ENTRYPOINT ["/app/media"]
