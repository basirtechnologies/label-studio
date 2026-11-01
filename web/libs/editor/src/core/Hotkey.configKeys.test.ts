/**
 * DW-891: the labeling config's hotkeys (Annotation#setupHotKeys namespace) are published for the tools
 * and the keyboard help; tool hotkeys on those keys belong to the config.
 */
import { getConfigHotkeys } from "@humansignal/core/lib/utils/configHotkeys";
import { Hotkey } from "./Hotkey";

describe("Hotkey config keys", () => {
  const config = Hotkey(Hotkey.CONFIG_NAMESPACE, "Annotations");
  const other = Hotkey("SomethingElse");

  afterEach(() => {
    config.unbindAll();
    other.unbindAll();
  });

  it("publishes the keys bound in the config namespace", () => {
    config.addKey("e", () => {});
    config.addKey("shift+f", () => {});
    expect(getConfigHotkeys().sort()).toEqual(["e", "shift+f"]);
    expect(Hotkey.isConfigKey("E")).toBe(true);
    expect(Hotkey.isConfigKey("Shift+F")).toBe(true);
    expect(Hotkey.isConfigKey("f")).toBe(false);
  });

  it("follows removals and unbinding", () => {
    config.addKey("r", () => {});
    config.addKey("w", () => {});
    config.removeKey("r");
    expect(getConfigHotkeys()).toEqual(["w"]);
    config.unbindAll();
    expect(getConfigHotkeys()).toEqual([]);
  });

  it("ignores keys of other namespaces (e.g. tools)", () => {
    other.addKey("x", () => {});
    expect(Hotkey.isConfigKey("x")).toBe(false);
  });

  it("the editor's annotation hotkeys use the config namespace", () => {
    expect(Hotkey.CONFIG_NAMESPACE).toBe("Annotations");
  });
});
