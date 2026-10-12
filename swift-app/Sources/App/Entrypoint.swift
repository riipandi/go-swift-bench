import Domain
import Fluent
import Foundation
import HTTPAPI
import Logging
import NIOCore
import NIOPosix
import Persistence
import Platform
import Vapor

@main
enum Entrypoint {
    static func main() async throws {
        let cfg: AppConfig
        do { cfg = try AppConfig.load() } catch {
            startupLogBootstrap()
            startupLogger().error("konfigurasi tidak valid: \(error)")
            exit(2)
        }
        // LOG_MODE -> LOG_LEVEL, lalu bootstrap bawaan Vapor (SwiftLog) membaca LOG_LEVEL.
        setenv("LOG_LEVEL", cfg.logLevel, 1)
        var env = try Environment.detect()
        try LoggingSystem.bootstrap(from: &env)

        startupLogger().info("server starting", metadata: [
            "port": "\(cfg.port)", "log_mode": "\(cfg.logMode)", "event_loops": "\(cfg.eventLoops)",
            "db_pool_total": "\(cfg.dbPoolTotal)", "pool_per_loop": "\(cfg.poolPerLoop)",
            "swift": "6.4",
        ])

        let group = MultiThreadedEventLoopGroup(numberOfThreads: cfg.eventLoops)
        let app = try await Application.make(env, .shared(group))
        do {
            configureServer(app, cfg)
            configureDatabase(app, cfg)
            // ErrorMiddleware khusus (bentuk {error}); log akses hanya pada mode access.
            app.middleware = .init()
            app.middleware.use(makeErrorMiddleware())
            if cfg.logMode == "access" {
                app.middleware.use(RouteLoggingMiddleware(logLevel: .info))
            }
            registerRoutes(app, Dependencies(
                users: { FluentUserRepository(db: $0.db) },
                orders: { FluentOrderRepository(db: $0.db) }))
            try await app.execute()
        } catch {
            startupLogger().error("server berhenti: \(error)")
            try? await app.asyncShutdown()
            try? await group.shutdownGracefully()
            exit(1)
        }
        try await app.asyncShutdown()
        try await group.shutdownGracefully()
    }

    private static func startupLogBootstrap() {
        LoggingSystem.bootstrap { StreamLogHandler.standardOutput(label: $0) }
    }
}
