/** Presentation-only grouping. Page ownership comes from the region, never its position in a list. */
export function groupRegionTreeByPage(tree: any[]): any[] {
  const pages = new Map<string, { object: any; index: number }>();
  const split = (nodes: any[]): Map<string, any[]> => {
    const buckets = new Map<string, any[]>();
    const append = (key: string, node: any) => buckets.set(key, [...(buckets.get(key) ?? []), node]);
    for (const node of nodes) {
      const children = split(node.children ?? []);
      if (node.isArea) {
        const object = node.item?.object;
        const index = node.item?.item_index ?? 0;
        const key = object?.type === "image" && object.multiImage ? `${object.name}:${index}` : "";
        if (key) pages.set(key, { object, index });
        append(key, { ...node, children: children.get(key) ?? [] });
        children.delete(key);
        // A historical manual parent may belong to another page. Promote that child, without changing parentID.
        for (const [childKey, descendants] of children) {
          for (const child of descendants) append(childKey, child);
        }
      } else {
        for (const [key, descendants] of children) {
          append(key, { ...node, key: key ? `${node.key}:page:${key}` : node.key, children: descendants });
        }
        if (!children.size) append("", node);
      }
    }
    return buckets;
  };
  const buckets = split(tree);
  if (!pages.size) return tree;
  const objects = new Set([...pages.values()].map(({ object }) => object.name));
  const result = [...(buckets.get("") ?? [])];
  for (const [key, { object, index }] of [...pages].sort(
    ([, a], [, b]) => a.object.name.localeCompare(b.object.name) || a.index - b.index,
  )) {
    result.push({
      key: `page:${key}`,
      isGroup: true,
      isPageGroup: true,
      selectable: false,
      draggable: false,
      label: `${objects.size > 1 ? `${object.name} — ` : ""}Page ${index + 1}`,
      children: buckets.get(key) ?? [],
    });
  }
  return result;
}

export function navigateToRegionPage(region: any) {
  if (region.object?.isMultiItem && region.item_index != null) {
    region.object.setCurrentItem?.(region.item_index);
  }
}
