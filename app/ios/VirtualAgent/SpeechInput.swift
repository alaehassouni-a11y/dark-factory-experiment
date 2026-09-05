import AVFoundation
import Speech

enum SpeechInputError: Error {
    case recognizerUnavailable
    case audioEngine(Error)
    case recognition(Error)
}

/// SFSpeechRecognizer + AVAudioEngine wrapper. One utterance per `start`: it ends on
/// `stop()`, after a pause in speech, or after `initialTimeout` seconds of nothing, and
/// reports `.final` exactly once. `cancel()` discards the utterance without any event.
@MainActor
final class SpeechInput {
    enum Event {
        case partial(String)
        case final(String)
        case failed(SpeechInputError)
    }

    private enum State {
        case idle, listening, stopping
    }

    /// Seconds of silence after the last recognised words before the utterance is sent.
    var silenceTimeout: TimeInterval = 1.8
    /// Seconds to wait for any speech at all before ending quietly with an empty transcript.
    var initialTimeout: TimeInterval = 8

    var isListening: Bool { state != .idle }

    private let audioEngine = AVAudioEngine()
    private var recognizer: SFSpeechRecognizer?
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var timer: Timer?
    private var state: State = .idle
    private var transcript = ""
    private var handler: ((Event) -> Void)?

    func requestAuthorization() async -> Bool {
        let speech = await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { continuation.resume(returning: $0) }
        }
        guard speech == .authorized else { return false }
        return await AVAudioApplication.requestRecordPermission()
    }

    func start(locale: Locale, onEvent: @escaping (Event) -> Void) throws {
        cancel()
        guard let recognizer = Self.recognizer(for: locale), recognizer.isAvailable else {
            throw SpeechInputError.recognizerUnavailable
        }
        try AudioSessionSetup.activateForConversation()

        let inputNode = audioEngine.inputNode
        let format = inputNode.outputFormat(forBus: 0)
        // A zero-channel format means there is no microphone (some simulators); installing
        // a tap on it would crash.
        guard format.channelCount > 0 else { throw SpeechInputError.recognizerUnavailable }

        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        request.requiresOnDeviceRecognition = recognizer.supportsOnDeviceRecognition
        inputNode.removeTap(onBus: 0)
        inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
            request.append(buffer)
        }
        audioEngine.prepare()
        do {
            try audioEngine.start()
        } catch {
            inputNode.removeTap(onBus: 0)
            throw SpeechInputError.audioEngine(error)
        }

        self.recognizer = recognizer
        self.request = request
        self.handler = onEvent
        transcript = ""
        state = .listening
        task = recognizer.recognitionTask(with: request) { [weak self] result, error in
            Task { @MainActor in
                self?.handle(result: result, error: error)
            }
        }
        arm(timeout: initialTimeout)
    }

    /// Ends the audio; the final transcript arrives through the event handler.
    func stop() {
        guard state == .listening else { return }
        state = .stopping
        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)
        request?.endAudio()
        // If the recogniser never confirms a final result, use what it gave so far.
        arm(timeout: 2)
    }

    func cancel() {
        guard state != .idle else { return }
        handler = nil
        tearDown()
    }

    private func handle(result: SFSpeechRecognitionResult?, error: Error?) {
        guard state != .idle else { return }
        if let result {
            transcript = result.bestTranscription.formattedString
            if result.isFinal {
                finish()
                return
            }
            handler?(.partial(transcript))
            if state == .listening {
                arm(timeout: silenceTimeout)
            }
        }
        if let error {
            // After endAudio, or when nothing was heard, the recogniser reports an error
            // instead of a final result; whatever was transcribed is the answer.
            if state == .stopping || !transcript.isEmpty {
                finish()
            } else {
                let handler = self.handler
                tearDown()
                handler?(.failed(.recognition(error)))
            }
        }
    }

    private func finish() {
        let handler = self.handler
        let text = transcript
        tearDown()
        handler?(.final(text))
    }

    private func tearDown() {
        timer?.invalidate()
        timer = nil
        task?.cancel()
        task = nil
        request?.endAudio()
        request = nil
        if audioEngine.isRunning {
            audioEngine.stop()
        }
        audioEngine.inputNode.removeTap(onBus: 0)
        handler = nil
        transcript = ""
        state = .idle
    }

    private func arm(timeout: TimeInterval) {
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: timeout, repeats: false) { [weak self] _ in
            Task { @MainActor in
                self?.timerFired()
            }
        }
    }

    private func timerFired() {
        switch state {
        case .listening: stop()
        case .stopping: finish()
        case .idle: break
        }
    }

    private static func recognizer(for locale: Locale) -> SFSpeechRecognizer? {
        SFSpeechRecognizer(locale: locale)
            ?? SFSpeechRecognizer(locale: Locale(identifier: SupportedLanguage.en.voiceLocale))
            ?? SFSpeechRecognizer()
    }
}
