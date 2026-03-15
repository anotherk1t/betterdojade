/**
 * BikeRouter Gdańsk — Main application entry point.
 * Wires together data loading, map, search, routing, and results display.
 */

import './style.css';

import { initMap, setOriginMarker, setDestMarker, drawRoute, clearRouteLines, onMapClick } from './ui/map.js';
import { initLayers, displayStops, displayBikeStations, displayTrainStations, toggleStops, toggleBikeStations, toggleTrainStations, updateVehicles, toggleVehicles } from './ui/layers.js';
import { startPolling, stopPolling } from './data/liveVehicles.js';
import { initSearch, setSearchLoading } from './ui/search.js';
import { initResults, displayResults, storeRouteData, hideResults } from './ui/results.js';

import { fetchTimetable } from './data/ztm.js';
import { loadStations } from './data/mevo.js';
import { loadTrainStations } from './data/trains.js';
import { buildTransferLinks } from './routing/graph.js';
import { planRoutes } from './routing/multimodal.js';

// Application state
let timetable = null;
let transfers = null;
let mevoStations = null;

async function init() {
    // Initialize map
    const map = initMap();
    initLayers(map);

    // Initialize results
    initResults((route) => {
        if (route) {
            drawRoute(route.legs);
            
            // On mobile, collapse sidebar automatically to show the map
            const sidebar = document.getElementById('sidebar');
            if (window.innerWidth <= 640 && sidebar && !sidebar.classList.contains('collapsed')) {
                sidebar.classList.add('collapsed');
            }
        } else {
            clearRouteLines();
        }
    });

    // Initialize search
    initSearch({
        onSearch: handleSearch,
        onMapClick,
        setOriginMarker,
        setDestMarker,
    });

    // Layers panel toggle
    const layersBtn = document.getElementById('layers-toggle-btn');
    const layersContainer = document.getElementById('layer-toggles-container');
    if (layersBtn && layersContainer) {
        layersBtn.addEventListener('click', () => {
            const isHidden = layersContainer.hidden;
            layersContainer.hidden = !isHidden;
            layersBtn.setAttribute('aria-expanded', isHidden ? 'true' : 'false');
        });
    }

    // Layer toggles
    document.getElementById('toggle-stops').addEventListener('change', (e) => {
        toggleStops(e.target.checked);
    });
    document.getElementById('toggle-bikes').addEventListener('change', (e) => {
        toggleBikeStations(e.target.checked);
    });
    document.getElementById('toggle-trains').addEventListener('change', (e) => {
        toggleTrainStations(e.target.checked);
    });
    document.getElementById('toggle-live').addEventListener('change', (e) => {
        if (e.target.checked) {
            toggleVehicles(true);
            startPolling(({ vehicles }) => updateVehicles(vehicles));
        } else {
            stopPolling();
            toggleVehicles(false);
        }
    });

    // Sidebar toggle
    const sidebar = document.getElementById('sidebar');
    const sidebarToggle = document.getElementById('sidebar-toggle');
    sidebarToggle.addEventListener('click', () => {
        sidebar.classList.toggle('collapsed');
    });

    // Load data
    await loadData();
}

async function loadData() {
    const overlay = document.getElementById('loading-overlay');
    const loadingText = document.getElementById('loading-text');
    overlay.hidden = false;

    try {
        // Load MEVO stations
        loadingText.textContent = 'Loading MEVO bike stations...';
        mevoStations = await loadStations();
        displayBikeStations(mevoStations);

        // Load train stations
        loadingText.textContent = 'Loading train stations...';
        const trainStations = await loadTrainStations();
        displayTrainStations(trainStations);

        overlay.hidden = true;
        console.log('[App] Data loaded, ready for routing');
    } catch (error) {
        console.error('[App] Failed to load data:', error);
        loadingText.textContent = `Error loading data: ${error.message}. Please refresh.`;
    }
}

async function handleSearch({ origin, destination, departureTimeSec }) {
    setSearchLoading(true);
    clearRouteLines();

    try {
        const ownBike = document.getElementById('own-bike-toggle')?.checked ?? false;
        const routes = await planRoutes({
            origin,
            destination,
            departureTimeSec,
            ownBike,
        });

        displayResults(routes);
        storeRouteData(routes);

        // Draw first route
        if (routes.length > 0) {
            drawRoute(routes[0].legs);
        }
    } catch (error) {
        console.error('[App] Route search failed:', error);
        displayResults([]);
    } finally {
        setSearchLoading(false);
    }
}

// Boot the app
init().catch(console.error);
