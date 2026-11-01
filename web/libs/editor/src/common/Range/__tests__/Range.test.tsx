/**
 * Range: optional value label (DW-890 stepped brush/eraser size sliders).
 */
import { render, screen } from "@testing-library/react";
import { Range } from "../Range";

const STEPS = [1, 2, 3, 5, 8, 10, 15, 20, 30, 40, 50];

describe("Range valueLabel", () => {
  it("renders no value label by default", () => {
    render(<Range value={3} min={0} max={10} />);
    expect(screen.queryByLabelText("range-value")).toBeNull();
  });

  it("shows the value label for the current value", () => {
    render(<Range value={6} min={0} max={10} valueLabel={(i) => STEPS[i as number]} />);
    expect(screen.getByLabelText("range-value").textContent).toBe("15");
  });

  it("follows value changes from outside (e.g. keyboard shortcuts)", () => {
    const { rerender } = render(<Range value={6} min={0} max={10} valueLabel={(i) => STEPS[i as number]} />);
    rerender(<Range value={8} min={0} max={10} valueLabel={(i) => STEPS[i as number]} />);
    expect(screen.getByLabelText("range-value").textContent).toBe("30");
  });
});
