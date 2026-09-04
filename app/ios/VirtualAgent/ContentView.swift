import SwiftUI

/// The single screen: transcript, status line, text composer, microphone button.
struct ContentView: View {
    @ObservedObject var model: SessionViewModel
    @Environment(\.scenePhase) private var scenePhase
    @State private var showSettings = false

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                transcript
                Divider()
                statusArea
                composer
                microphone
            }
            .navigationTitle("Virtual Agent")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { languageBadge }
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        showSettings = true
                    } label: {
                        Image(systemName: "gearshape")
                    }
                    .accessibilityLabel("Settings")
                }
            }
            .sheet(isPresented: $showSettings) { SettingsSheet(model: model) }
        }
        .task { await model.start() }
        .onChange(of: scenePhase) { _, newPhase in
            if newPhase == .background {
                model.didEnterBackground()
            }
        }
    }

    private var transcript: some View {
        ScrollView {
            LazyVStack(spacing: 12) {
                ForEach(model.messages) { MessageBubble(message: $0) }
            }
            .padding()
        }
        .defaultScrollAnchor(.bottom)
    }

    private var languageBadge: some View {
        HStack(spacing: 4) {
            Image(systemName: "globe")
            if let name = model.languageName {
                Text(name)
            }
        }
        .font(.caption.weight(.semibold))
        .padding(.horizontal, 10)
        .padding(.vertical, 5)
        .background(Capsule().fill(Color.accentColor.opacity(0.15)))
        .accessibilityLabel("Language: \(model.languageName ?? "not detected yet")")
    }

    private var statusArea: some View {
        VStack(spacing: 6) {
            if let error = model.errorMessage {
                Label(error, systemImage: "exclamationmark.triangle")
                    .font(.footnote)
                    .foregroundStyle(.red)
            }
            Text(statusText)
                .font(.footnote)
                .foregroundStyle(.secondary)
        }
        .multilineTextAlignment(.center)
        .frame(maxWidth: .infinity)
        .padding(.horizontal)
        .padding(.top, 8)
    }

    private var statusText: String {
        switch model.phase {
        case .listening:
            return model.partialTranscript.isEmpty ? model.phrase(.listening) : model.partialTranscript
        case .connecting, .streaming:
            return model.phrase(.thinking)
        case .idle:
            return model.phrase(.tapToSpeak)
        }
    }

    private var composer: some View {
        HStack {
            TextField(model.phrase(.typeMessage), text: $model.draftText)
                .textFieldStyle(.roundedBorder)
                .submitLabel(.send)
                .onSubmit { model.sendDraft() }
            Button {
                model.sendDraft()
            } label: {
                Image(systemName: "arrow.up.circle.fill").font(.title2)
            }
            .disabled(!canSend)
            .accessibilityLabel("Send")
        }
        .padding(.horizontal)
        .padding(.vertical, 8)
    }

    private var canSend: Bool {
        let hasText = !model.draftText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        return hasText && (model.phase == .idle || model.phase == .listening)
    }

    private var microphone: some View {
        let listening = model.phase == .listening
        let enabled = model.phase == .idle || listening
        return Button {
            model.toggleMicrophone()
        } label: {
            Image(systemName: listening ? "stop.fill" : "mic.fill")
                .font(.system(size: 36, weight: .semibold))
                .foregroundStyle(.white)
                .frame(width: 96, height: 96)
                .background(Circle().fill(listening ? Color.red : Color.accentColor))
                .scaleEffect(listening ? 1.08 : 1)
                .animation(listening ? .easeInOut(duration: 0.7).repeatForever(autoreverses: true) : .default,
                           value: listening)
        }
        .disabled(!enabled)
        .opacity(enabled ? 1 : 0.5)
        .accessibilityLabel(listening ? "Stop listening" : "Speak")
        .padding(.bottom, 16)
    }
}

private struct MessageBubble: View {
    let message: TranscriptMessage

    var body: some View {
        HStack {
            if message.role == .client {
                Spacer(minLength: 40)
            }
            VStack(alignment: .leading, spacing: 6) {
                if message.text.isEmpty && message.isStreaming {
                    ProgressView()
                } else {
                    Text(message.text).textSelection(.enabled)
                }
                if !message.sources.isEmpty {
                    sourcesList
                }
                if let label = turnLabel {
                    Text(label)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
            .padding(12)
            .background(
                RoundedRectangle(cornerRadius: 16)
                    .fill(message.role == .client ? Color.accentColor.opacity(0.2) : Color(.secondarySystemBackground))
            )
            if message.role == .agent {
                Spacer(minLength: 40)
            }
        }
    }

    private var sourcesList: some View {
        VStack(alignment: .leading, spacing: 2) {
            ForEach(Array(message.sources.enumerated()), id: \.offset) { _, source in
                HStack(spacing: 4) {
                    Image(systemName: source.kind == .web ? "globe" : "doc.text")
                    Text(source.title).bold()
                    if let reference = source.reference {
                        Text(reference).lineLimit(1).truncationMode(.middle)
                    }
                }
                .font(.caption)
                .foregroundStyle(.secondary)
            }
        }
    }

    private var turnLabel: String? {
        guard let kind = message.kind, let source = message.source else { return nil }
        return "\(kind.label) · \(source.label)"
    }
}

/// Only what MISSION Gate 2 tolerates: the service address and a way to start over.
private struct SettingsSheet: View {
    @ObservedObject var model: SessionViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var url = ""

    var body: some View {
        NavigationStack {
            Form {
                Section("Service URL") {
                    TextField(SessionViewModel.defaultServiceURL, text: $url)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                }
                Section {
                    Button("New session") {
                        model.applyServiceURL(url, restart: true)
                        dismiss()
                    }
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") {
                        model.applyServiceURL(url)
                        dismiss()
                    }
                }
            }
            .onAppear { url = model.serviceURLString }
        }
    }
}
