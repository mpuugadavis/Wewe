const fs = require("node:fs");
const path = require("node:path");

const frontendDir = __dirname;
const app = fs.readFileSync(path.join(frontendDir, "app.js"), "utf8");
const media = fs.readFileSync(path.join(frontendDir, "retailer-media.js"), "utf8");
const html = fs.readFileSync(path.join(frontendDir, "index.html"), "utf8");

const required = [
  ["frontend/app.js", app, "window.weweApiFetch = apiFetch;"],
  ["frontend/app.js", app, 'apiFetch("/products?limit=100")'],
  ["frontend/app.js", app, 'apiFetch("/categories")'],
  ["frontend/app.js", app, 'apiFetch("/retailers")'],
  ["frontend/app.js", app, 'apiFetch("/cart")'],
  ["frontend/app.js", app, 'apiFetch("/wishlist")'],
  ["frontend/app.js", app, 'apiFetch("/locations/me/delivery-points")'],
  ["frontend/app.js", app, 'apiFetch("/orders/delivery-quote"'],
  ["frontend/app.js", app, 'apiFetch("/orders"'],
  ["frontend/app.js", app, '/payments'],
  ["frontend/app.js", app, "MTN_MOMO"],
  ["frontend/app.js", app, "AIRTEL_MONEY"],
  ["frontend/app.js", app, "safeImage(value)"],
  ["frontend/retailer-media.js", media, "/retailers/me/products/"],
  ["frontend/retailer-media.js", media, "new FormData()"],
  ["frontend/index.html", html, '<script src="app.js"></script>'],
  ["frontend/index.html", html, '<script src="retailer-media.js"></script>'],
];

for (const [file, content, marker] of required) {
  if (!content.includes(marker)) {
    throw new Error(`${file} is missing required frontend integration marker: ${marker}`);
  }
}

if (media.includes('""" : "&quot;"')) {
  throw new Error("retailer-media.js contains the known malformed HTML-escape mapping.");
}

if (/value=["']CASH["']/i.test(app)) {
  throw new Error("Customer checkout must not expose CASH as a payment method.");
}

const checkoutQuoteBody = app.match(/const payload = {[\s\S]*?};/);
if (checkoutQuoteBody && /route_distance_km|distance_km/i.test(checkoutQuoteBody[0])) {
  throw new Error("Checkout quote requests must not accept a client-supplied route distance.");
}

const checkoutOrderBody = app.match(/const delivery = {[\s\S]*?};/);
if (checkoutOrderBody && /route_distance_km|distance_km/i.test(checkoutOrderBody[0])) {
  throw new Error("Order creation must not accept a client-supplied route distance.");
}

if (/Content-Type["']\s*:\s*["']multipart\/form-data/i.test(media)) {
  throw new Error("Retailer media upload must not manually set multipart Content-Type.");
}

if (!/safeImage\(product\.images\?\.\[0\]\)/.test(app)) {
  throw new Error("Catalog product images must use safeImage() before HTML rendering.");
}

if (!/function checkoutMarkerIcon\(\)/.test(app) || !/L\.divIcon\(/.test(app) || !/icon: checkoutMarkerIcon\(\)/.test(app)) {
  throw new Error("Checkout map markers must use the inline SVG icon instead of external Leaflet marker PNGs.");
}

if (!/function initializeCheckoutMap\(points\)/.test(app)) {
  throw new Error("Checkout must contain the Leaflet map initialization path.");
}

if (!/https:\/\/tile\.openstreetmap\.org\/\{z\}\/\{x\}\/\{y\}\.png/.test(app)) {
  throw new Error("Checkout map must use OpenStreetMap tiles as its primary provider.");
}

if (!/https:\/\/server\.arcgisonline\.com\/ArcGIS\/rest\/services\/World_Street_Map/.test(app)) {
  throw new Error("Checkout map must retain a secondary tile provider.");
}

if (!/\/locations\/map-tile\/\{z\}\/\{x\}\/\{y\}\.png/.test(app)) {
  throw new Error("Checkout map must retain the WEWE tile-relay fallback.");
}

if (!/invalidateSize/.test(app) || !/setView\(defaultCenter, 15\)/.test(app)) {
  throw new Error("Checkout map must handle modal sizing and initialize around Makerere.");
}

if (!/route_distance_km/.test(app) || !/delivery_fee_ugx/.test(app) || !/multi_retailer_discount_ugx/.test(app) || !/gross_delivery_fee_ugx/.test(app)) {
  throw new Error("Checkout must render server-authoritative road distance and delivery fee.");
}

console.log("WEWE checkout map and delivery-quote smoke checks passed.");
