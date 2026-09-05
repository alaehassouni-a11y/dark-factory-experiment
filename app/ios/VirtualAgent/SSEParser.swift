import Foundation

/// One dispatched Server-Sent Event: the optional `event:` name and the joined `data:` payload.
struct SSERecord: Equatable {
    var event: String?
    var data: String

    /// The stream terminator from API.md: an unnamed `data: [DONE]` frame.
    var isDone: Bool { event == nil && data == "[DONE]" }
}

/// Incremental SSE parser. Feed it one line at a time, without the line terminator; it
/// returns a record each time a blank line closes one. It is pure and synchronous so it
/// can be tested without a network, and it follows the WHATWG event-stream rules that
/// matter here: `event:`/`data:` fields, one optional space after the colon, multiple
/// `data:` lines joined with "\n", `:` comment lines ignored, other fields ignored.
struct SSEParser {
    private var eventName: String?
    private var dataLines: [String] = []

    init() {}

    mutating func feed(line rawLine: String) -> SSERecord? {
        let line = rawLine.hasSuffix("\r") ? String(rawLine.dropLast()) : rawLine
        if line.isEmpty {
            return dispatch()
        }
        if line.hasPrefix(":") {
            return nil
        }
        let (field, value) = Self.split(line)
        switch field {
        case "event":
            eventName = value
        case "data":
            dataLines.append(value)
        default:
            break
        }
        return nil
    }

    /// Dispatches a record left open when the stream ends without a closing blank line.
    mutating func flush() -> SSERecord? {
        dispatch()
    }

    private mutating func dispatch() -> SSERecord? {
        defer {
            eventName = nil
            dataLines = []
        }
        guard !dataLines.isEmpty else { return nil }
        return SSERecord(event: eventName, data: dataLines.joined(separator: "\n"))
    }

    private static func split(_ line: String) -> (field: String, value: String) {
        guard let colon = line.firstIndex(of: ":") else {
            return (line, "")
        }
        let field = String(line[..<colon])
        var value = line[line.index(after: colon)...]
        if value.hasPrefix(" ") {
            value = value.dropFirst()
        }
        return (field, String(value))
    }
}
