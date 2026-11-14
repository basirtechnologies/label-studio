import { emitRegionVisibilityToggled } from "./labelingTelemetry";

/** The panel eye and keyboard action both use RegionStore's annotation-wide toggle. */
export function toggleAnnotationVisibility(annotation: any, event?: KeyboardEvent): boolean {
  if (event?.repeat || event?.isComposing) return false;
  const target = event?.target as HTMLElement | null;
  if (
    target?.closest?.(
      'input, textarea, select, [contenteditable]:not([contenteditable="false"]), [role="textbox"], [role="searchbox"], [role="combobox"], .cm-editor, .CodeMirror',
    )
  )
    return false;
  const regions = annotation?.regionStore;
  if (!regions?.regions?.length) return false;
  emitRegionVisibilityToggled(annotation.store, annotation, { visible: Boolean(regions.isAllHidden), scope: "all" });
  regions.toggleVisibility();
  return true;
}
