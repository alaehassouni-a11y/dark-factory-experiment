import Foundation

enum AgentAPIError: Error, Equatable {
    case invalidServiceURL
    case unauthorized                                    // 401: no bearer token
    case forbidden                                       // 403: token from another session
    case notFound                                        // 404: unknown session
    case unprocessable(detail: String?)                  // 422
    case rateLimited(resetsAt: String?, detail: String?) // 429, MISSION hard invariant 5
    case http(status: Int, detail: String?)
    case transport(String)
    case badResponse
    case malformedEvent(event: String?)
}

struct ActiveSession: Equatable {
    let id: String
    let token: String
}

/// Maps one SSE record to a typed event. Kept apart from the parser so the framing and
/// the payload shapes in API.md can change independently.
enum AgentEventDecoder {
    /// Returns nil for event names this client does not know, so a newer service does not break it.
    static func decode(_ record: SSERecord, decoder: JSONDecoder) throws -> AgentEvent? {
        if record.isDone { return .done }
        let payload = Data(record.data.utf8)
        do {
            switch record.event {
            case nil:
                // Token frames are JSON-encoded strings ("Nous ") so newlines survive. A frame
                // that is not valid JSON is shown verbatim rather than lost.
                return .token((try? decoder.decode(String.self, from: payload)) ?? record.data)
            case "language":
                return .language(try decoder.decode(LanguageEvent.self, from: payload))
            case "sentence":
                return .sentence(try decoder.decode(SentenceEvent.self, from: payload))
            case "sources":
                return .sources(try decoder.decode([SourceItem].self, from: payload))
            case "turn":
                return .turn(try decoder.decode(TurnEvent.self, from: payload))
            default:
                return nil
            }
        } catch {
            throw AgentAPIError.malformedEvent(event: record.event)
        }
    }
}

/// Typed URLSession client for the service described in docs/API.md.
final class AgentAPI {
    let baseURL: URL
    private let urlSession: URLSession
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder

    init(baseURL: URL, urlSession: URLSession = .shared) {
        self.baseURL = baseURL
        self.urlSession = urlSession
        (encoder, decoder) = Self.makeCoders()
    }

    /// Fails for anything that is not an absolute http(s) URL with a host.
    convenience init?(serviceURL: String) {
        let trimmed = serviceURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: trimmed),
              let scheme = url.scheme?.lowercased(), scheme == "http" || scheme == "https",
              url.host() != nil else { return nil }
        self.init(baseURL: url)
    }

    static func makeCoders() -> (JSONEncoder, JSONDecoder) {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return (encoder, decoder)
    }

    // MARK: Endpoints

    func languages() async throws -> [LanguageInfo] {
        let request = makeRequest("api/languages", method: "GET", token: nil)
        let (data, response) = try await send(request)
        try check(response, body: data, expecting: 200)
        return try decode([LanguageInfo].self, from: data)
    }

    func createSession(clientId: String, languageHint: String?) async throws -> CreateSessionResponse {
        var request = makeRequest("api/sessions", method: "POST", token: nil)
        request.httpBody = try encoder.encode(CreateSessionRequest(clientId: clientId, languageHint: languageHint))
        let (data, response) = try await send(request)
        try check(response, body: data, expecting: 201)
        return try decode(CreateSessionResponse.self, from: data)
    }

    func readSession(_ session: ActiveSession) async throws -> SessionTranscript {
        let request = makeRequest("api/sessions/\(session.id)", method: "GET", token: session.token)
        let (data, response) = try await send(request)
        try check(response, body: data, expecting: 200)
        return try decode(SessionTranscript.self, from: data)
    }

    func deleteSession(_ session: ActiveSession) async throws {
        let request = makeRequest("api/sessions/\(session.id)", method: "DELETE", token: session.token)
        let (data, response) = try await send(request)
        try check(response, body: data, expecting: 204)
    }

    /// Opens the turn stream. HTTP errors (401/403/404/422/429) are thrown here, before a
    /// stream is returned; failures while streaming end the stream with a thrown error.
    func postTurn(_ session: ActiveSession, text: String) async throws -> AsyncThrowingStream<AgentEvent, Error> {
        var request = makeRequest("api/sessions/\(session.id)/turns", method: "POST", token: session.token)
        request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        request.httpBody = try encoder.encode(TurnRequest(text: text))
        request.timeoutInterval = 120

        let bytes: URLSession.AsyncBytes
        let response: URLResponse
        do {
            (bytes, response) = try await urlSession.bytes(for: request)
        } catch {
            throw AgentAPIError.transport(error.localizedDescription)
        }
        guard let http = response as? HTTPURLResponse else { throw AgentAPIError.badResponse }
        if http.statusCode != 200 {
            var body = Data()
            for try await byte in bytes { body.append(byte) }
            throw error(status: http.statusCode, body: body)
        }

        let decoder = self.decoder
        return AsyncThrowingStream { continuation in
            let task = Task {
                var parser = SSEParser()
                var lineBuffer: [UInt8] = []
                func handle(_ record: SSERecord?) throws -> Bool {
                    guard let record,
                          let event = try AgentEventDecoder.decode(record, decoder: decoder) else { return false }
                    continuation.yield(event)
                    return event == .done
                }
                do {
                    // Lines are split by hand so that the blank lines that delimit events
                    // are guaranteed to reach the parser.
                    for try await byte in bytes {
                        if byte == UInt8(ascii: "\n") {
                            let line = String(decoding: lineBuffer, as: UTF8.self)
                            lineBuffer.removeAll(keepingCapacity: true)
                            if try handle(parser.feed(line: line)) { break }
                        } else {
                            lineBuffer.append(byte)
                        }
                    }
                    if !lineBuffer.isEmpty {
                        _ = try handle(parser.feed(line: String(decoding: lineBuffer, as: UTF8.self)))
                    }
                    _ = try handle(parser.flush())
                    continuation.finish()
                } catch is CancellationError {
                    continuation.finish(throwing: CancellationError())
                } catch let apiError as AgentAPIError {
                    continuation.finish(throwing: apiError)
                } catch {
                    continuation.finish(throwing: AgentAPIError.transport(error.localizedDescription))
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    // MARK: Plumbing

    private func makeRequest(_ path: String, method: String, token: String?) -> URLRequest {
        var request = URLRequest(url: baseURL.appending(path: path))
        request.httpMethod = method
        request.timeoutInterval = 30
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let token {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        return request
    }

    private func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await urlSession.data(for: request)
        } catch {
            throw AgentAPIError.transport(error.localizedDescription)
        }
        guard let http = response as? HTTPURLResponse else { throw AgentAPIError.badResponse }
        return (data, http)
    }

    private func check(_ response: HTTPURLResponse, body: Data, expecting status: Int) throws {
        guard response.statusCode != status else { return }
        throw error(status: response.statusCode, body: body)
    }

    private func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        do {
            return try decoder.decode(type, from: data)
        } catch {
            throw AgentAPIError.badResponse
        }
    }

    private func error(status: Int, body: Data) -> AgentAPIError {
        let parsed = (try? decoder.decode(ErrorBody.self, from: body)) ?? ErrorBody()
        switch status {
        case 401: return .unauthorized
        case 403: return .forbidden
        case 404: return .notFound
        case 422: return .unprocessable(detail: parsed.detail)
        case 429: return .rateLimited(resetsAt: parsed.resetsAt, detail: parsed.detail)
        default: return .http(status: status, detail: parsed.detail)
        }
    }
}
