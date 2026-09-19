import Foundation

/// Everything the client reads or hears that the app says on its own behalf - status,
/// errors, button and accessibility labels, the two words under each answer - in the four
/// supported languages. Everything conversational comes from the service; these exist so
/// that a failure is explained out loud in the client's language (MISSION Gate 2) and so
/// that no screen is half in English. A string shown or spoken anywhere else in the app is
/// a bug `harness/static_ios.py` now fails on. The product name is the one exception: a
/// name is not translated. The two permission prompts cannot live here, because iOS shows
/// them before any code runs; they are in `VirtualAgent/<lang>.lproj/InfoPlist.strings`.
enum Phrase {
    case tapToSpeak
    case listening
    case thinking
    case typeMessage
    case networkFailure
    case invalidServiceURL
    case unauthorized
    case forbidden
    case sessionNotFound
    case rateLimited(resetsAt: String?)
    case serverError(status: Int)
    case microphoneDenied
    case microphoneUnavailable
    case speechNotUnderstood
    // What the screen shows and VoiceOver speaks. A label is as much a spoken string as a
    // sentence is: a French client must not meet an English button.
    case settings
    case done
    case newSession
    case serviceURL
    case send
    case speak
    case stopListening
    case language(name: String)
    case languageNotDetected
    // The two words under every answer: what the turn was, and where it came from
    // (API.md's `turn` event, hard invariant 3).
    case turnAnswer
    case turnQuestion
    case turnNoAnswer
    case turnUnknownKind
    case sourceWiki
    case sourceWeb
    case sourceNone
    case sourceUnknown

    /// `language` is a code from API.md; anything else, including nil, falls back to English.
    func text(in language: String?) -> String {
        let lang = SupportedLanguage(rawValue: language ?? "") ?? .en
        switch self {
        case .tapToSpeak:
            return pick(lang, en: "Tap the microphone to speak", fr: "Touchez le micro pour parler",
                        de: "Tippen Sie auf das Mikrofon, um zu sprechen", ar: "اضغط على الميكروفون للتحدث")
        case .listening:
            return pick(lang, en: "Listening…", fr: "Je vous écoute…", de: "Ich höre zu…", ar: "أنا أستمع…")
        case .thinking:
            return pick(lang, en: "One moment…", fr: "Un instant…", de: "Einen Moment…", ar: "لحظة من فضلك…")
        case .typeMessage:
            return pick(lang, en: "Or type here", fr: "Ou écrivez ici", de: "Oder hier schreiben", ar: "أو اكتب هنا")
        case .networkFailure:
            return pick(lang, en: "I can't reach the service right now. Please try again in a moment.",
                        fr: "Je n'arrive pas à joindre le service pour le moment. Veuillez réessayer dans un instant.",
                        de: "Ich kann den Dienst gerade nicht erreichen. Bitte versuchen Sie es gleich noch einmal.",
                        ar: "لا أستطيع الوصول إلى الخدمة الآن. يرجى المحاولة مرة أخرى بعد قليل.")
        case .invalidServiceURL:
            return pick(lang, en: "The service address is not valid. Please check it in the settings.",
                        fr: "L'adresse du service n'est pas valide. Veuillez la vérifier dans les réglages.",
                        de: "Die Dienstadresse ist ungültig. Bitte prüfen Sie sie in den Einstellungen.",
                        ar: "عنوان الخدمة غير صالح. يرجى التحقق منه في الإعدادات.")
        case .unauthorized:
            return pick(lang, en: "This conversation has no access token. I will start a new one.",
                        fr: "Cette conversation n'a pas de jeton d'accès. Je vais en commencer une nouvelle.",
                        de: "Dieses Gespräch hat kein Zugriffstoken. Ich beginne ein neues.",
                        ar: "هذه المحادثة لا تملك رمز وصول. سأبدأ محادثة جديدة.")
        case .forbidden:
            return pick(lang, en: "This conversation belongs to someone else. I will start a new one.",
                        fr: "Cette conversation appartient à quelqu'un d'autre. Je vais en commencer une nouvelle.",
                        de: "Dieses Gespräch gehört jemand anderem. Ich beginne ein neues.",
                        ar: "هذه المحادثة تخص شخصًا آخر. سأبدأ محادثة جديدة.")
        case .sessionNotFound:
            return pick(lang, en: "This conversation has ended. I will start a new one.",
                        fr: "Cette conversation est terminée. Je vais en commencer une nouvelle.",
                        de: "Dieses Gespräch ist beendet. Ich beginne ein neues.",
                        ar: "انتهت هذه المحادثة. سأبدأ محادثة جديدة.")
        case .rateLimited(let resetsAt):
            let when = Phrase.formatResetTime(resetsAt) ?? pick(lang, en: "later today",
                        fr: "plus tard dans la journée", de: "später am Tag", ar: "لاحقًا اليوم")
            return pick(lang, en: "You have reached today's limit. You can continue at \(when).",
                        fr: "Vous avez atteint la limite du jour. Vous pourrez continuer à \(when).",
                        de: "Sie haben das Tageslimit erreicht. Sie können ab \(when) weitermachen.",
                        ar: "لقد وصلت إلى الحد اليومي. يمكنك المتابعة في \(when).")
        case .serverError(let status):
            return pick(lang, en: "The service returned an error (\(status)). Please try again.",
                        fr: "Le service a renvoyé une erreur (\(status)). Veuillez réessayer.",
                        de: "Der Dienst hat einen Fehler gemeldet (\(status)). Bitte versuchen Sie es erneut.",
                        ar: "أعادت الخدمة خطأ (\(status)). يرجى المحاولة مرة أخرى.")
        case .microphoneDenied:
            return pick(lang, en: "I need permission to use the microphone and speech recognition. You can allow it in Settings, or type instead.",
                        fr: "J'ai besoin de l'autorisation d'utiliser le micro et la reconnaissance vocale. Vous pouvez l'accorder dans les Réglages, ou écrire à la place.",
                        de: "Ich brauche die Erlaubnis für Mikrofon und Spracherkennung. Sie können sie in den Einstellungen erteilen oder stattdessen schreiben.",
                        ar: "أحتاج إلى إذن لاستخدام الميكروفون والتعرف على الكلام. يمكنك السماح بذلك في الإعدادات، أو الكتابة بدلاً من ذلك.")
        case .microphoneUnavailable:
            return pick(lang, en: "I can't listen on this device right now. You can type instead.",
                        fr: "Je ne peux pas écouter sur cet appareil pour le moment. Vous pouvez écrire à la place.",
                        de: "Ich kann auf diesem Gerät gerade nicht zuhören. Sie können stattdessen schreiben.",
                        ar: "لا أستطيع الاستماع على هذا الجهاز الآن. يمكنك الكتابة بدلاً من ذلك.")
        case .speechNotUnderstood:
            return pick(lang, en: "I didn't catch that. Please try again.",
                        fr: "Je n'ai pas compris. Veuillez réessayer.",
                        de: "Das habe ich nicht verstanden. Bitte versuchen Sie es noch einmal.",
                        ar: "لم أفهم ذلك. يرجى المحاولة مرة أخرى.")
        case .settings:
            return pick(lang, en: "Settings", fr: "Réglages", de: "Einstellungen", ar: "الإعدادات")
        case .done:
            return pick(lang, en: "Done", fr: "Terminé", de: "Fertig", ar: "تم")
        case .newSession:
            return pick(lang, en: "New session", fr: "Nouvelle conversation",
                        de: "Neues Gespräch", ar: "محادثة جديدة")
        case .serviceURL:
            return pick(lang, en: "Service address", fr: "Adresse du service",
                        de: "Dienstadresse", ar: "عنوان الخدمة")
        case .send:
            return pick(lang, en: "Send", fr: "Envoyer", de: "Senden", ar: "إرسال")
        case .speak:
            return pick(lang, en: "Speak", fr: "Parler", de: "Sprechen", ar: "تحدث")
        case .stopListening:
            return pick(lang, en: "Stop listening", fr: "Arrêter l'écoute",
                        de: "Zuhören beenden", ar: "إيقاف الاستماع")
        case .language(let name):
            return pick(lang, en: "Language: \(name)", fr: "Langue : \(name)",
                        de: "Sprache: \(name)", ar: "اللغة: \(name)")
        case .languageNotDetected:
            return pick(lang, en: "not detected yet", fr: "non détectée pour l'instant",
                        de: "noch nicht erkannt", ar: "لم يتم تحديدها بعد")
        case .turnAnswer:
            return pick(lang, en: "answer", fr: "réponse", de: "Antwort", ar: "إجابة")
        case .turnQuestion:
            return pick(lang, en: "question", fr: "question", de: "Frage", ar: "سؤال")
        case .turnNoAnswer:
            return pick(lang, en: "no answer", fr: "pas de réponse",
                        de: "keine Antwort", ar: "لا توجد إجابة")
        case .turnUnknownKind:
            return pick(lang, en: "unknown", fr: "inconnu", de: "unbekannt", ar: "غير معروف")
        case .sourceWiki:
            return pick(lang, en: "wiki", fr: "wiki", de: "Wiki", ar: "الويكي")
        case .sourceWeb:
            return pick(lang, en: "web", fr: "web", de: "Web", ar: "الويب")
        case .sourceNone:
            return pick(lang, en: "no source", fr: "aucune source",
                        de: "keine Quelle", ar: "بدون مصدر")
        case .sourceUnknown:
            return pick(lang, en: "unknown source", fr: "source inconnue",
                        de: "unbekannte Quelle", ar: "مصدر غير معروف")
        }
    }

    /// Turns the 429 body's ISO 8601 `resets_at` into a short local time; falls back to the
    /// raw value, and to nil when the service sent no time at all - the caller then says
    /// "later today" in the client's language rather than showing a dash.
    static func formatResetTime(_ iso: String?) -> String? {
        guard let iso else { return nil }
        let withFraction = ISO8601DateFormatter()
        withFraction.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let plain = ISO8601DateFormatter()
        guard let date = withFraction.date(from: iso) ?? plain.date(from: iso) else { return iso }
        let isToday = Calendar.current.isDateInToday(date)
        return date.formatted(date: isToday ? .omitted : .abbreviated, time: .shortened)
    }

    private func pick(_ language: SupportedLanguage, en: String, fr: String, de: String, ar: String) -> String {
        switch language {
        case .en: return en
        case .fr: return fr
        case .de: return de
        case .ar: return ar
        }
    }
}

extension AgentAPIError {
    /// What the app says for each failure in API.md's error list.
    var phrase: Phrase {
        switch self {
        case .unauthorized: return .unauthorized
        case .forbidden: return .forbidden
        case .notFound: return .sessionNotFound
        case .rateLimited(let resetsAt, _): return .rateLimited(resetsAt: resetsAt)
        case .invalidServiceURL: return .invalidServiceURL
        case .unprocessable: return .serverError(status: 422)
        case .http(let status, _): return .serverError(status: status)
        case .transport, .badResponse, .malformedEvent: return .networkFailure
        }
    }

    /// 401/403/404 mean the session cannot be continued; the next turn opens a new one.
    var invalidatesSession: Bool {
        switch self {
        case .unauthorized, .forbidden, .notFound: return true
        default: return false
        }
    }
}

extension TurnKind {
    /// The word under an answer. The wire value is a protocol token, never shown as it is.
    var phrase: Phrase {
        switch self {
        case .answer: return .turnAnswer
        case .question: return .turnQuestion
        case .noAnswer: return .turnNoAnswer
        case .unknown: return .turnUnknownKind
        }
    }
}

extension TurnSource {
    /// Where the answer came from, in the client's language (hard invariant 3).
    var phrase: Phrase {
        switch self {
        case .wiki: return .sourceWiki
        case .web: return .sourceWeb
        case .noSource: return .sourceNone
        case .unknown: return .sourceUnknown
        }
    }
}
