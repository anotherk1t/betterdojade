/**
 * Preferences panel: theme, default mode, own-bike default, and saved places.
 * Everything is stored locally in localStorage — there are no accounts.
 */

import {
    DEFAULT_PREFERENCES,
    applyTheme,
    loadPreferences,
    normalizePreferences,
    savePreferences,
} from './preferences.js';

let current = null;
let onApplyCallback = null;
let onUsePlaceCallback = null;
let statusTimer = null;
let placeSaveTimer = null;

export function getPreferences() {
    return { ...(current || loadPreferences()) };
}

/**
 * Initialize the preferences panel and restore saved values.
 * @param {Object} options
 * @param {function} options.onApply - Called with the current preferences after changes.
 * @param {function} options.onUsePlace - Called with (place, target, value) when a saved place is used.
 */
export function initPreferences({ onApply, onUsePlace } = {}) {
    current = loadPreferences();
    onApplyCallback = onApply || null;
    onUsePlaceCallback = onUsePlace || null;

    // Apply the saved theme even if the panel markup is unavailable.
    applyTheme(current.theme);
    syncForm();
    notifyApply();
    setupSystemThemeListener();

    const overlay = document.getElementById('prefs-overlay');
    const openBtn = document.getElementById('prefs-open-btn');
    const closeBtn = document.getElementById('prefs-close-btn');
    const doneBtn = document.getElementById('prefs-done-btn');
    const resetBtn = document.getElementById('prefs-reset-btn');
    const ownBikeInput = document.getElementById('pref-own-bike-default');
    const homeInput = document.getElementById('pref-home');
    const workInput = document.getElementById('pref-work');

    if (!overlay || !openBtn) return { ...current };

    let lastFocused = null;

    const openPanel = () => {
        lastFocused = document.activeElement;
        overlay.hidden = false;
        openBtn.setAttribute('aria-expanded', 'true');
        (closeBtn || overlay).focus();
    };

    const closePanel = () => {
        flushPlaceSave();
        overlay.hidden = true;
        openBtn.setAttribute('aria-expanded', 'false');
        if (lastFocused && typeof lastFocused.focus === 'function' && document.contains(lastFocused)) {
            lastFocused.focus();
        } else {
            openBtn.focus();
        }
    };

    openBtn.addEventListener('click', openPanel);
    closeBtn?.addEventListener('click', closePanel);
    doneBtn?.addEventListener('click', closePanel);

    overlay.addEventListener('click', (event) => {
        if (event.target === overlay) closePanel();
    });

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && !overlay.hidden) closePanel();
    });

    // Theme choices
    document.querySelectorAll('[data-theme-choice]').forEach((btn) => {
        btn.addEventListener('click', () => {
            updatePreferences({ theme: btn.dataset.themeChoice });
        });
    });

    // Default travel mode
    document.querySelectorAll('[data-default-mode]').forEach((btn) => {
        btn.addEventListener('click', () => {
            updatePreferences({ defaultMode: btn.dataset.defaultMode });
        });
    });

    // Own bike default (button switch)
    ownBikeInput?.addEventListener('click', () => {
        updatePreferences({ ownBike: !current.ownBike });
    });

    // Saved places: save shortly after typing, and immediately on blur.
    const schedulePlaceSave = (field, input) => {
        updatePlaceButtons();
        clearTimeout(placeSaveTimer);
        placeSaveTimer = setTimeout(() => {
            placeSaveTimer = null;
            updatePreferences({ [field]: input.value }, { sync: false, announce: false });
        }, 300);
    };

    homeInput?.addEventListener('input', () => schedulePlaceSave('home', homeInput));
    workInput?.addEventListener('input', () => schedulePlaceSave('work', workInput));
    homeInput?.addEventListener('change', () => {
        updatePreferences({ home: homeInput.value }, { sync: false, announce: false });
    });
    workInput?.addEventListener('change', () => {
        updatePreferences({ work: workInput.value }, { sync: false, announce: false });
    });

    // Quick-fill From/To from a saved place.
    document.querySelectorAll('[data-place][data-target]').forEach((btn) => {
        btn.addEventListener('click', async () => {
            const place = btn.dataset.place;
            const target = btn.dataset.target;
            const input = place === 'home' ? homeInput : workInput;
            const value = input?.value.trim();

            if (!value) {
                input?.focus();
                return;
            }

            updatePreferences({ [place]: value }, { sync: false, announce: false });
            closePanel();

            if (onUsePlaceCallback) {
                await onUsePlaceCallback(place, target, value);
            }
        });
    });

    resetBtn?.addEventListener('click', () => {
        clearTimeout(placeSaveTimer);
        placeSaveTimer = null;
        current = { ...DEFAULT_PREFERENCES };
        savePreferences(current);
        applyTheme(current.theme);
        syncForm({ force: true });
        notifyApply();
        showStatus('Preferences reset to defaults');
    });

    updatePlaceButtons();

    return { ...current };

    function flushPlaceSave() {
        if (!placeSaveTimer) return;
        clearTimeout(placeSaveTimer);
        placeSaveTimer = null;
        updatePreferences(
            { home: homeInput?.value || '', work: workInput?.value || '' },
            { sync: false, announce: false }
        );
    }
}

/**
 * Update one or more preferences, persist them, and re-apply the theme.
 */
export function updatePreferences(partial, { sync = true, announce = true } = {}) {
    current = normalizePreferences({ ...(current || loadPreferences()), ...partial });
    savePreferences(current);
    applyTheme(current.theme);

    if (sync) syncForm();
    notifyApply();
    if (announce) showStatus('Saved on this device');

    return { ...current };
}

function syncForm({ force = false } = {}) {
    if (!current) return;

    document.querySelectorAll('[data-theme-choice]').forEach((btn) => {
        const active = btn.dataset.themeChoice === current.theme;
        btn.classList.toggle('active', active);
        btn.setAttribute('aria-pressed', String(active));
    });

    document.querySelectorAll('[data-default-mode]').forEach((btn) => {
        const active = btn.dataset.defaultMode === current.defaultMode;
        btn.classList.toggle('active', active);
        btn.setAttribute('aria-pressed', String(active));
    });

    const ownBikeInput = document.getElementById('pref-own-bike-default');
    if (ownBikeInput) {
        ownBikeInput.setAttribute('aria-checked', String(current.ownBike));
    }

    const homeInput = document.getElementById('pref-home');
    const workInput = document.getElementById('pref-work');

    // Don't move the caret while the user is typing in a saved-place field.
    if (homeInput && (force || document.activeElement !== homeInput)) {
        homeInput.value = current.home;
    }
    if (workInput && (force || document.activeElement !== workInput)) {
        workInput.value = current.work;
    }

    updatePlaceButtons();
}

function updatePlaceButtons() {
    const homeInput = document.getElementById('pref-home');
    const workInput = document.getElementById('pref-work');

    document.querySelectorAll('[data-place][data-target]').forEach((btn) => {
        const input = btn.dataset.place === 'home' ? homeInput : workInput;
        btn.disabled = !input?.value.trim();
    });
}

function notifyApply() {
    if (onApplyCallback) onApplyCallback({ ...current });
}

function showStatus(message) {
    const status = document.getElementById('prefs-status');
    if (!status) return;

    status.textContent = message;
    clearTimeout(statusTimer);
    statusTimer = setTimeout(() => {
        status.textContent = '';
    }, 2200);
}

function setupSystemThemeListener() {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;

    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = () => {
        if (current?.theme === 'auto') applyTheme('auto');
    };

    if (mediaQuery.addEventListener) {
        mediaQuery.addEventListener('change', onChange);
    } else if (mediaQuery.addListener) {
        mediaQuery.addListener(onChange);
    }
}
