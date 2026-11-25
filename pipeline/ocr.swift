import AppKit
import PDFKit
import Vision

let arguments = CommandLine.arguments.dropFirst()
guard let file = arguments.first, let document = PDFDocument(url: URL(fileURLWithPath: file)) else {
    exit(1)
}

for argument in arguments.dropFirst() {
    guard let number = Int(argument), let page = document.page(at: number - 1) else { exit(1) }
    let bounds = page.bounds(for: .mediaBox)
    let scale = min(2.8, 2400 / max(bounds.width, bounds.height))
    let size = CGSize(width: bounds.width * scale, height: bounds.height * scale)
    let image = page.thumbnail(of: size, for: .mediaBox)
    guard let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else { exit(1) }
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    let supported = (try? request.supportedRecognitionLanguages()) ?? ["en-US"]
    request.recognitionLanguages = ["ru-RU", "en-US"].filter { supported.contains($0) }
    do {
        try VNImageRequestHandler(cgImage: cgImage).perform([request])
    } catch {
        FileHandle.standardError.write(Data("OCR failed on page \(number): \(error)\n".utf8))
        exit(2)
    }
    let lines = request.results?.compactMap { $0.topCandidates(1).first?.string } ?? []
    print(lines.joined(separator: "\n"), terminator: "\u{000C}")
}
