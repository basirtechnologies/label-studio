/**
 * DW-891: a brush label picked while erasing selects the brush again.
 */
import { brushToSelectOnLabelPick } from "../brushLabelTool";

const brush = { toolName: "BrushTool" };
const eraser = { toolName: "EraserTool" };
const rect = { toolName: "RectangleTool" };

describe("brushToSelectOnLabelPick", () => {
  it("selects the label control's brush when the eraser is active", () => {
    expect(brushToSelectOnLabelPick({ Brush: brush, Erase: eraser }, eraser)).toBe(brush);
  });

  it("also when the eraser belongs to another brush control (it is shared)", () => {
    expect(brushToSelectOnLabelPick({ Brush: brush }, eraser)).toBe(brush);
  });

  it("keeps the current tool otherwise", () => {
    expect(brushToSelectOnLabelPick({ Brush: brush, Erase: eraser }, brush)).toBeNull();
    expect(brushToSelectOnLabelPick({ Brush: brush, Erase: eraser }, rect)).toBeNull();
    expect(brushToSelectOnLabelPick({ Brush: brush, Erase: eraser }, undefined)).toBeNull();
  });

  it("does nothing for labels without a brush (e.g. RectangleLabels)", () => {
    expect(brushToSelectOnLabelPick({ Rectangle: rect }, eraser)).toBeNull();
    expect(brushToSelectOnLabelPick(undefined, eraser)).toBeNull();
  });
});
