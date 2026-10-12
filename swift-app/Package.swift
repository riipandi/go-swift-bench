// swift-tools-version:6.0
import PackageDescription

let package = Package(
    name: "swift-app",
    platforms: [.macOS(.v14)],
    dependencies: [
        .package(url: "https://github.com/vapor/vapor.git", from: "4.122.2"),
        .package(url: "https://github.com/vapor/fluent.git", from: "4.13.0"),
        .package(url: "https://github.com/vapor/fluent-postgres-driver.git", from: "2.14.0"),
    ],
    targets: [
        // Domain: model dan validasi. Tanpa dependency eksternal.
        .target(name: "Domain"),
        // Persistence: repositori Fluent (HTTPAPI -> Persistence -> Domain).
        .target(name: "Persistence", dependencies: [
            "Domain",
            .product(name: "Fluent", package: "fluent"),
        ]),
        // HTTPAPI: route, handler, middleware Vapor.
        .target(name: "HTTPAPI", dependencies: [
            "Domain", "Persistence",
            .product(name: "Vapor", package: "vapor"),
        ]),
        // Platform: konfigurasi, logging, pool DB. Dipakai dari atas (App).
        .target(name: "Platform", dependencies: [
            .product(name: "Vapor", package: "vapor"),
            .product(name: "Fluent", package: "fluent"),
            .product(name: "FluentPostgresDriver", package: "fluent-postgres-driver"),
        ]),
        .executableTarget(name: "App", dependencies: [
            "Domain", "Persistence", "HTTPAPI", "Platform",
            .product(name: "Vapor", package: "vapor"),
        ]),
        .testTarget(name: "ParityTests", dependencies: [
            "Domain", "Persistence", "HTTPAPI",
            .product(name: "VaporTesting", package: "vapor"),
        ]),
    ],
    swiftLanguageModes: [.v5]
)
