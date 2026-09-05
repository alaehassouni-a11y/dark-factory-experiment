import XCTest
@testable import VirtualAgent

final class SSEParserTests: XCTestCase {
    private func records(from lines: [String]) -> [SSERecord] {
        var parser = SSEParser()
        var out: [SSERecord] = []
        for line in lines {
            if let record = parser.feed(line: line) {
                out.append(record)
            }
        }
        if let last = parser.flush() {
            out.append(last)
        }
        return out
    }

    // MARK: Framing

    func testTokenFrameIsUnnamedAndKeepsJSONQuotes() {
        var parser = SSEParser()
        XCTAssertNil(parser.feed(line: "data: \"Nous \""))
        XCTAssertEqual(parser.feed(line: ""), SSERecord(event: nil, data: "\"Nous \""))
    }

    func testNamedEventCarriesItsName() {
        let out = records(from: ["event: language", "data: {\"language\": \"fr\"}", ""])
        XCTAssertEqual(out, [SSERecord(event: "language", data: "{\"language\": \"fr\"}")])
    }

    func testMultipleDataLinesAreJoinedWithNewline() {
        let out = records(from: ["data: a", "data: b", ""])
        XCTAssertEqual(out, [SSERecord(event: nil, data: "a\nb")])
    }

    func testCRLFLineEndingsAreTolerated() {
        let out = records(from: ["event: turn\r", "data: {}\r", "\r"])
        XCTAssertEqual(out, [SSERecord(event: "turn", data: "{}")])
    }

    func testCommentLinesAreIgnored() {
        let out = records(from: [": keep-alive", "data: x", ""])
        XCTAssertEqual(out, [SSERecord(event: nil, data: "x")])
    }

    func testOnlyOneLeadingSpaceIsStripped() {
        XCTAssertEqual(records(from: ["data:x", ""]).first?.data, "x")
        XCTAssertEqual(records(from: ["data:  x", ""]).first?.data, " x")
    }

    func testEventNameWithoutDataIsDropped() {
        let out = records(from: ["event: sources", "", "data: 1", ""])
        XCTAssertEqual(out, [SSERecord(event: nil, data: "1")])
    }

    func testEventNameDoesNotLeakIntoNextRecord() {
        let out = records(from: ["event: sentence", "data: 1", "", "data: 2", ""])
        XCTAssertEqual(out.map(\.event), ["sentence", nil])
    }

    func testBlankLinesWithoutDataEmitNothing() {
        XCTAssertTrue(records(from: ["", "", ""]).isEmpty)
    }

    func testFlushEmitsRecordLeftOpenAtEndOfStream() {
        var parser = SSEParser()
        XCTAssertNil(parser.feed(line: "data: tail"))
        XCTAssertEqual(parser.flush(), SSERecord(event: nil, data: "tail"))
        XCTAssertNil(parser.flush())
    }

    func testDoneTerminator() {
        let done = records(from: ["data: [DONE]", ""])
        XCTAssertEqual(done.count, 1)
        XCTAssertTrue(done[0].isDone)
        XCTAssertFalse(SSERecord(event: "turn", data: "[DONE]").isDone)
    }

    func testStreamFromAPIDocInOrder() {
        let out = records(from: [
            "event: language",
            "data: {\"language\": \"fr\", \"voice_locale\": \"fr-FR\", \"confidence\": 0.6}",
            "",
            "data: \"Nous \"",
            "",
            "data: \"sommes ouverts \"",
            "",
            "data: \"de 9h à 18h.\"",
            "",
            "event: sentence",
            "data: {\"index\": 0, \"text\": \"Nous sommes ouverts de 9h à 18h.\", \"language\": \"fr\", \"voice_locale\": \"fr-FR\"}",
            "",
            "event: sources",
            "data: [{\"kind\": \"wiki\", \"title\": \"Opening hours\", \"location\": \"opening-hours.md\", \"snippet\": \"We are open\"}]",
            "",
            "event: turn",
            "data: {\"kind\": \"answer\", \"source\": \"wiki\", \"language\": \"fr\"}",
            "",
            "data: [DONE]",
            "",
        ])
        XCTAssertEqual(out.map(\.event), ["language", nil, nil, nil, "sentence", "sources", "turn", nil])
        XCTAssertTrue(out.last?.isDone ?? false)
    }

    // MARK: Typed decoding

    private let decoder = AgentAPI.makeCoders().1

    func testTokenFrameDecodesJSONStringIncludingNewline() throws {
        let event = try AgentEventDecoder.decode(SSERecord(event: nil, data: "\"line\\nbreak\""), decoder: decoder)
        XCTAssertEqual(event, .token("line\nbreak"))
    }

    func testTokenFrameThatIsNotJSONIsShownVerbatim() throws {
        let event = try AgentEventDecoder.decode(SSERecord(event: nil, data: "plain"), decoder: decoder)
        XCTAssertEqual(event, .token("plain"))
    }

    func testNamedEventsDecodeToTypedPayloads() throws {
        let language = try AgentEventDecoder.decode(
            SSERecord(event: "language", data: "{\"language\": \"de\", \"voice_locale\": \"de-DE\", \"confidence\": 0.9}"),
            decoder: decoder)
        XCTAssertEqual(language, .language(LanguageEvent(language: "de", voiceLocale: "de-DE", confidence: 0.9)))

        let sentence = try AgentEventDecoder.decode(
            SSERecord(event: "sentence", data: "{\"index\": 0, \"text\": \"Hallo.\", \"language\": \"de\", \"voice_locale\": \"de-DE\"}"),
            decoder: decoder)
        XCTAssertEqual(sentence, .sentence(SentenceEvent(index: 0, text: "Hallo.", language: "de", voiceLocale: "de-DE")))

        let sources = try AgentEventDecoder.decode(
            SSERecord(event: "sources", data: "[{\"kind\": \"web\", \"title\": \"Page\", \"url\": \"https://example.com\"}]"),
            decoder: decoder)
        XCTAssertEqual(sources, .sources([SourceItem(kind: .web, title: "Page", location: nil, url: "https://example.com", snippet: nil)]))

        let turn = try AgentEventDecoder.decode(
            SSERecord(event: "turn", data: "{\"kind\": \"no_answer\", \"source\": \"none\", \"language\": \"ar\"}"),
            decoder: decoder)
        XCTAssertEqual(turn, .turn(TurnEvent(kind: .noAnswer, source: .noSource, language: "ar")))
    }

    func testNullLanguageDecodes() throws {
        let event = try AgentEventDecoder.decode(
            SSERecord(event: "language", data: "{\"language\": null, \"voice_locale\": null, \"confidence\": 0}"),
            decoder: decoder)
        XCTAssertEqual(event, .language(LanguageEvent(language: nil, voiceLocale: nil, confidence: 0)))
    }

    func testDoneRecordDecodesToDone() throws {
        XCTAssertEqual(try AgentEventDecoder.decode(SSERecord(event: nil, data: "[DONE]"), decoder: decoder), .done)
    }

    func testUnknownEventNameIsIgnored() throws {
        XCTAssertNil(try AgentEventDecoder.decode(SSERecord(event: "metrics", data: "{}"), decoder: decoder))
    }

    func testUnknownEnumValuesDecodeAsUnknownInsteadOfFailing() throws {
        let turn = try AgentEventDecoder.decode(
            SSERecord(event: "turn", data: "{\"kind\": \"shrug\", \"source\": \"oracle\"}"),
            decoder: decoder)
        XCTAssertEqual(turn, .turn(TurnEvent(kind: .unknown, source: .unknown, language: nil)))
    }

    func testMalformedNamedEventThrows() {
        XCTAssertThrowsError(try AgentEventDecoder.decode(SSERecord(event: "turn", data: "not json"), decoder: decoder)) {
            XCTAssertEqual($0 as? AgentAPIError, .malformedEvent(event: "turn"))
        }
    }
}
