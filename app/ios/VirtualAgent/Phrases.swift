import Foundation

/// The few sentences the app says on its own behalf (status and errors), in the four
/// supported languages. Everything conversational comes from the service; these exist so
/// that a failure is explained out loud in the client's language (MISSION Gate 2).
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
    case rateLimited(resetsAt: String)
    case serverError(status: Int)
    case microphoneDenied
    case microphoneUnavailable
    case speechNotUnderstood

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
            return pick(lang, en: "You have reached today's limit. You can continue at \(resetsAt).",
                        fr: "Vous avez atteint la limite du jour. Vous pourrez continuer à \(resetsAt).",
                        de: "Sie haben das Tageslimit erreicht. Sie können ab \(resetsAt) weitermachen.",
                        ar: "لقد وصلت إلى الحد اليومي. يمكنك المتابعة في \(resetsAt).")
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
        }
    }

    /// Turns the 429 body's ISO 8601 `resets_at` into a short local time; falls back to the raw value.
    static func formatResetTime(_ iso: String?) -> String {
        guard let iso else { return "—" }
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
        case .rateLimited(let resetsAt, _): return .rateLimited(resetsAt: Phrase.formatResetTime(resetsAt))
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
