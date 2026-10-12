# Flavor distroless: runtime gcr.io/distroless/static-debian13:nonroot (tanpa shell, non-root uid 65532).
ARG GO_BUILD_IMAGE
ARG RUNTIME_IMAGE
FROM ${GO_BUILD_IMAGE} AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
ARG GO_PGO=0
RUN --mount=type=cache,target=/root/.cache/go-build \
    if [ "$GO_PGO" = "1" ]; then PGO=pgo/default.pgo; else PGO=off; fi; \
    CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags='-s -w' -pgo=$PGO -o /out/server ./cmd/server

FROM ${RUNTIME_IMAGE}
COPY --from=build /out/server /server
USER 65532:65532
EXPOSE 8080
ENTRYPOINT ["/server"]
