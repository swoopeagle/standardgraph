// Apple Vision OCR for page PNGs (default zh-Hans + en-US; OCR_LANGS=es-ES,en-US overrides). Usage: vision_ocr page1.png page2.png ...
// Prints one JSON object per page: {"file":..., "lines":[{"t":text,"x":minX,"y":topY,"h":height,"c":confidence}]} (y from top, 0..1)
import Foundation
import Vision
import AppKit

for path in CommandLine.arguments.dropFirst() {
    guard let img = NSImage(contentsOfFile: path), let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else { continue }
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.recognitionLanguages = (ProcessInfo.processInfo.environment["OCR_LANGS"] ?? "zh-Hans,en-US").split(separator: ",").map(String.init)
    req.usesLanguageCorrection = false
    try? VNImageRequestHandler(cgImage: cg, options: [:]).perform([req])
    var lines: [[String: Any]] = []
    for o in (req.results ?? []) {
        guard let c = o.topCandidates(1).first else { continue }
        let b = o.boundingBox
        lines.append(["t": c.string, "x": b.minX, "y": 1 - b.maxY, "h": b.height, "c": c.confidence])
    }
    lines.sort { ($0["y"] as! CGFloat) < ($1["y"] as! CGFloat) }
    let data = try! JSONSerialization.data(withJSONObject: ["file": path, "lines": lines])
    print(String(data: data, encoding: .utf8)!)
}
