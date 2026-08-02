// Paints the default Sticky Note app icon into a captured notification.
//
// The icon macOS shows in a banner is cached when notification permission is
// first granted, so it cannot be changed without a new bundle identifier and
// a fresh permission prompt. Screenshots are taken on a machine whose icon has
// been personalised, while visitors to the site will see the default note, so
// the default is drawn back in rather than shipping a misleading image.
//
//   swift docs/shot.swift in.png out.png x y size

import AppKit

let arguments = CommandLine.arguments
guard arguments.count >= 6,
      let originX = Double(arguments[3]),
      let originY = Double(arguments[4]),
      let size = Double(arguments[5]) else {
    FileHandle.standardError.write("usage: shot.swift in.png out.png x y size\n".data(using: .utf8)!)
    exit(2)
}

guard let source = NSImage(contentsOfFile: arguments[1]),
      let tiff = source.tiffRepresentation,
      let bitmap = NSBitmapImageRep(data: tiff) else {
    FileHandle.standardError.write("could not read \(arguments[1])\n".data(using: .utf8)!)
    exit(1)
}

let width = bitmap.pixelsWide
let height = bitmap.pixelsHigh

guard let canvas = NSBitmapImageRep(
    bitmapDataPlanes: nil,
    pixelsWide: width, pixelsHigh: height,
    bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
    colorSpaceName: .calibratedRGB, bytesPerRow: 0, bitsPerPixel: 0
) else {
    FileHandle.standardError.write("could not allocate the canvas\n".data(using: .utf8)!)
    exit(1)
}

NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: canvas)

bitmap.draw(in: NSRect(x: 0, y: 0, width: width, height: height))

// Coordinates are given from the top left, the way they read off a screenshot.
let rect = NSRect(x: originX, y: Double(height) - originY - size, width: size, height: size)

let noteYellow = NSColor(calibratedRed: 1.0, green: 0.902, blue: 0.427, alpha: 1)
let noteAmber = NSColor(calibratedRed: 0.949, green: 0.702, blue: 0.180, alpha: 1)
let ink = NSColor(calibratedRed: 0.114, green: 0.110, blue: 0.098, alpha: 1)

// Cover whatever icon is underneath before drawing, since a larger or
// differently shaped one would peek out at the corners. The patch is filled
// with the banner's own background, sampled just to the left of the icon, so
// clearing to transparent does not punch a hole through the banner.
let backdrop = bitmap.colorAt(x: max(0, Int(originX) - 10),
                              y: Int(originY + size / 2)) ?? .clear
backdrop.setFill()
NSBezierPath(rect: rect.insetBy(dx: -12, dy: -12)).fill()

let squircle = NSBezierPath(roundedRect: rect,
                            xRadius: size * 0.225, yRadius: size * 0.225)
NSGradient(starting: noteYellow, ending: noteAmber)?.draw(in: squircle, angle: -70)

ink.withAlphaComponent(0.30).setFill()
let inset = size * 0.20
let lineHeight = size * 0.072
let gap = size * 0.185
for row in 0..<3 {
    let y = rect.maxY - inset - gap * Double(row) - lineHeight
    let lineWidth = row == 2 ? (size - inset * 2) * 0.58 : size - inset * 2
    NSBezierPath(roundedRect: NSRect(x: rect.minX + inset, y: y,
                                     width: lineWidth, height: lineHeight),
                 xRadius: lineHeight / 2, yRadius: lineHeight / 2).fill()
}

NSGraphicsContext.restoreGraphicsState()

guard let png = canvas.representation(using: .png, properties: [:]) else {
    FileHandle.standardError.write("could not encode the result\n".data(using: .utf8)!)
    exit(1)
}

do {
    try png.write(to: URL(fileURLWithPath: arguments[2]))
    print("wrote \(arguments[2])")
} catch {
    FileHandle.standardError.write("could not write \(arguments[2]): \(error)\n".data(using: .utf8)!)
    exit(1)
}
