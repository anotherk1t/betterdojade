import { describe, expect, it } from 'vitest';
import { calculateUnpavedRatio, exceedsUnpavedLimit, getCyclingRoute } from '../../src/routing/graphhopper.js';
import { jsonResponse, mockFetch } from '../setup.js';

function pathWithSurface(surfaceDetails, pointCount = 3) {
    const coordinates = Array.from({ length: pointCount }, (_, i) => [18.0 + i * 0.001, 54.0]);
    return {
        time: 1000,
        distance: pointCount * 100,
        points: {
            coordinates,
        },
        details: { surface: surfaceDetails },
    };
}

describe('GraphHopper bike surface guardrail', () => {
    it('rejects only when unpaved share is greater than 10%', () => {
        expect(exceedsUnpavedLimit(pathWithSurface([
            [0, 1, 'gravel'],
            [1, 10, 'paved'],
        ], 11))).toBe(false);

        expect(exceedsUnpavedLimit(pathWithSurface([
            [0, 2, 'gravel'],
            [2, 11, 'paved'],
        ], 12))).toBe(true);
    });

    it('rejects routes above 10% unpaved', () => {
        expect(exceedsUnpavedLimit(pathWithSurface([
            [0, 1, 'gravel'],
            [1, 2, 'paved'],
        ]))).toBe(true);

        expect(calculateUnpavedRatio(pathWithSurface([
            [0, 2, 'dirt'],
        ]))).toBe(1);
    });

    it('returns null for missing surface details', () => {
        expect(calculateUnpavedRatio(pathWithSurface([]))).toBeNull();
    });

    it('returns null when a cycling route exceeds the guardrail', async () => {
        mockFetch(jsonResponse({
            paths: [pathWithSurface([
                [0, 1, 'gravel'],
                [1, 2, 'paved'],
            ])],
        }));

        expect(await getCyclingRoute(
            { lat: 54.0, lon: 18.0 },
            { lat: 54.0, lon: 18.002 },
        )).toBeNull();
    });
});
