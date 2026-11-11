/**
 * Local preferences: storage and theme helpers.
 *
 * There are no accounts — preferences live in localStorage on this device.
 */

export const PREFERENCES_KEY = 'betterdojade.preferences.v1';

export const DEFAULT_PREFERENCES = Object.freeze({
    theme: 'light',
    defaultMode: 'mevo',
    ownBike: false,
    home: '',
    work: '',
});

const THEMES = ['light', 'dark', 'auto'];
const MODES = ['mevo', 'walk', 'transit'];

function getStorage() {
    try {
        return typeof localStorage === 'undefined' ? null : localStorage;
    } catch {
        return null;
    }
}

/**
 * Coerce an arbitrary object into a valid preferences object.
 */
export function normalizePreferences(value = {}) {
    const source = value && typeof value === 'object' ? value : {};

    return {
        theme: THEMES.includes(source.theme) ? source.theme : DEFAULT_PREFERENCES.theme,
        defaultMode: MODES.includes(source.defaultMode)
            ? source.defaultMode
            : DEFAULT_PREFERENCES.defaultMode,
        ownBike: typeof source.ownBike === 'boolean'
            ? source.ownBike
            : DEFAULT_PREFERENCES.ownBike,
        home: typeof source.home === 'string' ? source.home.trim() : DEFAULT_PREFERENCES.home,
        work: typeof source.work === 'string' ? source.work.trim() : DEFAULT_PREFERENCES.work,
    };
}

/**
 * Load preferences from localStorage, falling back to defaults on any error.
 */
export function loadPreferences(storage = getStorage()) {
    if (!storage) return { ...DEFAULT_PREFERENCES };

    try {
        const raw = storage.getItem(PREFERENCES_KEY);
        if (!raw) return { ...DEFAULT_PREFERENCES };
        const parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== 'object') return { ...DEFAULT_PREFERENCES };
        return normalizePreferences(parsed);
    } catch {
        return { ...DEFAULT_PREFERENCES };
    }
}

/**
 * Persist preferences, returning the normalized object that was stored.
 */
export function savePreferences(prefs, storage = getStorage()) {
    const normalized = normalizePreferences(prefs);

    if (storage) {
        try {
            storage.setItem(PREFERENCES_KEY, JSON.stringify(normalized));
        } catch {
            // Private mode / quota exceeded — the app still works for this session.
        }
    }

    return normalized;
}

/**
 * Resolve a theme preference to the concrete theme in use.
 */
export function resolveTheme(theme, prefersDark = false) {
    if (theme === 'dark') return 'dark';
    if (theme === 'auto') return prefersDark ? 'dark' : 'light';
    return 'light';
}

export function systemPrefersDark(win = typeof window === 'undefined' ? null : window) {
    return Boolean(win?.matchMedia?.('(prefers-color-scheme: dark)')?.matches);
}

/**
 * Apply a theme preference to the document root.
 * @returns {'light'|'dark'} The resolved theme.
 */
export function applyTheme(theme, {
    root = typeof document === 'undefined' ? null : document.documentElement,
    prefersDark = systemPrefersDark(),
} = {}) {
    const choice = THEMES.includes(theme) ? theme : DEFAULT_PREFERENCES.theme;
    const resolved = resolveTheme(choice, prefersDark);

    if (root) {
        root.setAttribute('data-theme', resolved);
        root.setAttribute('data-theme-choice', choice);
    }

    return resolved;
}
