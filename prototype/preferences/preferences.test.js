import { describe, it, expect } from 'vitest';

import {
    DEFAULT_PREFERENCES,
    PREFERENCES_KEY,
    applyTheme,
    loadPreferences,
    normalizePreferences,
    resolveTheme,
    savePreferences,
} from './preferences.js';

describe('local preferences', () => {
    it('returns light defaults when nothing is stored', () => {
        expect(loadPreferences()).toEqual(DEFAULT_PREFERENCES);
        expect(DEFAULT_PREFERENCES).toEqual({
            theme: 'light',
            defaultMode: 'mevo',
            ownBike: false,
            home: '',
            work: '',
        });
    });

    it('persists and restores every preference', () => {
        savePreferences({
            theme: 'dark',
            defaultMode: 'transit',
            ownBike: true,
            home: 'Gdańsk Główny',
            work: '54.3520, 18.6466',
        });

        expect(loadPreferences()).toEqual({
            theme: 'dark',
            defaultMode: 'transit',
            ownBike: true,
            home: 'Gdańsk Główny',
            work: '54.3520, 18.6466',
        });

        expect(JSON.parse(localStorage.getItem(PREFERENCES_KEY))).toEqual(loadPreferences());
    });

    it('trims saved place text', () => {
        expect(normalizePreferences({ home: '  Home  ', work: '  Work ' })).toMatchObject({
            home: 'Home',
            work: 'Work',
        });
    });

    it('falls back on invalid values without discarding valid ones', () => {
        expect(normalizePreferences({
            theme: 'neon',
            defaultMode: 'teleport',
            ownBike: 'yes',
            home: 'Home',
        })).toEqual({
            ...DEFAULT_PREFERENCES,
            home: 'Home',
        });
    });

    it('survives corrupt or non-object storage', () => {
        localStorage.setItem(PREFERENCES_KEY, '{not-json');
        expect(loadPreferences()).toEqual(DEFAULT_PREFERENCES);

        localStorage.setItem(PREFERENCES_KEY, '"a string"');
        expect(loadPreferences()).toEqual(DEFAULT_PREFERENCES);

        expect(normalizePreferences(null)).toEqual(DEFAULT_PREFERENCES);
    });

    it('works without a storage object', () => {
        expect(loadPreferences(null)).toEqual(DEFAULT_PREFERENCES);
        expect(savePreferences({ theme: 'dark' }, null)).toMatchObject({ theme: 'dark' });
    });

    it('resolves light, dark, and auto themes', () => {
        expect(resolveTheme('light', true)).toBe('light');
        expect(resolveTheme('dark', false)).toBe('dark');
        expect(resolveTheme('auto', true)).toBe('dark');
        expect(resolveTheme('auto', false)).toBe('light');
        expect(resolveTheme('unknown', true)).toBe('light');
    });

    it('applies the resolved theme to the document root', () => {
        const root = document.documentElement;

        expect(applyTheme('dark', { root, prefersDark: false })).toBe('dark');
        expect(root.getAttribute('data-theme')).toBe('dark');
        expect(root.getAttribute('data-theme-choice')).toBe('dark');

        expect(applyTheme('auto', { root, prefersDark: true })).toBe('dark');
        expect(root.getAttribute('data-theme')).toBe('dark');
        expect(root.getAttribute('data-theme-choice')).toBe('auto');

        expect(applyTheme('auto', { root, prefersDark: false })).toBe('light');
        expect(root.getAttribute('data-theme')).toBe('light');
        expect(root.getAttribute('data-theme-choice')).toBe('auto');
    });
});
