// Crops a screenshot down to its non-transparent content.
//
// Capturing a notification banner with `screencapture -l` yields the whole
// full-screen notification window, which is almost entirely transparent with
// the banner in one corner. This finds the banner and trims to it, keeping a
// margin so the drop shadow survives.
//
// The alpha threshold decides what counts as content. A low value keeps the
// drop shadow; a high one crops to the solid window, which is what you want
// when the page draws its own shadow, since a part-faded shadow cropped
// mid-gradient shows up as a grey box on a light background.
//
//   swift docs/trim.swift in.png out.png [margin] [threshold]

import AppKit

let arguments = CommandLine.arguments
guard arguments.count >= 3 else {
    FileHandle.standardError.write("usage: trim.swift in.png out.png [margin] [threshold]\n".data(using: .utf8)!)
    exit(2)
}

let margin = arguments.count > 3 ? Int(arguments[3]) ?? 40 : 40
let threshold = arguments.count > 4 ? Int(arguments[4]) ?? 24 : 24

guard let source = NSImage(contentsOfFile: arguments[1]),
      let tiff = source.tiffRepresentation,
      let bitmap = NSBitmapImageRep(data: tiff) else {
    FileHandle.standardError.write("could not read \(arguments[1])\n".data(using: .utf8)!)
    exit(1)
}

let width = bitmap.pixelsWide
let height = bitmap.pixelsHigh

var minX = width, minY = height, maxX = -1, maxY = -1

guard let data = bitmap.bitmapData else {
    FileHandle.standardError.write("no pixel data\n".data(using: .utf8)!)
    exit(1)
}

let bytesPerRow = bitmap.bytesPerRow
let samples = bitmap.samplesPerPixel

for y in 0..<height {
    let row = y * bytesPerRow
    for x in 0..<width {
        let alpha = Int(data[row + x * samples + (samples - 1)])
        if alpha > threshold {
            if x < minX { minX = x }
            if x > maxX { maxX = x }
            if y < minY { minY = y }
            if y > maxY { maxY = y }
        }
    }
}

guard maxX >= 0 else {
    FileHandle.standardError.write("the image is entirely transparent\n".data(using: .utf8)!)
    exit(1)
}

minX = max(0, minX - margin)
minY = max(0, minY - margin)
maxX = min(width - 1, maxX + margin)
maxY = min(height - 1, maxY + margin)

let cropWidth = maxX - minX + 1
let cropHeight = maxY - minY + 1

guard let canvas = NSBitmapImageRep(
    bitmapDataPlanes: nil,
    pixelsWide: cropWidth, pixelsHigh: cropHeight,
    bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
    colorSpaceName: .calibratedRGB, bytesPerRow: 0, bitsPerPixel: 0
) else {
    FileHandle.standardError.write("could not allocate the canvas\n".data(using: .utf8)!)
    exit(1)
}

NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: canvas)
// Bitmap rows count from the top, Cocoa drawing from the bottom.
let flippedY = height - maxY - 1
bitmap.draw(in: NSRect(x: -minX, y: -flippedY, width: width, height: height))
NSGraphicsContext.restoreGraphicsState()

guard let png = canvas.representation(using: .png, properties: [:]) else {
    FileHandle.standardError.write("could not encode the result\n".data(using: .utf8)!)
    exit(1)
}

do {
    try png.write(to: URL(fileURLWithPath: arguments[2]))
    print("trimmed to \(cropWidth)x\(cropHeight) -> \(arguments[2])")
} catch {
    FileHandle.standardError.write("could not write \(arguments[2]): \(error)\n".data(using: .utf8)!)
    exit(1)
}
