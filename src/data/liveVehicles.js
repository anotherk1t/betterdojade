/**
 * Real-time GPS vehicle positions from ZTM Gdańsk Tristar system.
 *
 * API: https://ckan2.multimediagdansk.pl/gpsPositions?v=2
 * Now using direct URL as CORS is supported.
 *
 * Returns positions for all ZTM vehicles with ~20s cache delay.
 * Polls every 15 seconds when active.
 */

const GPS_URL = 'https://ckan2.multimediagdansk.pl/gpsPositions?v=2';
const POLL_INTERVAL = 15_000; // 15 seconds

// ZTM Gdańsk tram route short names (lines 2–12)
const TRAM_LINES = new Set(['2','3','4','5','6','7','8','9','10','11','12']);

let pollTimer = null;
let onUpdate = null;

/**
 * Fetch current vehicle positions.
 * @returns {Promise<{lastUpdate: string, vehicles: Array}>}
 */
export async function fetchVehiclePositions() {
    const res = await fetch(GPS_URL);
    if (!res.ok) throw new Error(`GPS API returned ${res.status}`);
    const data = await res.json();

    // Normalize vehicles with a display type
    const vehicles = (data.vehicles || []).map(v => ({
        lat: v.lat,
        lon: v.lon,
        line: v.routeShortName || '',
        headsign: v.headsign || '',
        delay: v.delay ?? null,         // seconds, negative = early
        speed: v.speed ?? 0,            // km/h
        vehicleCode: v.vehicleCode || '',
        direction: v.direction ?? 0,    // compass bearing 0-315
        generated: v.generated || '',
        isTram: TRAM_LINES.has(v.routeShortName || ''),
    }));

    return { lastUpdate: data.lastUpdate, vehicles };
}

/**
 * Start polling for vehicle positions.
 * @param {Function} callback - Called with { lastUpdate, vehicles } on each update
 */
export function startPolling(callback) {
    onUpdate = callback;
    // Fetch immediately, then poll
    fetchAndNotify();
    pollTimer = setInterval(fetchAndNotify, POLL_INTERVAL);
}

/**
 * Stop polling.
 */
export function stopPolling() {
    if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
    }
    onUpdate = null;
}

/**
 * Whether polling is currently active.
 */
export function isPolling() {
    return pollTimer !== null;
}

async function fetchAndNotify() {
    try {
        const data = await fetchVehiclePositions();
        if (onUpdate) onUpdate(data);
    } catch (err) {
        console.warn('[LiveVehicles] Fetch failed:', err.message);
    }
}
