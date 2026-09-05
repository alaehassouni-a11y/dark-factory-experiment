import Foundation

/// The `client_id` from API.md: generated once per install and kept in UserDefaults.
/// The service counts the daily turn cap per client_id, so it must not change between launches.
enum ClientIdentity {
    private static let key = "client_id"

    static func id(defaults: UserDefaults = .standard) -> String {
        if let existing = defaults.string(forKey: key), !existing.isEmpty {
            return existing
        }
        let fresh = UUID().uuidString
        defaults.set(fresh, forKey: key)
        return fresh
    }
}
