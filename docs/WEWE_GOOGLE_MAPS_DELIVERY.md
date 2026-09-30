# WEWE Google Maps Delivery Setup

WEWE now supports Google Maps as the authoritative delivery-routing provider.
The backend uses Google Routes API for road distance and Google Geocoding only when a stored location does not have coordinates. The frontend uses Maps JavaScript + Places for the interactive delivery map and place search.

## Google Cloud APIs

Enable these APIs in the Google Cloud project used by WEWE:
- Routes API
- Geocoding API
- Maps JavaScript API
- Places API (New)

Google recommends Place IDs for route waypoints when available because they can represent a property's access point more accurately than raw coordinates.

## Server key

Set `GOOGLE_MAPS_API_KEY=...`.

This key is used only by the FastAPI backend. Restrict it to the APIs required by the backend and do not expose it to the browser.

Set `ROUTING_PROVIDER=GOOGLE_MAPS`.

## Browser key

Set `GOOGLE_MAPS_BROWSER_API_KEY=...`.

This key is returned by `/api/v1/locations/maps-config` and loaded by the storefront only when the checkout map is opened. Restrict it by HTTP referrer to the deployed WEWE frontend origin(s) and enable only the browser APIs required by the map/Places UI.

## Delivery flow

1. Customer opens checkout.
2. WEWE loads curated Makerere delivery points, including the nine current Main Campus undergraduate halls and selected nearby hostels.
3. Customer can choose a predefined point, search Google Maps, or explicitly grant browser geolocation for the current location.
4. Google place selections are saved as private delivery points with coordinates and Place IDs.
5. The backend resolves the retailer origin and customer destination.
6. Google Routes API returns the actual driving distance.
7. WEWE's own pricing engine calculates the delivery fee: base UGX 1,500 + UGX 500/km, minimum UGX 2,500, rounded to UGX 500, subject to the 15 km maximum configured in the commerce rules.
8. Multi-retailer carts receive one route and one fee per retailer fulfillment, then the fees are summed.

## Local run

After adding the keys to `backend/.env`, run migrations and start the backend/frontend normally.

The frontend map degrades gracefully when the browser key is not configured, but Google routing requires the server key when `ROUTING_PROVIDER=GOOGLE_MAPS`.