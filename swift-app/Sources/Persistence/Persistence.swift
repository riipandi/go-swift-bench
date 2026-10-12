import Domain
import Fluent
import Foundation

/// Antarmuka repositori kecil: handler memakainya sehingga test bisa memakai repositori palsu.
public protocol UserRepository: Sendable {
    func getUser(id: Int64) async throws -> User
    func listOrders(userID: Int64, limit: Int) async throws -> [Order]
    func getUserWithOrders(id: Int64) async throws -> UserWithOrders
}

public protocol OrderRepository: Sendable {
    func createOrder(_ input: CreateOrderInput) async throws -> Order
    func updateOrderStatus(id: Int64, status: String) async throws -> Order
    func payOrder(id: Int64) async throws -> PayResult
}

// MARK: - Model Fluent (pemetaan tabel/kolom eksplisit; TIDAK ada migrasi)

final class UserModel: Model, @unchecked Sendable {
    static let schema = "users"
    @ID(custom: "id", generatedBy: .database) var id: Int64?
    @Field(key: "name") var name: String
    @Field(key: "email") var email: String
    @Field(key: "created_at") var createdAt: Date
    @Children(for: \.$user) var orders: [OrderModel]
    init() {}
}

final class OrderModel: Model, @unchecked Sendable {
    static let schema = "orders"
    @ID(custom: "id", generatedBy: .database) var id: Int64?
    @Parent(key: "user_id") var user: UserModel
    @Field(key: "status") var status: String
    @Field(key: "total_cents") var totalCents: Int
    @Field(key: "note") var note: String
    @Field(key: "created_at") var createdAt: Date
    @Field(key: "updated_at") var updatedAt: Date
    init() {}
    init(userID: Int64, status: String, totalCents: Int, note: String, createdAt: Date, updatedAt: Date) {
        self.$user.id = userID
        self.status = status; self.totalCents = totalCents; self.note = note
        self.createdAt = createdAt; self.updatedAt = updatedAt
    }
}

final class PaymentModel: Model, @unchecked Sendable {
    static let schema = "payments"
    @ID(custom: "id", generatedBy: .database) var id: Int64?
    @Parent(key: "order_id") var order: OrderModel
    @Field(key: "amount_cents") var amountCents: Int
    @Field(key: "created_at") var createdAt: Date
    init() {}
    init(orderID: Int64, amountCents: Int, createdAt: Date) {
        self.$order.id = orderID
        self.amountCents = amountCents; self.createdAt = createdAt
    }
}

// MARK: - Pemetaan ke domain

extension UserModel {
    func toDomain() throws -> User {
        User(id: try requireID(), name: name, email: email, createdAt: createdAt)
    }
}

extension OrderModel {
    func toDomain() throws -> Order {
        Order(id: try requireID(), userID: $user.id, status: status, totalCents: totalCents,
              note: note, createdAt: createdAt, updatedAt: updatedAt)
    }
}

// MARK: - Implementasi Fluent

public struct FluentUserRepository: UserRepository {
    let db: any Database
    public init(db: any Database) { self.db = db }

    public func getUser(id: Int64) async throws -> User {
        guard let m = try await UserModel.find(id, on: db) else { throw DomainError.notFound }
        return try m.toDomain()
    }

    public func listOrders(userID: Int64, limit: Int) async throws -> [Order] {
        try await OrderModel.query(on: db)
            .filter(\.$user.$id == userID)
            .sort(\.$createdAt, .descending)
            .sort(\.$id, .descending)
            .limit(limit)
            .all()
            .map { try $0.toDomain() }
    }

    public func getUserWithOrders(id: Int64) async throws -> UserWithOrders {
        let found = try await UserModel.query(on: db)
            .filter(\.$id == id)
            .with(\.$orders)
            .first()
        guard let m = found else { throw DomainError.notFound }
        // Fluent `with` tidak mendukung ORDER BY; urutan (created_at DESC, id DESC) diterapkan di memori (Go melakukan hal sama).
        let orders = try m.orders.map { try $0.toDomain() }
            .sorted { ($0.createdAt, $0.id) > ($1.createdAt, $1.id) }
        return UserWithOrders(user: try m.toDomain(), orders: orders)
    }
}

public struct FluentOrderRepository: OrderRepository {
    let db: any Database
    public init(db: any Database) { self.db = db }

    public func createOrder(_ input: CreateOrderInput) async throws -> Order {
        let now = Date()
        let m = OrderModel(userID: input.userID, status: input.status, totalCents: input.totalCents,
                           note: input.note, createdAt: now, updatedAt: now)
        try await m.create(on: db)
        return try m.toDomain()
    }

    public func updateOrderStatus(id: Int64, status: String) async throws -> Order {
        guard let m = try await OrderModel.find(id, on: db) else { throw DomainError.notFound }
        m.status = status
        m.updatedAt = Date()
        try await m.update(on: db)
        return try m.toDomain()
    }

    public func payOrder(id: Int64) async throws -> PayResult {
        try await db.transaction { tx in
            guard let m = try await OrderModel.find(id, on: tx) else { throw DomainError.notFound }
            let now = Date()
            m.status = OrderStatus.paid
            m.updatedAt = now
            try await m.update(on: tx)
            let p = PaymentModel(orderID: id, amountCents: m.totalCents, createdAt: now)
            try await p.create(on: tx)
            return PayResult(
                order: try m.toDomain(),
                payment: Payment(id: try p.requireID(), orderID: id, amountCents: p.amountCents, createdAt: now))
        }
    }
}
