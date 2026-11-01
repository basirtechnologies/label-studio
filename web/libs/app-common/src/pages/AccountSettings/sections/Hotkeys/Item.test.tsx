/**
 * DW-891: Account Settings -> Hotkeys shows the new tool defaults.
 */
import { render, screen } from "@testing-library/react";
import { getTypedDefaultHotkeys } from "./utils";
import { HotkeyItem } from "./Item";

const noop = () => {};
const defaultTool = (element: string) => {
  const hotkey = getTypedDefaultHotkeys().find((h) => h.section === "tools" && h.element === element);
  if (!hotkey) throw new Error(`no default for ${element}`);
  return hotkey;
};
const renderItem = (element: string) =>
  render(
    <HotkeyItem
      hotkey={defaultTool(element)}
      isEditing={false}
      onEdit={noop}
      onSave={noop}
      onCancel={noop}
      onToggle={noop}
    />,
  );

describe("HotkeyItem defaults (DW-891)", () => {
  it("the eraser defaults to X", () => {
    const { container } = renderItem("tool:eraser");
    expect([...container.querySelectorAll("kbd")].map((k) => k.textContent)).toEqual(["X"]);
  });

  it("the brush has no default key and says so", () => {
    const { container } = renderItem("tool:brush");
    expect(container.querySelector("kbd")).toBeNull();
    expect(screen.getByText("Not set")).toBeInTheDocument();
  });

  it("each tool hotkey is defined once", () => {
    const ids = getTypedDefaultHotkeys().map((h) => `${h.section}:${h.element}`);
    expect(ids.length).toBe(new Set(ids).size);
  });
});
