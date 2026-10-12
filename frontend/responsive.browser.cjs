/* Run from repository root. All API responses are fixtures; no real orders/payments. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");
const { chromium, firefox, webkit } = require("playwright");

const root = path.resolve("frontend");
const output = path.resolve("artifacts/brand-responsive");
fs.mkdirSync(output, { recursive: true });
const server = http.createServer((req, res) => {
  const requested = decodeURIComponent(new URL(req.url, "http://localhost").pathname);
  const filename = path.resolve(root, "." + (requested === "/" ? "/index.html" : requested));
  if (!filename.startsWith(root + path.sep)) { res.writeHead(403).end(); return; }
  const types = { ".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".svg": "image/svg+xml", ".webp": "image/webp" };
  fs.readFile(filename, (error, data) => {
    if (error) { res.writeHead(404).end(); return; }
    res.writeHead(200, { "Content-Type": types[path.extname(filename)] || "application/octet-stream" });
    res.end(data);
  });
});
const categories = ["Food & drinks","Fashion","Electronics","Stationery","Beauty","Home essentials","Health & fitness"].map((name, i) => ({ id: "c" + i, name }));
const products = categories.map((category, i) => ({
  id: "p" + i, category_id: category.id,
  name: i === 0 ? "Fresh lunch with a very long product name for wrapping checks" : category.name + " campus favourite",
  description: "Everyday essentials from a local campus shop", images: [],
  listings: [{ retailer_product_id: "l" + i, retailer_name: "Makerere community shop with a long business name", price_ugx: 12500 + i * 1000, original_price_ugx: 18000, discount_percent: 15, stock_available: 12 }]
}));
const point = { id: "d1", name: "Makerere main campus delivery destination with long directions", latitude: 0.335, longitude: 32.57, is_private: false, directions: "Meet at the entrance" };
const cart = { subtotal_ugx: 25000, items: [{ id: "i1", product_name: products[0].name, retailer_name: "Makerere community shop with a long business name", unit_price_ugx: 12500, quantity: 2, line_total_ugx: 25000 }] };

async function noOverflow(page, label, selector) {
  const result = await page.evaluate(selector => {
    const element = selector ? document.querySelector(selector) : document.documentElement;
    const bounds = element.getBoundingClientRect();
    const offenders = [...element.querySelectorAll("*")].filter(child => child.getClientRects().length && child.getBoundingClientRect().right > bounds.right + 2).slice(0, 6).map(child => child.tagName + "#" + child.id + "." + child.className);
    const scrollOffenders = [...element.querySelectorAll("*")].filter(child => child.getClientRects().length && child.scrollWidth > child.clientWidth + 2).slice(0, 10).map(child => [child.tagName, child.id, child.className, child.clientWidth, child.scrollWidth]);
    return { width: element.clientWidth, scroll: element.scrollWidth, offenders, scrollOffenders };
  }, selector);
  assert.ok(result.scroll <= result.width + 2, label + " overflows: " + JSON.stringify(result));
}
async function screenshot(page, name) {
  await page.screenshot({ path: path.join(output, name + ".png"), fullPage: process.env.WEWE_TEST_PREVIEW !== "viewport" });
}
async function runCase(browser, engine, width, height = 900) {
  const context = await browser.newContext({ viewport: { width, height }, reducedMotion: "reduce" });
  const page = await context.newPage();
  const errors = [];
  const calls = [];
  let failCatalog = false;
  page.on("pageerror", error => errors.push(error.message));
  await page.addInitScript(() => { window.WEWE_API_BASE = "/api/v1"; });
  await page.route("**/*", async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.pathname.startsWith("/api/v1/")) {
      const endpoint = url.pathname.slice(7);
      let body;
      if (request.postData()) body = JSON.parse(request.postData());
      calls.push({ endpoint, method: request.method(), body, headers: request.headers() });
      let response = [];
      let status = 200;
      if (endpoint === "/products") {
        if (failCatalog) { response = { detail: "Catalog temporarily unavailable" }; status = 503; }
        else response = products;
      } else if (endpoint === "/categories") response = categories;
      else if (endpoint === "/retailers") response = [{ id: "r1", slug: "campus-shop", business_name: "Campus community shop", product_count: 7 }];
      else if (endpoint === "/auth/me") response = { id: "u1", name: "Campus shopper", role: "CUSTOMER", email: "shopper@example.com" };
      else if (endpoint === "/cart" || endpoint.startsWith("/cart/items")) response = cart;
      else if (endpoint === "/users/me/profile") response = { preferred_delivery_point_id: "d1" };
      else if (endpoint.includes("/delivery-points")) response = [point];
      else if (endpoint === "/locations/campuses") response = [{ id: "campus1", slug: "main-campus" }];
      else if (endpoint === "/locations/pickup-points") response = [{ id: "pickup1", name: "Campus pickup desk" }];
      else if (endpoint === "/orders/delivery-quote") response = {
        subtotal_ugx: 25000, delivery_fee_ugx: body.delivery_method === "PICKUP" ? 0 : 3500,
        total_ugx: body.delivery_method === "PICKUP" ? 25000 : 28500,
        gross_delivery_fee_ugx: 3500, multi_retailer_discount_ugx: 0, routing_provider: "openrouteservice",
        fulfillments: body.delivery_method === "PICKUP" ? [] : [{ retailer_name: "Campus shop", route_distance_km: 2.4, delivery_fee_ugx: 3500 }]
      };
      else if (endpoint === "/orders" && request.method() === "POST") response = { id: "order1", order_number: "WEWE-TEST-001", subtotal_ugx: 25000, delivery_fee_ugx: 3500, total_ugx: 28500, status: "PENDING", payment_status: "PENDING" };
      else if (endpoint.endsWith("/payments")) response = { id: "payment1", status: "PENDING" };
      else if (endpoint === "/payments/payment1") response = { id: "payment1", status: "SUCCESSFUL" };
      return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(response) });
    }
    // Exercise the map-unavailable path deterministically; location selection/quotes still work.
    if (url.hostname === "cdn.jsdelivr.net" || url.hostname === "unpkg.com") return route.abort();
    // Keep layout tests deterministic/offline; photography loads normally in the product.
    if (url.hostname === "images.unsplash.com") {
      if (process.env.WEWE_TEST_PHOTOS === "live") return route.continue();
      return route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="850" height="1050"><rect width="850" height="1050" fill="#8a72aa"/><circle cx="425" cy="430" r="250" fill="#d5c1eb"/></svg>' });
    }
    if (url.hostname === "fonts.googleapis.com" || url.hostname === "fonts.gstatic.com") {
      return process.env.WEWE_TEST_PHOTOS === "live" ? route.continue() : route.abort();
    }
    if (url.origin !== base) throw new Error("Unexpected external request: " + url.origin);
    return route.continue();
  });
  try {
    await page.goto(base);
    await page.locator("#productGrid .product-card").first().waitFor();
    await noOverflow(page, engine + " homepage " + width);
    assert.equal(await page.locator(".brand-logo").count(), 3);
    await page.locator(".brand-logo").evaluateAll(images => Promise.all(images.map(image => image.decode())));
    const logoStates = await page.locator(".brand-logo").evaluateAll(images => images.map(image => ({ source: image.getAttribute("src"), complete: image.complete, width: image.naturalWidth, height: image.naturalHeight })));
    assert.ok(logoStates.every(image => image.complete && image.width > 0), "All SVG logos load: " + JSON.stringify(logoStates));
    const logo = await page.locator("#topbar .brand-logo").boundingBox();
    assert.ok(Math.abs(logo.width / logo.height - 337 / 80) < 0.02, "Logo aspect ratio is preserved");
    if (process.env.WEWE_TEST_PHOTOS === "live" && engine === "chromium") await screenshot(page, engine + "-" + width + "-homepage");
    await page.locator("#searchInput").fill("no-such-product");
    await page.locator("#productGrid .empty-state").waitFor();
    await noOverflow(page, "Empty catalog " + width);
    await page.locator('[data-action="clear-search"]').click();
    await page.locator("#productGrid .product-card").first().waitFor();
    await page.locator('#sortFilter').selectOption("price-high");
    await page.locator("#accountButton").click();
    await page.locator(".auth-form").waitFor();
    await noOverflow(page, "Auth " + width, "#modalContent");
    assert.equal(await page.locator("#topbar").evaluate(element => element.inert), true);
    assert.ok(await page.locator("#modalContent").evaluate(element => element.contains(document.activeElement)), "Dialog takes focus");
    await page.locator("#modalContent .text-link").last().focus();
    await page.keyboard.press("Tab");
    assert.ok(await page.locator(".close-modal").evaluate(element => element === document.activeElement), "Dialog traps Tab");
    if (engine === "chromium" && [320, 768, 1440].includes(width)) await screenshot(page, engine + "-" + width + "-auth");
    await page.keyboard.press("Escape");
    assert.ok(await page.locator("#accountButton").evaluate(element => element === document.activeElement), "Dialog restores focus");
    await page.evaluate(() => { localStorage.setItem("wewe_access_token", "fixture-token"); });
    await page.reload();
    await page.getByRole("button", { name: "My account", exact: true }).waitFor();
    // Wait for the customer state requests as well as the account label.
    await page.waitForFunction(() => document.querySelector("#cartCount").textContent === "2");
    await page.locator("#cartButton").click();
    await page.locator("#cartContents .cart-line").waitFor();
    await noOverflow(page, "Basket " + width, "#modalContent");
    await page.locator('[data-action="cart-quantity"][data-quantity="3"]').click();
    await page.locator("#cartContents .cart-line").waitFor();
    if (engine === "chromium" && [320, 768, 1440].includes(width)) await screenshot(page, engine + "-" + width + "-basket");
    await page.locator('[data-action="checkout"]').click();
    await page.locator('form[data-form="checkout"]').waitFor();
    await page.locator("#checkoutQuote").getByText("UGX 28,500", { exact: true }).waitFor();
    await noOverflow(page, "Checkout " + width, "#modalContent");
    assert.equal(await page.locator('[name="payment_method"]').count(), 2, "Two online payment methods");
    assert.ok(calls.filter(call => call.endpoint === "/orders/delivery-quote").every(call => !("route_distance_km" in call.body) && !("distance_km" in call.body)), "Distance remains server-authoritative");
    await page.locator('[name="delivery_method"]').selectOption("PICKUP");
    await page.locator("#checkoutQuote").getByText("UGX 25,000", { exact: true }).last().waitFor();
    await page.locator('[name="delivery_method"]').selectOption("DELIVERY");
    await page.locator("#checkoutQuote").getByText("UGX 28,500", { exact: true }).waitFor();
    if (engine === "chromium" && [320, 768, 1440].includes(width)) await screenshot(page, engine + "-" + width + "-checkout");
    // Verify payment payload contracts against fixture endpoints, never the sandbox/provider.
    const paymentMethod = width <= 540 ? "AIRTEL_MONEY" : "MTN_MOMO";
    await page.locator('[name="payment_method"][value="' + paymentMethod + '"]').check();
    await page.locator('[name="phone"]').fill("0700000000");
    await page.locator('form[data-form="checkout"] > .button-primary').click();
    await page.getByRole("heading", { name: "WEWE-TEST-001" }).waitFor();
    const payment = calls.find(call => call.endpoint === "/orders/order1/payments");
    assert.equal(payment.body.method, paymentMethod);
    assert.equal(payment.body.phone, "+256700000000");
    assert.ok(payment.headers["idempotency-key"], "Payment retains idempotency");
    const order = calls.find(call => call.endpoint === "/orders" && call.method === "POST");
    assert.deepEqual(order.body, { delivery_method: "DELIVERY", delivery_point_id: "d1" });
    assert.ok(order.headers["idempotency-key"], "Order retains idempotency");
    await page.keyboard.press("Escape");
    await page.locator("#accountButton").click();
    await page.locator("#dashboardContent .workspace-intro").waitFor();
    await noOverflow(page, "Customer workspace " + width);
    if (width <= 780) assert.equal(await page.locator(".mobile-store-nav").isVisible(), false);
    await page.getByRole("button", { name: "Back to shop", exact: true }).click();
    await page.locator("#storefront").waitFor();
    if (process.env.WEWE_TEST_PHOTOS !== "live" && engine === "chromium" && [320, 390, 768, 1024, 1440].includes(width)) await screenshot(page, engine + "-" + width + "-homepage");
    // Error and retry states preserve interactive controls.
    await page.evaluate(() => localStorage.removeItem("wewe_access_token"));
    failCatalog = true;
    await page.reload();
    await page.locator("#productGrid .api-error").waitFor();
    await noOverflow(page, "Catalog error " + width);
    failCatalog = false;
    await page.locator('[data-action="retry-catalog"]').click();
    await page.locator("#productGrid .product-card").first().waitFor();
    assert.deepEqual(errors, [], "No uncaught browser errors");
    console.log("PASS " + engine + " " + width + "x" + height + ": storefront, SVG, search, auth keyboard, basket, delivery/pickup, payment contract, dashboard, retry");
  } catch (error) {
    await screenshot(page, engine + "-" + width + "-failure");
    throw error;
  } finally {
    await context.close();
  }
}
let base;
(async () => {
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  base = "http://127.0.0.1:" + server.address().port;
  try {
    for (const [name, type, widths] of [
      ["chromium", chromium, [320, 360, 390, 540, 680, 768, 900, 1024, 1280, 1440]],
      ["firefox", firefox, [390, 768, 1440]],
      ["webkit", webkit, [390, 768, 1440]]
    ]) {
      if (process.env.WEWE_TEST_ENGINE && process.env.WEWE_TEST_ENGINE !== name) continue;
      const launchOptions = name === "chromium" && process.env.WEWE_TEST_CHANNEL ? { channel: process.env.WEWE_TEST_CHANNEL } : {};
      const browser = await type.launch(launchOptions);
      try {
        const requestedWidths = process.env.WEWE_TEST_WIDTHS?.split(",").map(Number);
        for (const width of widths.filter(width => !requestedWidths || requestedWidths.includes(width))) await runCase(browser, name, width);
        if (name === "chromium" && !requestedWidths) await runCase(browser, name, 844, 390);
      } finally { await browser.close(); }
    }
  } finally { server.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
