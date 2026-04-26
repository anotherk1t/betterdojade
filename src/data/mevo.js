/**
 * MEVO bike station data provider with GBFS real-time availability.
 * 
 * GBFS (General Bikeshare Feed Specification):
 * - station_information.json: Static station metadata
 * - station_status.json: Real-time availability (bikes, dock capacity)
 * 
 * API endpoint: https://mevo-middleware.fly.dev/gbfs/en/station_status.json
 * Updates every ~30 seconds
 */

import { findNearby } from '../routing/geo.js';

let stations = null;
let availabilityCache = new Map(); // { stationId → { bikesAvailable, docksAvailable, lastUpdate } }
let fetchPromise = null; // Prevent concurrent fetches
const CACHE_TTL_MS = 60000; // 60 seconds

const GBFS_URL = 'https://mevo-middleware.fly.dev/gbfs/en/station_status.json';

/**
 * Load the MEVO station snapshot.
 * @returns {Promise<Array>} Array of { id, name, address, lat, lon, capacity }
 */
export async function loadStations() {
    if (stations) return stations;

    try {
        const { default: data } = await import('./mevo_stations_snapshot.json');

        stations = data.stations.map(s => ({
            id: s.id,
            name: s.name,
            address: s.address || '',
            lat: s.lat,
            lon: s.lon,
            capacity: s.capacity || 0,
            type: 'mevo',
        }));

        console.log(`[MEVO] Loaded ${stations.length} stations`);
        
        // Pre-generate mock availability for all stations
        if (availabilityCache.size === 0) {
            const now = Date.now();
            stations.forEach(station => {
                availabilityCache.set(station.id, {
                    bikesAvailable: Math.random() > 0.4 ? Math.floor(Math.random() * 8) + 2 : 0,
                    docksAvailable: Math.random() > 0.3 ? Math.floor(Math.random() * 10) + 3 : 0,
                    lastUpdate: now,
                    isMockData: true,
                });
            });
            console.log(`[MEVO] Pre-generated mock availability for ${availabilityCache.size} stations`);
        }
        
        return stations;
    } catch (err) {
        console.error('Failed to load MEVO stations from snapshot', err);
        throw err;
    }
}

/**
 * Get all loaded stations.
 */
export function getStations() {
    return stations || [];
}

/**
 * Get stations within a radius of a point.
 * @param {number} lat
 * @param {number} lon
 * @param {number} radiusM - Radius in meters (default 800).
 * @returns {Array<{ item: Station, distance: number }>}
 */
export function getStationsNear(lat, lon, radiusM = 800) {
    if (!stations) return [];
    return findNearby({ lat, lon }, stations, radiusM);
}

/**
 * Fetch real-time availability for all MEVO stations.
 * Caches results for CACHE_TTL_MS.
 * Falls back to pre-generated mock data if GBFS is unavailable.
 * Prevents concurrent fetches with fetchPromise queue.
 */
async function fetchStationAvailability() {
    const now = Date.now();
    
    // Check if cache is fresh
    if (availabilityCache.size > 0) {
        const firstEntry = Array.from(availabilityCache.values())[0];
        if (now - firstEntry.lastUpdate < CACHE_TTL_MS) {
            return availabilityCache;
        }
    }

    // If already fetching, wait for that promise instead of fetching again
    if (fetchPromise) {
        return fetchPromise;
    }

    fetchPromise = (async () => {
        try {
            console.log('[MEVO] Fetching GBFS availability...');
            const response = await fetch(GBFS_URL, {
                method: 'GET',
                headers: {
                    'Accept': 'application/json',
                },
            });

            if (!response.ok) {
                throw new Error(`GBFS HTTP ${response.status}`);
            }

            const data = await response.json();

            // Clear old cache
            availabilityCache.clear();

            // Parse GBFS station_status response
            if (data.data && data.data.stations) {
                data.data.stations.forEach(station => {
                    availabilityCache.set(station.station_id, {
                        bikesAvailable: station.num_bikes_available,
                        docksAvailable: station.num_docks_available,
                        lastUpdate: now,
                    });
                });
            }

            console.log(`[MEVO GBFS] ✅ Updated ${availabilityCache.size} stations`);
        } catch (err) {
            console.warn(`[MEVO GBFS] Fetch failed (${err.message}), using cached mock data`);
            // Cache is already populated with mock data from loadStations
        } finally {
            fetchPromise = null;
        }

        return availabilityCache;
    })();

    return fetchPromise;
}

/**
 * Get availability for a specific station.
 * @param {string} stationId
 * @returns {Promise<{ bikesAvailable, docksAvailable, isAvailable, warning } | null>}
 */
export async function getStationAvailability(stationId) {
    const cache = await fetchStationAvailability();
    const data = cache.get(stationId);

    if (!data) {
        // If no data, generate random mock
        const mockBikes = Math.random() > 0.4 ? Math.floor(Math.random() * 8) + 2 : 0;
        const mockDocks = Math.random() > 0.3 ? Math.floor(Math.random() * 10) + 3 : 0;
        
        return {
            bikesAvailable: mockBikes,
            docksAvailable: mockDocks,
            isAvailable: mockBikes > 0 && mockDocks > 0,
            warning: mockBikes === 0 ? 'No bikes available' : 
                     mockDocks === 0 ? 'No dock space' : null,
            isMockData: true,
        };
    }

    return {
        bikesAvailable: data.bikesAvailable,
        docksAvailable: data.docksAvailable,
        isAvailable: data.bikesAvailable > 0 && data.docksAvailable > 0,
        warning: data.bikesAvailable === 0 ? 'No bikes available' : 
                 data.docksAvailable === 0 ? 'No dock space' : null,
        isMockData: data.isMockData,
    };
}

/**
 * Find alternative bike stations if primary is unavailable.
 * @param {number} lat
 * @param {number} lon
 * @param {number} radiusM
 * @returns {Promise<Array>} Sorted by: available first, then by distance
 */
export async function getAvailableStationsNear(lat, lon, radiusM = 800) {
    console.log(`[MEVO] Checking availability for stations near (${lat.toFixed(4)}, ${lon.toFixed(4)})`);
    
    const nearby = getStationsNear(lat, lon, radiusM);
    console.log(`[MEVO] Found ${nearby.length} nearby stations`);
    
    if (nearby.length === 0) return [];

    // Fetch availability for all nearby stations in parallel
    const withAvailability = await Promise.all(
        nearby.map(async (stn) => ({
            ...stn,
            availability: await getStationAvailability(stn.item.id),
        }))
    );

    // Sort: available first, then by distance
    const sorted = withAvailability.sort((a, b) => {
        const aAvail = a.availability.isAvailable ? 1 : 0;
        const bAvail = b.availability.isAvailable ? 1 : 0;
        if (aAvail !== bAvail) return bAvail - aAvail;
        return a.distance - b.distance;
    });
    
    console.log(`[MEVO] Availability: ${sorted.filter(s => s.availability.isAvailable).length}/${sorted.length} stations available`);
    
    return sorted;
}
