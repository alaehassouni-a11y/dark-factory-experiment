import Foundation

// Wire types for docs/API.md. Property names are camelCase; the coders built in
// `AgentAPI.makeCoders()` translate to and from the service's snake_case keys.

/// The four supported languages (MISSION hard invariant 1) and the voice locale
/// API.md's `GET /api/languages` assigns to each.
enum SupportedLanguage: String, CaseIterable {
    case ar, de, en, fr

    var name: String {
        switch self {
        case .ar: return "Arabic"
        case .de: return "German"
        case .en: return "English"
        case .fr: return "French"
        }
    }

    var voiceLocale: String {
        switch self {
        case .ar: return "ar-SA"
        case .de: return "de-DE"
        case .en: return "en-US"
        case .fr: return "fr-FR"
        }
    }
}

// MARK: - Sessions

struct CreateSessionRequest: Encodable, Equatable {
    var clientId: String
    var languageHint: String?
}

struct Greeting: Decodable, Equatable {
    var text: String
    var language: String?
    var voiceLocale: String
}

struct CreateSessionResponse: Decodable, Equatable {
    var sessionId: String
    var sessionToken: String
    var language: String?
    var greeting: Greeting
}

struct TurnRequest: Encodable, Equatable {
    var text: String
}

struct TranscriptTurn: Decodable, Equatable {
    var role: String
    var text: String
    var language: String?
    var kind: TurnKind?
    var source: TurnSource?
}

struct SessionTranscript: Decodable, Equatable {
    var sessionId: String
    var language: String?
    var createdAt: String
    var turns: [TranscriptTurn]
}

// MARK: - System

struct LanguageInfo: Decodable, Equatable {
    var code: String
    var name: String
    var voiceLocale: String
}

/// Error bodies: `{"detail": ...}` everywhere, plus `resets_at` on 429. `detail` is decoded
/// leniently because FastAPI-style 422 bodies carry an array there instead of a string.
struct ErrorBody: Decodable, Equatable {
    var detail: String?
    var resetsAt: String?

    private enum CodingKeys: String, CodingKey {
        case detail, resetsAt
    }

    init(detail: String? = nil, resetsAt: String? = nil) {
        self.detail = detail
        self.resetsAt = resetsAt
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        detail = try? container.decodeIfPresent(String.self, forKey: .detail)
        resetsAt = try? container.decodeIfPresent(String.self, forKey: .resetsAt)
    }
}

// MARK: - Turn stream events

// The three enums below decode an unexpected value as `.unknown` instead of failing the
// whole turn: the service must never send one (hard invariant 3), but the app must never crash.

enum TurnKind: String, Decodable, Equatable {
    case answer
    case question
    case noAnswer = "no_answer"
    case unknown

    init(from decoder: Decoder) throws {
        self = Self(rawValue: try decoder.singleValueContainer().decode(String.self)) ?? .unknown
    }

    var label: String { rawValue.replacingOccurrences(of: "_", with: " ") }
}

enum TurnSource: String, Decodable, Equatable {
    case wiki
    case web
    case noSource = "none"
    case unknown

    init(from decoder: Decoder) throws {
        self = Self(rawValue: try decoder.singleValueContainer().decode(String.self)) ?? .unknown
    }

    var label: String { rawValue }
}

enum SourceKind: String, Decodable, Equatable {
    case wiki
    case web
    case unknown

    init(from decoder: Decoder) throws {
        self = Self(rawValue: try decoder.singleValueContainer().decode(String.self)) ?? .unknown
    }
}

struct LanguageEvent: Decodable, Equatable {
    var language: String?
    var voiceLocale: String?
    var confidence: Double?
}

struct SentenceEvent: Decodable, Equatable {
    var index: Int
    var text: String
    var language: String?
    var voiceLocale: String
}

struct SourceItem: Decodable, Equatable {
    var kind: SourceKind
    var title: String
    var location: String?
    var url: String?
    var snippet: String?

    /// What the transcript shows next to the title: the wiki path or the web page.
    var reference: String? { location ?? url }
}

struct TurnEvent: Decodable, Equatable {
    var kind: TurnKind
    var source: TurnSource
    var language: String?
}

/// One decoded frame of the `POST /turns` stream, in the order API.md lists them.
enum AgentEvent: Equatable {
    case language(LanguageEvent)
    case token(String)
    case sentence(SentenceEvent)
    case sources([SourceItem])
    case turn(TurnEvent)
    case done
}

// MARK: - Screen state

enum ConversationPhase: Equatable {
    case idle, connecting, listening, streaming
}

/// One bubble of the transcript. Agent bubbles fill in as the turn streams.
struct TranscriptMessage: Identifiable, Equatable {
    enum Role {
        case client, agent
    }

    let id = UUID()
    let role: Role
    var text: String
    var sources: [SourceItem] = []
    var kind: TurnKind?
    var source: TurnSource?
    var isStreaming = false
}
