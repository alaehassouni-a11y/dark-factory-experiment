import AVFoundation

/// One audio session for both listening and speaking: play-and-record through the
/// speaker, so a spoken answer is not routed to the earpiece after the microphone was used.
enum AudioSessionSetup {
    static func activateForConversation() throws {
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord, mode: .default, options: [.defaultToSpeaker, .duckOthers])
        try session.setActive(true)
    }
}

/// AVSpeechSynthesizer wrapper. Sentences are queued in arrival order, each in the best
/// available voice for its `voice_locale` (API.md). `stop()` clears the queue.
@MainActor
final class SpeechOutput: NSObject, ObservableObject {
    @Published private(set) var isSpeaking = false

    private let synthesizer = AVSpeechSynthesizer()
    private var voices: [String: AVSpeechSynthesisVoice] = [:]

    override init() {
        super.init()
        synthesizer.delegate = self
    }

    func speak(_ text: String, localeIdentifier: String) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        // Best effort: synthesis still works on the default session if activation fails.
        try? AudioSessionSetup.activateForConversation()
        let utterance = AVSpeechUtterance(string: trimmed)
        utterance.voice = voice(for: localeIdentifier)
        synthesizer.speak(utterance)
        isSpeaking = true
    }

    func stop() {
        synthesizer.stopSpeaking(at: .immediate)
        isSpeaking = false
    }

    private func voice(for localeIdentifier: String) -> AVSpeechSynthesisVoice? {
        if let cached = voices[localeIdentifier] { return cached }
        let all = AVSpeechSynthesisVoice.speechVoices()
        let exact = all.filter { $0.language.caseInsensitiveCompare(localeIdentifier) == .orderedSame }
        let languageCode = localeIdentifier.split(separator: "-").first.map(String.init) ?? localeIdentifier
        let sameLanguage = all.filter { $0.language.lowercased().hasPrefix(languageCode.lowercased() + "-") }
        let chosen = Self.best(of: exact)
            ?? Self.best(of: sameLanguage)
            ?? AVSpeechSynthesisVoice(language: localeIdentifier)
            ?? AVSpeechSynthesisVoice(language: SupportedLanguage.en.voiceLocale)
        if let chosen {
            voices[localeIdentifier] = chosen
        }
        return chosen
    }

    /// Prefers enhanced or premium voices when the user has downloaded them.
    private static func best(of candidates: [AVSpeechSynthesisVoice]) -> AVSpeechSynthesisVoice? {
        candidates.max { $0.quality.rawValue < $1.quality.rawValue }
    }
}

extension SpeechOutput: AVSpeechSynthesizerDelegate {
    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        noteQueueState(of: synthesizer)
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        noteQueueState(of: synthesizer)
    }

    private nonisolated func noteQueueState(of synthesizer: AVSpeechSynthesizer) {
        let stillSpeaking = synthesizer.isSpeaking
        Task { @MainActor in
            self.isSpeaking = stillSpeaking
        }
    }
}
