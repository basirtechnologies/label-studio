/**
 * Basir DW-891: hotkeys that belong to the labeling config currently loaded in the editor
 * (Label / Choice / Filter / any control `hotkey`, including auto-assigned ones).
 *
 * A key used by the config wins over a tool hotkey on the same key: the editor does not register
 * the tool hotkey (and ignores it if it was bound earlier), and the keyboard help shows it as
 * unavailable in this project. The editor publishes the keys here; the help reads them.
 *
 * The state lives on `window` so the editor and the app share it even when they are bundled apart.
 */

type Listener = () => void;

interface ConfigHotkeysStore {
  keys: Set<string>;
  signature: string;
  version: number;
  listeners: Set<Listener>;
  notifyScheduled: boolean;
}

const STORE_KEY = "__basirConfigHotkeys";

const MODIFIER_ORDER = ["ctrl", "alt", "shift", "command"];

const MODIFIER_ALIASES: Record<string, string> = {
  ctrl: "ctrl",
  control: "ctrl",
  "⌃": "ctrl",
  alt: "alt",
  option: "alt",
  "⌥": "alt",
  shift: "shift",
  "⇧": "shift",
  command: "command",
  cmd: "command",
  meta: "command",
  "⌘": "command",
};

// same aliases the editor applies before binding (core/Hotkey.ts)
const KEY_ALIASES: Record<string, string> = {
  plus: "=",
  minus: "-",
  ",": "¼",
};

const getStore = (): ConfigHotkeysStore => {
  const holder = (typeof window !== "undefined" ? window : globalThis) as unknown as Record<string, ConfigHotkeysStore>;

  if (!holder[STORE_KEY]) {
    holder[STORE_KEY] = { keys: new Set(), signature: "", version: 0, listeners: new Set(), notifyScheduled: false };
  }

  return holder[STORE_KEY];
};

/** Splits "a, shift+b" (the editor's comma-separated key lists) into single combinations. */
export const splitHotkeyCombos = (key: string | null | undefined): string[] => {
  if (!key) return [];

  const tokenRegex = /((?:\w+\+)*(?:[^,]+|,)),?/g;

  return [...key.replace(/\s/g, "").matchAll(tokenRegex)].map((match) => match[1]).filter(Boolean);
};

/**
 * One combination in a comparable form: lower case, aliases applied, modifiers in a fixed order.
 * "Shift+F", "shift+f" and "F+shift" are the same; "f" and "shift+f" are not.
 */
export const normalizeHotkeyCombo = (combo: string): string => {
  const parts = combo
    .toLowerCase()
    .split("+")
    .map((part) => part.trim())
    .filter(Boolean);

  const modifiers = new Set<string>();
  const keys: string[] = [];

  for (const part of parts) {
    if (MODIFIER_ALIASES[part]) modifiers.add(MODIFIER_ALIASES[part]);
    else keys.push(KEY_ALIASES[part] ?? part);
  }

  return [...MODIFIER_ORDER.filter((modifier) => modifiers.has(modifier)), ...keys].join("+");
};

const notify = (store: ConfigHotkeysStore) => {
  if (store.notifyScheduled) return;
  store.notifyScheduled = true;
  // coalesce the many updates of one hotkey setup, and never re-render React from inside it
  queueMicrotask(() => {
    store.notifyScheduled = false;
    for (const listener of [...store.listeners]) listener();
  });
};

/** Replaces the config hotkeys (raw keys as bound by the editor; comma lists allowed). */
export const setConfigHotkeys = (keys: Iterable<string>): void => {
  const store = getStore();
  const normalized = new Set<string>();

  for (const key of keys) {
    for (const combo of splitHotkeyCombos(key)) normalized.add(normalizeHotkeyCombo(combo));
  }

  const signature = [...normalized].sort().join(" ");

  if (signature === store.signature) return;

  store.keys = normalized;
  store.signature = signature;
  store.version += 1;
  notify(store);
};

/** True when any combination of `key` is used by the current labeling config. */
export const isConfigHotkey = (key: string | null | undefined): boolean => {
  const { keys } = getStore();

  if (!keys.size) return false;

  return splitHotkeyCombos(key).some((combo) => keys.has(normalizeHotkeyCombo(combo)));
};

export const getConfigHotkeys = (): string[] => [...getStore().keys];

export const getConfigHotkeysVersion = (): number => getStore().version;

export const subscribeConfigHotkeys = (listener: Listener): (() => void) => {
  const store = getStore();

  store.listeners.add(listener);

  return () => {
    store.listeners.delete(listener);
  };
};
