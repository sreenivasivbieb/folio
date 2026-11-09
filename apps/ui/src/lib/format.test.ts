import { describe, expect, it } from "vitest";
import { basename, confidenceBand, fileSize, locatorLabel, seconds } from "./format";

describe("format", () => {
  it("formats locators the way evidence links show them", () => {
    expect(locatorLabel({ kind: "page", page: 3 })).toBe("p.3");
    expect(locatorLabel({ kind: "time", start: 65, end: 72 })).toBe("1:05–1:12");
    expect(locatorLabel({ kind: "text", line_start: 10, line_end: 14 })).toBe("L10–14");
    expect(locatorLabel({ kind: "text", line_start: 4, line_end: 4 })).toBe("L4");
  });

  it("handles times, paths and confidence bands", () => {
    expect(seconds(3725)).toBe("1:02:05");
    expect(basename("/a/b/contract.pdf")).toBe("contract.pdf");
    expect(basename("C:\\docs\\x.md")).toBe("x.md");
    expect(confidenceBand(0.9)).toBe("high");
    expect(confidenceBand(0.45)).toBe("low");
    expect(fileSize(512)).toBe("512 B");
    expect(fileSize(4300)).toBe("4.2 KB");
    expect(fileSize(3_984_588)).toBe("3.8 MB");
  });
});
