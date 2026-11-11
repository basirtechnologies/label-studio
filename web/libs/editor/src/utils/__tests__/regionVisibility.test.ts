import { describe, expect, it, mock } from "bun:test";
import { toggleAnnotationVisibility } from "../regionVisibility";
import keymap from "../../core/settings/keymap.json";

const annotation = () => {
  const regions = [{ hidden: false }, { hidden: true }];
  return {
    store: {},
    regionStore: {
      regions,
      get isAllHidden() {
        return regions.every((r) => r.hidden);
      },
      toggleVisibility: mock(function (this: any) {
        const hide = !this.isAllHidden;
        this.regions.forEach((region: any) => {
          region.hidden = hide;
        });
      }),
    },
  };
};

describe("DW-896 annotation-wide visibility shortcut", () => {
  it("uses one Ctrl chord on both platforms without Ctrl+H/Command+H browser conflicts", () => {
    expect(keymap["region:visibility-all"].key).toBe("ctrl+shift+h");
    expect(keymap["region:visibility-all"].mac).toBe("ctrl+shift+h");
    expect(
      Object.entries(keymap).filter(
        ([name, value]) => name !== "region:visibility-all" && value.key === "ctrl+shift+h",
      ),
    ).toEqual([]);
  });
  it("reuses the same toggle for button and shortcut; mixed visibility hides all, then shows all", () => {
    const ann = annotation();
    expect(toggleAnnotationVisibility(ann)).toBe(true);
    expect(ann.regionStore.regions.map((r) => r.hidden)).toEqual([true, true]);
    expect(toggleAnnotationVisibility(ann, new KeyboardEvent("keydown"))).toBe(true);
    expect(ann.regionStore.regions.map((r) => r.hidden)).toEqual([false, false]);
    expect(ann.regionStore.toggleVisibility).toHaveBeenCalledTimes(2);
  });
  it.each([
    "input",
    "textarea",
    "select",
    'div[contenteditable="true"]',
    'div[contenteditable="plaintext-only"]',
    'div[role="textbox"]',
    'div[role="combobox"]',
  ])("ignores text entry inside %s", (selector) => {
    const ann = annotation();
    const tag = selector.split("[")[0];
    const el = document.createElement(tag);
    const attr = selector.match(/\[([^=]+)="([^"]+)"\]/);
    if (attr) el.setAttribute(attr[1], attr[2]);
    const event = new KeyboardEvent("keydown", { bubbles: true });
    el.addEventListener("keydown", (e) => expect(toggleAnnotationVisibility(ann, e)).toBe(false));
    el.dispatchEvent(event);
    expect(ann.regionStore.toggleVisibility).not.toHaveBeenCalled();
  });
  it("ignores held keys, composition, and missing/empty annotations", () => {
    const ann = annotation();
    expect(toggleAnnotationVisibility(ann, new KeyboardEvent("keydown", { repeat: true }))).toBe(false);
    expect(toggleAnnotationVisibility(ann, new KeyboardEvent("keydown", { isComposing: true }))).toBe(false);
    expect(toggleAnnotationVisibility(undefined)).toBe(false);
    ann.regionStore.regions.length = 0;
    expect(toggleAnnotationVisibility(ann)).toBe(false);
  });
});
