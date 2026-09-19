import Foundation

/// The language table the service publishes at `GET /api/languages` (docs/API.md): the
/// display name and the voice locale of every supported language.
///
/// The service owns that mapping (`languages.py`, MISSION hard invariant 1) and the app
/// asks for it once per session rather than keeping a second copy of it. Until the answer
/// arrives - and on a device that never reaches the service - `SupportedLanguage`'s
/// compiled-in values stand in, so the microphone and the voice still work.
struct LanguageTable: Equatable {
    /// What the app knows before it has asked: the four codes, English names, one locale each.
    static let fallback = LanguageTable(SupportedLanguage.allCases.map {
        LanguageInfo(code: $0.rawValue, name: $0.fallbackName, voiceLocale: $0.fallbackVoiceLocale)
    })

    /// The locale to listen and speak in when no language is known yet.
    static let defaultVoiceLocale = SupportedLanguage.en.fallbackVoiceLocale

    private let byCode: [String: LanguageInfo]

    init(_ languages: [LanguageInfo]) {
        byCode = Dictionary(languages.map { ($0.code, $0) }, uniquingKeysWith: { first, _ in first })
    }

    /// The name shown on the badge: the service's, then the compiled-in one, then the code
    /// itself, so a language the app has never heard of is still named on screen.
    func name(for code: String) -> String {
        byCode[code]?.name ?? SupportedLanguage(rawValue: code)?.fallbackName ?? code
    }

    /// The locale for the recogniser and for the app's own spoken phrases. Sentences the
    /// service streams carry their own `voice_locale` and never come through here.
    func voiceLocale(for code: String?) -> String {
        guard let code else { return Self.defaultVoiceLocale }
        return byCode[code]?.voiceLocale
            ?? SupportedLanguage(rawValue: code)?.fallbackVoiceLocale
            ?? Self.defaultVoiceLocale
    }
}
