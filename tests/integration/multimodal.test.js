import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../src/routing/graphhopper.js', () => ({
    getWalkingRoute: vi.fn(),
    getCyclingRoute: vi.fn(),
    getPtRoutes: vi.fn(),
}));

vi.mock('../../src/data/shapes.js', () => ({
    loadShapes: vi.fn().mockResolvedValue(undefined),
    getShapeForLeg: vi.fn(() => null),
    shapesLoaded: vi.fn(() => true),
}));

vi.mock('../../src/data/mevo.js', () => ({
    getStationsNear: vi.fn(() => []),
    getAvailableStationsNear: vi.fn().mockResolvedValue([]),
    loadStations: vi.fn().mockResolvedValue([]),
    getStationAvailability: vi.fn().mockResolvedValue(null),
}));

let planRoutes;
let gh;
let mevo;

beforeEach(async () => {
    vi.resetModules();
    const mm = await import('../../src/routing/multimodal.js');
    planRoutes = mm.planRoutes;
    gh = await import('../../src/routing/graphhopper.js');
    mevo = await import('../../src/data/mevo.js');

    gh.getWalkingRoute.mockReset();
    gh.getCyclingRoute.mockReset();
    gh.getPtRoutes.mockReset();
    mevo.getStationsNear.mockReset();
    mevo.getAvailableStationsNear.mockReset();
    mevo.loadStations.mockReset();
    mevo.getStationAvailability.mockReset();
    mevo.getStationsNear.mockReturnValue([]);
    mevo.getAvailableStationsNear.mockResolvedValue([]);
    mevo.loadStations.mockResolvedValue([]);
});

const ORIGIN = { lat: 54.350, lon: 18.650 };
const DEST_CLOSE = { lat: 54.355, lon: 18.655 };       // ~700m — within 2km walk threshold
const DEST_FAR = { lat: 54.450, lon: 18.650 };          // ~11km — outside walk threshold
const DEP = 8 * 3600;

const ptFixture = {
    type: 'transit',
    totalTime: 1200,
    departureTime: DEP + 60,
    arrivalTime: DEP + 1260,
    legs: [
        { mode: 'walk', from: ORIGIN, to: { lat: 54.351, lon: 18.651, name: 'Stop A' },
          departureTime: DEP + 60, arrivalTime: DEP + 180, duration: 120, distance: 100 },
        { mode: 'tram', routeName: '6', routeType: 'TRAM', feedId: 'gtfs_0', routeId: 'R6', tripId: 'tr1',
          from: { lat: 54.351, lon: 18.651, name: 'Stop A' },
          to: { lat: 54.450, lon: 18.650, name: 'Stop B' },
          departureTime: DEP + 240, arrivalTime: DEP + 1140, duration: 900 },
        { mode: 'walk', from: { lat: 54.450, lon: 18.650, name: 'Stop B' }, to: DEST_FAR,
          departureTime: DEP + 1140, arrivalTime: DEP + 1260, duration: 120, distance: 100 },
    ],
};

describe('planRoutes', () => {
    it('returns a walking route when direct distance < 2 km and GH walk succeeds', async () => {
        gh.getWalkingRoute.mockResolvedValue({ duration: 600, distance: 700, geometry: null });
        gh.getPtRoutes.mockResolvedValue([]);
        gh.getCyclingRoute.mockResolvedValue(null);

        const routes = await planRoutes({
            origin: ORIGIN, destination: DEST_CLOSE,
            departureTimeSec: DEP, ownBike: false,
        });

        expect(routes.some(r => r.type === 'walk')).toBe(true);
        const walk = routes.find(r => r.type === 'walk');
        expect(walk.totalTime).toBe(600);
        expect(walk.legs).toHaveLength(1);
        expect(walk.legs[0].mode).toBe('walk');
    });

    it('does not attempt a walking route when distance >= 2 km', async () => {
        gh.getWalkingRoute.mockResolvedValue({ duration: 999, distance: 999, geometry: null });
        gh.getPtRoutes.mockResolvedValue([]);

        await planRoutes({
            origin: ORIGIN, destination: DEST_FAR,
            departureTimeSec: DEP, ownBike: false,
        });

        // Only enrichment-time getWalkingRoute calls would happen — and there's no walk leg in the
        // empty PT result, so it should not be called for the direct origin→destination walk.
        const calls = gh.getWalkingRoute.mock.calls;
        const directWalkCalled = calls.some(([from, to]) =>
            from.lat === ORIGIN.lat && from.lon === ORIGIN.lon &&
            to.lat === DEST_FAR.lat && to.lon === DEST_FAR.lon
        );
        expect(directWalkCalled).toBe(false);
    });

    it('includes a transit alternative when GH PT returns one with a transit leg', async () => {
        gh.getWalkingRoute.mockResolvedValue(null);
        gh.getPtRoutes.mockResolvedValue([ptFixture]);
        gh.getCyclingRoute.mockResolvedValue(null);

        const routes = await planRoutes({
            origin: ORIGIN, destination: DEST_FAR,
            departureTimeSec: DEP, ownBike: false,
        });

        const transit = routes.find(r => r.legs.some(l => l.mode === 'tram'));
        expect(transit).toBeDefined();
        expect(transit.arrivalTime).toBe(DEP + 1260);
    });

    it('filters out walk-only "PT" results (must contain a real transit leg)', async () => {
        const walkOnlyPt = {
            ...ptFixture,
            legs: [{ mode: 'walk', from: ORIGIN, to: DEST_FAR,
                    departureTime: DEP, arrivalTime: DEP + 600, duration: 600 }],
        };
        gh.getWalkingRoute.mockResolvedValue(null);
        gh.getPtRoutes.mockResolvedValue([walkOnlyPt]);

        const routes = await planRoutes({
            origin: ORIGIN, destination: DEST_FAR,
            departureTimeSec: DEP, ownBike: false,
        });

        expect(routes.find(r => r === walkOnlyPt)).toBeUndefined();
    });

    it('returns a MEVO bike alternative when stations exist near both ends and cycling route resolves', async () => {
        const stnA = { id: 'A', name: 'A', lat: 54.351, lon: 18.650 };
        const stnB = { id: 'B', name: 'B', lat: 54.449, lon: 18.650 };

        mevo.getAvailableStationsNear.mockImplementation((lat) => {
            // Near origin or destination, return appropriate station with availability; otherwise empty.
            if (Math.abs(lat - ORIGIN.lat) < 0.005) return Promise.resolve([{
                item: stnA, distance: 100,
                availability: { bikesAvailable: 5, docksAvailable: 3, isAvailable: true, isMockData: true },
            }]);
            if (Math.abs(lat - DEST_FAR.lat) < 0.005) return Promise.resolve([{
                item: stnB, distance: 100,
                availability: { bikesAvailable: 4, docksAvailable: 4, isAvailable: true, isMockData: true },
            }]);
            return Promise.resolve([]);
        });

        gh.getWalkingRoute.mockResolvedValue({ duration: 100, distance: 100, geometry: null });
        gh.getCyclingRoute.mockResolvedValue({ duration: 1500, distance: 11000, geometry: null });
        gh.getPtRoutes.mockResolvedValue([]);
        mevo.loadStations.mockResolvedValue([]);

        const routes = await planRoutes({
            origin: ORIGIN, destination: DEST_FAR,
            departureTimeSec: DEP, ownBike: false,
        });

        const bike = routes.find(r => r.type === 'bike');
        expect(bike).toBeDefined();
        // 3 legs: walk → bike → walk
        expect(bike.legs.map(l => l.mode)).toEqual(['walk', 'bike', 'walk']);
        expect(bike.legs[1].duration).toBe(1500);
    });

    it('returns an empty array when GH walk + PT + bike all fail or yield nothing', async () => {
        gh.getWalkingRoute.mockRejectedValue(new Error('boom'));
        gh.getPtRoutes.mockRejectedValue(new Error('boom'));
        gh.getCyclingRoute.mockRejectedValue(new Error('boom'));

        const routes = await planRoutes({
            origin: ORIGIN, destination: DEST_FAR,
            departureTimeSec: DEP, ownBike: false,
        });
        expect(routes).toEqual([]);
    });

    it('sorts the final routes by arrivalTime ascending', async () => {
        const slowPt = { ...ptFixture, arrivalTime: DEP + 3000,
            legs: [{ ...ptFixture.legs[1], arrivalTime: DEP + 3000 }] };
        const fastPt = { ...ptFixture, arrivalTime: DEP + 1260 };

        gh.getWalkingRoute.mockResolvedValue(null);
        gh.getPtRoutes.mockResolvedValue([slowPt, fastPt]);

        const routes = await planRoutes({
            origin: ORIGIN, destination: DEST_FAR,
            departureTimeSec: DEP, ownBike: false,
        });

        const arrivals = routes.map(r => r.arrivalTime);
        expect(arrivals).toEqual([...arrivals].sort((a, b) => a - b));
    });
});
