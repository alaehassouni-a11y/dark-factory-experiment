# Virtual Agent - iOS client

Native SwiftUI iPhone app for the service described in `docs/API.md`. iOS 17+, Swift 5.9,
no third-party dependencies. The project is described by `project.yml` (XcodeGen) so it
can be generated on any Mac with Xcode 15 or newer.

## Generate and run

1. Install XcodeGen once: `brew install xcodegen`.
2. From this directory: `xcodegen generate`, then `open VirtualAgent.xcodeproj`.
3. In Xcode, select the `VirtualAgent` target, then *Signing & Capabilities*: pick your
   team and, if the default `com.virtualagent.mobile` is taken, change the bundle id.
4. Start the service (see the repository README) and run the app on an iPhone or a
   simulator.
5. Service URL: the app defaults to `http://localhost:8000`, which only works in the
   simulator. On a physical iPhone open the gear icon and enter the Mac's LAN address,
   for example `http://192.168.1.20:8000`, then tap *Done*. The app opens a new session
   against the new address. `Info.plist` allows plain HTTP to local-network hosts only
   (`NSAllowsLocalNetworking`); a remote deployment needs HTTPS.
6. Tests: Product > Test (`Cmd+U`) runs `VirtualAgentTests`.

The app asks for microphone and speech-recognition permission the first time the
microphone button is tapped. Speech recognition runs on-device when iOS reports that the
locale supports it, otherwise through Apple's servers.

## What the app does

- On launch it creates a session with a stable `client_id` and a `language_hint` equal to
  the device language when that is one of `ar`, `de`, `en`, `fr`, then speaks and shows
  the greeting.
- The microphone button listens in the session's current language (device locale if
  supported, else `en-US`, until the first `language` event). Listening stops on a second
  tap or after a pause; the transcript is sent as a turn. A text field does the same for
  typed input.
- While a turn streams, tokens fill the agent bubble, every `sentence` event is spoken in
  its `voice_locale`, `language` updates the badge and the recogniser for the next turn,
  `sources` appear under the bubble, and `turn` adds a small `kind - source` label.
- Errors (401, 403, 404, 429 with its `resets_at`, network failures) are shown and spoken
  in the current language, English before one is known. 401/403/404 drop the session; the
  next turn opens a new one.
- Going to the background while listening stops the microphone; what was heard is kept
  in the text field. Speech output keeps playing.

## Files

| File | Role |
|---|---|
| `project.yml` | XcodeGen spec: app target, unit-test target, scheme |
| `VirtualAgent/Info.plist` | Permissions strings, local-network ATS exception, display name |
| `VirtualAgent/VirtualAgentApp.swift` | App entry |
| `VirtualAgent/ContentView.swift` | The single screen plus the settings sheet |
| `VirtualAgent/SessionViewModel.swift` | Session lifecycle, turns, transcript, language, errors |
| `VirtualAgent/AgentAPI.swift` | Typed URLSession client, SSE stream to typed events |
| `VirtualAgent/SSEParser.swift` | Line-fed Server-Sent Events parser |
| `VirtualAgent/SpeechInput.swift` | `SFSpeechRecognizer` + `AVAudioEngine` wrapper |
| `VirtualAgent/SpeechOutput.swift` | `AVSpeechSynthesizer` wrapper and shared audio-session setup |
| `VirtualAgent/ClientIdentity.swift` | Persistent `client_id` |
| `VirtualAgent/Models.swift` | Codable types for every request, response and event |
| `VirtualAgent/Phrases.swift` | The app's own status and error sentences in the four languages |
| `VirtualAgentTests/SSEParserTests.swift` | Parser and event-decoding tests |

## Not verified

Nothing in this directory has been compiled, generated, or run. It was written on a
Windows machine without Xcode, XcodeGen, or an iOS SDK. Expect to fix at least the first
build: API availability on the iOS 17 SDK, Swift concurrency diagnostics, and XcodeGen
schema details are the likely places. The unit tests have not been executed either. The
voice behaviour (silence detection, voice selection, audio-session routing) has not been
tried on a device.
