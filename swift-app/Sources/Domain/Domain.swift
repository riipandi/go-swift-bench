import Foundation

/// Kesalahan domain: notFound -> 404, validation -> 400.
public enum DomainError: Error, Equatable, Sendable {
    case notFound
    case validation(String)

    public var message: String {
        switch self {
        case .notFound: return "not found"
        case .validation(let m): return m
        }
    }
}

public enum Msg {
    public static let invalidBody = "invalid JSON body"
    public static let invalidID = "invalid id"
    public static let invalidStatus = "status must be one of pending, paid, shipped, cancelled"
}

public enum OrderStatus {
    public static let pending = "pending"
    public static let paid = "paid"
    public static let shipped = "shipped"
    public static let cancelled = "cancelled"
    public static func isValid(_ s: String) -> Bool { [pending, paid, shipped, cancelled].contains(s) }
}

public struct User: Codable, Sendable, Equatable {
    public var id: Int64
    public var name: String
    public var email: String
    public var createdAt: Date
    public init(id: Int64, name: String, email: String, createdAt: Date) {
        self.id = id; self.name = name; self.email = email; self.createdAt = createdAt
    }
    enum CodingKeys: String, CodingKey { case id, name, email; case createdAt = "created_at" }
}

public struct Order: Codable, Sendable, Equatable {
    public var id: Int64
    public var userID: Int64
    public var status: String
    public var totalCents: Int
    public var note: String
    public var createdAt: Date
    public var updatedAt: Date
    public init(id: Int64, userID: Int64, status: String, totalCents: Int, note: String, createdAt: Date, updatedAt: Date) {
        self.id = id; self.userID = userID; self.status = status; self.totalCents = totalCents
        self.note = note; self.createdAt = createdAt; self.updatedAt = updatedAt
    }
    enum CodingKeys: String, CodingKey {
        case id, status, note
        case userID = "user_id", totalCents = "total_cents", createdAt = "created_at", updatedAt = "updated_at"
    }
}

/// User + semua order; di-encode datar (field user di tingkat atas) seperti Go.
public struct UserWithOrders: Codable, Sendable, Equatable {
    public var user: User
    public var orders: [Order]
    public init(user: User, orders: [Order]) { self.user = user; self.orders = orders }
    enum CodingKeys: String, CodingKey { case id, name, email, orders; case createdAt = "created_at" }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        user = User(id: try c.decode(Int64.self, forKey: .id), name: try c.decode(String.self, forKey: .name),
                    email: try c.decode(String.self, forKey: .email), createdAt: try c.decode(Date.self, forKey: .createdAt))
        orders = try c.decode([Order].self, forKey: .orders)
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(user.id, forKey: .id)
        try c.encode(user.name, forKey: .name)
        try c.encode(user.email, forKey: .email)
        try c.encode(user.createdAt, forKey: .createdAt)
        try c.encode(orders, forKey: .orders)
    }
}

public struct Payment: Codable, Sendable, Equatable {
    public var id: Int64
    public var orderID: Int64
    public var amountCents: Int
    public var createdAt: Date
    public init(id: Int64, orderID: Int64, amountCents: Int, createdAt: Date) {
        self.id = id; self.orderID = orderID; self.amountCents = amountCents; self.createdAt = createdAt
    }
    enum CodingKeys: String, CodingKey {
        case id
        case orderID = "order_id", amountCents = "amount_cents", createdAt = "created_at"
    }
}

public struct PayResult: Codable, Sendable, Equatable {
    public var order: Order
    public var payment: Payment
    public init(order: Order, payment: Payment) { self.order = order; self.payment = payment }
}

// MARK: - Masukan (decode longgar: kunci hilang = nilai nol, seperti encoding/json Go)

public struct CreateOrderInput: Codable, Sendable, Equatable {
    public var userID: Int64
    public var totalCents: Int
    public var status: String
    public var note: String
    public init(userID: Int64 = 0, totalCents: Int = 0, status: String = "", note: String = "") {
        self.userID = userID; self.totalCents = totalCents; self.status = status; self.note = note
    }
    enum CodingKeys: String, CodingKey { case status, note; case userID = "user_id", totalCents = "total_cents" }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        userID = try c.decodeIfPresent(Int64.self, forKey: .userID) ?? 0
        totalCents = try c.decodeIfPresent(Int.self, forKey: .totalCents) ?? 0
        status = try c.decodeIfPresent(String.self, forKey: .status) ?? ""
        note = try c.decodeIfPresent(String.self, forKey: .note) ?? ""
    }

    /// Menerapkan status default lalu memvalidasi.
    public mutating func normalize() throws {
        if userID <= 0 { throw DomainError.validation("user_id must be positive") }
        if totalCents < 0 || totalCents > 10_000_000 {
            throw DomainError.validation("total_cents must be between 0 and 10000000")
        }
        if status.isEmpty { status = OrderStatus.pending }
        else if !OrderStatus.isValid(status) { throw DomainError.validation(Msg.invalidStatus) }
        if note.unicodeScalars.count > 200 { throw DomainError.validation("note must be at most 200 characters") }
    }
}

public struct UpdateOrderInput: Codable, Sendable, Equatable {
    public var status: String
    public init(status: String = "") { self.status = status }
    enum CodingKeys: String, CodingKey { case status }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        status = try c.decodeIfPresent(String.self, forKey: .status) ?? ""
    }
    public func validate() throws {
        if !OrderStatus.isValid(status) { throw DomainError.validation(Msg.invalidStatus) }
    }
}

public enum Params {
    public static func parseID(_ s: String) throws -> Int64 {
        guard let id = Int64(s), id > 0 else { throw DomainError.validation(Msg.invalidID) }
        return id
    }
    /// ?limit= (default 20, 1...100)
    public static func parseLimit(_ s: String?) throws -> Int {
        guard let s = s, !s.isEmpty else { return 20 }
        guard let n = Int(s), n >= 1, n <= 100 else {
            throw DomainError.validation("limit must be between 1 and 100")
        }
        return n
    }
}

// MARK: - Payload benchmark tanpa database

public struct EchoAddress: Codable, Sendable, Equatable {
    public var street: String, city: String, zip: String, country: String
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        street = try c.decodeIfPresent(String.self, forKey: .street) ?? ""
        city = try c.decodeIfPresent(String.self, forKey: .city) ?? ""
        zip = try c.decodeIfPresent(String.self, forKey: .zip) ?? ""
        country = try c.decodeIfPresent(String.self, forKey: .country) ?? ""
    }
    enum CodingKeys: String, CodingKey { case street, city, zip, country }
}

public struct EchoCustomer: Codable, Sendable, Equatable {
    public var id: Int64, name: String, email: String, address: EchoAddress
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decodeIfPresent(Int64.self, forKey: .id) ?? 0
        name = try c.decodeIfPresent(String.self, forKey: .name) ?? ""
        email = try c.decodeIfPresent(String.self, forKey: .email) ?? ""
        address = try c.decodeIfPresent(EchoAddress.self, forKey: .address)
            ?? (try EchoAddress(from: EmptyDecoder()))
    }
    enum CodingKeys: String, CodingKey { case id, name, email, address }
}

public struct EchoItem: Codable, Sendable, Equatable {
    public var sku: String, name: String, qty: Int, priceCents: Int, labels: [String]
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        sku = try c.decodeIfPresent(String.self, forKey: .sku) ?? ""
        name = try c.decodeIfPresent(String.self, forKey: .name) ?? ""
        qty = try c.decodeIfPresent(Int.self, forKey: .qty) ?? 0
        priceCents = try c.decodeIfPresent(Int.self, forKey: .priceCents) ?? 0
        labels = try c.decodeIfPresent([String].self, forKey: .labels) ?? []
    }
    enum CodingKeys: String, CodingKey { case sku, name, qty, labels; case priceCents = "price_cents" }
}

public struct EchoRequest: Codable, Sendable, Equatable {
    public var requestID: String, customer: EchoCustomer, items: [EchoItem], tags: [String], note: String
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        requestID = try c.decodeIfPresent(String.self, forKey: .requestID) ?? ""
        customer = try c.decodeIfPresent(EchoCustomer.self, forKey: .customer) ?? (try EchoCustomer(from: EmptyDecoder()))
        items = try c.decodeIfPresent([EchoItem].self, forKey: .items) ?? []
        tags = try c.decodeIfPresent([String].self, forKey: .tags) ?? []
        note = try c.decodeIfPresent(String.self, forKey: .note) ?? ""
    }
    enum CodingKeys: String, CodingKey { case customer, items, tags, note; case requestID = "request_id" }

    public func validate() throws {
        if requestID.isEmpty { throw DomainError.validation("request_id is required") }
        if customer.id <= 0 { throw DomainError.validation("customer.id must be positive") }
        if !customer.email.contains("@") { throw DomainError.validation("customer.email is invalid") }
        if items.count < 1 || items.count > 50 { throw DomainError.validation("items must contain 1 to 50 entries") }
        for (i, it) in items.enumerated() {
            if it.qty < 1 { throw DomainError.validation("items[\(i)].qty must be at least 1") }
            if it.priceCents < 0 { throw DomainError.validation("items[\(i)].price_cents must not be negative") }
        }
        if tags.count > 20 { throw DomainError.validation("tags must contain at most 20 entries") }
    }
}

/// Decoder kosong: dipakai untuk membuat nilai nol saat objek bersarang tidak ada.
struct EmptyDecoder: Decoder {
    var codingPath: [CodingKey] { [] }
    var userInfo: [CodingUserInfoKey: Any] { [:] }
    func container<Key: CodingKey>(keyedBy type: Key.Type) throws -> KeyedDecodingContainer<Key> {
        KeyedDecodingContainer(EmptyKeyed<Key>())
    }
    func unkeyedContainer() throws -> UnkeyedDecodingContainer { throw DecodingError.dataCorrupted(.init(codingPath: [], debugDescription: "empty")) }
    func singleValueContainer() throws -> SingleValueDecodingContainer { throw DecodingError.dataCorrupted(.init(codingPath: [], debugDescription: "empty")) }
}

struct EmptyKeyed<Key: CodingKey>: KeyedDecodingContainerProtocol {
    var codingPath: [CodingKey] { [] }
    var allKeys: [Key] { [] }
    func contains(_ key: Key) -> Bool { false }
    func decodeNil(forKey key: Key) throws -> Bool { true }
    func decode<T: Decodable>(_ type: T.Type, forKey key: Key) throws -> T {
        throw DecodingError.keyNotFound(key, .init(codingPath: [], debugDescription: "empty"))
    }
    func nestedContainer<NestedKey: CodingKey>(keyedBy type: NestedKey.Type, forKey key: Key) throws -> KeyedDecodingContainer<NestedKey> {
        throw DecodingError.keyNotFound(key, .init(codingPath: [], debugDescription: "empty"))
    }
    func nestedUnkeyedContainer(forKey key: Key) throws -> UnkeyedDecodingContainer {
        throw DecodingError.keyNotFound(key, .init(codingPath: [], debugDescription: "empty"))
    }
    func superDecoder() throws -> Decoder { throw DecodingError.dataCorrupted(.init(codingPath: [], debugDescription: "empty")) }
    func superDecoder(forKey key: Key) throws -> Decoder { throw DecodingError.dataCorrupted(.init(codingPath: [], debugDescription: "empty")) }
}

/// Objek tetap ~1 KB (20 field + satu array kecil), dibuat di memori per request.
public struct BenchPayload: Codable, Sendable {
    public var id: Int64 = 1_234_567
    public var uuid = "3f2b8c1e-9a4d-4e6f-8b7a-1c2d3e4f5a6b"
    public var name = "Benchmark Subject"
    public var title = "A fixed object used to measure framework and JSON overhead"
    public var summary = "Built in memory on every request, no database involved."
    public var description = BenchPayload.longText
    public var category = "benchmark"
    public var status = "active"
    public var active = true
    public var verified = true
    public var score = 98
    public var rank = 7
    public var level = 42
    public var views: Int64 = 9_876_543_210
    public var balanceCents: Int64 = 123_456_789
    public var currency = "IDR"
    public var country = "ID"
    public var city = "Jakarta"
    public var email = "subject@example.test"
    public var createdAt = "2025-01-01T00:00:00Z"
    public var tags = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta"]

    public init() {}

    static let longText = "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. "
        + "Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. "
        + "Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. "
        + "Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum."

    enum CodingKeys: String, CodingKey {
        case id, uuid, name, title, summary, description, category, status, active, verified
        case score, rank, level, views, currency, country, city, email, tags
        case balanceCents = "balance_cents", createdAt = "created_at"
    }
}
