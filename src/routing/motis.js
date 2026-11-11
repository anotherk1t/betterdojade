/**
 * MOTIS routing client (skeleton).
 *
 * MOTIS is the chosen routing backend. This module should:
 *  - call /api/v6/plan with a timezone offset;
 *  - map MOTIS itineraries/legs into the internal route model;
 *  - expose a GraphHopper fallback until parity is verified.
 *
 * Spike reports: docs/spikes/motis-full-test.md and docs/spikes/bike-route-quality.md
 */

export const MOTIS_BASE = (import.meta.env.VITE_MOTIS_URL || 'http://localhost:8080').replace(/\/$/, '');

/**
 * Query MOTIS for multimodal routes.
 *
 * @param {{lat:number, lon:number}} from
 * @param {{lat:number, lon:number}} to
 * @param {Date|string} departureTime
 * @param {Object} [opts]
 * @returns {Promise<Array>} internal route objects
 */
export async function getMotisRoutes(from, to, departureTime, opts = {}) {
    // TODO: build /api/v6/plan URL, fetch, parse, map legs.
    // Use maxMatchingDistance=250 for bike/walk queries.
    throw new Error('MOTIS client not implemented yet');
}

/**
 * Map one MOTIS itinerary to the app's route shape.
 * @param {Object} itinerary
 * @returns {Object}
 */
export function mapMotisItinerary(itinerary) {
    // TODO: map legs, modes, times, geometry, stops, route names.
    throw new Error('MOTIS itinerary mapping not implemented yet');
}
