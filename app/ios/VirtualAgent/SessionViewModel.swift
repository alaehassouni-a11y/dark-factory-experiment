import Foundation
import SwiftUI

/// Owns the session, the transcript and both speech engines for the single screen.
@MainActor
final class SessionViewModel: ObservableObject {
    static let defaultServiceURL = "http://localhost:8000"
    private static let serviceURLKey = "service_url"

    @Published private(set) var messages: [TranscriptMessage] = []
    @Published private(set) var phase: ConversationPhase = .idle
    @Published private(set) var currentLanguage: String?
    @Published private(set) var partialTranscript = ""
    @Published private(set) var errorMessage: String?
    @Published private(set) var serviceURLString: String
    @Published var draftText = ""

    private let defaults: UserDefaults
    private let clientId: String
    private let input: SpeechInput
    private let output: SpeechOutput
    private var session: ActiveSession?
    private var recognizerLocale = SupportedLanguage.en.voiceLocale
    private var turnTask: Task<Void, Never>?
    private var sessionTask: Task<Void, Never>?

    init(defaults: UserDefaults = .standard, input: SpeechInput = SpeechInput(), output: SpeechOutput = SpeechOutput()) {
        self.defaults = defaults
        self.clientId = ClientIdentity.id(defaults: defaults)
        self.input = input
        self.output = output
        self.serviceURLString = defaults.string(forKey: Self.serviceURLKey) ?? Self.defaultServiceURL
    }

    /// Badge text: the language name for a supported code, the code itself otherwise, nil before any is known.
    var languageName: String? {
        currentLanguage.map { SupportedLanguage(rawValue: $0)?.name ?? $0 }
    }

    func phrase(_ phrase: Phrase) -> String {
        phrase.text(in: currentLanguage)
    }

    // MARK: Lifecycle

    func start() async {
        guard session == nil, phase == .idle else { return }
        await openSession()
    }

    func newSession() {
        turnTask?.cancel()
        turnTask = nil
        sessionTask?.cancel()
        input.cancel()
        output.stop()
        let old = session
        session = nil
        messages = []
        partialTranscript = ""
        errorMessage = nil
        currentLanguage = nil
        phase = .idle
        sessionTask = Task {
            if let old, let api = makeAPI() {
                try? await api.deleteSession(old) // best effort; the old transcript is gone either way
            }
            await openSession()
        }
    }

    /// Stores the service address. A changed address, or `restart`, starts a new session.
    func applyServiceURL(_ raw: String, restart: Bool = false) {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        let value = trimmed.isEmpty ? Self.defaultServiceURL : trimmed
        let changed = value != serviceURLString
        if changed {
            serviceURLString = value
            defaults.set(value, forKey: Self.serviceURLKey)
        }
        if changed || restart {
            newSession()
        }
    }

    func didEnterBackground() {
        guard phase == .listening else { return }
        let heard = partialTranscript
        input.cancel()
        partialTranscript = ""
        phase = .idle
        if !heard.isEmpty {
            draftText = heard // keep what was heard so nothing is lost silently
        }
    }

    // MARK: Client input

    func toggleMicrophone() {
        switch phase {
        case .listening:
            input.stop()
        case .idle:
            Task { await beginListening() }
        case .connecting, .streaming:
            break
        }
    }

    func sendDraft() {
        let text = draftText
        draftText = ""
        send(text)
    }

    func send(_ raw: String) {
        let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, phase == .idle || phase == .listening else { return }
        if phase == .listening {
            input.cancel()
            partialTranscript = ""
        }
        output.stop()
        errorMessage = nil
        turnTask = Task { await runTurn(text) }
    }

    private func beginListening() async {
        output.stop()
        guard await input.requestAuthorization() else {
            say(.microphoneDenied)
            return
        }
        if session == nil {
            await openSession()
        }
        guard session != nil else { return }
        do {
            try input.start(locale: Locale(identifier: recognizerLocale)) { [weak self] event in
                self?.handleSpeech(event)
            }
            partialTranscript = ""
            errorMessage = nil
            phase = .listening
        } catch {
            say(.microphoneUnavailable)
        }
    }

    private func handleSpeech(_ event: SpeechInput.Event) {
        partialTranscript = ""
        switch event {
        case .partial(let text):
            partialTranscript = text
        case .final(let text):
            phase = .idle
            send(text)
        case .failed:
            phase = .idle
            say(.speechNotUnderstood)
        }
    }

    // MARK: Session and turns

    private func openSession() async {
        guard let api = makeAPI() else {
            say(.invalidServiceURL)
            return
        }
        phase = .connecting
        errorMessage = nil
        // A cancelled opener (New session tapped while connecting) must not touch the
        // state the replacement is already building.
        defer { if !Task.isCancelled { phase = .idle } }
        do {
            let hint = Self.deviceLanguage()?.rawValue
            let response = try await api.createSession(clientId: clientId, languageHint: hint)
            guard !Task.isCancelled else { return }
            session = ActiveSession(id: response.sessionId, token: response.sessionToken)
            currentLanguage = response.language
            // API.md voice contract: device locale if supported, else English, until the first `language` event.
            recognizerLocale = (Self.deviceLanguage() ?? .en).voiceLocale
            messages = [TranscriptMessage(role: .agent, text: response.greeting.text, kind: .question, source: .noSource)]
            output.speak(response.greeting.text, localeIdentifier: response.greeting.voiceLocale)
        } catch {
            handle(error)
        }
    }

    private func runTurn(_ text: String) async {
        if session == nil {
            await openSession()
        }
        guard !Task.isCancelled else { return }
        guard let session, let api = makeAPI() else {
            draftText = text // the failure was spoken; the client keeps their text
            return
        }
        messages.append(TranscriptMessage(role: .client, text: text))
        let reply = TranscriptMessage(role: .agent, text: "", isStreaming: true)
        messages.append(reply)
        phase = .streaming
        do {
            let events = try await api.postTurn(session, text: text)
            for try await event in events {
                apply(event, to: reply.id)
            }
        } catch {
            handle(error)
        }
        update(reply.id) { $0.isStreaming = false }
        if let index = messages.firstIndex(where: { $0.id == reply.id }), messages[index].text.isEmpty {
            messages.remove(at: index)
        }
        if phase == .streaming {
            phase = .idle
        }
    }

    private func apply(_ event: AgentEvent, to id: UUID) {
        switch event {
        case .language(let detected):
            // A null language means the client was not understood; the agent asks, in
            // English, to continue in a supported language, and the recogniser stays as is.
            guard let code = detected.language else { return }
            currentLanguage = code
            recognizerLocale = detected.voiceLocale ?? SupportedLanguage(rawValue: code)?.voiceLocale ?? recognizerLocale
        case .token(let token):
            update(id) { $0.text += token }
        case .sentence(let sentence):
            output.speak(sentence.text, localeIdentifier: sentence.voiceLocale)
        case .sources(let sources):
            update(id) { $0.sources = sources }
        case .turn(let turn):
            update(id) {
                $0.kind = turn.kind
                $0.source = turn.source
            }
        case .done:
            break
        }
    }

    private func update(_ id: UUID, _ change: (inout TranscriptMessage) -> Void) {
        guard let index = messages.firstIndex(where: { $0.id == id }) else { return }
        change(&messages[index])
    }

    // MARK: Errors

    private func handle(_ error: Error) {
        if error is CancellationError { return }
        guard let apiError = error as? AgentAPIError else {
            say(.networkFailure)
            return
        }
        if apiError.invalidatesSession {
            session = nil
        }
        say(apiError.phrase)
    }

    /// Every failure is shown and spoken in the session language, English before one is known.
    private func say(_ phrase: Phrase) {
        let text = phrase.text(in: currentLanguage)
        errorMessage = text
        output.stop()
        let locale = SupportedLanguage(rawValue: currentLanguage ?? "")?.voiceLocale ?? SupportedLanguage.en.voiceLocale
        output.speak(text, localeIdentifier: locale)
    }

    private func makeAPI() -> AgentAPI? {
        AgentAPI(serviceURL: serviceURLString)
    }

    private static func deviceLanguage() -> SupportedLanguage? {
        Locale.current.language.languageCode.flatMap { SupportedLanguage(rawValue: $0.identifier) }
    }
}
