/**
 * Multimodal route planner.
 * Generates route alternatives combining walking, transit, and biking.
 * Uses GraphHopper for street routing (foot/bike) and public-transit routing.
 */

import { runCSA } from './csa.js';
import { findNearbyStops, buildTransferLinks } from './graph.js';
import { haversine, estimateWalkTime, estimateBikeTime } from './geo.js';
import { getStationsNear, getAvailableStationsNear, getStationAvailability } from '../data/mevo.js';
import { getWalkingRoute, getCyclingRoute, getPtRoutes } from './graphhopper.js';
import { loadShapes, getShapeForLeg, shapesLoaded } from '../data/shapes.js';

/**
 * Plan multimodal routes between two points.
 *
 * @param {Object} params
 * @param {{ lat, lon }} params.origin
 * @param {{ lat, lon }} params.destination
 * @param {number} params.departureTimeSec - Seconds since midnight.
 * @param {Object} params.timetable - { stops, connections, stopMap, routeMap }
 * @param {Map} params.transfers - Pre-built transfer links.
 * @returns {Array<Route>} Up to 5 route alternatives, sorted by arrival time.
 */
export async function planRoutes({ origin, destination, departureTimeSec, timetable, transfers, ownBike = false }) {
    const routes = [];

    const directDistance = haversine(origin.lat, origin.lon, destination.lat, destination.lon);

    // Build an ISO departure time string for GH PT queries.
    const now = new Date();
    const todayBase = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const departureDate = new Date(todayBase.getTime() + departureTimeSec * 1000);
    const departureISO = departureDate.toISOString();

    // -----------------------------------------------------------------------
    // 1. Direct walking (if < 2 km)
    // -----------------------------------------------------------------------
    const walkPromise = directDistance < 2000
        ? getWalkingRoute(origin, destination).catch(() => null)
        : Promise.resolve(null);

    // (Direct biking removed — MEVO walk-bike-walk route uses GH bike paths)

    // -----------------------------------------------------------------------
    // 3. GraphHopper PT: transit-only (walk access/egress)
    // -----------------------------------------------------------------------
    const ptPromise = getPtRoutes(origin, destination, departureISO, {
        limitSolutions: 5,
        accessProfile: 'foot',
        egressProfile: 'foot',
    }).catch(() => []);

    // -----------------------------------------------------------------------
    // 4. GraphHopper PT: transit + bike egress (only when "own bike" is enabled)
    // -----------------------------------------------------------------------
    const ptBikePromise = ownBike
        ? getPtRoutes(origin, destination, departureISO, {
            limitSolutions: 3,
            accessProfile: 'foot',
            egressProfile: 'bike',
        }).catch(() => [])
        : Promise.resolve([]);

    // Fire all independent network requests in parallel
    const [walkRoute, ptRoutes, ptBikeRoutes] = await Promise.all([
        walkPromise,
        ptPromise,
        ptBikePromise,
    ]);

    // --- Walking result ---
    if (walkRoute) {
        routes.push({
            type: 'walk',
            totalTime: walkRoute.duration,
            departureTime: departureTimeSec,
            arrivalTime: departureTimeSec + walkRoute.duration,
            legs: [{
                mode: 'walk',
                from: { lat: origin.lat, lon: origin.lon, name: 'Start' },
                to: { lat: destination.lat, lon: destination.lon, name: 'Destination' },
                departureTime: departureTimeSec,
                arrivalTime: departureTimeSec + walkRoute.duration,
                duration: walkRoute.duration,
                distance: walkRoute.distance,
                geometry: walkRoute.geometry,
            }],
        });
    }



    // --- MEVO bike with walk access/egress (if stations nearby) ---
    // UPDATED: Now checks real-time availability and tries multiple stations if needed
    console.log('[Multimodal] Planning routes, fetching MEVO stations...');
    const originBikeStations = await getAvailableStationsNear(origin.lat, origin.lon, 800);
    const destBikeStations = await getAvailableStationsNear(destination.lat, destination.lon, 800);
    
    console.log(`[Multimodal] Found ${originBikeStations.length} MEVO stations near origin, ${destBikeStations.length} near destination`);

    // Try to find a viable route with available stations
    for (let i = 0; i < Math.min(originBikeStations.length, 2); i++) {
        for (let j = 0; j < Math.min(destBikeStations.length, 2); j++) {
            const bikeStn = originBikeStations[i].item;
            const destStn = destBikeStations[j].item;
            const originAvail = originBikeStations[i].availability;
            const destAvail = destBikeStations[j].availability;

            console.log(`[Multimodal] Trying: ${bikeStn.name} (${originAvail.bikesAvailable} bikes) → ${destStn.name} (${destAvail.docksAvailable} docks)`);

            // Skip if origin has no bikes or destination has no docks
            if (originAvail.bikesAvailable < 1 || destAvail.docksAvailable < 1) {
                console.log(`[Multimodal] Skipped: Not enough availability`);
                continue; // Try next station
            }

            const mevoBikeRoute = await getCyclingRoute(bikeStn, destStn).catch(() => null);
            const walkToRoute = await getWalkingRoute(origin, bikeStn).catch(() => null);
            const walkFromRoute = await getWalkingRoute(destStn, destination).catch(() => null);

            const walkToBike = walkToRoute?.duration ?? estimateWalkTime(originBikeStations[i].distance);
            const walkFromBike = walkFromRoute?.duration ?? estimateWalkTime(destBikeStations[j].distance);
            const bikeTime = mevoBikeRoute?.duration ?? estimateBikeTime(haversine(bikeStn.lat, bikeStn.lon, destStn.lat, destStn.lon));
            const totalBikeTime = walkToBike + bikeTime + walkFromBike;

            if (mevoBikeRoute) {
                routes.push({
                    type: 'bike',
                    totalTime: totalBikeTime,
                    departureTime: departureTimeSec,
                    arrivalTime: departureTimeSec + totalBikeTime,
                    // ADD availability metadata
                    mevoMeta: {
                        originStationId: bikeStn.id,
                        originBikesAvailable: originAvail.bikesAvailable,
                        originStationName: bikeStn.name,
                        destStationId: destStn.id,
                        destDocksAvailable: destAvail.docksAvailable,
                        destStationName: destStn.name,
                    },
                    legs: [
                        {
                            mode: 'walk',
                            from: { lat: origin.lat, lon: origin.lon, name: 'Start' },
                            to: { lat: bikeStn.lat, lon: bikeStn.lon, name: `MEVO ${bikeStn.name}` },
                            departureTime: departureTimeSec,
                            arrivalTime: departureTimeSec + walkToBike,
                            duration: walkToBike,
                            distance: walkToRoute?.distance ?? originBikeStations[i].distance,
                            geometry: walkToRoute?.geometry,
                        },
                        {
                            mode: 'bike',
                            from: { lat: bikeStn.lat, lon: bikeStn.lon, name: `MEVO ${bikeStn.name}` },
                            to: { lat: destStn.lat, lon: destStn.lon, name: `MEVO ${destStn.name}` },
                            departureTime: departureTimeSec + walkToBike,
                            arrivalTime: departureTimeSec + walkToBike + bikeTime,
                            duration: bikeTime,
                            distance: mevoBikeRoute.distance,
                            geometry: mevoBikeRoute.geometry,
                        },
                        {
                            mode: 'walk',
                            from: { lat: destStn.lat, lon: destStn.lon, name: `MEVO ${destStn.name}` },
                            to: { lat: destination.lat, lon: destination.lon, name: 'Destination' },
                            departureTime: departureTimeSec + walkToBike + bikeTime,
                            arrivalTime: departureTimeSec + totalBikeTime,
                            duration: walkFromBike,
                            distance: walkFromRoute?.distance ?? destBikeStations[j].distance,
                            geometry: walkFromRoute?.geometry,
                        },
                    ],
                });
                break; // Found viable route, no need to try more destinations
            }
        }
        if (routes.some(r => r.type === 'bike')) break; // If found bike route, stop
    }

    // --- GraphHopper PT transit routes (filter out walk-only results) ---
    const TRANSIT_MODES = new Set(['transit', 'tram', 'skm', 'pkm', 'polregio']);
    for (const ptRoute of ptRoutes) {
        const hasPtLeg = ptRoute.legs?.some(l => TRANSIT_MODES.has(l.mode));
        if (hasPtLeg) routes.push(ptRoute);
    }

    // --- GraphHopper PT transit + bike routes (filter out walk/bike-only results) ---
    for (const ptBikeRoute of ptBikeRoutes) {
        const hasPtLeg = ptBikeRoute.legs?.some(l => TRANSIT_MODES.has(l.mode));
        if (hasPtLeg) {
            ptBikeRoute.type = 'hybrid';
            routes.push(ptBikeRoute);
        }
    }

    // -----------------------------------------------------------------------
    // MEVO + PT hybrid routes
    // For each GH PT route, try replacing walk access/egress with MEVO bike.
    // Generates: walk→MEVO→PT→walk, walk→PT→MEVO→walk, walk→MEVO→PT→MEVO→walk
    // -----------------------------------------------------------------------
    for (const ptRoute of ptRoutes) {
        if (!ptRoute.legs || ptRoute.legs.length === 0) continue;

        // Find the first and last PT (non-walk) legs to get boarding/alighting points
        const firstPtLegIdx = ptRoute.legs.findIndex(l => l.mode !== 'walk' && l.mode !== 'bike');
        const lastPtLegIdx = findLastIndex(ptRoute.legs, l => l.mode !== 'walk' && l.mode !== 'bike');
        if (firstPtLegIdx < 0) continue;

        const firstPtLeg = ptRoute.legs[firstPtLegIdx];
        const lastPtLeg = ptRoute.legs[lastPtLegIdx];
        const ptLegs = ptRoute.legs.slice(firstPtLegIdx, lastPtLegIdx + 1); // all PT+transfer legs

        const boardingPoint = firstPtLeg.from;
        const alightingPoint = lastPtLeg.to;
        if (!boardingPoint || !alightingPoint) continue;

        // Find MEVO stations near boarding and alighting points
        const mevoNearBoarding = getStationsNear(boardingPoint.lat, boardingPoint.lon, 500);
        const mevoNearAlighting = getStationsNear(alightingPoint.lat, alightingPoint.lon, 500);

        // --- Pattern A: walk → MEVO → PT → walk ---
        // Bike from origin-area MEVO to boarding-area MEVO, then PT, then walk
        if (originBikeStations.length > 0 && mevoNearBoarding.length > 0) {
            const originStn = originBikeStations[0].item;
            const boardStn = mevoNearBoarding[0].item;
            // Only if biking to the station is meaningful (>200m)
            const bikeDist = haversine(originStn.lat, originStn.lon, boardStn.lat, boardStn.lon);
            if (bikeDist > 200) {
                const hybrid = await buildMevoPtHybrid({
                    origin, destination, departureTimeSec,
                    mevoAccessStn: originStn, mevoAccessDist: originBikeStations[0].distance,
                    mevoEgressStn: null, mevoEgressDist: 0,
                    boardingPoint, alightingPoint, ptLegs,
                });
                if (hybrid) routes.push(hybrid);
            }
        }

        // --- Pattern B: walk → PT → MEVO → walk ---
        // Walk to PT, then bike from alighting-area MEVO to dest-area MEVO
        if (destBikeStations.length > 0 && mevoNearAlighting.length > 0) {
            const alightStn = mevoNearAlighting[0].item;
            const destStn = destBikeStations[0].item;
            const bikeDist = haversine(alightStn.lat, alightStn.lon, destStn.lat, destStn.lon);
            if (bikeDist > 200) {
                const hybrid = await buildMevoPtHybrid({
                    origin, destination, departureTimeSec,
                    mevoAccessStn: null, mevoAccessDist: 0,
                    mevoEgressStn: destBikeStations[0],
                    mevoEgressAlightStn: alightStn,
                    boardingPoint, alightingPoint, ptLegs,
                });
                if (hybrid) routes.push(hybrid);
            }
        }

        // --- Pattern C: walk → MEVO → PT → MEVO → walk ---
        if (originBikeStations.length > 0 && mevoNearBoarding.length > 0 &&
            destBikeStations.length > 0 && mevoNearAlighting.length > 0) {
            const originStn = originBikeStations[0].item;
            const boardStn = mevoNearBoarding[0].item;
            const alightStn = mevoNearAlighting[0].item;
            const destStn = destBikeStations[0].item;
            const accessDist = haversine(originStn.lat, originStn.lon, boardStn.lat, boardStn.lon);
            const egressDist = haversine(alightStn.lat, alightStn.lon, destStn.lat, destStn.lon);
            if (accessDist > 200 && egressDist > 200) {
                const hybrid = await buildMevoPtHybrid({
                    origin, destination, departureTimeSec,
                    mevoAccessStn: originStn, mevoAccessDist: originBikeStations[0].distance,
                    mevoEgressStn: destBikeStations[0],
                    mevoEgressAlightStn: alightStn,
                    boardingPoint, alightingPoint, ptLegs,
                });
                if (hybrid) routes.push(hybrid);
            }
        }

        break; // Only augment the first PT route to avoid too many combos
    }

    // Sort by arrival time and deduplicate similar routes
    routes.sort((a, b) => a.arrivalTime - b.arrivalTime);

    // Remove duplicates (same arrival within 60s and same number of legs)
    const unique = [];
    for (const r of routes) {
        const isDup = unique.some(u =>
            Math.abs(u.arrivalTime - r.arrivalTime) < 60 &&
            u.legs.length === r.legs.length &&
            u.type === r.type
        );
        if (!isDup) unique.push(r);
    }

    const finalRoutes = unique.slice(0, 7);

    // Enrich walk/bike legs with real GraphHopper geometry (replace straight lines)
    await enrichLegsWithGeometry(finalRoutes);

    return finalRoutes;
}

/**
 * Find the last index matching a predicate.
 */
function findLastIndex(arr, pred) {
    for (let i = arr.length - 1; i >= 0; i--) {
        if (pred(arr[i])) return i;
    }
    return -1;
}

/**
 * Build a MEVO+PT hybrid route.
 * Replaces walk access and/or egress of a PT route with MEVO bike legs.
 *
 * @param {Object} params
 * @param {{ lat, lon }} params.origin
 * @param {{ lat, lon }} params.destination
 * @param {number} params.departureTimeSec
 * @param {Object|null} params.mevoAccessStn - MEVO station near origin (null = walk access)
 * @param {number} params.mevoAccessDist - Walk distance to access MEVO station
 * @param {Object|null} params.mevoEgressStn - { item, distance } near destination (null = walk egress)
 * @param {Object|null} params.mevoEgressAlightStn - MEVO station near alighting point
 * @param {{ lat, lon, name }} params.boardingPoint - PT boarding location
 * @param {{ lat, lon, name }} params.alightingPoint - PT alighting location
 * @param {Array} params.ptLegs - The PT legs to keep in the middle
 * @returns {Object|null} A hybrid route, or null if routing fails.
 */
async function buildMevoPtHybrid({
    origin, destination, departureTimeSec,
    mevoAccessStn, mevoAccessDist,
    mevoEgressStn, mevoEgressAlightStn,
    boardingPoint, alightingPoint, ptLegs,
}) {
    const legs = [];
    let clock = departureTimeSec;

    // --- Access: walk → MEVO → ride to boarding, OR walk to boarding ---
    if (mevoAccessStn) {
        // Walk from origin to MEVO station
        const walkToMevo = await getWalkingRoute(origin, mevoAccessStn).catch(() => null);
        const walkDur = walkToMevo?.duration ?? estimateWalkTime(mevoAccessDist);
        legs.push({
            mode: 'walk',
            from: { lat: origin.lat, lon: origin.lon, name: 'Start' },
            to: { lat: mevoAccessStn.lat, lon: mevoAccessStn.lon, name: `MEVO ${mevoAccessStn.name}` },
            departureTime: clock,
            arrivalTime: clock + walkDur,
            duration: walkDur,
            distance: walkToMevo?.distance ?? mevoAccessDist,
            geometry: walkToMevo?.geometry,
        });
        clock += walkDur;

        // Bike from MEVO to near boarding point — find MEVO station near boarding
        const mevoNearBoard = getStationsNear(boardingPoint.lat, boardingPoint.lon, 500);
        const boardMevoStn = mevoNearBoard.length > 0 ? mevoNearBoard[0].item : null;
        if (boardMevoStn) {
            const bikeRoute = await getCyclingRoute(mevoAccessStn, boardMevoStn).catch(() => null);
            const bikeDur = bikeRoute?.duration ?? estimateBikeTime(
                haversine(mevoAccessStn.lat, mevoAccessStn.lon, boardMevoStn.lat, boardMevoStn.lon)
            );
            legs.push({
                mode: 'bike',
                from: { lat: mevoAccessStn.lat, lon: mevoAccessStn.lon, name: `MEVO ${mevoAccessStn.name}` },
                to: { lat: boardMevoStn.lat, lon: boardMevoStn.lon, name: `MEVO ${boardMevoStn.name}` },
                departureTime: clock,
                arrivalTime: clock + bikeDur,
                duration: bikeDur,
                distance: bikeRoute?.distance ?? haversine(mevoAccessStn.lat, mevoAccessStn.lon, boardMevoStn.lat, boardMevoStn.lon),
                geometry: bikeRoute?.geometry,
            });
            clock += bikeDur;

            // Walk from MEVO drop-off to boarding point
            const walkToBoard = await getWalkingRoute(boardMevoStn, boardingPoint).catch(() => null);
            const walkBoardDur = walkToBoard?.duration ?? estimateWalkTime(
                haversine(boardMevoStn.lat, boardMevoStn.lon, boardingPoint.lat, boardingPoint.lon)
            );
            if (walkBoardDur > 30) { // Only add if > 30s walk
                legs.push({
                    mode: 'walk',
                    from: { lat: boardMevoStn.lat, lon: boardMevoStn.lon, name: `MEVO ${boardMevoStn.name}` },
                    to: { lat: boardingPoint.lat, lon: boardingPoint.lon, name: boardingPoint.name },
                    departureTime: clock,
                    arrivalTime: clock + walkBoardDur,
                    duration: walkBoardDur,
                    distance: walkToBoard?.distance ?? haversine(boardMevoStn.lat, boardMevoStn.lon, boardingPoint.lat, boardingPoint.lon),
                    geometry: walkToBoard?.geometry,
                });
                clock += walkBoardDur;
            }
        } else {
            return null; // No MEVO station near boarding — can't build this hybrid
        }
    } else {
        // Walk access to boarding point
        const walkToBoard = await getWalkingRoute(origin, boardingPoint).catch(() => null);
        const walkDur = walkToBoard?.duration ?? estimateWalkTime(
            haversine(origin.lat, origin.lon, boardingPoint.lat, boardingPoint.lon)
        );
        legs.push({
            mode: 'walk',
            from: { lat: origin.lat, lon: origin.lon, name: 'Start' },
            to: { lat: boardingPoint.lat, lon: boardingPoint.lon, name: boardingPoint.name },
            departureTime: clock,
            arrivalTime: clock + walkDur,
            duration: walkDur,
            distance: walkToBoard?.distance ?? haversine(origin.lat, origin.lon, boardingPoint.lat, boardingPoint.lon),
            geometry: walkToBoard?.geometry,
        });
        clock += walkDur;
    }

    // --- PT legs (use their actual timings) ---
    const ptDepartureTime = ptLegs[0]?.departureTime ?? clock;
    // If we arrive before PT departs, we wait
    const waitTime = Math.max(0, ptDepartureTime - clock);
    clock = ptDepartureTime;

    for (const ptLeg of ptLegs) {
        legs.push({ ...ptLeg }); // Copy PT legs as-is
    }
    clock = ptLegs[ptLegs.length - 1]?.arrivalTime ?? clock;

    // --- Egress: walk from alighting → MEVO → ride → walk to dest, OR walk ---
    if (mevoEgressStn && mevoEgressAlightStn) {
        const destStn = mevoEgressStn.item;

        // Walk from alighting point to MEVO station nearby
        const walkToMevo = await getWalkingRoute(alightingPoint, mevoEgressAlightStn).catch(() => null);
        const walkDur = walkToMevo?.duration ?? estimateWalkTime(
            haversine(alightingPoint.lat, alightingPoint.lon, mevoEgressAlightStn.lat, mevoEgressAlightStn.lon)
        );
        if (walkDur > 30) {
            legs.push({
                mode: 'walk',
                from: { lat: alightingPoint.lat, lon: alightingPoint.lon, name: alightingPoint.name },
                to: { lat: mevoEgressAlightStn.lat, lon: mevoEgressAlightStn.lon, name: `MEVO ${mevoEgressAlightStn.name}` },
                departureTime: clock,
                arrivalTime: clock + walkDur,
                duration: walkDur,
                distance: walkToMevo?.distance ?? haversine(alightingPoint.lat, alightingPoint.lon, mevoEgressAlightStn.lat, mevoEgressAlightStn.lon),
                geometry: walkToMevo?.geometry,
            });
            clock += walkDur;
        }

        // Bike from alighting-area MEVO to dest-area MEVO
        const bikeRoute = await getCyclingRoute(mevoEgressAlightStn, destStn).catch(() => null);
        const bikeDur = bikeRoute?.duration ?? estimateBikeTime(
            haversine(mevoEgressAlightStn.lat, mevoEgressAlightStn.lon, destStn.lat, destStn.lon)
        );
        legs.push({
            mode: 'bike',
            from: { lat: mevoEgressAlightStn.lat, lon: mevoEgressAlightStn.lon, name: `MEVO ${mevoEgressAlightStn.name}` },
            to: { lat: destStn.lat, lon: destStn.lon, name: `MEVO ${destStn.name}` },
            departureTime: clock,
            arrivalTime: clock + bikeDur,
            duration: bikeDur,
            distance: bikeRoute?.distance ?? haversine(mevoEgressAlightStn.lat, mevoEgressAlightStn.lon, destStn.lat, destStn.lon),
            geometry: bikeRoute?.geometry,
        });
        clock += bikeDur;

        // Walk from MEVO to destination
        const walkToDest = await getWalkingRoute(destStn, destination).catch(() => null);
        const walkDestDur = walkToDest?.duration ?? estimateWalkTime(mevoEgressStn.distance);
        legs.push({
            mode: 'walk',
            from: { lat: destStn.lat, lon: destStn.lon, name: `MEVO ${destStn.name}` },
            to: { lat: destination.lat, lon: destination.lon, name: 'Destination' },
            departureTime: clock,
            arrivalTime: clock + walkDestDur,
            duration: walkDestDur,
            distance: walkToDest?.distance ?? mevoEgressStn.distance,
            geometry: walkToDest?.geometry,
        });
        clock += walkDestDur;
    } else {
        // Walk egress from alighting to destination
        const walkToDest = await getWalkingRoute(alightingPoint, destination).catch(() => null);
        const walkDur = walkToDest?.duration ?? estimateWalkTime(
            haversine(alightingPoint.lat, alightingPoint.lon, destination.lat, destination.lon)
        );
        legs.push({
            mode: 'walk',
            from: { lat: alightingPoint.lat, lon: alightingPoint.lon, name: alightingPoint.name },
            to: { lat: destination.lat, lon: destination.lon, name: 'Destination' },
            departureTime: clock,
            arrivalTime: clock + walkDur,
            duration: walkDur,
            distance: walkToDest?.distance ?? haversine(alightingPoint.lat, alightingPoint.lon, destination.lat, destination.lon),
            geometry: walkToDest?.geometry,
        });
        clock += walkDur;
    }

    const totalTime = legs.reduce((sum, l) => sum + (l.duration || 0), 0);

    return {
        type: 'hybrid',
        totalTime,
        departureTime: legs[0].departureTime,
        arrivalTime: legs[legs.length - 1].arrivalTime,
        legs,
    };
}

/**
 * Fetch GraphHopper walking/cycling geometry for all walk and bike legs that
 * don't already have proper geometry (more than just 2 endpoints).
 * Requests are batched in parallel per route to keep latency low.
 */
async function enrichLegsWithGeometry(routes) {
    // Ensure GTFS shapes are loaded (lazy, one-time fetch)
    if (!shapesLoaded()) {
        await loadShapes();
    }

    const tasks = [];
    const PT_MODES = new Set(['transit', 'tram', 'skm', 'pkm', 'polregio']);

    for (const route of routes) {
        for (const leg of route.legs) {
            if (!leg.from || !leg.to) continue;

            // --- PT legs: enrich with GTFS shape geometry ---
            if (PT_MODES.has(leg.mode) && leg.feedId && leg.routeId) {
                const shape = getShapeForLeg(
                    leg.feedId, leg.routeId, leg.from, leg.to
                );
                if (shape && shape.length > 2) {
                    leg.geometry = shape;
                    continue;  // done with this leg
                }
                // else: no shape found → keep whatever geometry we have
            }

            // Skip legs that already have real geometry (>2 points)
            if (leg.geometry && leg.geometry.length > 2) continue;

            if (leg.mode === 'walk') {
                tasks.push(
                    getWalkingRoute(leg.from, leg.to)
                        .then(result => {
                            if (result) {
                                leg.geometry = result.geometry;
                                leg.distance = result.distance;
                                leg.duration = result.duration;
                            }
                        })
                        .catch(() => { /* keep straight-line fallback */ })
                );
            } else if (leg.mode === 'bike' && (!leg.geometry || leg.geometry.length <= 2)) {
                tasks.push(
                    getCyclingRoute(leg.from, leg.to)
                        .then(result => {
                            if (result) {
                                leg.geometry = result.geometry;
                                leg.distance = result.distance;
                                leg.duration = result.duration;
                            }
                        })
                        .catch(() => { /* keep straight-line fallback */ })
                );
            }
        }
    }

    if (tasks.length > 0) {
        await Promise.all(tasks);
    }
}
