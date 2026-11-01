/**
 * DW-891: label hotkeys win over tool hotkeys.
 *
 * The hooks the toolbar Tool registers its hotkeys with, driven with the real keymap and the real list of
 * config hotkeys (core/configHotkeys, which Hotkey.ts fills from Annotation#setupHotKeys - see
 * core/Hotkey.configKeys.test.ts). The toolbar namespace is a small in-memory stand-in: core/Hotkey is
 * module-mocked by other test files in the same run.
 *
 * A key press is simulated the way keymaster dispatches it: every handler bound to the key is called,
 * the config's (selects the label) and the toolbar's (selects the tool).
 */
import { act, render } from "@testing-library/react";
import { setConfigHotkeys } from "@humansignal/core/lib/utils/configHotkeys";
import defaultKeymap from "../../../core/settings/keymap.json";
import { useToolExtraShortcuts, useToolShortcut } from "../useToolHotkeys";

/** in-memory toolbar namespace with the subset of the Hotkey API the hooks use */
const createToolbarHotkeys = (keymap) => {
  const bound = {};
  const keyOf = (name) => keymap[name]?.key ?? null;
  const bind = (name, fn) => {
    const key = keyOf(name);
    if (key) bound[key.toLowerCase()] = fn;
  };

  return {
    bound,
    lookupKey: keyOf,
    hasKeyByName: (name) => Boolean(keyOf(name) && bound[keyOf(name).toLowerCase()]),
    addNamed: bind,
    overwriteNamed: bind,
    removeNamed: (name) => {
      const key = keyOf(name);
      if (key) delete bound[key.toLowerCase()];
    },
  };
};

const flush = () => act(() => new Promise((resolve) => setTimeout(resolve, 0)));

let keymap;
let toolbar;
let labels; // the config's label hotkeys: key -> label value
let selectedLabels;
let toolClicks;

/** load a labeling config whose labels use these hotkeys, e.g. { e: "brass_knuckles" } */
const loadConfig = async (labelKeys) => {
  labels = labelKeys;
  await act(async () => setConfigHotkeys(Object.keys(labelKeys)));
};

const press = (key) => {
  if (labels[key]) selectedLabels.push(labels[key]);
  toolbar.bound[key]?.();
};

const NO_EXTRA = {};

/** what Tool.jsx does with its hotkeys; shows the key Tool would show */
const ToolHarness = ({ name, active = false, extraShortcuts = NO_EXTRA }) => {
  const { shortcutKey } = useToolShortcut({ shortcut: name, onClick: () => toolClicks.push(name), hotkeys: toolbar });
  useToolExtraShortcuts(extraShortcuts, active, toolbar);
  return <span data-testid={name}>{shortcutKey ?? ""}</span>;
};

const renderTools = (names) =>
  render(
    <div>
      {names.map((name) => (
        <ToolHarness key={name} name={name} />
      ))}
    </div>,
  );

const shownKey = (container, name) => container.querySelector(`[data-testid="${name}"]`).textContent;

describe("DW-891: label hotkeys win over tool hotkeys", () => {
  beforeEach(() => {
    keymap = structuredClone(defaultKeymap);
    toolbar = createToolbarHotkeys(keymap);
    labels = {};
    selectedLabels = [];
    toolClicks = [];
  });

  afterEach(async () => {
    await act(async () => setConfigHotkeys([]));
  });

  it("defaults: the eraser is on X and the brush has no key", () => {
    expect(defaultKeymap["tool:eraser"].key).toBe("X");
    expect(defaultKeymap["tool:brush"].key).toBeNull();
  });

  it("x is not used by any other default hotkey", () => {
    const usesX = Object.entries(defaultKeymap).filter(([, { key, mac }]) =>
      [key, mac].some((k) => typeof k === "string" && k.split(",").some((c) => c.trim().toLowerCase() === "x")),
    );
    expect(usesX.map(([name]) => name)).toEqual(["tool:eraser"]);
  });

  it("the brush tool registers no key and shows none", async () => {
    const { container, unmount } = renderTools(["tool:brush"]);
    await flush();
    expect(shownKey(container, "tool:brush")).toBe("");
    expect(toolbar.bound).toEqual({});
    unmount();
  });

  it("BrushLabels on e and b: e and b select the labels, no tool changes; x selects the eraser", async () => {
    await loadConfig({ e: "brass_knuckles", b: "metal_gun" });
    const { container, unmount } = renderTools(["tool:brush", "tool:eraser"]);
    await flush();

    press("e");
    press("b");
    expect(selectedLabels).toEqual(["brass_knuckles", "metal_gun"]);
    expect(toolClicks).toEqual([]);

    press("x");
    expect(toolClicks).toEqual(["tool:eraser"]);
    expect(shownKey(container, "tool:eraser")).toBe("X");
    unmount();
  });

  it("RectangleLabels on r: r selects the label, not the rectangle tool", async () => {
    await loadConfig({ r: "car" });
    const { container, unmount } = renderTools(["tool:rect"]);
    await flush();

    expect(toolbar.bound.r).toBeUndefined();
    press("r");
    expect(selectedLabels).toEqual(["car"]);
    expect(toolClicks).toEqual([]);
    // the toolbar does not advertise a key that is not the tool's here
    expect(shownKey(container, "tool:rect")).toBe("");
    unmount();
  });

  it("a config without r: r selects the rectangle tool", async () => {
    await loadConfig({ 1: "person" });
    const { container, unmount } = renderTools(["tool:rect"]);
    await flush();

    press("r");
    expect(toolClicks).toEqual(["tool:rect"]);
    expect(selectedLabels).toEqual([]);
    expect(shownKey(container, "tool:rect")).toBe("R");
    unmount();
  });

  it("matching is case-insensitive and respects modifiers", async () => {
    await loadConfig({ R: "upper", "shift+o": "shifted" }); // R = the tool's "R"; the ellipse tool is plain "O"
    const { unmount } = renderTools(["tool:rect", "tool:ellipse"]);
    await flush();

    expect(toolbar.bound.r).toBeUndefined();
    press("o");
    expect(toolClicks).toEqual(["tool:ellipse"]);
    unmount();
  });

  it("a customised tool key that clashes with a config key: the config wins", async () => {
    // Account Settings -> Hotkeys: eraser on Q, and the config has <Label hotkey="q"/>
    keymap["tool:eraser"] = { ...keymap["tool:eraser"], key: "q" };
    await loadConfig({ q: "bat" });
    const { container, unmount } = renderTools(["tool:eraser"]);
    await flush();

    press("q");
    expect(selectedLabels).toEqual(["bat"]);
    expect(toolClicks).toEqual([]);
    expect(shownKey(container, "tool:eraser")).toBe("");
    unmount();
  });

  it("a user-bound brush key works when the config does not use it", async () => {
    keymap["tool:brush"] = { ...keymap["tool:brush"], key: "j" };
    await loadConfig({ e: "brass_knuckles" });
    const { container, unmount } = renderTools(["tool:brush"]);
    await flush();

    press("j");
    expect(toolClicks).toEqual(["tool:brush"]);
    expect(shownKey(container, "tool:brush")).toBe("j");
    unmount();
  });

  it("the config also wins when it takes the key after the tool was bound", async () => {
    const { container, unmount } = renderTools(["tool:rect"]);
    await flush();
    const boundRect = toolbar.bound.r;
    expect(boundRect).toBeDefined();

    // e.g. labels added later (dynamic labels): the handler bound before ignores the key at once
    setConfigHotkeys(["r"]);
    boundRect();
    expect(toolClicks).toEqual([]);

    await flush();
    expect(toolbar.bound.r).toBeUndefined();
    expect(shownKey(container, "tool:rect")).toBe("");

    // and the tool gets its key back when the config no longer uses it
    await loadConfig({});
    await flush();
    press("r");
    expect(toolClicks).toEqual(["tool:rect"]);
    unmount();
  });

  it("extra tool shortcuts ([ / ]) follow the same rule and keep working otherwise", async () => {
    const decrease = mock();
    const increase = mock();
    const extra = {
      "tool:decrease-tool": ["Decrease size", decrease],
      "tool:increase-tool": ["Increase size", increase],
    };
    await loadConfig({ "]": "bracket" });
    const { unmount } = render(<ToolHarness active name="tool:brush" extraShortcuts={extra} />);
    await flush();

    press("[");
    expect(decrease).toHaveBeenCalledTimes(1);
    expect(toolbar.bound["]"]).toBeUndefined();
    press("]");
    expect(increase).not.toHaveBeenCalled();
    expect(selectedLabels).toEqual(["bracket"]);
    unmount();
  });
});
