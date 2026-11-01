/**
 * DW-891: stored copies of changed defaults follow the new defaults.
 */
import { effectiveHotkeys, toEditorKeymap } from "./effectiveHotkeys";
import { dropRetiredDefaults } from "./retiredDefaults";

describe("dropRetiredDefaults", () => {
  it("drops the old eraser (E) and brush (B) defaults, any case", () => {
    expect(
      dropRetiredDefaults({
        "tools:tool:eraser": { key: "E", active: true },
        "tools:tool:brush": { key: "b", active: true },
        "tools:tool:rect": { key: "R", active: true },
      }),
    ).toEqual({ "tools:tool:rect": { key: "R", active: true } });
  });

  it("keeps keys the user chose and disabled hotkeys", () => {
    const chosen = {
      "tools:tool:eraser": { key: "q", active: true },
      "tools:tool:brush": { key: "B", active: false },
    };
    expect(dropRetiredDefaults(chosen)).toBe(chosen);
  });
});

describe("effectiveHotkeys with old defaults saved (DW-891)", () => {
  afterEach(() => effectiveHotkeys.resetForTests());

  it("does not pass the old eraser/brush keys to the editor", () => {
    effectiveHotkeys.apply({
      account: {
        "tools:tool:eraser": { key: "E", active: true },
        "tools:tool:brush": { key: "B", active: true },
        "annotation:annotation:submit": { key: "alt+enter", active: true },
      },
    });

    const keymap = toEditorKeymap(effectiveHotkeys.getCustomHotkeys());
    expect(keymap["tool:eraser"]).toBeUndefined(); // editor default X applies
    expect(keymap["tool:brush"]).toBeUndefined(); // editor default: no key
    expect(keymap["annotation:submit"]).toEqual({ key: "alt+enter", active: true });
    expect(window.APP_SETTINGS.user?.customHotkeys?.["tools:tool:eraser"]).toBeUndefined();
  });

  it("project overrides are kept as saved (they were chosen)", () => {
    effectiveHotkeys.apply({ account: {}, project: { "tools:tool:eraser": { key: "E", active: true } } });
    expect(effectiveHotkeys.get("tools:tool:eraser")?.key).toBe("E");
  });
});
