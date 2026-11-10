import { describe, expect, it } from "vitest";
import { dropCountLabel, groupByFolder, latestProjects } from "./drops";

const file = (name: string, folder: string | null) =>
  ({ source_id: name, rel_path: `p/${name}`, name, kind: "text", status: "indexed", folder });

describe("groupByFolder", () => {
  it("groups files by AI folder in first-seen order", () => {
    const groups = groupByFolder({ files: [file("a.md", "Docs"), file("b.csv", "Data"), file("c.md", "Docs")] });
    expect(groups.map(([f, xs]) => [f, xs.map((x) => x.name)])).toEqual([["Docs", ["a.md", "c.md"]], ["Data", ["b.csv"]]]);
  });
  it("puts files without a folder under Unsorted", () => {
    expect(groupByFolder({ files: [file("x.txt", null)] })[0][0]).toBe("Unsorted");
    expect(groupByFolder({ files: undefined })).toEqual([]);
  });
});

describe("latestProjects", () => {
  it("keeps one organized drop per project, newest first as given", () => {
    const drops = [
      { id: "3", status: "organized", project: { id: "p1", name: "Solar" } },
      { id: "2", status: "organizing", project: null },
      { id: "1", status: "organized", project: { id: "p1", name: "Solar" } },
      { id: "0", status: "organized", project: { id: "p2", name: "Thesis" } },
    ];
    expect(latestProjects(drops).map((d) => d.id)).toEqual(["3", "0"]);
  });
});

describe("dropCountLabel", () => {
  it("shows the estimate while importing and the real outcome after", () => {
    expect(dropCountLabel({ status: "importing", file_count: 4, skipped: 0, import_stats: null })).toBe("4 files · importing…");
    expect(dropCountLabel({ status: "imported", file_count: 4, skipped: 0,
      import_stats: { imported: 2, duplicates: 1, failed: 1, skipped: 0 } })).toBe("3 files · 1 already in Folio · 1 failed");
    expect(dropCountLabel({ status: "organized", file_count: 1, skipped: 0, import_stats: undefined })).toBe("1 file");
  });
});
