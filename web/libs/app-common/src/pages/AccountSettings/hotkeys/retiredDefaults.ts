/**
 * Basir DW-891: default hotkeys that changed.
 *
 * Saving account hotkeys stores every hotkey, also the ones the user never changed, so a stored
 * entry equal to an old default does not mean the user chose it. Such entries are dropped from the
 * account baseline and the new default applies (eraser shift+E, brush without a key). A key the user
 * picked themselves (anything else, or a disabled hotkey) is kept. Project overrides are kept as
 * they are: they are only stored when they differ from the account, so they were chosen.
 */
import type { CustomHotkeys } from "./effectiveHotkeys";

export const RETIRED_DEFAULT_KEYS: Record<string, string[]> = {
  "tools:tool:eraser": ["e", "x"], // E (upstream), then X (first DW-891 default)
  "tools:tool:brush": ["b"],
};

const isRetiredDefault = (id: string, hotkey: CustomHotkeys[string] | undefined): boolean => {
  const retired = RETIRED_DEFAULT_KEYS[id];

  if (!retired || !hotkey || hotkey.active === false || typeof hotkey.key !== "string") return false;

  return retired.includes(hotkey.key.trim().toLowerCase());
};

export const dropRetiredDefaults = (hotkeys: CustomHotkeys): CustomHotkeys => {
  if (!hotkeys || !Object.keys(RETIRED_DEFAULT_KEYS).some((id) => isRetiredDefault(id, hotkeys[id]))) {
    return hotkeys;
  }

  return Object.fromEntries(Object.entries(hotkeys).filter(([id, hotkey]) => !isRetiredDefault(id, hotkey)));
};
