/**
 * DW-891: hotkeys of the loaded labeling config (shared by the editor and the keyboard help).
 */
import {
  getConfigHotkeys,
  getConfigHotkeysVersion,
  isConfigHotkey,
  normalizeHotkeyCombo,
  setConfigHotkeys,
  splitHotkeyCombos,
  subscribeConfigHotkeys,
} from "./configHotkeys";

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("configHotkeys", () => {
  afterEach(() => setConfigHotkeys([]));

  it("normalises case, aliases and modifier order", () => {
    expect(normalizeHotkeyCombo("E")).toBe("e");
    expect(normalizeHotkeyCombo("Shift+F")).toBe("shift+f");
    expect(normalizeHotkeyCombo("f+shift")).toBe("shift+f");
    expect(normalizeHotkeyCombo("shift+ctrl+x")).toBe("ctrl+shift+x");
    expect(normalizeHotkeyCombo("control+plus")).toBe("ctrl+=");
    expect(normalizeHotkeyCombo("cmd+minus")).toBe("command+-");
  });

  it("splits comma-separated key lists", () => {
    expect(splitHotkeyCombos("a, shift+b")).toEqual(["a", "shift+b"]);
    expect(splitHotkeyCombos("")).toEqual([]);
    expect(splitHotkeyCombos(null)).toEqual([]);
  });

  it("matches keys case-insensitively with the same modifiers only", () => {
    setConfigHotkeys(["e", "b", "shift+f", "1"]);
    expect(isConfigHotkey("E")).toBe(true);
    expect(isConfigHotkey("b")).toBe(true);
    expect(isConfigHotkey("Shift+F")).toBe(true);
    expect(isConfigHotkey("f")).toBe(false); // shift+f is not f
    expect(isConfigHotkey("shift+e")).toBe(false); // e is not shift+e
    expect(isConfigHotkey("x")).toBe(false);
    expect(isConfigHotkey("q, e")).toBe(true); // any combination of a list
    expect(isConfigHotkey(null)).toBe(false);
  });

  it("is empty when no config is loaded", () => {
    expect(getConfigHotkeys()).toEqual([]);
    expect(isConfigHotkey("e")).toBe(false);
  });

  it("bumps the version only on a real change and notifies once per batch", async () => {
    const listener = mock();
    const unsubscribe = subscribeConfigHotkeys(listener);
    const v0 = getConfigHotkeysVersion();

    setConfigHotkeys(["e"]);
    setConfigHotkeys(["e", "b"]);
    setConfigHotkeys(["b", "E"]); // same set
    expect(getConfigHotkeysVersion()).toBe(v0 + 2);
    expect(listener).not.toHaveBeenCalled(); // asynchronous, never from inside a hotkey setup

    await tick();
    expect(listener).toHaveBeenCalledTimes(1);

    unsubscribe();
    setConfigHotkeys([]);
    await tick();
    expect(listener).toHaveBeenCalledTimes(1);
  });
});
