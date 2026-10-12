import Fluent
import FluentPostgresDriver
import Foundation
import Logging
import NIOCore
import Vapor

public struct AppConfig: Sendable {
    public var port: Int
    public var dbHost: String
    public var dbPort: Int
    public var dbUser: String
    public var dbPass: String
    public var dbName: String
    public var dbPoolTotal: Int
    public var eventLoops: Int
    public var logMode: String // quiet | access

    public var poolPerLoop: Int { dbPoolTotal / eventLoops }
    /// LOG_MODE diterjemahkan ke LOG_LEVEL: quiet = error, access = info.
    public var logLevel: String { logMode == "access" ? "info" : "error" }

    public struct ConfigError: Error, CustomStringConvertible {
        public let description: String
    }

    public static func load() throws -> AppConfig {
        func str(_ k: String, _ d: String) -> String {
            if let v = ProcessInfo.processInfo.environment[k], !v.isEmpty { return v }
            return d
        }
        func int(_ k: String, _ d: Int) throws -> Int {
            guard let v = Int(str(k, String(d))), v > 0 else { throw ConfigError(description: "\(k) tidak valid") }
            return v
        }
        let cfg = AppConfig(
            port: try int("PORT", 8080),
            dbHost: str("DB_HOST", "localhost"),
            dbPort: try int("DB_PORT", 54322),
            dbUser: str("DB_USER", "bench"),
            dbPass: str("DB_PASSWORD", "bench"),
            dbName: str("DB_NAME", "bench"),
            dbPoolTotal: try int("DB_POOL", 16),
            eventLoops: try int("EVENT_LOOPS", 2),
            logMode: str("LOG_MODE", "quiet"))
        guard cfg.logMode == "quiet" || cfg.logMode == "access" else {
            throw ConfigError(description: "LOG_MODE harus quiet atau access")
        }
        guard cfg.dbPoolTotal % cfg.eventLoops == 0 else {
            throw ConfigError(description: "DB_POOL (\(cfg.dbPoolTotal)) harus habis dibagi EVENT_LOOPS (\(cfg.eventLoops))")
        }
        return cfg
    }
}

/// Pool Fluent per event loop: maxConnectionsPerEventLoop = total / jumlah event loop.
public func configureDatabase(_ app: Application, _ cfg: AppConfig) {
    let pg = SQLPostgresConfiguration(
        hostname: cfg.dbHost, port: cfg.dbPort, username: cfg.dbUser,
        password: cfg.dbPass, database: cfg.dbName, tls: .disable)
    app.databases.use(
        .postgres(configuration: pg, maxConnectionsPerEventLoop: cfg.poolPerLoop, connectionPoolTimeout: .seconds(10)),
        as: .psql)
}

public func configureServer(_ app: Application, _ cfg: AppConfig) {
    app.http.server.configuration.hostname = "0.0.0.0"
    app.http.server.configuration.port = cfg.port
    app.routes.defaultMaxBodySize = "1mb"
}

/// Log startup selalu tertulis (level info) walau LOG_LEVEL=error.
public func startupLogger() -> Logger {
    var l = Logger(label: "startup")
    l.logLevel = .info
    return l
}
