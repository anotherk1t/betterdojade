/**
 * Route results display.
 */

import { formatDuration, formatTime } from '../routing/geo.js';

let activeCardIndex = -1;
let onRouteSelectCallback = null;

/**
 * Initialize results panel.
 * @param {function} onRouteSelect - Called with route object when a card is clicked.
 */
export function initResults(onRouteSelect) {
    onRouteSelectCallback = onRouteSelect;

    document.getElementById('clear-results-btn').addEventListener('click', () => {
        hideResults();
    });
}

/**
 * Display route results.
 * @param {Array} routes - Array of route alternatives.
 */
export function displayResults(routes) {
    const panel = document.getElementById('results-panel');
    const list = document.getElementById('results-list');

    list.innerHTML = '';
    activeCardIndex = -1;

    if (routes.length === 0) {
        list.innerHTML = '<div class="no-results-msg">No routes found. Try a different origin/destination or departure time.</div>';
        panel.hidden = false;
        return;
    }

    routes.forEach((route, index) => {
        const card = createRouteCard(route, index);
        list.appendChild(card);
    });

    panel.hidden = false;

    // Auto-select first route
    if (routes.length > 0) {
        selectRoute(0, routes);
    }
}

/**
 * Hide results panel.
 */
export function hideResults() {
    document.getElementById('results-panel').hidden = true;
    document.getElementById('results-list').innerHTML = '';
    activeCardIndex = -1;
    if (onRouteSelectCallback) onRouteSelectCallback(null);
}

function createRouteCard(route, index) {
    const card = document.createElement('div');
    card.className = 'route-card';
    card.dataset.index = index;

    const modeIcons = {
        walk: '🚶',
        transit: '🚌',
        tram: '🚊',
        skm: '🚆',
        pkm: '🚆',
        polregio: '🚆',
        bike: '🚲',
    };

    const typeLabels = {
        walk: 'Walking',
        bike: 'Cycling',
        transit: 'Transit',
        hybrid: 'Transit + Bike',
    };

    const modeLabels = {
        transit: 'Bus',
        tram: 'Tram',
        skm: 'SKM',
        pkm: 'PKM',
        polregio: 'PolRegio',
    };

    // Header row
    const header = document.createElement('div');
    header.className = 'route-card-header';

    const duration = document.createElement('span');
    duration.className = 'route-duration';
    duration.textContent = formatDuration(route.totalTime);

    const times = document.createElement('span');
    times.className = 'route-times';
    times.textContent = `${formatTime(route.departureTime)} → ${formatTime(route.arrivalTime)}`;

    header.appendChild(duration);
    header.appendChild(times);

    // Legs badges
    const legsRow = document.createElement('div');
    legsRow.className = 'route-legs';

    route.legs.forEach((leg, i) => {
        if (i > 0) {
            const arrow = document.createElement('span');
            arrow.className = 'leg-arrow';
            arrow.textContent = '→';
            legsRow.appendChild(arrow);
        }

        const badge = document.createElement('span');
        badge.className = `leg-badge ${leg.mode}`;

        let label = modeIcons[leg.mode] || '';
        if (['transit','tram','skm','pkm','polregio'].includes(leg.mode)) {
            const mLabel = modeLabels[leg.mode] || '';
            const rName = leg.routeName || '';
            label += ` ${mLabel}${rName && rName !== mLabel ? ' ' + rName : ''}`;
        } else if (leg.mode === 'walk') {
            label += ` ${formatDuration(leg.duration)}`;
        } else if (leg.mode === 'bike') {
            label += ` ${formatDuration(leg.duration)}`;
        }

        badge.textContent = label;
        legsRow.appendChild(badge);
    });

    // Details (shown on active)
    const details = document.createElement('div');
    details.className = 'route-card-details';

    for (const leg of route.legs) {
        const detail = document.createElement('div');
        detail.className = 'leg-detail';

        const timeEl = document.createElement('span');
        timeEl.className = 'leg-time';
        timeEl.textContent = formatTime(leg.departureTime);

        const descEl = document.createElement('span');
        const fromName = leg.from?.name || '';
        const toName = leg.to?.name || '';

        if (leg.mode === 'walk') {
            descEl.textContent = `🚶 Walk ${fromName ? 'from ' + fromName : ''} ${toName ? 'to ' + toName : ''} (${formatDuration(leg.duration)})`;
        } else if (leg.mode === 'bike') {
            descEl.textContent = `🚲 Bike ${fromName ? 'from ' + fromName : ''} ${toName ? 'to ' + toName : ''} (${formatDuration(leg.duration)})`;
        } else {
            const mLabel = modeLabels[leg.mode] || 'Bus';
            const rName = leg.routeName || '';
            const transitDesc = `${mLabel}${rName && rName !== mLabel ? ' ' + rName : ''}`;
            descEl.textContent = `${modeIcons[leg.mode] || '🚌'} ${transitDesc}: ${fromName} → ${toName}`;
        }

        detail.appendChild(timeEl);
        detail.appendChild(descEl);
        details.appendChild(detail);
    }

    card.appendChild(header);
    card.appendChild(legsRow);
    card.appendChild(details);

    card.addEventListener('click', () => {
        selectRoute(index, null);
    });

    return card;
}

function selectRoute(index, routes) {
    const cards = document.querySelectorAll('.route-card');
    cards.forEach((c, i) => {
        c.classList.toggle('active', i === index);
    });

    activeCardIndex = index;

    if (onRouteSelectCallback) {
        // We need to pass the route data — store it on the card
        const card = cards[index];
        if (card && card._routeData) {
            onRouteSelectCallback(card._routeData);
        }
    }
}

/**
 * Store route data on cards for selection.
 */
export function storeRouteData(routes) {
    const cards = document.querySelectorAll('.route-card');
    cards.forEach((card, i) => {
        if (routes[i]) {
            card._routeData = routes[i];
        }
    });
}
