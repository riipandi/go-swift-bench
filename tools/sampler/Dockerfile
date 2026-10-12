# Sampler + probe: binary Go statis di Alpine (non-root tidak dipakai: sampler perlu membaca /proc proses lain sebagai root).
ARG GO_BUILD_IMAGE
ARG ALPINE_IMAGE
FROM ${GO_BUILD_IMAGE} AS build
WORKDIR /src
COPY go.mod ./
COPY *.go ./
RUN CGO_ENABLED=0 go build -trimpath -ldflags='-s -w' -o /out/sampler .

FROM ${ALPINE_IMAGE}
COPY --from=build /out/sampler /sampler
ENTRYPOINT ["/sampler"]
