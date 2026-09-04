import SwiftUI

@main
struct VirtualAgentApp: App {
    @StateObject private var model = SessionViewModel()

    var body: some Scene {
        WindowGroup {
            ContentView(model: model)
        }
    }
}
