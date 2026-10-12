import Domain
import Foundation
import HTTPAPI
import NIOCore
import Persistence
import Testing
import VaporTesting

// Suite paritas: kasus dibaca dari contract-tests/parity-cases/cases.json (dipakai juga oleh suite Go).
// Framework test Swift: Swift Testing (bawaan toolchain 6.x).

struct ParityCase: Sendable, CustomTestStringConvertible {
    let id: String
    let kind: String
    let input: Data?
    let request: Data?
    let expect: Data
    var testDescription: String { id }
}

func fragment(_ any: Any?) -> Data? {
    guard let any = any else { return nil }
    return try? JSONSerialization.data(withJSONObject: any, options: [.fragmentsAllowed])
}

func loadCases() -> [ParityCase] {
    let url = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        .appendingPathComponent("contract-tests/parity-cases/cases.json")
    guard let data = try? Data(contentsOf: url),
          let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
          let cases = root["cases"] as? [[String: Any]] else { return [] }
    return cases.map {
        ParityCase(id: $0["id"] as! String, kind: $0["kind"] as! String, input: fragment($0["input"]),
                   request: fragment($0["request"]), expect: fragment($0["expect"])!)
    }
}

let reportLock = NSLock()
func recordRan(_ id: String) {
    guard let path = ProcessInfo.processInfo.environment["PARITY_REPORT"] else { return }
    reportLock.lock(); defer { reportLock.unlock() }
    if let h = FileHandle(forWritingAtPath: path) {
        h.seekToEndOfFile(); h.write(Data((id + "\n").utf8)); try? h.close()
    } else {
        try? Data((id + "\n").utf8).write(to: URL(fileURLWithPath: path))
    }
}

func subset(_ want: Any, _ got: Any) -> Bool {
    if let w = want as? [String: Any] {
        guard let g = got as? [String: Any] else { return false }
        return w.allSatisfy { k, v in g[k].map { subset(v, $0) } ?? false }
    }
    if let w = want as? [Any] {
        guard let g = got as? [Any], g.count == w.count else { return false }
        return zip(w, g).allSatisfy { subset($0, $1) }
    }
    if let w = want as? String { return (got as? String) == w }
    if let w = want as? NSNumber, let g = got as? NSNumber { return w == g }
    return false
}

struct FakeRepo: UserRepository, OrderRepository {
    static let t = Date(timeIntervalSince1970: 1_735_689_600) // 2025-01-01T00:00:00Z
    static func order(_ id: Int64) -> Order {
        Order(id: id, userID: 1, status: "pending", totalCents: 1000 * Int(id), note: "n", createdAt: t, updatedAt: t)
    }
    func getUser(id: Int64) async throws -> User {
        guard id == 1 else { throw DomainError.notFound }
        return User(id: 1, name: "Fake User", email: "fake@example.test", createdAt: Self.t)
    }
    func listOrders(userID: Int64, limit: Int) async throws -> [Order] {
        Array([Self.order(3), Self.order(2), Self.order(1)].prefix(limit))
    }
    func getUserWithOrders(id: Int64) async throws -> UserWithOrders {
        UserWithOrders(user: try await getUser(id: id), orders: try await listOrders(userID: id, limit: 100))
    }
    func createOrder(_ i: CreateOrderInput) async throws -> Order {
        Order(id: 101, userID: i.userID, status: i.status, totalCents: i.totalCents, note: i.note, createdAt: Self.t, updatedAt: Self.t)
    }
    func updateOrderStatus(id: Int64, status: String) async throws -> Order {
        guard id == 1 else { throw DomainError.notFound }
        var o = Self.order(1); o.status = status; return o
    }
    func payOrder(id: Int64) async throws -> PayResult {
        guard id == 1 else { throw DomainError.notFound }
        var o = Self.order(1); o.status = OrderStatus.paid
        return PayResult(order: o, payment: Payment(id: 1, orderID: 1, amountCents: o.totalCents, createdAt: Self.t))
    }
}

func check(_ exp: [String: Any], _ error: Error?, _ extra: [String: Any] = [:]) {
    if let want = exp["error"] as? String {
        #expect((error as? DomainError)?.message == want, "error = \(String(describing: error)), want \(want)")
        return
    }
    #expect(error == nil, "tidak diharapkan error: \(String(describing: error))")
    for (k, v) in extra {
        if let want = exp[k] { #expect(subset(want, v), "\(k) = \(v), want \(want)") }
    }
}

@Suite struct Parity {
    @Test(arguments: loadCases())
    func parity(_ c: ParityCase) async throws {
        recordRan(c.id)
        let exp = try JSONSerialization.jsonObject(with: c.expect) as! [String: Any]
        let dec = JSONDecoder()
        switch c.kind {
        case "validate_order":
            var i = try dec.decode(CreateOrderInput.self, from: c.input!)
            let err: Error? = { do { try i.normalize(); return nil } catch { return error } }()
            check(exp, err, ["status": i.status])
        case "validate_status":
            let s = try JSONSerialization.jsonObject(with: c.input!, options: [.fragmentsAllowed]) as! String
            let err: Error? = { do { try UpdateOrderInput(status: s).validate(); return nil } catch { return error } }()
            check(exp, err)
        case "validate_echo":
            let e = try dec.decode(EchoRequest.self, from: c.input!)
            let err: Error? = { do { try e.validate(); return nil } catch { return error } }()
            check(exp, err)
        case "parse_limit":
            let s = try JSONSerialization.jsonObject(with: c.input!, options: [.fragmentsAllowed]) as! String
            do { let v = try Params.parseLimit(s); check(exp, nil, ["value": v]) } catch { check(exp, error) }
        case "parse_id":
            let s = try JSONSerialization.jsonObject(with: c.input!, options: [.fragmentsAllowed]) as! String
            do { let v = try Params.parseID(s); check(exp, nil, ["value": v]) } catch { check(exp, error) }
        case "bench_json":
            let b = try JSONEncoder().encode(BenchPayload())
            let m = try JSONSerialization.jsonObject(with: b) as! [String: Any]
            #expect(m.count == (exp["keys"] as! Int))
            #expect(b.count >= (exp["min_bytes"] as! Int) && b.count <= (exp["max_bytes"] as! Int))
            #expect((m[exp["array_key"] as! String] as! [Any]).count == (exp["array_len"] as! Int))
        case "handler":
            let req = try JSONSerialization.jsonObject(with: c.request!) as! [String: Any]
            let method = HTTPMethod(rawValue: req["method"] as! String)
            let path = req["path"] as! String
            var bodyData: Data? = nil
            if let b = req["body"] { // string = badan mentah; selain itu objek JSON
                if let s = b as? String { bodyData = Data(s.utf8) } else { bodyData = try JSONSerialization.data(withJSONObject: b) }
            }
            try await withApp { app in
                app.middleware = .init()
                app.middleware.use(makeErrorMiddleware())
                registerRoutes(app, Dependencies(users: { _ in FakeRepo() }, orders: { _ in FakeRepo() }))
                try await app.testing().test(method, path, beforeRequest: { r in
                    if let d = bodyData { r.headers.contentType = .json; r.body = ByteBuffer(data: d) }
                }, afterResponse: { res async throws in
                    #expect(Int(res.status.code) == (exp["status"] as! Int), "status \(res.status.code)")
                    let got = try JSONSerialization.jsonObject(with: Data(res.body.readableBytesView), options: [.fragmentsAllowed])
                    if let want = exp["json"] { #expect(subset(want, got), "json \(got) want \(want)") }
                    if let n = exp["array_len"] as? Int { #expect((got as? [Any])?.count == n) }
                    if let n = exp["orders_len"] as? Int { #expect(((got as? [String: Any])?["orders"] as? [Any])?.count == n) }
                    #expect(res.headers.contentType == .json)
                })
            }
        default:
            Issue.record("kind tidak dikenal: \(c.kind)")
        }
    }

    @Test func casesAtLeast20() { #expect(loadCases().count >= 20) }
}
