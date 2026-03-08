# JakosDojade

JakosDojade is a public transit and city bike route planning application designed for the Gdańsk region. It integrates public transit networks (ZTM Gdańsk and ZKM Gdynia) and bike station data (MEVO) to provide multi-modal routing capabilities.

## Why?

Most people who have tried using public transit in Gdańsk have experienced the wonderful feeling of arriving at a bus stop, checking the app, and finding out their bus is delayed by 15+ minutes. But hey, good thing the *previous* delayed bus just arrived! 

Coupled with these constant delays and the rising prices of SKM train tickets, MEVO bike sharing is an attractive option. It costs just 30 PLN / month for 60 e-bike minutes a day, compared to a staggering 117 PLN (or 58.5 PLN for students) for a monthly public transit pass.

Of course, bike sharing has its own problems. It is a station-based system, meaning you usually have to walk from the docking station to your final destination. You cannot easily plan this in the official MEVO app — it forces you to visually scan the map, locate your destination, and manually find the nearest station to it. The only workaround right now is juggling an OSM-based map to find the closest station yourself. On top of that, there's the risk that the station you want to depart from is empty, or your destination station is full (incurring an extra fee).

This project was built to solve these personal frustrations with the current state of map and transit applications, specifically tailored for living in Gdańsk:
- **Lack of True Predictability**: While apps like Jakdojade and ZTM data (the one most likely displayed on the stops) show live vehicle locations and delay estimations, their accuracy is often highly questionable. Most importantly, they lack true predictability — if a bus arrives at its terminus 15 minutes late, these apps fail to account for the fact that its subsequent return journey will also be delayed.
- **The MEVO "Last-Mile" Problem**: No existing app natively handles the walking distance between a MEVO station and your final destination.
- **True Multi-Modal Routing**: No apps can successfully combine bike sharing (or using your own bicycle) with public transit. Biking is often the fastest option, but sometimes a transit leg is faster. If the goal is getting from point A to point B as fast as possible, why not automatically combine the best of both?

## Features
- Multi-modal route planning integrating public transit and bike networks.
- Dockerized setup for quick local development.
- Uses GraphHopper and Leaflet for routing and map visualization.

## Roadmap & Planned Features
- **Bug fixing and polishing**: Current project is not really usable, bus/tram numbers are not displayed, the route graph is not properly mapped for pt, etc.
- **Go live**: Get the app running somewhere with a domain name. 
- **Enhanced UI/UX**: Overhauling the user interface for a smoother, more intuitive experience.
- **Tri-City Live Tracking**: Real-time position tracking for public transit vehicles across Gdańsk, Sopot, and Gdynia.
- **Live MEVO Availability**: Real-time validation of bike availability and open docking slots at MEVO stations.
- **Scooter ride sharing support**: Real-time availability of scooters from various operators.
- **Predictive Analytics**: Advanced delay analysis and arrival time prediction for transit services.
- **?Money-Saving Route Finder**: Route optimization to find the cheapest journey path across different operators (ZTM, ZKM, SKM, Polregio) based on current ticket tariffs.
- **?Crowd prediction**: Predict how crowded a bus/tram will be based on historical data and time of day.

## GraphHopper Integration
This application heavily relies on an external [GraphHopper](https://github.com/graphhopper/graphhopper) routing engine to calculate multimodal routes. 
- JakosDojade expects a GraphHopper instance (configured with the `pt` public transit module and Tri-City GTFS data) to be running alongside it.
- **Vite Proxy**: In development mode, Vite automatically proxies all requests made to `/graphhopper/*` directly to `http://host.docker.internal:8989` (or `localhost:8989`), avoiding any CORS issues.
- **Routing Modules**: The logic for interacting with GraphHopper's Route API and Isochrone API is encapsulated in `src/routing/graphhopper.js` and `src/routing/multimodal.js`.

## Prerequisites
- Node.js (v20+)
- Docker & Docker Compose (optional, for containerized development)

## Installation & Setup

### 1. Running with Docker (Recommended)
You can easily spin up the development environment using Docker Compose:
```bash
docker-compose up --build
```
The application will be accessible at `http://localhost:5173`.

### 2. Running locally (without Docker)
1. Install dependencies:
   ```bash
   npm install
   ```
2. Start the development server:
   ```bash
   npm run dev
   ```

## Building for Production
To build the application for production, run:
```bash
npm run build
```
The optimized files will be generated in the `dist` directory.


