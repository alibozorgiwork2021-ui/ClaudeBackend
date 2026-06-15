import { describe, expect, it } from "vitest";

import { parseUnifiedDiff } from "../lib/diff";

const DIFF = `diff --git a/a.py b/a.py
index 1111111..2222222 100644
--- a/a.py
+++ b/a.py
@@ -1,2 +1,2 @@
-VALUE = 1
+VALUE = 2
 CONST = 3
`;

describe("parseUnifiedDiff", () => {
  it("returns empty for null/empty input", () => {
    expect(parseUnifiedDiff(null)).toEqual([]);
    expect(parseUnifiedDiff("")).toEqual([]);
  });

  it("parses a single-file unified diff into render-ready lines", () => {
    const files = parseUnifiedDiff(DIFF);
    expect(files).toHaveLength(1);
    expect(files[0].path).toBe("a.py");
    expect(files[0].additions).toBe(1);
    expect(files[0].deletions).toBe(1);
    const types = files[0].lines.map((l) => l.type);
    expect(types).toContain("add");
    expect(types).toContain("del");
    expect(types).toContain("normal");
    const added = files[0].lines.find((l) => l.type === "add");
    expect(added?.content).toBe("VALUE = 2");
  });
});
