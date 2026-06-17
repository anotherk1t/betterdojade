import { beforeEach, describe, expect, it, vi } from 'vitest';

// Mock the JSON snapshot so the test is hermetic and independent of the real file.
vi.mock('../../src/data/mevo_stations_snapshot.json', () => ({
    default: {
        stations: [
            { id: 's1', name: 'Centrum', address: 'Main St', lat: 54.350, lon: 18.650, capacity: 10 },
            { id: 's2', name: 'Park',                       lat: 54.351, lon: 18.650, capacity: 5 },
            { id: 's3', name: 'Far',                        lat: 54.370, lon: 18.650 },
        ],
    },
}));

describe('mevo', () => {
    let mevo;

    beforeEach(async () => {
        // Re-import the module fresh so the module-level `stations` cache resets.
        vi.resetModules();
        mevo = await import('../../src/data/mevo.js');
    });

    it('getStations returns [] before loadStations is called', () => {
        expect(mevo.getStations()).toEqual([]);
    });

    it('getStationsNear returns [] before stations are loaded', () => {
        expect(mevo.getStationsNear(54.35, 18.65)).toEqual([]);
    });

    it('loadStations normalizes shape and defaults address/capacity', async () => {
        const stations = await mevo.loadStations();
        expect(stations).toHaveLength(3);
        expect(stations[0]).toEqual({
            id: 's1', name: 'Centrum', address: 'Main St',
            lat: 54.350, lon: 18.650, capacity: 10, type: 'mevo',
        });
        // Missing address → empty string, missing capacity → 0
        expect(stations[2].address).toBe('');
        expect(stations[2].capacity).toBe(0);
    });

    it('loadStations is idempotent (returns cached list on second call)', async () => {
        const first = await mevo.loadStations();
        const second = await mevo.loadStations();
        expect(second).toBe(first);
    });

    it('getStationsNear filters by radius and sorts by distance', async () => {
        await mevo.loadStations();
        // 800m default — s1 (0m) and s2 (~111m) are in range; s3 (~2.2km) is not.
        const near = mevo.getStationsNear(54.350, 18.650);
        const ids = near.map(n => n.item.id);
        expect(ids).toEqual(['s1', 's2']);
        // Sorted ascending by distance
        expect(near[0].distance).toBeLessThanOrEqual(near[1].distance);
    });

    it('getStationsNear honors a custom radius', async () => {
        await mevo.loadStations();
        const near = mevo.getStationsNear(54.350, 18.650, 50);
        expect(near.map(n => n.item.id)).toEqual(['s1']);
    });

    it('getStationAvailability returns availability data with mock defaults', async () => {
        await mevo.loadStations();
        const result = await mevo.getStationAvailability('s1');
        expect(result).toBeDefined();
        expect(result).toHaveProperty('bikesAvailable');
        expect(result).toHaveProperty('docksAvailable');
        expect(result).toHaveProperty('isAvailable');
        expect(result).toHaveProperty('isMockData');
        expect(typeof result.bikesAvailable).toBe('number');
        expect(typeof result.docksAvailable).toBe('number');
        expect(typeof result.isAvailable).toBe('boolean');
    });

    it('getAvailableStationsNear returns stations with availability', async () => {
        await mevo.loadStations();
        const available = await mevo.getAvailableStationsNear(54.350, 18.650, 800);
        expect(Array.isArray(available)).toBe(true);
        // Should include stations with availability data wrapped in {item, distance, availability}
        if (available.length > 0) {
            expect(available[0]).toHaveProperty('item');
            expect(available[0]).toHaveProperty('distance');
            expect(available[0]).toHaveProperty('availability');
            expect(available[0].item).toHaveProperty('id');
            expect(available[0].availability).toHaveProperty('bikesAvailable');
            expect(available[0].availability).toHaveProperty('docksAvailable');
        }
    });
});
