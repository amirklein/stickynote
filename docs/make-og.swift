// Draws docs/og.png, the card LinkedIn and friends show when the site is linked.
//
// Committed as code rather than as an exported image so the wording can be
// changed without hunting for whatever design tool made it.
//
//   swift docs/make-og.swift docs/og.png

import AppKit

let width = 1200.0
let height = 630.0

let paper = NSColor(calibratedRed: 0.992, green: 0.988, blue: 0.969, alpha: 1)
let ink = NSColor(calibratedRed: 0.114, green: 0.110, blue: 0.098, alpha: 1)
let muted = NSColor(calibratedRed: 0.427, green: 0.416, blue: 0.388, alpha: 1)
let noteYellow = NSColor(calibratedRed: 1.0, green: 0.902, blue: 0.427, alpha: 1)
let noteAmber = NSColor(calibratedRed: 0.969, green: 0.718, blue: 0.200, alpha: 1)

func font(_ size: CGFloat, _ weight: NSFont.Weight) -> NSFont {
    return NSFont.systemFont(ofSize: size, weight: weight)
}

func draw(_ text: String, at point: NSPoint, size: CGFloat,
          weight: NSFont.Weight, color: NSColor, tracking: CGFloat = 0) {
    let style = NSMutableParagraphStyle()
    style.lineHeightMultiple = 1.02
    var attributes: [NSAttributedString.Key: Any] = [
        .font: font(size, weight),
        .foregroundColor: color,
        .paragraphStyle: style,
    ]
    if tracking != 0 { attributes[.kern] = tracking }
    NSAttributedString(string: text, attributes: attributes).draw(at: point)
}

func rounded(_ rect: NSRect, _ radius: CGFloat) -> NSBezierPath {
    return NSBezierPath(roundedRect: rect, xRadius: radius, yRadius: radius)
}

// Drawing into an explicitly sized bitmap rather than locking focus on an
// NSImage: focus follows the screen's scale factor, so on a retina Mac the
// file comes out at twice the requested size and several times the weight.
guard let canvas = NSBitmapImageRep(
    bitmapDataPlanes: nil,
    pixelsWide: Int(width), pixelsHigh: Int(height),
    bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
    colorSpaceName: .calibratedRGB, bytesPerRow: 0, bitsPerPixel: 0
) else {
    FileHandle.standardError.write("could not allocate the canvas\n".data(using: .utf8)!)
    exit(1)
}

NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: canvas)

// Background, with a warm glow in the top right so it is not a flat slab.
paper.setFill()
NSRect(x: 0, y: 0, width: width, height: height).fill()

// Filling the whole canvas and offsetting the centre, rather than drawing
// into a smaller rect: a radial gradient is clipped to its rect, and the
// clip shows up as a hard vertical seam across the card.
NSGradient(starting: noteYellow.withAlphaComponent(0.46),
           ending: paper.withAlphaComponent(0))?
    .draw(in: NSRect(x: 0, y: 0, width: width, height: height),
          relativeCenterPosition: NSPoint(x: 0.55, y: 0.45))

// A sticky note, tilted, as the one piece of illustration.
NSGraphicsContext.saveGraphicsState()
let tilt = NSAffineTransform()
tilt.translateX(by: 905, yBy: 330)
tilt.rotate(byDegrees: -8)
tilt.concat()

let shadow = NSShadow()
shadow.shadowColor = NSColor.black.withAlphaComponent(0.16)
shadow.shadowBlurRadius = 34
shadow.shadowOffset = NSSize(width: 0, height: -14)
shadow.set()

let noteRect = NSRect(x: -125, y: -125, width: 250, height: 250)
NSGradient(starting: noteYellow, ending: noteAmber)?
    .draw(in: rounded(noteRect, 10), angle: -70)

NSShadow().set()
// Ruled lines, as if something were written on it.
ink.withAlphaComponent(0.13).setFill()
for row in 0..<4 {
    let y = 52.0 - Double(row) * 42.0
    let inset = row == 3 ? 96.0 : 34.0
    NSRect(x: -85, y: y, width: 170 - inset + 34, height: 9).fill()
}
NSGraphicsContext.restoreGraphicsState()

// Wordmark and pitch.
draw("Sticky Note", at: NSPoint(x: 92, y: 372),
     size: 96, weight: .bold, color: ink, tracking: -3.2)
draw("Cute, funny notes that turn up on your Mac", at: NSPoint(x: 96, y: 300),
     size: 34, weight: .regular, color: muted, tracking: -0.4)
draw("when you need them.", at: NSPoint(x: 96, y: 254),
     size: 34, weight: .regular, color: muted, tracking: -0.4)

// A small notification, so the thing being offered is visible at a glance.
let cardRect = NSRect(x: 96, y: 74, width: 620, height: 96)
let cardShadow = NSShadow()
cardShadow.shadowColor = NSColor.black.withAlphaComponent(0.12)
cardShadow.shadowBlurRadius = 26
cardShadow.shadowOffset = NSSize(width: 0, height: -8)
cardShadow.set()
NSColor.white.setFill()
rounded(cardRect, 20).fill()
NSShadow().set()

let iconRect = NSRect(x: 118, y: 96, width: 52, height: 52)
NSGradient(starting: noteYellow, ending: noteAmber)?.draw(in: rounded(iconRect, 12), angle: -70)
draw("📝", at: NSPoint(x: 129, y: 106), size: 30, weight: .regular, color: ink)

draw("Sticky Note", at: NSPoint(x: 188, y: 122), size: 19, weight: .semibold, color: ink)
draw("The universe is chaos and you made a spreadsheet.", at: NSPoint(x: 188, y: 94),
     size: 19, weight: .regular, color: muted)
draw("🪐", at: NSPoint(x: 648, y: 104), size: 34, weight: .regular, color: ink)

draw("Free · open source · everything stays on your machine",
     at: NSPoint(x: 98, y: 30), size: 19, weight: .medium, color: muted)

NSGraphicsContext.restoreGraphicsState()

let destination = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "docs/og.png"
guard let png = canvas.representation(using: .png, properties: [:]) else {
    FileHandle.standardError.write("could not render the image\n".data(using: .utf8)!)
    exit(1)
}

do {
    try png.write(to: URL(fileURLWithPath: destination))
    print("wrote \(destination)")
} catch {
    FileHandle.standardError.write("could not write \(destination): \(error)\n".data(using: .utf8)!)
    exit(1)
}
