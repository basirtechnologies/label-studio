import { useEffect, useSyncExternalStore } from "react";
import { getConfigHotkeysVersion, subscribeConfigHotkeys } from "@humansignal/core/lib/utils/configHotkeys";
import { Hotkey } from "../../core/Hotkey";
import { isDefined } from "../../utils/utilities";

/** Hotkeys of the toolbar tools (tool:* names from the keymap). */
export const toolbarHotkeys = Hotkey("SegmentationToolbar", "Segmentation Tools");

/** DW-891: changes whenever the hotkeys of the loaded labeling config change. */
export const useConfigHotkeysVersion = () =>
  useSyncExternalStore(subscribeConfigHotkeys, getConfigHotkeysVersion, getConfigHotkeysVersion);

/**
 * DW-891: a tool hotkey on a key that the loaded labeling config uses (Label, Choice, Filter, ... hotkey)
 * belongs to the config: the label wins, the tool hotkey is not registered and is ignored if it was bound
 * before the config took the key.
 */
export const isTakenByConfig = (name) => Hotkey.isConfigKey(toolbarHotkeys.lookupKey(name));

/**
 * Registers the tool's own shortcut (e.g. "tool:eraser") while the tool is shown.
 * @returns {{ shortcutKey: string | null, takenByConfig: boolean }} shortcutKey is the key to show for the
 *   tool: null when it has no key or the key belongs to the labeling config
 */
export const useToolShortcut = ({ shortcut, tool, onClick }) => {
  // re-render (and re-register) when the config's hotkeys change
  useConfigHotkeysVersion();

  const resolvedShortcut = shortcut ? toolbarHotkeys.lookupKey(shortcut) : null;
  const takenByConfig = isDefined(resolvedShortcut) && Hotkey.isConfigKey(resolvedShortcut);

  useEffect(() => {
    const removeShortcut = () => {
      if (shortcut && toolbarHotkeys.hasKeyByName(shortcut)) {
        toolbarHotkeys.removeNamed(shortcut);
      }
    };

    removeShortcut();

    if (shortcut && !takenByConfig && !toolbarHotkeys.hasKeyByName(shortcut)) {
      toolbarHotkeys.addNamed(shortcut, () => {
        // the config may have taken the key after it was bound here
        if (isTakenByConfig(shortcut)) return;
        if (!tool?.disabled && !tool?.annotation?.isDrawing) {
          if (tool?.unselectRegionOnToolChange) {
            tool.annotation.unselectAreas();
          }
          onClick?.();
        }
      });
    }

    return removeShortcut;
  }, [shortcut, resolvedShortcut, takenByConfig, tool?.annotation]);

  return { shortcutKey: isDefined(resolvedShortcut) && !takenByConfig ? resolvedShortcut : null, takenByConfig };
};

/**
 * Registers the tool's extra shortcuts (e.g. "[" / "]" sizes) while the tool is active.
 * @param {Record<string, [string, Function]>} extraShortcuts
 * @param {boolean} active
 */
export const useToolExtraShortcuts = (extraShortcuts, active) => {
  const configHotkeysVersion = useConfigHotkeysVersion();

  useEffect(() => {
    const removeShortcuts = () => {
      Object.keys(extraShortcuts).forEach((key) => {
        if (toolbarHotkeys.hasKeyByName(key)) toolbarHotkeys.removeNamed(key);
      });
    };

    const addShortcuts = () => {
      Object.entries(extraShortcuts).forEach(([key, [_label, fn]]) => {
        if (isTakenByConfig(key) || toolbarHotkeys.hasKeyByName(key)) return;

        toolbarHotkeys.overwriteNamed(key, (...args) => {
          if (!isTakenByConfig(key)) fn(...args);
        });
      });
    };

    if (active) {
      addShortcuts();
    }

    return removeShortcuts;
  }, [extraShortcuts, active, configHotkeysVersion]);
};
