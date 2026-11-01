/**
 * DW-891: label hotkeys win over tool hotkeys.
 *
 * Real Hotkey namespaces and the hooks the toolbar Tool registers its hotkeys with. The labeling config's hotkeys are registered the
 * way Annotation#setupHotKeys does it: Hotkey(Hotkey.CONFIG_NAMESPACE).addKey(label.hotkey, label.onHotKey).
 * A key press is simulated by calling the handlers bound to that key in the config and toolbar
 * namespaces (keymaster calls every handler bound to a key).
 */
import { act, render } from "@testing-library/react";
import { getConfigHotkeys } from "@humansignal/core/lib/utils/configHotkeys";
import { Hotkey } from "../../../core/Hotkey";
import defaultKeymap from "../../../core/settings/keymap.json";
import { toolbarHotkeys, useToolExtraShortcuts, useToolShortcut } from "../useToolHotkeys";

const configHotkeys = Hotkey(Hotkey.CONFIG_NAMESPACE, "Annotations");
const toolbarKeys = () => Object.fromEntries(toolbarHotkeys.getKeys().map((key) => [key, toolbarHandler(key)]));
const toolbarHandler = (key) => Hotkey.namespaces().SegmentationToolbar.keys[key];

const flush = () => act(() => new Promise((resolve) => setTimeout(resolve, 0)));

let selectedLabels;
let toolClicks;

// handlers of the config's hotkeys, by key, so press() can call them
const configHandlers = {};

/** <Label value hotkey/> of the config: pressing its key selects it */
const addConfigLabel = (value, hotkey) => {
  const select = () => selectedLabels.push(value);
  configHandlers[configHotkeys.applyAliases(hotkey.toLowerCase())] = select;
  configHotkeys.addKey(hotkey, select);
};

/** keymaster calls every handler bound to the key: the config's (label) and the toolbar's (tool) */
const press = (key) => {
  if (configHotkeys.hasKey(key)) configHandlers[key]?.();
  toolbarKeys()[key]?.();
};

const NO_EXTRA = {};

/** what Tool.jsx does with its hotkeys; shows the key Tool would show */
const ToolHarness = ({ name, active = false, extraShortcuts = NO_EXTRA, onClick }) => {
  const { shortcutKey } = useToolShortcut({ shortcut: name, onClick: onClick ?? (() => toolClicks.push(name)) });
  useToolExtraShortcuts(extraShortcuts, active);
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
    selectedLabels = [];
    toolClicks = [];
    Hotkey.keymap = { ...defaultKeymap };
  });

  afterEach(async () => {
    configHotkeys.unbindAll();
    for (const key of Object.keys(configHandlers)) delete configHandlers[key];
    Hotkey.keymap = { ...defaultKeymap };
    await flush();
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
    expect(Object.keys(toolbarKeys())).toEqual([]);
    unmount();
  });

  it("BrushLabels on e and b: e and b select the labels, no tool changes; x selects the eraser", async () => {
    addConfigLabel("brass_knuckles", "e");
    addConfigLabel("metal_gun", "b");
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
    addConfigLabel("car", "r");
    const { container, unmount } = renderTools(["tool:rect"]);
    await flush();

    expect(toolbarKeys().r).toBeUndefined();
    press("r");
    expect(selectedLabels).toEqual(["car"]);
    expect(toolClicks).toEqual([]);
    // the toolbar does not advertise a key that is not the tool's here
    expect(shownKey(container, "tool:rect")).toBe("");
    unmount();
  });

  it("a config without r: r selects the rectangle tool", async () => {
    addConfigLabel("person", "1");
    const { container, unmount } = renderTools(["tool:rect"]);
    await flush();

    press("r");
    expect(toolClicks).toEqual(["tool:rect"]);
    expect(selectedLabels).toEqual([]);
    expect(shownKey(container, "tool:rect")).toBe("R");
    unmount();
  });

  it("matching is case-insensitive and respects modifiers", async () => {
    addConfigLabel("upper", "R"); // same key as the tool's "R"
    addConfigLabel("shifted", "shift+o"); // the ellipse tool is plain "O": no clash
    const { unmount } = renderTools(["tool:rect", "tool:ellipse"]);
    await flush();

    expect(toolbarKeys().r).toBeUndefined();
    press("o");
    expect(toolClicks).toEqual(["tool:ellipse"]);
    unmount();
  });

  it("a customised tool key that clashes with a config key: the config wins", async () => {
    // e.g. Account Settings -> Hotkeys: eraser on Q, and the config has <Label hotkey="q"/>
    Hotkey.setKeymap({ "tool:eraser": { ...defaultKeymap["tool:eraser"], key: "q" } });
    addConfigLabel("bat", "q");
    const { container, unmount } = renderTools(["tool:eraser"]);
    await flush();

    press("q");
    expect(selectedLabels).toEqual(["bat"]);
    expect(toolClicks).toEqual([]);
    expect(shownKey(container, "tool:eraser")).toBe("");
    unmount();
  });

  it("a user-bound brush key works when the config does not use it", async () => {
    Hotkey.setKeymap({ "tool:brush": { ...defaultKeymap["tool:brush"], key: "j" } });
    const { unmount } = renderTools(["tool:brush"]);
    await flush();

    press("j");
    expect(toolClicks).toEqual(["tool:brush"]);
    unmount();
  });

  it("the config also wins when it takes the key after the tool was bound", async () => {
    const { container, unmount } = renderTools(["tool:rect"]);
    await flush();
    const boundRect = toolbarKeys().r;
    expect(boundRect).toBeDefined();

    addConfigLabel("car", "r"); // e.g. labels added later (dynamic labels)
    // ignored at once, even before the toolbar re-renders
    boundRect();
    expect(toolClicks).toEqual([]);

    await flush();
    expect(toolbarKeys().r).toBeUndefined();
    expect(shownKey(container, "tool:rect")).toBe("");

    // and the tool gets its key back when the config no longer uses it
    configHotkeys.unbindAll();
    await flush();
    press("r");
    expect(toolClicks).toEqual(["tool:rect"]);
    unmount();
  });

  it("extra tool shortcuts ([ / ]) follow the same rule and keep working otherwise", async () => {
    const decrease = mock();
    const increase = mock();
    const extra = { "tool:decrease-tool": ["Decrease size", decrease], "tool:increase-tool": ["Increase size", increase] };
    addConfigLabel("bracket", "]");
    const { unmount } = render(<ToolHarness active name="tool:brush" extraShortcuts={extra} onClick={() => {}} />);
    await flush();

    toolbarKeys()["["]?.();
    expect(decrease).toHaveBeenCalledTimes(1);
    expect(toolbarKeys()["]"]).toBeUndefined();
    unmount();
  });

  it("publishes the config's keys for the keyboard help", async () => {
    addConfigLabel("brass_knuckles", "e");
    addConfigLabel("filter", "shift+f");
    expect(getConfigHotkeys().sort()).toEqual(["e", "shift+f"]);
    expect(Hotkey.isConfigKey("E")).toBe(true);
    expect(Hotkey.isConfigKey("Shift+F")).toBe(true);
    expect(Hotkey.isConfigKey("f")).toBe(false);
    configHotkeys.unbindAll();
    expect(getConfigHotkeys()).toEqual([]);
  });
});
