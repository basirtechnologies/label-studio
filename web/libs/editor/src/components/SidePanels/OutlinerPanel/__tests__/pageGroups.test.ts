import { describe, expect, it, mock } from "bun:test";
import { groupRegionTreeByPage, navigateToRegionPage } from "../pageGroups";

const image = { type: "image", name: "pages", multiImage: true, isMultiItem: true, setCurrentItem: mock() };
const region = (id: string, index: number | null, type = "brushregion", object = image): any => ({
  key: id,
  isArea: true,
  item: { id, item_index: index, type, object },
  children: [],
});

describe("DW-892 page groups", () => {
  it("groups masks and boxes using their saved ownership, independent of list order", () => {
    const nodes = [region("box-3", 2, "rectangleregion"), region("mask-1", 0), region("mask-3", 2), region("box-2", 1)];
    const groups = groupRegionTreeByPage(nodes);
    expect(groups.map((g) => g.label)).toEqual(["Page 1", "Page 2", "Page 3"]);
    expect(groups.map((g) => g.children.map((r: any) => r.key))).toEqual([["mask-1"], ["box-2"], ["box-3", "mask-3"]]);
    expect(groups[0]).toMatchObject({ isPageGroup: true, selectable: false, draggable: false });
    expect(groups[0].children[0].item).toBe(nodes[1].item);
  });
  it("preserves ordinary single images and defaults missing historical item_index to page zero", () => {
    const nodes = [region("single", null, "rectangleregion", { ...image, multiImage: false })];
    expect(groupRegionTreeByPage(nodes)).toBe(nodes);
    expect(groupRegionTreeByPage([region("legacy", null)])[0].label).toBe("Page 1");
  });
  it("retains label/tool groups inside each page without mutating region parents", () => {
    const a = region("a", 0);
    const b = region("b", 1);
    const group = { key: "label-x", isGroup: true, children: [a, b] };
    const pages = groupRegionTreeByPage([group]);
    expect(pages.map((p) => p.children[0].children[0].key)).toEqual(["a", "b"]);
    expect(group.children).toEqual([a, b]);
    a.children = [b];
    expect(groupRegionTreeByPage([a]).map((p) => p.children[0].key)).toEqual(["a", "b"]);
  });
  it("does not combine different Image objects having the same page index", () => {
    const pages = groupRegionTreeByPage([region("a", 0), region("b", 0, "brushregion", { ...image, name: "other" })]);
    expect(pages).toHaveLength(2);
    expect(pages.map((p) => p.label)).toEqual(["other — Page 1", "pages — Page 1"]);
  });
  it("navigates to the saved page before row selection, without changing association", () => {
    const node = region("r", 2);
    navigateToRegionPage(node.item);
    expect(image.setCurrentItem).toHaveBeenCalledWith(2);
    expect(node.item.item_index).toBe(2);
  });
});
