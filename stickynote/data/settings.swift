// The settings window and menu bar item.
//
// Compiled on the user's own machine alongside the notifier, which is what
// keeps the whole project free of Gatekeeper: nothing arrives already built,
// so nothing is ever quarantined.
//
// Everything shown here is read from `stickynote dump`, and every change is
// applied by calling the CLI back. That indirection is deliberate. Changing
// the app icon has to bump the bundle generation and rebuild the app;
// changing the frequency has to reschedule the next notification. Duplicating
// those rules in Swift would mean two implementations that drift apart, and
// the Swift one would be the one nobody tests.

import AppKit
import SwiftUI

// MARK: - Talking to the CLI

/// How to re-enter the Python side. Passed in at launch because the app
/// bundle has no reliable way to find the interpreter that installed it.
struct Runtime {
    var python: String
    var pythonPath: String

    static func parse(_ args: [String]) -> Runtime {
        // The build records both in the bundle, so that a launch which carries
        // no arguments at all -- from Spotlight, Finder or the Dock -- can
        // still find the interpreter the app was installed with. Arguments,
        // when there are any, win.
        let info = Bundle.main.infoDictionary
        var runtime = Runtime(
            python: info?["StickyNotePython"] as? String ?? "/usr/bin/python3",
            pythonPath: info?["StickyNotePythonPath"] as? String ?? ""
        )
        var index = 0
        while index < args.count - 1 {
            switch args[index] {
            case "--python": runtime.python = args[index + 1]
            case "--pypath": runtime.pythonPath = args[index + 1]
            default: index -= 1
            }
            index += 2
        }
        return runtime
    }

    @discardableResult
    func run(_ arguments: [String]) -> String {
        let task = Process()
        task.executableURL = URL(fileURLWithPath: python)
        task.arguments = ["-m", "stickynote"] + arguments

        var environment = ProcessInfo.processInfo.environment
        if !pythonPath.isEmpty { environment["PYTHONPATH"] = pythonPath }
        task.environment = environment

        let pipe = Pipe()
        task.standardOutput = pipe
        task.standardError = Pipe()

        do {
            try task.run()
        } catch {
            return ""
        }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        task.waitUntilExit()
        return String(data: data, encoding: .utf8) ?? ""
    }
}

struct PackInfo: Identifiable, Hashable {
    let id: String
    let name: String
    let description: String
    let count: Int
    let bundled: Bool
}

// MARK: - Model

final class Model: ObservableObject {
    let runtime: Runtime

    @Published var enabled = true
    @Published var minMinutes = 15.0
    @Published var maxMinutes = 50.0
    @Published var activeStart = "09:00"
    @Published var activeEnd = "21:00"
    @Published var weekends = true
    @Published var requireActivity = true
    @Published var lingerSeconds = 15.0
    @Published var emojiMode = "random"
    @Published var chosen: Set<String> = []

    @Published var available: [PackInfo] = []
    @Published var messageCount = 0
    @Published var running = false
    @Published var delivered = 0
    @Published var transport = ""
    @Published var pausedUntil: Double = 0
    @Published var busy = false

    init(runtime: Runtime) {
        self.runtime = runtime
        reload()
    }

    var pausedText: String? {
        guard pausedUntil > Date().timeIntervalSince1970 else { return nil }
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm"
        return formatter.string(from: Date(timeIntervalSince1970: pausedUntil))
    }

    func reload() {
        let output = runtime.run(["dump"])
        guard let data = output.data(using: .utf8),
              let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return }

        if let config = root["config"] as? [String: Any] {
            enabled = config["enabled"] as? Bool ?? true
            minMinutes = config["min_minutes"] as? Double ?? 15
            maxMinutes = config["max_minutes"] as? Double ?? 50
            activeStart = config["active_start"] as? String ?? "09:00"
            activeEnd = config["active_end"] as? String ?? "21:00"
            requireActivity = config["require_activity"] as? Bool ?? true
            lingerSeconds = config["linger_seconds"] as? Double ?? 15
            emojiMode = config["emoji"] as? String ?? "random"
            chosen = Set(config["packs"] as? [String] ?? ["funny"])
            let days = config["active_days"] as? [Int] ?? []
            weekends = days.contains(5) || days.contains(6)
        }

        if let list = root["packs"] as? [[String: Any]] {
            available = list.map {
                PackInfo(
                    id: $0["id"] as? String ?? "?",
                    name: $0["name"] as? String ?? "?",
                    description: $0["description"] as? String ?? "",
                    count: $0["count"] as? Int ?? 0,
                    bundled: $0["bundled"] as? Bool ?? true
                )
            }
        }

        if let status = root["status"] as? [String: Any] {
            running = status["running"] as? Bool ?? false
            delivered = status["delivered"] as? Int ?? 0
            transport = status["transport"] as? String ?? ""
            messageCount = status["messages"] as? Int ?? 0
            pausedUntil = status["paused_until"] as? Double ?? 0
        }
    }

    /// Apply in the background: rebuilding the app can take a few seconds and
    /// the window must not freeze while it happens.
    func apply(_ arguments: [String], reloadAfter: Bool = true) {
        busy = true
        DispatchQueue.global(qos: .userInitiated).async {
            self.runtime.run(arguments)
            DispatchQueue.main.async {
                if reloadAfter { self.reload() }
                self.busy = false
            }
        }
    }

    func set(_ key: String, _ value: String) {
        apply(["config", key, value])
    }

    func togglePack(_ id: String) {
        var next = chosen
        if next.contains(id) { next.remove(id) } else { next.insert(id) }
        // At least one pack has to remain, or there is nothing to say.
        guard !next.isEmpty else { return }
        chosen = next
        apply(["packs", next.sorted().joined(separator: ",")])
    }
}

// MARK: - Window

struct SettingsView: View {
    @ObservedObject var model: Model

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                header
                Divider()
                rhythm
                Divider()
                hours
                Divider()
                themes
                Divider()
                appearance
                Divider()
                footer
            }
            .padding(24)
            .frame(width: 460, alignment: .leading)
        }
        .frame(width: 460, height: 640)
        .disabled(model.busy)
        .opacity(model.busy ? 0.6 : 1)
    }

    private var header: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 4) {
                Text("Sticky Note").font(.title2).bold()
                Text(model.running
                     ? "Running · \(model.delivered) delivered"
                     : "Not running")
                    .font(.caption).foregroundColor(.secondary)
                if let paused = model.pausedText {
                    Text("Paused until \(paused)").font(.caption).foregroundColor(.orange)
                }
            }
            Spacer()
            Button("Send one now") { model.apply(["now"], reloadAfter: false) }
        }
    }

    private var rhythm: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Rhythm").font(.headline)
            Text("A note lands at a random point in this range.")
                .font(.caption).foregroundColor(.secondary)

            slider("At least", value: $model.minMinutes, range: 5...120) {
                if model.maxMinutes < model.minMinutes {
                    model.maxMinutes = model.minMinutes
                    model.set("max_minutes", String(Int(model.maxMinutes)))
                }
                model.set("min_minutes", String(Int(model.minMinutes)))
            }
            slider("At most", value: $model.maxMinutes, range: 5...360) {
                if model.maxMinutes < model.minMinutes {
                    model.minMinutes = model.maxMinutes
                    model.set("min_minutes", String(Int(model.minMinutes)))
                }
                model.set("max_minutes", String(Int(model.maxMinutes)))
            }
        }
    }

    private var hours: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("When").font(.headline)
            HStack {
                Text("From")
                TextField("09:00", text: $model.activeStart, onCommit: {
                    model.set("active_start", model.activeStart)
                }).frame(width: 70)
                Text("until")
                TextField("21:00", text: $model.activeEnd, onCommit: {
                    model.set("active_end", model.activeEnd)
                }).frame(width: 70)
                Spacer()
            }
            Toggle("Weekends too", isOn: Binding(
                get: { model.weekends },
                set: { on in
                    model.weekends = on
                    model.set("active_days", on ? "0,1,2,3,4,5,6" : "0,1,2,3,4")
                }
            ))
            Toggle("Only when I'm at the machine", isOn: Binding(
                get: { model.requireActivity },
                set: { on in
                    model.requireActivity = on
                    model.set("require_activity", on ? "true" : "false")
                }
            ))
        }
    }

    private var themes: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("Notes").font(.headline)
                Spacer()
                Text("\(model.messageCount) in rotation")
                    .font(.caption).foregroundColor(.secondary)
            }
            ForEach(model.available) { pack in
                Toggle(isOn: Binding(
                    get: { model.chosen.contains(pack.id) },
                    set: { _ in model.togglePack(pack.id) }
                )) {
                    VStack(alignment: .leading, spacing: 1) {
                        Text("\(pack.name)  ·  \(pack.count)")
                        Text(pack.description).font(.caption).foregroundColor(.secondary)
                    }
                }
            }
        }
    }

    private var appearance: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Appearance").font(.headline)
            Picker("Badge", selection: Binding(
                get: { model.emojiMode == "off" ? "off" : "random" },
                set: { mode in
                    model.emojiMode = mode
                    model.set("emoji", mode)
                }
            )) {
                Text("A different emoji each time").tag("random")
                Text("No badge").tag("off")
            }.pickerStyle(.radioGroup)

            slider("On screen", value: $model.lingerSeconds, range: 0...60,
                   unit: "s") {
                model.set("linger_seconds", String(Int(model.lingerSeconds)))
            }
            Text("Only applies once Sticky Note is set to Alerts; macOS takes "
                 + "banners away after about five seconds regardless.")
                .font(.caption).foregroundColor(.secondary)
        }
    }

    private var footer: some View {
        HStack {
            Button(model.running ? "Stop" : "Start") {
                model.apply([model.running ? "stop" : "start"])
            }
            Button("Notification style…") { model.apply(["alerts"], reloadAfter: false) }
            Spacer()
            Button("Reload") { model.reload() }
        }
    }

    private func slider(_ label: String, value: Binding<Double>,
                        range: ClosedRange<Double>, unit: String = "min",
                        commit: @escaping () -> Void) -> some View {
        HStack {
            Text(label).frame(width: 60, alignment: .leading)
            Slider(value: value, in: range, step: 1) { editing in
                if !editing { commit() }
            }
            Text("\(Int(value.wrappedValue))\(unit)")
                .frame(width: 46, alignment: .trailing)
                .monospacedDigit()
        }
    }
}

// MARK: - Hosting

final class SettingsWindowController {
    private var window: NSWindow?

    func show(model: Model) {
        if let existing = window {
            existing.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }
        let hosting = NSHostingController(rootView: SettingsView(model: model))
        let created = NSWindow(contentViewController: hosting)
        created.title = "Sticky Note"
        created.styleMask = [.titled, .closable, .miniaturizable]
        created.center()
        created.isReleasedWhenClosed = false
        created.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        // The first text field otherwise becomes first responder on open, and
        // the scroll view jumps down to reveal it, hiding the title and the
        // rhythm controls above it. Deferred, because SwiftUI installs the
        // responder chain after this returns.
        DispatchQueue.main.async { created.makeFirstResponder(nil) }
        window = created
    }
}

/// The settings window on its own: opened by `stickynote settings`, and it
/// quits when closed rather than lingering as an invisible process.
final class SettingsApp: NSObject, NSApplicationDelegate {
    let model: Model
    private let controller = SettingsWindowController()

    init(runtime: Runtime) {
        self.model = Model(runtime: runtime)
    }

    func applicationDidFinishLaunching(_ note: Notification) {
        controller.show(model: model)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ app: NSApplication) -> Bool {
        return true
    }

    /// Opening the app again while it is running should bring the window back
    /// rather than silently doing nothing.
    func applicationShouldHandleReopen(_ app: NSApplication, hasVisibleWindows: Bool) -> Bool {
        controller.show(model: model)
        return true
    }
}

/// The menu bar item: pause, a nudge on demand, and a way into the window.
final class MenuBarApp: NSObject, NSApplicationDelegate {
    let model: Model
    private var item: NSStatusItem?
    private let controller = SettingsWindowController()

    init(runtime: Runtime) {
        self.model = Model(runtime: runtime)
    }

    func applicationDidFinishLaunching(_ note: Notification) {
        let status = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        status.button?.title = "📝"
        status.menu = buildMenu()
        item = status
    }

    /// With the menu bar item running, opening the app from Spotlight would
    /// otherwise just activate this process and show nothing.
    func applicationShouldHandleReopen(_ app: NSApplication, hasVisibleWindows: Bool) -> Bool {
        controller.show(model: model)
        return true
    }

    private func buildMenu() -> NSMenu {
        let menu = NSMenu()
        menu.delegate = self

        add(menu, "Send a note now", #selector(nudge))
        menu.addItem(.separator())
        add(menu, "Pause for an hour", #selector(pauseHour))
        add(menu, "Pause for the day", #selector(pauseToday))
        add(menu, "Resume", #selector(resume))
        menu.addItem(.separator())
        add(menu, "Settings…", #selector(openSettings))
        menu.addItem(.separator())
        add(menu, "Quit menu bar item", #selector(quit))
        return menu
    }

    private func add(_ menu: NSMenu, _ title: String, _ action: Selector) {
        let entry = NSMenuItem(title: title, action: action, keyEquivalent: "")
        entry.target = self
        menu.addItem(entry)
    }

    @objc private func nudge() { model.apply(["now"], reloadAfter: false) }
    @objc private func pauseHour() { model.apply(["pause", "1h"]) }
    @objc private func pauseToday() { model.apply(["pause", "today"]) }
    @objc private func resume() { model.apply(["resume"]) }
    @objc private func openSettings() { controller.show(model: model) }
    @objc private func quit() { NSApp.terminate(nil) }
}

extension MenuBarApp: NSMenuDelegate {
    func menuWillOpen(_ menu: NSMenu) {
        // Cheap enough to re-read every time, and it means the state shown is
        // never stale after a change made from the command line.
        model.reload()
        if let paused = model.pausedText {
            menu.item(at: 0)?.title = "Send a note now (paused until \(paused))"
        } else {
            menu.item(at: 0)?.title = "Send a note now"
        }
    }
}

func runSettings(_ arguments: [String], asMenuBar: Bool) -> Never {
    let runtime = Runtime.parse(arguments)
    let app = NSApplication.shared
    // Accessory, not regular: neither surface deserves a Dock icon.
    app.setActivationPolicy(asMenuBar ? .accessory : .regular)

    let delegate: NSApplicationDelegate = asMenuBar
        ? MenuBarApp(runtime: runtime)
        : SettingsApp(runtime: runtime)
    // The delegate is weakly held, so it has to outlive this scope.
    objc_setAssociatedObject(app, "stickynote.delegate", delegate, .OBJC_ASSOCIATION_RETAIN)
    app.delegate = delegate
    app.run()
    exit(0)
}
