// Sticky Note's notification helper.
//
// AppleScript's `display notification` cannot carry an image, so anything with
// a per-notification badge has to go through UserNotifications. This binary is
// bundled into ~/Applications/StickyNote.app and launched with `open`, which
// matters: run directly from a terminal the request is attributed to the
// terminal instead of this bundle and macOS refuses authorization outright.
//
//   stickynote-notifier render <text> <out.png>
//   stickynote-notifier notify --title T --body B [--emoji E] [--sound S] [--linger N]

import AppKit
import UserNotifications

// Diagnostics have to go to a file: when launched via `open` there is no
// terminal attached to inherit stderr.
let logURL = URL(fileURLWithPath: NSHomeDirectory())
    .appendingPathComponent(".config/stickynote/notifier.log")

func log(_ message: String) {
    let stamp = ISO8601DateFormatter().string(from: Date())
    let line = "[\(stamp)] \(message)\n"
    FileHandle.standardError.write(line.data(using: .utf8)!)
    guard let data = line.data(using: .utf8) else { return }
    if let handle = try? FileHandle(forWritingTo: logURL) {
        handle.seekToEndOfFile()
        handle.write(data)
        try? handle.close()
    } else {
        try? FileManager.default.createDirectory(
            at: logURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? data.write(to: logURL)
    }
}

/// Draw text (an emoji, in practice) centred on a transparent square.
func renderBadge(_ text: String, to path: String, size: CGFloat = 512) -> Bool {
    let image = NSImage(size: NSSize(width: size, height: size))
    image.lockFocus()

    NSColor.clear.set()
    NSRect(x: 0, y: 0, width: size, height: size).fill()

    let style = NSMutableParagraphStyle()
    style.alignment = .center
    let attributed = NSAttributedString(string: text, attributes: [
        .font: NSFont.systemFont(ofSize: size * 0.72),
        .paragraphStyle: style,
    ])
    let bounds = attributed.boundingRect(
        with: NSSize(width: size, height: size), options: [.usesLineFragmentOrigin])
    attributed.draw(in: NSRect(
        x: 0, y: (size - bounds.height) / 2, width: size, height: bounds.height))
    // Must come before reading the bitmap: tiffRepresentation fails while the
    // image still has focus locked.
    image.unlockFocus()

    guard let tiff = image.tiffRepresentation,
          let rep = NSBitmapImageRep(data: tiff),
          let png = rep.representation(using: .png, properties: [:]) else { return false }
    return (try? png.write(to: URL(fileURLWithPath: path))) != nil
}

struct Options {
    var title = "Sticky Note"
    var body = ""
    var emoji = ""
    var sound = ""
    var linger: Double = 0
}

func parseOptions(_ args: [String]) -> Options {
    var options = Options()
    var index = 0
    while index < args.count - 1 {
        let value = args[index + 1]
        switch args[index] {
        case "--title": options.title = value
        case "--body": options.body = value
        case "--emoji": options.emoji = value
        case "--sound": options.sound = value
        case "--linger": options.linger = Double(value) ?? 0
        default: index -= 1
        }
        index += 2
    }
    return options
}

final class Notifier: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
    let options: Options

    init(options: Options) {
        self.options = options
    }

    func applicationDidFinishLaunching(_ note: Notification) {
        let center = UNUserNotificationCenter.current()
        center.delegate = self
        // An accessory app that is not frontmost never gets the authorization
        // prompt surfaced, so ask for focus before requesting.
        NSApp.activate(ignoringOtherApps: true)
        center.requestAuthorization(options: [.alert, .sound]) { granted, error in
            if let error = error {
                log("authorization error: \(error.localizedDescription)")
            }
            guard granted else {
                log("authorization denied; enable Sticky Note in System Settings > Notifications")
                exit(2)
            }
            self.post(to: center)
        }
    }

    private func attachment() -> UNNotificationAttachment? {
        guard !options.emoji.isEmpty else { return nil }
        // The system moves an attachment into its own store, so render into a
        // throwaway file rather than anything we want to keep.
        let url = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("stickynote-\(UUID().uuidString).png")
        guard renderBadge(options.emoji, to: url.path) else {
            log("could not render badge for \(options.emoji)")
            return nil
        }
        do {
            return try UNNotificationAttachment(identifier: "badge", url: url, options: nil)
        } catch {
            log("could not attach badge: \(error.localizedDescription)")
            return nil
        }
    }

    private func post(to center: UNUserNotificationCenter) {
        let content = UNMutableNotificationContent()
        content.title = options.title
        content.body = options.body
        if !options.sound.isEmpty {
            content.sound = UNNotificationSound(named: UNNotificationSoundName(options.sound))
        }
        if let attachment = attachment() {
            content.attachments = [attachment]
        }

        let identifier = UUID().uuidString
        let request = UNNotificationRequest(
            identifier: identifier, content: content, trigger: nil)
        center.add(request) { error in
            if let error = error {
                log("delivery failed: \(error.localizedDescription)")
                exit(3)
            }
            // How long the notification stays on screen is not ours to set: a
            // banner is dismissed by the system after roughly five seconds, and
            // only the user can promote the app to the persistent Alert style.
            // Under Alerts, withdrawing the notification ourselves takes it off
            // screen, which turns "until dismissed" into a chosen duration.
            // Zero means leave it up.
            guard self.options.linger > 0 else {
                DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { exit(0) }
                return
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + self.options.linger) {
                center.removeDeliveredNotifications(withIdentifiers: [identifier])
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { exit(0) }
            }
        }
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                willPresent notification: UNNotification,
                                withCompletionHandler handler: @escaping (UNNotificationPresentationOptions) -> Void) {
        handler([.banner, .list, .sound])
    }
}

let arguments = Array(CommandLine.arguments.dropFirst())

switch arguments.first {
case "render":
    guard arguments.count >= 3 else {
        log("usage: stickynote-notifier render <text> <out.png>")
        exit(64)
    }
    exit(renderBadge(arguments[1], to: arguments[2]) ? 0 : 1)

case "notify":
    let app = NSApplication.shared
    let notifier = Notifier(options: parseOptions(Array(arguments.dropFirst())))
    app.delegate = notifier
    app.setActivationPolicy(.accessory)
    app.run()

default:
    log("usage: stickynote-notifier [render|notify] ...")
    exit(64)
}
