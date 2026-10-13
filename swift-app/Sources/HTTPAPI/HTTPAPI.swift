import Domain
import Foundation
import NIOCore
import Persistence
import Vapor

/// Pabrik repositori per request. Produksi: Fluent; test: repositori palsu.
public struct Dependencies: Sendable {
    public var users: @Sendable (Request) -> any UserRepository
    public var orders: @Sendable (Request) -> any OrderRepository
    public init(users: @escaping @Sendable (Request) -> any UserRepository,
                orders: @escaping @Sendable (Request) -> any OrderRepository) {
        self.users = users
        self.orders = orders
    }
}

struct ErrorBody: Content { var error: String }
struct StatusBody: Content { var status: String }

extension Domain.User: Content {}
extension Domain.Order: Content {}
extension Domain.UserWithOrders: Content {}
extension Domain.PayResult: Content {}
extension Domain.EchoRequest: Content {}
extension Domain.BenchPayload: Content {}

/// Encode memakai ContentConfiguration.global (Foundation JSONEncoder lewat Vapor Content).
func jsonResponse<T: Encodable>(_ value: T, status: HTTPResponseStatus = .ok) throws -> Response {
    var headers = HTTPHeaders()
    var buffer = ByteBufferAllocator().buffer(capacity: 512)
    try ContentConfiguration.global.requireEncoder(for: .json).encode(value, to: &buffer, headers: &headers)
    return Response(status: status, headers: headers, body: .init(buffer: buffer))
}

func decodeBody<T: Decodable>(_ type: T.Type, _ req: Request) throws -> T {
    do { return try req.content.decode(T.self, as: .json) }
    catch { throw DomainError.validation(Msg.invalidBody) }
}

/// Memetakan error domain ke respons {error: pesan}. Respons dibuat langsung (bukan Abort) agar
/// ErrorMiddleware Vapor tidak menulis baris log tambahan.
func run(_ req: Request, _ body: () async throws -> Response) async -> Response {
    do { return try await body() }
    catch let e as DomainError {
        let status: HTTPResponseStatus = { if case .notFound = e { return .notFound } else { return .badRequest } }()
        return (try? jsonResponse(ErrorBody(error: e.message), status: status)) ?? Response(status: status)
    } catch {
        req.logger.error("request failed: \(error)")
        return (try? jsonResponse(ErrorBody(error: "internal error"), status: .internalServerError))
            ?? Response(status: .internalServerError)
    }
}

/// Middleware galat: rute tak dikenal dll tetap berbentuk {error: pesan}.
public func makeErrorMiddleware() -> ErrorMiddleware {
    ErrorMiddleware { req, error in
        let status = (error as? any AbortError)?.status ?? .internalServerError
        let message = status == .notFound ? "not found" : ((error as? any AbortError)?.reason ?? "internal error")
        return (try? jsonResponse(ErrorBody(error: message), status: status)) ?? Response(status: status)
    }
}

public func registerRoutes(_ app: Application, _ deps: Dependencies) {
    app.get("healthz") { req in
        try jsonResponse(StatusBody(status: "ok"))
    }
    app.get("bench", "json") { req in
        try jsonResponse(BenchPayload())
    }
    app.post("bench", "echo") { req in
        await run(req) {
            let input = try decodeBody(EchoRequest.self, req)
            try input.validate()
            return try jsonResponse(input)
        }
    }
    app.get("users", ":id") { req in
        await run(req) {
            let id = try Params.parseID(req.parameters.get("id") ?? "")
            if (try? req.query.get(String.self, at: "include")) == "orders" {
                return try jsonResponse(try await deps.users(req).getUserWithOrders(id: id))
            }
            return try jsonResponse(try await deps.users(req).getUser(id: id))
        }
    }
    app.get("users", ":id", "orders") { req in
        await run(req) {
            let id = try Params.parseID(req.parameters.get("id") ?? "")
            let limit = try Params.parseLimit(try? req.query.get(String.self, at: "limit"))
            return try jsonResponse(try await deps.users(req).listOrders(userID: id, limit: limit))
        }
    }
    app.post("orders") { req in
        await run(req) {
            var input = try decodeBody(CreateOrderInput.self, req)
            try input.normalize()
            return try jsonResponse(try await deps.orders(req).createOrder(input), status: .created)
        }
    }
    app.put("orders", ":id") { req in
        await run(req) {
            let id = try Params.parseID(req.parameters.get("id") ?? "")
            let input = try decodeBody(UpdateOrderInput.self, req)
            try input.validate()
            return try jsonResponse(try await deps.orders(req).updateOrderStatus(id: id, status: input.status))
        }
    }
    app.post("orders", ":id", "pay") { req in
        await run(req) {
            let id = try Params.parseID(req.parameters.get("id") ?? "")
            return try jsonResponse(try await deps.orders(req).payOrder(id: id))
        }
    }
}
