# Flavor distroless: build glibc (swift:6.4-noble) dengan --static-swift-stdlib, runtime gcr.io/distroless/cc-debian13:nonroot.
# --build-system native: pada Swift 6.4 Linux, sistem build default (Swift Build) gagal link dengan --static-swift-stdlib
# (undefined reference ke _FoundationICU/_FoundationCollections/CoreFoundation); sistem native (deprecated) berhasil. Lihat README > Deviasi.
ARG SWIFT_BUILD_IMAGE
ARG RUNTIME_IMAGE
FROM ${SWIFT_BUILD_IMAGE} AS build
WORKDIR /build
COPY Package.swift Package.resolved ./
RUN swift package resolve
COPY Sources Sources
COPY Tests Tests
ARG SWIFT_EXTRA_FLAGS=""
RUN --mount=type=cache,target=/build/.build,id=swift-build-glibc \
    swift build -c release --static-swift-stdlib --build-system native --product App $SWIFT_EXTRA_FLAGS \
    && mkdir -p /out \
    && cp "$(swift build -c release --static-swift-stdlib --build-system native --show-bin-path)/App" /out/App \
    && strip /out/App

FROM ${RUNTIME_IMAGE}
COPY --from=build /out/App /App
USER 65532:65532
EXPOSE 8080
ENTRYPOINT ["/App"]
