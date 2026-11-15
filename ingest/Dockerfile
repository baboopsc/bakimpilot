# ---- Flight-data ingestion service (Go, standard library only) ----
FROM golang:1.24-alpine AS build
WORKDIR /src
COPY go.mod ./
COPY *.go ./
RUN go vet ./... && go test ./... && CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /ingest .

# Final image: just the static binary, no shell, non-root.
FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /ingest /ingest
EXPOSE 8080
ENTRYPOINT ["/ingest"]
