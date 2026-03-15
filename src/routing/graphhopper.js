/**
 * GraphHopper API client for walking, cycling, and public-transit route geometries.
 * Expects a local GraphHopper server running at http://localhost:8989.
 * Requests are proxied through Vite's dev server at /graphhopper to avoid CORS.
 */

const GH_BASE = import.meta.env.VITE_GRAPH_HOPPER_URL || '/graphhopper';

// ---------------------------------------------------------------------------
// Street routing (foot / bike)
// ---------------------------------------------------------------------------

/**
 * Get a route between two points via GraphHopper.
 *
 * @param {{ lat, lon }} from
 * @param {{ lat, lon }} to
 * @param {'foot'|'bike'} profile - GraphHopper profile name.
 * @returns {Promise<{ duration: number, distance: number, geometry: Array<[number, number]> }|null>}
 */
async function getRoute(from, to, profile) {
    try {
        const url =
            `${GH_BASE}/route` +
            `?point=${from.lat},${from.lon}` +
            `&point=${to.lat},${to.lon}` +
            `&profile=${encodeURIComponent(profile)}` +
            `&locale=en` +
            `&points_encoded=false`;

        const resp = await fetch(url);
        if (!resp.ok) {
            console.warn(`[GraphHopper] HTTP ${resp.status} for ${profile} route`);
            return null;
        }

        const data = await resp.json();
        if (!data.paths || data.paths.length === 0) return null;

        const path = data.paths[0];

        // GeoJSON coordinates are [lon, lat]; convert to Leaflet [lat, lon].
        const geometry = path.points.coordinates.map(([lon, lat]) => [lat, lon]);

        return {
            duration: path.time / 1000,  // ms → seconds
            distance: path.distance,     // already in meters
            geometry,
        };
    } catch (e) {
        console.warn(`[GraphHopper] Failed to get ${profile} route:`, e.message);
        return null;
    }
}

/**
 * Get a walking route using the 'foot' profile.
 */
export async function getWalkingRoute(from, to) {
    return getRoute(from, to, 'foot');
}

/**
 * Get a cycling route using the 'bike' profile.
 */
export async function getCyclingRoute(from, to) {
    return getRoute(from, to, 'bike');
}

// ---------------------------------------------------------------------------
// Public-transit routing  (/route-pt)
// ---------------------------------------------------------------------------

/**
 * Convert a GeoJSON LineString geometry to Leaflet [lat, lon] array.
 */
function geoJsonToLeaflet(geojson) {
    if (!geojson || !geojson.coordinates) return [];
    return geojson.coordinates.map(([lon, lat]) => [lat, lon]);
}

/**
 * Parse an ISO / Java-serialized date string to seconds-since-midnight (local).
 */
function toSecondsSinceMidnight(dateStr) {
    const d = new Date(dateStr);
    return d.getHours() * 3600 + d.getMinutes() * 60 + d.getSeconds();
}

/**
 * Query GraphHopper's public-transit router.
 *
 * @param {{ lat, lon }} from
 * @param {{ lat, lon }} to
 * @param {Date|string}  departureTime  - ISO-8601 or Date object.
 * @param {Object}       [opts]
 * @param {number}       [opts.limitSolutions=5]
 * @param {string}       [opts.accessProfile='foot']  - first-mile profile
 * @param {string}       [opts.egressProfile='foot']  - last-mile profile
 * @returns {Promise<Array<PtRoute>>} Parsed routes ready for the UI.
 *
 * Each PtRoute has the same shape the existing multimodal planner produces:
 *   { type, totalTime, departureTime, arrivalTime, legs[] }
 */
export async function getPtRoutes(from, to, departureTime, opts = {}) {
    const {
        limitSolutions = 5,
        accessProfile = 'foot',
        egressProfile = 'foot',
    } = opts;

    const dtStr = typeof departureTime === 'string'
        ? departureTime
        : departureTime.toISOString();

    const url =
        `${GH_BASE}/route-pt` +
        `?point=${from.lat},${from.lon}` +
        `&point=${to.lat},${to.lon}` +
        `&pt.earliest_departure_time=${encodeURIComponent(dtStr)}` +
        `&pt.access_profile=${encodeURIComponent(accessProfile)}` +
        `&pt.egress_profile=${encodeURIComponent(egressProfile)}` +
        `&pt.limit_solutions=${limitSolutions}` +
        `&locale=en`;

    try {
        const resp = await fetch(url);
        if (!resp.ok) {
            console.warn(`[GraphHopper PT] HTTP ${resp.status}`);
            return [];
        }

        const data = await resp.json();
        if (!data.paths || data.paths.length === 0) return [];

        return data.paths.map(path => parsePtPath(path, egressProfile));
    } catch (e) {
        console.warn('[GraphHopper PT] Failed:', e.message);
        return [];
    }
}

/**
 * Convert one GH PT `path` into the internal route format used by our UI.
 */
function parsePtPath(path, egressProfile) {
    const legs = [];

    for (const ghLeg of (path.legs || [])) {
        if (ghLeg.type === 'pt') {
            // Public-transit leg
            const stops = ghLeg.stops || [];
            const firstStop = stops[0];
            const lastStop  = stops[stops.length - 1];

            const mode = classifyPtMode(ghLeg);
            legs.push({
                mode,
                routeName: buildRouteName(ghLeg, mode),
                routeShortName: ghLeg.route_short_name || '',
                feedId: ghLeg.feed_id || '',
                routeId: ghLeg.route_id,
                tripId: ghLeg.trip_id,
                from: firstStop ? {
                    lat: firstStop.geometry?.coordinates?.[1],
                    lon: firstStop.geometry?.coordinates?.[0],
                    name: firstStop.stop_name,
                } : null,
                to: lastStop ? {
                    lat: lastStop.geometry?.coordinates?.[1],
                    lon: lastStop.geometry?.coordinates?.[0],
                    name: lastStop.stop_name,
                } : null,
                departureTime: toSecondsSinceMidnight(ghLeg.departure_time),
                arrivalTime:   toSecondsSinceMidnight(ghLeg.arrival_time),
                duration: (new Date(ghLeg.arrival_time) - new Date(ghLeg.departure_time)) / 1000,
                geometry: geoJsonToLeaflet(ghLeg.geometry),
                stops: stops.map(s => ({
                    id: s.stop_id,
                    name: s.stop_name,
                    lat: s.geometry?.coordinates?.[1],
                    lon: s.geometry?.coordinates?.[0],
                    arrivalTime: s.arrival_time ? toSecondsSinceMidnight(s.arrival_time) : null,
                    departureTime: s.departure_time ? toSecondsSinceMidnight(s.departure_time) : null,
                })),
            });
        } else {
            // Walking (or cycling) leg
            const mode = (egressProfile === 'bike' || ghLeg._profile === 'bike') ? 'bike' : 'walk';
            const geom = geoJsonToLeaflet(ghLeg.geometry);
            const coords = ghLeg.geometry?.coordinates || [];
            const firstPt = coords[0];
            const lastPt  = coords[coords.length - 1];

            legs.push({
                mode,
                from: firstPt ? { lat: firstPt[1], lon: firstPt[0], name: ghLeg.departure_location || '' } : null,
                to:   lastPt  ? { lat: lastPt[1],  lon: lastPt[0],  name: '' } : null,
                departureTime: toSecondsSinceMidnight(ghLeg.departure_time),
                arrivalTime:   toSecondsSinceMidnight(ghLeg.arrival_time),
                duration: (new Date(ghLeg.arrival_time) - new Date(ghLeg.departure_time)) / 1000,
                distance: ghLeg.distance || 0,
                geometry: geom,
            });
        }
    }

    const depart = legs[0]?.departureTime ?? 0;
    const arrive = legs[legs.length - 1]?.arrivalTime ?? 0;

    // Total time = sum of leg durations (handles midnight crossing correctly)
    const totalTime = legs.reduce((sum, l) => sum + (l.duration || 0), 0);

    // Determine route type from legs composition
    const RAIL_MODES = new Set(['skm', 'pkm', 'polregio']);
    const hasPt   = legs.some(l => l.mode === 'transit' || l.mode === 'tram' || RAIL_MODES.has(l.mode));
    const hasBike = legs.some(l => l.mode === 'bike');
    let type = 'transit';
    if (hasPt && hasBike)  type = 'hybrid';
    else if (hasBike)      type = 'bike';

    return {
        type,
        totalTime,
        departureTime: depart,
        arrivalTime: arrive,
        transfers: path.transfers ?? 0,
        fare: path.fare ?? null,
        legs,
    };
}

/**
 * Classify a PT leg into a display mode and operator name.
 * - gtfs_0 = ZTM Gdańsk (bus route_ids ≥100 / tram route_ids 2-12)
 * - gtfs_1 = SKM (all-stops coastal line)
 * - gtfs_2 + route_id containing '-8P-' = PKM (airport line, operated by PolRegio)
 * - gtfs_2 otherwise = PolRegio (express coastal line, fewer stops)
 * - gtfs_3 = ZKM Gdynia (bus / trolleybus)
 */

// ZTM Gdańsk tram route_ids (route_type 900) — simple numbers 2-12
const ZTM_TRAM_ROUTE_IDS = new Set(['2','3','4','5','6','7','8','9','10','11','12']);

function classifyPtMode(ghLeg) {
    const feedId = (ghLeg.feed_id || '').toLowerCase();
    const id = (ghLeg.route_id || '');

    // SKM feed — all-stops coastal suburban rail
    if (feedId === 'gtfs_1') return 'skm';

    // PolRegio feed — distinguish PKM airport line from express coastal
    if (feedId === 'gtfs_2') {
        // PKM airport line route_ids contain '-8P-' (region code 8P = Pomorskie PKM)
        if (id.includes('-8P-')) return 'pkm';
        return 'polregio';
    }

    // ZTM Gdańsk — trams have route_ids 2-12, buses start at 100+
    if (feedId === 'gtfs_0') {
        if (ZTM_TRAM_ROUTE_IDS.has(id)) return 'tram';
        return 'transit';
    }

    // ZKM Gdynia (gtfs_3) — all buses / trolleybuses
    // Default: bus
    return 'transit';
}

/**
 * Build a human-readable route name for a PT leg.
 */
function buildRouteName(ghLeg, mode) {
    const line = ghLeg.route_short_name || ghLeg.route_id || '';

    switch (mode) {
        case 'skm':      return 'SKM';
        case 'pkm':      return 'PKM';
        case 'polregio': return 'PolRegio';
        default:         return line;
    }
}
