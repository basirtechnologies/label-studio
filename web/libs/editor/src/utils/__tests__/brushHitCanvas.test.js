import { brushHitCanvas } from "../brushHitCanvas";

describe("DW-894 bitmap hit-map ownership", () => {
  it("reuses only the same bitmap, dimensions, and Konva color key", () => {
    const image = document.createElement("canvas");
    image.width = image.height = 4;
    const first = brushHitCanvas(null, image, 4, 4, "#ff0000");
    expect(brushHitCanvas(first, image, 4, 4, "#ff0000")).toBe(first);
    const recolored = brushHitCanvas(first, image, 4, 4, "#00ff00");
    expect(recolored).not.toBe(first);
    expect(recolored.colorKey).toBe("#00ff00");
    const resized = brushHitCanvas(recolored, image, 8, 6, "#00ff00");
    expect(resized.canvas.width).toBe(8);
    expect(resized.canvas.height).toBe(6);
    expect(brushHitCanvas(resized, document.createElement("canvas"), 8, 6, "#00ff00")).not.toBe(resized);
  });
});
