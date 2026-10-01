const fs = require("node:fs");

const app = fs.readFileSync("frontend/app.js", "utf8");
const media = fs.readFileSync("frontend/retailer-media.js", "utf8");
const html = fs.readFileSync("frontend/index.html", "utf8");

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

console.log("WEWE frontend contract and security smoke checks passed.");
