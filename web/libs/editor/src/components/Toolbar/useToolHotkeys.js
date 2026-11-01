import { useEffect, useSyncExternalStore } from "react";
import {
  getConfigHotkeysVersion,
  isConfigHotkey,
  subscribeConfigHotkeys,
} from "@humansignal/core/lib/utils/configHotkeys";
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
 * @param {string} name keymap name, e.g. "tool:eraser"
 * @param {typeof toolbarHotkeys} [hotkeys]
 */
export const isTakenByConfig = (name, hotkeys = toolbarHotkeys) => isConfigHotkey(hotkeys.lookupKey(name));

/**
 * Registers the tool's own shortcut (e.g. "tool:eraser") while the tool is shown.
 * @param {object} props
 * @param {string} [props.shortcut] keymap name
 * @param {object} [props.tool] tool model
 * @param {Function} [props.onClick] selects the tool
 * @param {typeof toolbarHotkeys} [props.hotkeys] hotkey namespace (the toolbar's)
 * @returns {{ shortcutKey: string | null, takenByConfig: boolean }} shortcutKey is the key to show for the
 *   tool: null when it has no key or the key belongs to the labeling config
 */
export const useToolShortcut = ({ shortcut, tool, onClick, hotkeys = toolbarHotkeys }) => {
  // re-render (and re-register) when the config's hotkeys change
  useConfigHotkeysVersion();

  const resolvedShortcut = shortcut ? hotkeys.lookupKey(shortcut) : null;
  const takenByConfig = isDefined(resolvedShortcut) && isConfigHotkey(resolvedShortcut);

  useEffect(() => {
    const removeShortcut = () => {
      if (shortcut && hotkeys.hasKeyByName(shortcut)) {
        hotkeys.removeNamed(shortcut);
      }
    };

    removeShortcut();

    if (shortcut && !takenByConfig && !hotkeys.hasKeyByName(shortcut)) {
      hotkeys.addNamed(shortcut, () => {
        // the config may have taken the key after it was bound here
        if (isTakenByConfig(shortcut, hotkeys)) return;
        if (!tool?.disabled && !tool?.annotation?.isDrawing) {
          if (tool?.unselectRegionOnToolChange) {
            tool.annotation.unselectAreas();
          }
          onClick?.();
        }
      });
    }

    return removeShortcut;
  }, [shortcut, resolvedShortcut, takenByConfig, tool?.annotation, hotkeys]);

  return { shortcutKey: isDefined(resolvedShortcut) && !takenByConfig ? resolvedShortcut : null, takenByConfig };
};

/**
 * Registers the tool's extra shortcuts (e.g. "[" / "]" sizes) while the tool is active.
 * @param {Record<string, [string, Function]>} extraShortcuts
 * @param {boolean} active
 * @param {typeof toolbarHotkeys} [hotkeys] hotkey namespace (the toolbar's)
 */
export const useToolExtraShortcuts = (extraShortcuts, active, hotkeys = toolbarHotkeys) => {
  const configHotkeysVersion = useConfigHotkeysVersion();

  useEffect(() => {
    const removeShortcuts = () => {
      Object.keys(extraShortcuts).forEach((key) => {
        if (hotkeys.hasKeyByName(key)) hotkeys.removeNamed(key);
      });
    };

    const addShortcuts = () => {
      Object.entries(extraShortcuts).forEach(([key, [_label, fn]]) => {
        if (isTakenByConfig(key, hotkeys) || hotkeys.hasKeyByName(key)) return;

        hotkeys.overwriteNamed(key, (...args) => {
          if (!isTakenByConfig(key, hotkeys)) fn(...args);
        });
      });
    };

    if (active) {
      addShortcuts();
    }

    return removeShortcuts;
  }, [extraShortcuts, active, configHotkeysVersion, hotkeys]);
};
