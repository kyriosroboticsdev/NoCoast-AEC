import { describe, expect, it } from "vitest";
import { toElementInfo } from "../src/core/inspector";

describe("toElementInfo", () => {
  it("flattens attributes and property sets", () => {
    const info = toElementInfo(42, {
      _category: { value: "IFCWALL" },
      _localId: { value: 42 },
      Name: { value: "Wall South" },
      GlobalId: { value: "0abc" },
      Height: { value: 2.95 },
      IsDefinedBy: [
        {
          Name: { value: "NoCoast_Agent" },
          HasProperties: [
            { Name: { value: "Material" }, NominalValue: { value: "Brick" } },
            { Name: { value: "AgentTurn" }, NominalValue: { value: 3 } },
          ],
        },
      ],
    });
    expect(info).toEqual({
      localId: 42,
      category: "IFCWALL",
      name: "Wall South",
      guid: "0abc",
      attributes: { Name: "Wall South", GlobalId: "0abc", Height: "2.950" },
      psets: { NoCoast_Agent: { Material: "Brick", AgentTurn: "3" } },
    });
  });

  it("handles items without relations", () => {
    expect(toElementInfo(1, {}).category).toBe("Element");
  });
});
