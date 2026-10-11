(() => {
  "use strict";

  const API_BASE = document.querySelector('meta[name="wewe-api-base"]')?.content || "http://localhost:8000/api/v1";
  const ACCESS_KEY = "wewe_access_token";
  const REFRESH_KEY = "wewe_refresh_token";
  const $ = (selector, root = document) => root.querySelector(selector);
  // Initialize notification polling state before startup can invoke the polling function.
  let notificationRefreshTimer = null;

  const state = {
    user: null,
    products: [],
    categories: [],
    retailers: [],
    cart: null,
    wishlist: new Set(),
    activeCategory: "all",
    search: "",
    sort: "featured",
    availability: "all",
    dashboardSection: "overview",
    campuses: null,
    checkoutPoints: [],
    checkoutHallKinds: new Map(),
    addressForCheckout: false,
    mapsApiKey: null,
    checkoutMap: null,
    checkoutMarker: null,
    checkoutAccuracyCircle: null,
    checkoutTileLayer: null,
    checkoutAutocomplete: null,
    refreshPromise: null,
    riderLocationWatchId: null,
    riderOfferRefreshTimer: null,
    unreadNotifications: [],
    orderTrackingTimer: null,
    incomeRefreshTimer: null
  };

  class ApiError extends Error {
    constructor(message, status, payload) {
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.payload = payload;
    }
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, character => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;"
    })[character]);
  }

  function safeImage(value) {
    try {
      const raw = String(value || "").trim();
      if (!raw) return "";
      if (raw.startsWith("/api/v1/")) return new URL(raw, API_BASE + "/").href;
      const url = new URL(raw, location.href);
      const isHttps = url.protocol === "https:";
      const isLocalMinio = url.protocol === "http:" &&
        (url.hostname === "localhost" || url.hostname === "127.0.0.1") &&
        url.port === "9000";
      return (isHttps || isLocalMinio) && !url.username && !url.password ? url.href : "";
    } catch {
      return "";
    }
  }


  const CATALOG_FALLBACK_IMAGES = [
    { keys: ["food","snack","meal","chapati","rolex","pizza","chicken","rice","bean","juice","drink","water"], url: "https://images.unsplash.com/photo-1504674900247-0877df9cc836?auto=format&fit=crop&w=900&q=82" },
    { keys: ["shoe","sneaker","sandals","slipper","footwear"], url: "https://images.unsplash.com/photo-1542291026-7eec264c27ff?auto=format&fit=crop&w=900&q=82" },
    { keys: ["shirt","t-shirt","dress","jean","hoodie","clothes","fashion","bag","backpack"], url: "https://images.unsplash.com/photo-1441986300917-64674bd600d8?auto=format&fit=crop&w=900&q=82" },
    { keys: ["phone","laptop","computer","earphone","headphone","charger","electronic"], url: "https://images.unsplash.com/photo-1496181133206-80ce9b88a853?auto=format&fit=crop&w=900&q=82" },
    { keys: ["book","stationery","pen","notebook","paper","school"], url: "https://images.unsplash.com/photo-1456324504439-367cee3b3c32?auto=format&fit=crop&w=900&q=82" },
    { keys: ["beauty","hair","cosmetic","cream","perfume","makeup"], url: "https://images.unsplash.com/photo-1596462502278-27bfdc403348?auto=format&fit=crop&w=900&q=82" },
    { keys: ["home","lamp","mug","bottle","bucket","storage"], url: "https://images.unsplash.com/photo-1556911220-e15b29be8c8f?auto=format&fit=crop&w=900&q=82" }
  ];
  const DEFAULT_CATALOG_IMAGE = "https://images.unsplash.com/photo-1523474253046-8cd2748b5fd2?auto=format&fit=crop&w=900&q=82";

  function catalogFallbackImage(product) {
    const haystack = `${product?.name || ""} ${product?.description || ""} ${product?.category_name || ""}`.toLocaleLowerCase();
    const match = CATALOG_FALLBACK_IMAGES.find(group => group.keys.some(key => haystack.includes(key)));
    return match?.url || DEFAULT_CATALOG_IMAGE;
  }

  function startHeroSlider() {
    const slides = [...document.querySelectorAll(".hero-slide")];
    const dots = [...document.querySelectorAll(".hero-slider-dot")];
    if (slides.length < 2) return;
    let index = 0;
    let timer;
    const show = next => {
      index = (next + slides.length) % slides.length;
      slides.forEach((slide, i) => slide.classList.toggle("active", i === index));
      dots.forEach((dot, i) => {
        dot.classList.toggle("active", i === index);
        dot.setAttribute("aria-current", i === index ? "true" : "false");
      });
    };
    const restart = () => {
      clearInterval(timer);
      timer = setInterval(() => show(index + 1), 5000);
    };
    dots.forEach((dot, i) => dot.addEventListener("click", () => { show(i); restart(); }));
    show(0);
    restart();
  }

  function money(value) {
    return `UGX ${Number(value || 0).toLocaleString("en-UG")}`;
  }

  function normalizeUgandanPaymentPhone(value) {
    let cleaned = String(value || "").trim()
      .replace(/[\s\-()]/g, "");
    if (cleaned.startsWith("00")) cleaned = "+" + cleaned.slice(2);
    else if (cleaned.startsWith("0") && /^\d{10}$/.test(cleaned)) cleaned = "+256" + cleaned.slice(1);
    else if (cleaned.startsWith("256") && /^256\d+$/.test(cleaned)) cleaned = "+" + cleaned;
    if (!/^\+2567\d{8}$/.test(cleaned)) {
      throw new Error("Enter a valid Ugandan mobile number, for example +256700000000.");
    }
    return cleaned;
  }


  function messageFrom(payload, status) {
    const detail = payload?.detail;
    if (typeof detail === "string") return detail;
    if (detail?.message) return detail.message;
    if (Array.isArray(detail)) {
      const messages = detail.map(item => {
        const location = Array.isArray(item?.loc) ? item.loc.join(".") : "";
        const message = item?.msg || item?.message;
        return location && message ? `${location}: ${message}` : message;
      }).filter(Boolean);
      if (messages.length) return messages.join("; ");
    }
    if (payload?.message) return payload.message;
    if (payload?.error?.message) return payload.error.message;
    if (payload?.error?.code) return `Request failed (${status}): ${payload.error.code}`;
    return `Request failed (${status}). Please try again.`;
  }

  function clearPrivateState() {
    stopIncomePolling();
    state.user = null;
    state.cart = null;
    state.wishlist.clear();
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
    resetUserScopedUI();
  }

  function resetUserScopedUI() {
    state.user = null;
    state.cart = null;
    state.wishlist.clear();
    closeModal();
    updateAccountButton();
    $("#dashboard")?.classList.add("hidden");
    $("#storefront")?.classList.remove("hidden");
    $("#footer")?.classList.remove("hidden");
    $("#topbar")?.classList.remove("hidden");
    if ($("#dashNav")) $("#dashNav").replaceChildren();
    if ($("#dashboardContent")) $("#dashboardContent").replaceChildren();
  }

  function saveTokens(tokens) {
    if (!tokens?.access_token || !tokens?.refresh_token) {
      throw new Error("The server did not return a complete session.");
    }
    localStorage.setItem(ACCESS_KEY, tokens.access_token);
    localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
  }

  async function refreshSession() {
    if (state.refreshPromise) return state.refreshPromise;
    const refreshToken = localStorage.getItem(REFRESH_KEY);
    if (!refreshToken) {
      clearPrivateState();
      throw new Error("Your session has expired. Please sign in again.");
    }
    state.refreshPromise = (async () => {
      const response = await fetch(`${API_BASE}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken })
      });
      const payload = response.status === 204 ? null : await response.json().catch(() => null);
      if (!response.ok) throw new ApiError(messageFrom(payload, response.status), response.status, payload);
      saveTokens(payload);
      return payload.access_token;
    })();
    try {
      return await state.refreshPromise;
    } catch (error) {
      clearPrivateState();
      throw error;
    } finally {
      state.refreshPromise = null;
    }
  }

  async function apiFetch(path, options = {}, retry = true) {
    const accessToken = localStorage.getItem(ACCESS_KEY);
    const headers = new Headers(options.headers || {});
    if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
    if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
    let response = await fetch(`${API_BASE}${path}`, { ...options, headers });
    if (response.status === 401 && retry && accessToken && (!path.startsWith("/auth/") || path === "/auth/me")) {
      try {
        await refreshSession();
      } catch (error) {
        showToast(error.message);
        throw error;
      }
      return apiFetch(path, options, false);
    }
    if (response.status === 204) return null;
    const payload = await response.json().catch(() => null);
    if (!response.ok) throw new ApiError(messageFrom(payload, response.status), response.status, payload);
    return payload;
  }

  window.weweApiFetch = apiFetch;

  function showToast(message) {
    const toast = $("#toast");
    if (!toast) return;
    toast.textContent = message;
    toast.classList.add("show");
    clearTimeout(showToast.timer);
    showToast.timer = setTimeout(() => toast.classList.remove("show"), 3600);
  }

  function setModal(content, wide = false) {
    const modal = $("#modalContent");
    modal.classList.toggle("modal-wide", wide);
    modal.innerHTML = content;
    $("#modalBackdrop").classList.add("open");
    document.body.classList.add("modal-open");
  }

  function closeModal() {
    if (state.orderTrackingTimer) clearInterval(state.orderTrackingTimer);
    state.orderTrackingTimer = null;
    $("#modalBackdrop").classList.remove("open");
    document.body.classList.remove("modal-open");
  }

  function statusBadge(status) {
    const label = String(status || "UNKNOWN").replaceAll("_", " ");
    return `<span class="role-pill">${escapeHtml(label)}</span>`;
  }

  function formatDate(value) {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? escapeHtml(value) : date.toLocaleString();
  }

  function updateAccountButton() {
    const button = $("#accountButton");
    if (button) button.textContent = state.user ? "My account" : "Sign in";
  }

  function syncCartBadge() {
    const count = (state.cart?.items || []).reduce((sum, item) => sum + Number(item.quantity || 0), 0);
    const badge = $("#cartCount");
    if (badge) badge.textContent = String(count);
    const mobileBadge = $("#mobileCartCount");
    if (mobileBadge) mobileBadge.textContent = String(count);
  }

  async function loadCatalog() {
    const grid = $("#productGrid");
    grid.innerHTML = '<div class="skeleton-grid" aria-label="Loading products">'+Array.from({length: 8}, () => '<div class="skeleton"></div>').join("")+'</div>';
    $("#categoryList").innerHTML = "";
    $("#sellerRow").innerHTML = "";
    try {
      const [products, categories, retailers] = await Promise.all([
        apiFetch("/products?limit=100"),
        apiFetch("/categories"),
        apiFetch("/retailers")
      ]);
      state.products = products;
      state.categories = categories;
      state.retailers = retailers;
      renderCatalog();
      renderCategories();
      renderRetailers();
    } catch (error) {
      grid.innerHTML = `<div class="api-state api-error"><p>${escapeHtml(error.message)}</p><button class="button-outline" data-action="retry-catalog">Try again</button></div>`;
      $("#categoryList").innerHTML = "";
      $("#sellerRow").innerHTML = "";
    }
  }

  function productListings(product) {
    return (product.listings || []).filter(listing => listing.retailer_product_id);
  }

  function visibleProducts() {
    const query = state.search.toLocaleLowerCase();
    const rows = [];
    for (const product of state.products) {
      if (state.activeCategory !== "all" && product.category_id !== state.activeCategory) continue;
      const matchesText = !query || `${product.name} ${product.description || ""}`.toLocaleLowerCase().includes(query);
      if (!matchesText) continue;
      for (const listing of productListings(product)) {
        if (state.availability === "in-stock" && Number(listing.stock_available) < 1) continue;
        rows.push({ product, listing });
      }
    }
    if (state.sort === "price-low") rows.sort((a, b) => a.listing.price_ugx - b.listing.price_ugx);
    if (state.sort === "price-high") rows.sort((a, b) => b.listing.price_ugx - a.listing.price_ugx);
    return rows;
  }

  function renderCatalog() {
    const rows = visibleProducts();
    const count = $("#productCount");
    if (count) count.textContent = rows.length ? rows.length + " product" + (rows.length === 1 ? "" : "s") + " available" : "";
    $("#productGrid").innerHTML = rows.length ? rows.map(({ product, listing }) => {
      const image = safeImage(product.images?.[0]) || catalogFallbackImage(product);
      const productId = escapeHtml(product.id);
      const listingId = escapeHtml(listing.retailer_product_id);
      const wished = state.wishlist.has(product.id);
      const stock = Number(listing.stock_available || 0);
      const stockLabel = stock < 1 ? "Out of stock" : stock <= 5 ? stock + " left" : "In stock";
      const stockClass = stock < 1 ? "out" : stock <= 5 ? "low" : "";
      return `<article class="product-card" data-product-id="${productId}" data-listing-id="${listingId}">
        <div class="product-image"><img class="catalog-image-fallback" src="${escapeHtml(image)}" alt="${escapeHtml(product.name)}" loading="lazy" onerror="this.onerror=null;this.src='${DEFAULT_CATALOG_IMAGE}'">
          <button class="wish-button ${wished ? "is-wished" : ""}" aria-label="${wished ? "Remove from" : "Add to"} wishlist" data-action="toggle-wishlist" data-product-id="${productId}">${wished ? "♥" : "♡"}</button>
          <button class="quick-add" data-action="add-cart" data-listing-id="${listingId}" ${stock < 1 ? "disabled" : ""}>${stock < 1 ? "Unavailable" : "Quick add"}</button>
        </div>
        <div class="product-info">
          <div class="product-seller">${escapeHtml(listing.retailer_name || "Campus retailer")}</div>
          <button class="product-title" data-action="product-details" data-product-id="${productId}">${escapeHtml(product.name)}</button>
          <div class="product-meta"><span class="stock-pill ${stockClass}">${stockLabel}</span><span class="muted">Campus listing</span></div>
          <div class="product-price-row"><div class="product-price">${priceMarkup(listing)}</div><button class="add-button" data-action="add-cart" data-listing-id="${listingId}" ${stock < 1 ? "disabled" : ""}>${stock < 1 ? "Unavailable" : "Add to cart"}</button></div>
        </div>
      </article>`;
    }).join("") : '<div class="empty-state"><div class="empty-icon">⌕</div><h3>No products found</h3><p>Try another search, category or availability filter.</p><button class="button-outline" data-action="clear-search">Clear filters</button></div>';
    syncCartBadge();
  }

  function renderCategories() {
    const categories = [{ id: "all", name: "Everything" }, ...state.categories];
    const categoryIcon = name => {
      const key = String(name || "").toLowerCase();
      if (key === "everything" || key === "all") return "◈";
      if (/food|grocer|grocery|meal|restaurant|bakery|snack|drink|beverage/.test(key)) return "🍴";
      if (/fashion|cloth|wear|shoe|footwear|bag|accessor/.test(key)) return "👟";
      if (/electronic|phone|computer|laptop|tech|gadget/.test(key)) return "⌁";
      if (/station|book|school|academic|study|office/.test(key)) return "✎";
      if (/beauty|cosmetic|hair|skin/.test(key)) return "✦";
      if (/home|house|furniture|decor|kitchen/.test(key)) return "⌂";
      if (/health|care|pharmacy|fitness|sport/.test(key)) return "✚";
      if (/service|repair|delivery|other/.test(key)) return "⚙";
      return "◇";
    };
    $("#categoryList").innerHTML = categories.map(category => `<button class="category ${state.activeCategory === category.id ? "active" : ""}" data-action="category" data-category-id="${escapeHtml(category.id)}" aria-label="Browse ${escapeHtml(category.name)}"><span class="cat-icon" aria-hidden="true">${categoryIcon(category.name)}</span><span>${escapeHtml(category.name)}</span></button>`).join("");
  }

  function renderRetailers() {
    $("#sellerRow").innerHTML = state.retailers.length ? state.retailers.map(retailer => {
      const image = safeImage(retailer.profile_image_url || retailer.logo_url || retailer.image_url);
      return `<button class="seller-card" data-action="retailer-details" data-retailer-slug="${escapeHtml(retailer.slug)}"><span class="seller-avatar">${image ? `<img src="${escapeHtml(image)}" alt="">` : escapeHtml((retailer.business_name || "?").slice(0, 1))}</span><span><b>${escapeHtml(retailer.business_name)}</b><small>${escapeHtml(retailer.product_count ?? "Campus retailer")}</small></span></button>`;
    }).join("") : '<p class="api-state">No retailers are listed right now.</p>';
  }

  async function ensureCart() {
    state.cart = await apiFetch("/cart");
    syncCartBadge();
    return state.cart;
  }

  function showCart() {
    if (!state.user) return showAuth();
    if (state.user.role !== "CUSTOMER") return showToast("Shopping cart is available to customer accounts.");
    setModal('<div class="modal-head"><div><div class="section-kicker">Your basket</div><h2>Shopping cart</h2></div><button class="close-modal" data-action="close-modal" aria-label="Close">×</button></div><div id="cartContents"><p class="api-state">Loading your cart…</p></div>', true);
    renderCartContents().catch(error => {
      $("#cartContents").innerHTML = `<p class="api-state api-error">${escapeHtml(error.message)}</p>`;
    });
  }

  async function renderCartContents() {
    const cart = await ensureCart();
    const items = cart.items || [];
    $("#cartContents").innerHTML = items.length ? `<div class="cart-lines">${items.map(item => `<div class="cart-line">
      <div><b>${escapeHtml(item.product_name)}</b><small>${escapeHtml(item.retailer_name)} · ${money(item.unit_price_ugx)} each</small></div>
      <div class="cart-line-controls"><button data-action="cart-quantity" data-item-id="${escapeHtml(item.id)}" data-quantity="${Number(item.quantity) - 1}" ${Number(item.quantity) <= 1 ? "disabled" : ""} aria-label="Decrease quantity">−</button><span>${Number(item.quantity)}</span><button data-action="cart-quantity" data-item-id="${escapeHtml(item.id)}" data-quantity="${Number(item.quantity) + 1}" aria-label="Increase quantity">+</button><button data-action="remove-cart" data-item-id="${escapeHtml(item.id)}" aria-label="Remove item">Remove</button></div>
      <b>${money(item.line_total_ugx)}</b></div>`).join("")}</div><div class="cart-summary"><p>Subtotal <b>${money(cart.subtotal_ugx)}</b></p><p>Delivery fee <span>Calculated securely at checkout</span></p><button class="button-primary" data-action="checkout">Continue to checkout</button></div>` : '<div class="api-state"><p>Your cart is empty.</p><button class="button-outline" data-action="close-modal">Continue shopping</button></div>';
  }

  async function addToCart(listingId, quantity = 1) {
    if (!state.user) return showAuth();
    if (state.user.role !== "CUSTOMER") return showToast("Sign in with a customer account to add items.");
    const safeQuantity = Math.max(1, Math.min(100, Number(quantity) || 1));
    state.cart = await apiFetch("/cart/items", { method: "POST", body: JSON.stringify({ retailer_product_id: listingId, quantity: safeQuantity }) });
    syncCartBadge();
    showToast(safeQuantity > 1 ? `${safeQuantity} items added to your cart.` : "Added to your cart.");
  }

  async function cartQuantity(itemId, quantity) {
    if (quantity < 1) return;
    state.cart = await apiFetch(`/cart/items/${encodeURIComponent(itemId)}`, { method: "PATCH", body: JSON.stringify({ quantity }) });
    await renderCartContents();
    syncCartBadge();
  }

  async function removeCartItem(itemId) {
    await apiFetch(`/cart/items/${encodeURIComponent(itemId)}`, { method: "DELETE" });
    await renderCartContents();
    await ensureCart();
  }

  function passwordField(name, label, autocomplete, minlength = "1") {
    return '<label class="field password-field">' +
      escapeHtml(label) +
      '<span class="password-input-wrap"><input name="' + escapeHtml(name) + '" type="password" required minlength="' + minlength + '" autocomplete="' + escapeHtml(autocomplete) + '"><button type="button" class="password-toggle" data-action="toggle-password" aria-label="Show password" title="Show password">◉</button></span>' +
      '</label>';
  }

  function togglePassword(button) {
    const input = button.closest(".password-input-wrap")?.querySelector("input");
    if (!input) return;
    const visible = input.type === "text";
    input.type = visible ? "password" : "text";
    button.textContent = visible ? "◉" : "○";
    button.setAttribute("aria-label", visible ? "Show password" : "Hide password");
    button.title = visible ? "Show password" : "Hide password";
  }

  function priceMarkup(listing) {
    const current = Number(listing.price_ugx || 0);
    const original = Number(listing.original_price_ugx || 0);
    const discount = Number(listing.discount_percent || 0);
    if (original > current && discount > 0) {
      return '<span class="price-current">' + money(current) + '</span><span class="price-old">' + money(original) + '</span><span class="discount-badge">-' + discount + '%</span>';
    }
    return '<span class="price-current">' + money(current) + '</span>';
  }

  function showAuth(register = false, role = "CUSTOMER") {
    const title = register ? "Create your WEWE account" : "Welcome back";
    setModal(`<div class="modal-head"><div><div class="section-kicker">WEWE account</div><h2>${title}</h2></div><button class="close-modal" data-action="close-modal" aria-label="Close">×</button></div>
      <form data-form="${register ? "register" : "login"}" class="api-form">
        ${register ? '<label class="field">Full name<input name="name" required minlength="2" autocomplete="name"></label>' : ""}
        ${register ? `<label class="field">Account type<select name="role"><option value="CUSTOMER" selected>Customer</option><option value="RETAILER">Retailer</option></select></label>` : ""}
        <label class="field">Email or phone<input name="email" type="text" required autocomplete="username"></label>
        ${register ? '<label class="field">Phone<input name="phone" type="tel" autocomplete="tel"></label><label class="field hidden" data-register-business>Business name<input name="business_name" maxlength="180"></label><label class="field hidden" data-register-transport>Transport mode<input name="transport_mode" maxlength="40"></label>' : ""}
        ${passwordField("password", register ? "Create password" : "Password", register ? "new-password" : "current-password", register ? "12" : "1")}
        <p class="form-message" aria-live="polite"></p><button class="button-primary" type="submit">${register ? "Create account" : "Sign in"}</button>
      </form><button class="text-link" data-action="${register ? "show-login" : "show-register"}">${register ? "Already registered? Sign in" : "New to WEWE? Create an account"}</button>`, false);
    if (register) updateRegistrationFields();
  }

  function showRiderApplication() {
    setModal(`<div class="modal-head"><div><div class="section-kicker">WEWE delivery partner</div><h2>Become a WEWE rider</h2></div><button class="close-modal" data-action="close-modal" aria-label="Close">×</button></div>
      <div class="rider-apply-intro"><div class="rider-apply-icon">🚴</div><div><p>Earn by helping students get their orders from campus retailers to their chosen delivery points.</p><small>Your application creates a delivery-agent account for review. You can only receive delivery work after WEWE verification.</small></div></div>
      <form data-form="rider-application" class="api-form">
        <label class="field">Full name<input name="name" required minlength="2" autocomplete="name"></label>
        <label class="field">Email or phone<input name="email" required autocomplete="username"></label>
        <label class="field">Phone number<input name="phone" required type="tel" autocomplete="tel" placeholder="+256…"></label>
        <label class="field">Transport mode<select name="transport_mode" required><option value="">Choose transport</option><option>Walking</option><option>Bicycle</option><option>Motorcycle</option><option>Car</option><option>Other</option></select></label>
        ${passwordField("password", "Create password", "new-password", "12")}
        <p class="form-message" aria-live="polite"></p><button class="button-primary" type="submit">Submit rider application</button>
      </form>
      <p class="rider-apply-note">Already a delivery agent? <button class="text-link" data-action="show-login">Sign in instead</button></p>`, true);
  }

  async function submitRiderApplication(form) {
    const body = Object.fromEntries(new FormData(form));
    body.role = "DELIVERY_AGENT";
    const response = await apiFetch("/auth/register", { method: "POST", body: JSON.stringify(body) }, false);
    $( "#modalContent" ).innerHTML = `<div class="modal-head"><div><div class="section-kicker">Application received</div><h2>Thanks, ${escapeHtml(body.name)}.</h2></div><button class="close-modal" data-action="close-modal">×</button></div><div class="rider-apply-success"><div>✓</div><h3>Your rider account is ready for review.</h3><p>${escapeHtml(response?.message || "Sign in once your delivery-agent account has been verified by WEWE.")}</p><button class="button-primary" data-action="show-login">Go to sign in</button></div>`;
  }

  async function login(form) {
    const body = Object.fromEntries(new FormData(form));
    body.identifier = body.email;
    delete body.email;
    const tokens = await apiFetch("/auth/login", { method: "POST", body: JSON.stringify(body) }, false);
    saveTokens(tokens);
    await loadCurrentUser();
    closeModal();
    showToast(`Signed in as ${state.user.name}.`);
  }

  async function register(form) {
    const body = Object.fromEntries(new FormData(form));
    if (!body.phone) delete body.phone;
    if (!body.business_name) delete body.business_name;
    if (!body.transport_mode) delete body.transport_mode;
    const response = await apiFetch("/auth/register", { method: "POST", body: JSON.stringify(body) }, false);
    showAuth();
    showToast(response?.message || "Account created. Sign in to continue.");
  }

  function updateRegistrationFields() {
    const form = $('form[data-form="register"]');
    if (!form) return;
    const role = form.elements.role.value;
    const phone = form.elements.phone;
    const business = $("[data-register-business]", form);
    const transport = $("[data-register-transport]", form);
    phone.required = role !== "CUSTOMER";
    business.classList.toggle("hidden", role !== "RETAILER");
    $('input[name="business_name"]', business).required = role === "RETAILER";
    transport.classList.toggle("hidden", role !== "DELIVERY_AGENT");
  }

  startNotificationPolling();
  async function loadCurrentUser() {
    state.user = await apiFetch("/auth/me");
    updateAccountButton();
    if (state.user.role === "CUSTOMER") {
      const [cart, wishlist, profile, points] = await Promise.all([
        apiFetch("/cart"), apiFetch("/wishlist"), apiFetch("/users/me/profile"), apiFetch("/locations/me/delivery-points")
      ]);
      state.cart = cart;
      state.wishlist = new Set((wishlist || []).map(item => item.product_id || item.id));
      const selectedPoint = points.find(point => point.id === profile.preferred_delivery_point_id);
      const location = $("#locationButton");
      if (location) location.innerHTML = `<span>⌖</span><span><small>Delivering to</small><br>${selectedPoint ? escapeHtml(selectedPoint.name) : "Choose at checkout"} ▾</span>`;
      syncCartBadge();
      renderCatalog();
    } else {
      state.cart = null;
      state.wishlist.clear();
      const location = $("#locationButton");
      if (location) location.innerHTML = '<span>⌖</span><span><small>Delivery location</small><br>Choose at checkout ▾</span>';
    }
  }

  async function signOut() {
    stopNotificationPolling();
    stopRiderLocationTracking();
    syncRiderOfferPolling();
    const refreshToken = localStorage.getItem(REFRESH_KEY);
    try {
      if (refreshToken) await apiFetch("/auth/logout", { method: "POST", body: JSON.stringify({ refresh_token: refreshToken }) });
    } finally {
      clearPrivateState();
      closeModal();
      showDashboard(false);
      showToast("You have signed out.");
      renderCatalog();
    }
  }

  async function toggleWishlist(productId) {
    if (!state.user) return showAuth();
    if (state.user.role !== "CUSTOMER") return showToast("Wishlist is available to customer accounts.");
    if (state.wishlist.has(productId)) {
      await apiFetch(`/wishlist/${encodeURIComponent(productId)}`, { method: "DELETE" });
      state.wishlist.delete(productId);
      showToast("Removed from your wishlist.");
    } else {
      await apiFetch("/wishlist", { method: "POST", body: JSON.stringify({ product_id: productId }) });
      state.wishlist.add(productId);
      showToast("Saved to your wishlist.");
    }
    renderCatalog();
    if (!$("#dashboard").classList.contains("hidden") && state.dashboardSection === "wishlist") await renderDashboard();
  }

  async function showProduct(productId) {
    const product = state.products.find(item => item.id === productId);
    if (!product) return;
    setModal(`<div class="product-modal"><div class="product-modal-image">${safeImage(product.images?.[0]) ? `<img src="${escapeHtml(safeImage(product.images[0]))}" alt="${escapeHtml(product.name)}">` : '<span>WEWE</span>'}</div><div class="product-modal-copy"><button class="close-modal" data-action="close-modal" aria-label="Close">×</button><div class="section-kicker">Campus marketplace</div><h2>${escapeHtml(product.name)}</h2><p>${escapeHtml(product.description || "Details are provided by the retailer.")}</p><h3>Available listings</h3><label class="field detail-quantity-field">Quantity<input id="detailQuantity" type="number" min="1" max="100" value="1"></label><div id="productListings"><p class="api-state">Loading listings…</p></div><h3>Customer reviews</h3><div id="productReviews"><p class="api-state">Loading reviews…</p></div><div id="reviewFormSlot"></div></div></div>`, true);
    const listings = productListings(product);
    $("#productListings").innerHTML = listings.length ? listings.map(listing => `<div class="listing-row"><span><b>${escapeHtml(listing.retailer_name)}</b><small>${Number(listing.stock_available) > 0 ? `${Number(listing.stock_available)} available` : "Out of stock"}</small></span><span class="listing-price">${priceMarkup(listing)}</span><button class="add-button" data-action="add-cart" data-listing-id="${escapeHtml(listing.retailer_product_id)}" ${Number(listing.stock_available) < 1 ? "disabled" : ""}>Add</button></div>`).join("") : '<p>No active listings.</p>';
    try {
      const reviews = await apiFetch(`/products/${encodeURIComponent(productId)}/reviews`);
      const rows = Array.isArray(reviews) ? reviews : reviews.items || [];
      $("#productReviews").innerHTML = rows.length ? rows.map(review => `<div class="review-row"><b>${escapeHtml(review.rating)}/5</b><span>${escapeHtml(review.body || "No written review.")}</span><small>${escapeHtml(review.customer_name || review.user_name || "Verified customer")}</small></div>`).join("") : '<p class="api-state">No customer reviews yet.</p>';
    } catch (error) {
      $("#productReviews").innerHTML = `<p class="api-state api-error">${escapeHtml(error.message)}</p>`;
    }
    if (state.user?.role === "CUSTOMER") addReviewForm(productId);
  }

  async function addReviewForm(productId) {
    try {
      const orders = await apiFetch("/orders");
      const eligible = (orders || []).flatMap(order => (order.items || []).filter(item => item.product_id === productId && item.id).map(item => ({ id: item.id, order })));
      if (!eligible.length) return;
      $("#reviewFormSlot").innerHTML = `<form data-form="review" data-product-id="${escapeHtml(productId)}" class="api-form"><h4>Review a purchased item</h4><label class="field">Order item<select name="order_item_id">${eligible.map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.order.order_number)}</option>`).join("")}</select></label><label class="field">Rating<select name="rating"><option value="5">5 - Excellent</option><option value="4">4 - Good</option><option value="3">3 - Okay</option><option value="2">2 - Poor</option><option value="1">1 - Bad</option></select></label><label class="field">Review<textarea name="body" maxlength="2000"></textarea></label><button class="button-primary">Submit review</button></form>`;
    } catch (error) {
      showToast(error.message);
    }
  }

  async function submitReview(form) {
    const body = Object.fromEntries(new FormData(form));
    body.rating = Number(body.rating);
    await apiFetch("/reviews", { method: "POST", body: JSON.stringify(body) });
    showToast("Your review was submitted.");
    await showProduct(form.dataset.productId);
  }

  async function showRetailer(slug) {
    setModal('<div class="modal-head"><h2>Retailer</h2><button class="close-modal" data-action="close-modal">×</button></div><p class="api-state">Loading retailer…</p>', true);
    let retailer;
    try {
      retailer = await apiFetch(`/retailers/${encodeURIComponent(slug)}`);
    } catch (error) {
      $("#modalContent").innerHTML = `<div class="modal-head"><h2>Retailer unavailable</h2><button class="close-modal" data-action="close-modal">×</button></div><p class="api-state api-error">${escapeHtml(error.message)}<br><button class="button-outline" data-action="retailer-details" data-retailer-slug="${escapeHtml(slug)}">Try again</button></p>`;
      throw error;
    }
    const products = retailer.products || retailer.listings || [];
    $("#modalContent").innerHTML = `<div class="modal-head"><div><div class="section-kicker">Campus retailer</div><h2>${escapeHtml(retailer.business_name)}</h2></div><button class="close-modal" data-action="close-modal">×</button></div><p>${escapeHtml(retailer.description || "")}</p><p>${escapeHtml(retailer.phone || "")}</p><div class="retailer-products">${products.map(item => `<article class="listing-row"><span><b>${escapeHtml(item.name || item.product_name)}</b><small>${escapeHtml(item.category_name || "")}</small></span><b>${money(item.price_ugx)}</b></article>`).join("") || '<p>No active products are listed.</p>'}</div>`;
  }

  async function loadGoogleMaps() {
    if (window.google?.maps) return true;
    if (state.mapsApiKey === null) {
      try {
        const config = await apiFetch("/locations/maps-config");
        state.mapsApiKey = config.google_maps_api_key || "";
      } catch {
        state.mapsApiKey = "";
      }
    }
    if (!state.mapsApiKey) return false;
    await new Promise((resolve, reject) => {
      const existing = document.querySelector('script[data-wewe-google-maps]');
      if (existing) {
        existing.addEventListener("load", resolve, { once: true });
        existing.addEventListener("error", reject, { once: true });
        if (window.google?.maps) resolve();
        return;
      }
      const script = document.createElement("script");
      script.src = "https://maps.googleapis.com/maps/api/js?key=" + encodeURIComponent(state.mapsApiKey) + "&v=weekly";
      script.async = true;
      script.defer = true;
      script.dataset.weweGoogleMaps = "true";
      script.onload = resolve;
      script.onerror = () => reject(new Error("Google Maps could not be loaded."));
      document.head.appendChild(script);
    });
    return Boolean(window.google?.maps);
  }

  async function loadLeafletMap() {
    if (window.L?.map) return true;

    // Do not get stuck on a previously failed CDN script. Try two independent
    // public CDNs so a transient/unreachable unpkg connection does not disable
    // the checkout map.
    const sources = [
      {
        css: "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css",
        js: "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js"
      },
      {
        css: "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css",
        js: "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
      }
    ];

    const loadScript = (src) => new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = src;
      script.async = true;
      script.defer = true;
      script.dataset.weweLeaflet = "true";
      const timer = setTimeout(() => {
        script.remove();
        reject(new Error("Leaflet CDN timed out."));
      }, 8000);
      script.onload = () => {
        clearTimeout(timer);
        resolve();
      };
      script.onerror = () => {
        clearTimeout(timer);
        script.remove();
        reject(new Error("Leaflet CDN failed."));
      };
      document.head.appendChild(script);
    });

    for (const source of sources) {
      try {
        const css = document.createElement("link");
        css.rel = "stylesheet";
        css.href = source.css;
        css.dataset.weweLeafletCss = "true";
        document.head.appendChild(css);
        await loadScript(source.js);
        if (window.L?.map) return true;
      } catch {
        // Try the next CDN.
      }
    }
    return false;
  }

  function centerCheckoutMap(point) {
    if (!state.checkoutMap || !point) return;
    const lat = Number(point.latitude);
    const lng = Number(point.longitude);
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
    if (typeof state.checkoutMap.setCenter === "function") {
      state.checkoutMap.setCenter({ lat, lng });
      state.checkoutMap.setZoom(17);
    } else if (typeof state.checkoutMap.setView === "function") {
      state.checkoutMap.setView([lat, lng], 17);
    }
  }

  async function initializeCheckoutMap(points) {
    const mapElement = $("#checkoutMap");
    if (!mapElement) return;
    try {
      // Leaflet/OpenStreetMap is the primary checkout map. This deliberately
      // avoids a configured-but-broken Google Maps key producing a blank/blue
      // Google canvas. Google remains available only for future enhancements.
      const leafletLoaded = await loadLeafletMap();
      if (!leafletLoaded) throw new Error("Campus map could not be loaded.");
      const defaultCenter = [0.3350, 32.5700];
      // Remove any previous Leaflet instance before rebuilding the checkout
      // modal. This prevents stale tile layers and Leaflet initialization state
      // from surviving repeated checkout openings.
      if (state.checkoutMap) {
        try { state.checkoutMap.remove(); } catch {}
        state.checkoutMap = null;
      }
      state.checkoutTileLayer = null;
      state.checkoutMarker = null;
      state.checkoutAccuracyCircle = null;
      mapElement.replaceChildren();
      delete mapElement.dataset.mapProvider;
      delete mapElement.dataset.tileStatus;
      delete mapElement.dataset.tileFallback;

      state.checkoutMap = window.L.map(mapElement, {
        scrollWheelZoom: true,
        zoomControl: true,
        preferCanvas: false
      }).setView(defaultCenter, 15);

      // Use public map tiles directly in the browser. This keeps the checkout
      // map independent of the WEWE API container's ability to reach an
      // upstream tile provider. The backend relay remains a final fallback.
      // Prefer the WEWE server-side relay. This keeps checkout tile delivery
      // independent of browser CORS/referrer/network quirks and gives us one
      // controlled path for production. Public providers remain fallbacks.
      const tileSources = [
        {
          id: "wewe-relay",
          url: API_BASE + "/locations/map-tile/{z}/{x}/{y}.png",
          attribution: '&copy; OpenStreetMap contributors'
        },
        {
          id: "openstreetmap",
          url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
          attribution: '&copy; OpenStreetMap contributors'
        },
        {
          id: "esri",
          url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
          attribution: 'Sources: Esri, HERE, Garmin, USGS, Intermap, &copy; OpenStreetMap contributors, GIS User Community'
        }
      ];

      let tileIndex = 0;
      let tileLayer = null;
      let tileErrors = 0;
      const activateTileProvider = index => {
        const source = tileSources[index];
        if (!source || !state.checkoutMap) return;
        tileIndex = index;
        tileErrors = 0;
        if (tileLayer) state.checkoutMap.removeLayer(tileLayer);
        tileLayer = window.L.tileLayer(source.url, {
          maxZoom: 19,
          keepBuffer: 4,
          updateWhenZooming: false,
          updateWhenIdle: true,
          referrerPolicy: "strict-origin-when-cross-origin",
          attribution: source.attribution
        }).addTo(state.checkoutMap);
        state.checkoutTileLayer = tileLayer;
        mapElement.dataset.mapProvider = source.id;
        mapElement.dataset.tileFallback = index > 0 ? source.id : "";
        tileLayer.on("tileload", () => {
          tileErrors = 0;
          mapElement.dataset.tileStatus = "ready";
        });
        tileLayer.on("tileerror", () => {
          tileErrors += 1;
          // A single failed tile is normal on a moving map. Only switch
          // providers after several failures in the same viewport.
          if (tileErrors >= 8 && index + 1 < tileSources.length) {
            mapElement.dataset.tileStatus = "error";
            activateTileProvider(index + 1);
          }
        });
      };
      activateTileProvider(0);

      // The checkout map lives inside a modal. Force Leaflet to recalculate
      // its dimensions immediately and again after the modal transition.
      requestAnimationFrame(() => state.checkoutMap?.invalidateSize?.({ pan: false }));
      setTimeout(() => state.checkoutMap?.invalidateSize?.({ pan: false }), 150);

      const usable = points.filter(point =>
        Number.isFinite(Number(point.latitude)) &&
        Number.isFinite(Number(point.longitude)) &&
        Math.abs(Number(point.latitude)) <= 90 &&
        Math.abs(Number(point.longitude)) <= 180
      );

      // Deliberately do not render every destination as a marker. The
      // catalogue can contain many halls, hostels and service areas, so
      // rendering all of them makes the checkout map visually congested.
      // The selected destination is rendered by selectCheckoutPoint().
      mapElement.dataset.locationCount = String(usable.length);

      // Modals can report zero dimensions while opening. Recalculate after
      // paint, after layout, and once more after external tiles begin loading.
      [100, 350, 900].forEach(delay => {
        setTimeout(() => state.checkoutMap?.invalidateSize?.({ pan: false }), delay);
      });

      return;
    } catch (error) {
      mapElement.innerHTML = '<div class="map-unavailable"><b>Map unavailable</b><span>' +
        escapeHtml(error.message) + '</span></div>';
    }
  }

  function selectCheckoutPoint(pointId) {
    const form = $('form[data-form="checkout"]');
    const point = state.checkoutPoints.find(item => item.id === pointId);
    if (!form || !point) return;
    const select = form.elements.delivery_point_id;
    select.value = point.id;
    state.checkoutSelectedExternal = null;
    const label = $("#selectedDeliveryLocation");
    if (label) label.textContent = point.name + (point.directions ? " · " + point.directions : "");
    centerCheckoutMap(point);
    if (state.checkoutMap && Number.isFinite(Number(point.latitude)) && Number.isFinite(Number(point.longitude)) && window.L?.marker) {
      if (state.checkoutMarker) {
        try { state.checkoutMap.removeLayer(state.checkoutMarker); } catch {}
      }
      if (state.checkoutAccuracyCircle) {
        try { state.checkoutMap.removeLayer(state.checkoutAccuracyCircle); } catch {}
        state.checkoutAccuracyCircle = null;
      }
      state.checkoutMarker = window.L.marker([Number(point.latitude), Number(point.longitude)])
        .addTo(state.checkoutMap)
        .bindTooltip(point.name || "Delivery destination", { direction: "top" })
        .openTooltip();
    }
    requestAnimationFrame(() => state.checkoutMap?.invalidateSize?.({ pan: false }));
    setTimeout(() => state.checkoutMap?.invalidateSize?.({ pan: false }), 200);
    updateCheckoutQuote().catch(error => showToast(error.message));
  }

  async function useCurrentLocation() {
    if (!window.isSecureContext && location.hostname !== "localhost" && location.hostname !== "127.0.0.1") {
      throw new Error("Current location requires HTTPS (or localhost). Open WEWE through your local web server, not a plain file.");
    }
    if (!navigator.geolocation) throw new Error("Your browser does not provide location services.");

    // Do not trust the first desktop/browser fix. Windows Chrome can initially
    // return a coarse Wi-Fi/IP estimate and improve after several seconds.
    // Collect fresh high-accuracy fixes briefly and keep the best one.
    const position = await new Promise((resolve, reject) => {
      const startedAt = Date.now();
      const maxWaitMs = 15000;
      const targetAccuracyMeters = 150;
      let bestPosition = null;
      let settled = false;
      let watchId = null;
      let timer = null;

      const finish = (position, error) => {
        if (settled) return;
        settled = true;
        if (watchId !== null) navigator.geolocation.clearWatch(watchId);
        if (timer !== null) clearTimeout(timer);
        if (position) resolve(position);
        else reject(error);
      };

      const messages = {
        1: "Location permission was denied. Allow location access for WEWE in your browser and try again.",
        2: "Your device could not determine its location. Check that location services are enabled.",
        3: "Location lookup timed out. Move to an area with better GPS/network reception and try again."
      };

      const onPosition = candidate => {
        const accuracy = Number(candidate?.coords?.accuracy);
        if (!Number.isFinite(accuracy)) return;
        if (!bestPosition || accuracy < Number(bestPosition.coords.accuracy)) bestPosition = candidate;
        if (accuracy <= targetAccuracyMeters) finish(candidate);
        else if (Date.now() - startedAt >= maxWaitMs) {
          finish(
            null,
            new Error(
              "Your current location is too inaccurate for delivery (" +
              Math.round(Number(bestPosition.coords.accuracy)).toLocaleString("en-UG") +
              " m). Turn on Windows/browser location services or choose your hall/hostel on the map."
            )
          );
        }
      };

      const onError = error => {
        if (bestPosition && Date.now() - startedAt >= maxWaitMs) {
          finish(
            null,
            new Error(
              "Your current location is too inaccurate for delivery (" +
              Math.round(Number(bestPosition.coords.accuracy)).toLocaleString("en-UG") +
              " m). Turn on Windows/browser location services or choose your hall/hostel on the map."
            )
          );
          return;
        }
        if (error.code === 1) finish(null, new Error(messages[1]));
        else if (error.code === 2) finish(null, new Error(messages[2]));
        else if (error.code === 3 && !bestPosition) finish(null, new Error(messages[3]));
      };

      watchId = navigator.geolocation.watchPosition(onPosition, onError, {
        enableHighAccuracy: true,
        maximumAge: 0,
        timeout: maxWaitMs
      });

      timer = setTimeout(() => {
        if (bestPosition && Number(bestPosition.coords.accuracy) <= targetAccuracyMeters) {
          finish(bestPosition);
        } else {
          const accuracyText = bestPosition && Number.isFinite(Number(bestPosition.coords.accuracy))
            ? Math.round(Number(bestPosition.coords.accuracy)).toLocaleString("en-UG") + " m"
            : "unknown";
          finish(
            null,
            new Error(
              "Your current location is too inaccurate for delivery (" + accuracyText +
              "). Turn on Windows/browser location services or choose your hall/hostel on the map."
            )
          );
        }
      }, maxWaitMs + 250);
    });

    const latitude = Number(position.coords.latitude);
    const longitude = Number(position.coords.longitude);
    const accuracyMeters = Number(position.coords.accuracy);
    if (!Number.isFinite(latitude) || !Number.isFinite(longitude) ||
        latitude < -90 || latitude > 90 || longitude < -180 || longitude > 180) {
      throw new Error("Your browser returned invalid GPS coordinates. Choose a delivery point manually.");
    }
    if (!Number.isFinite(accuracyMeters) || accuracyMeters > 150) {
      throw new Error(
        "Your current location is too inaccurate for delivery (" +
        (Number.isFinite(accuracyMeters) ? Math.round(accuracyMeters).toLocaleString("en-UG") + " m" : "unknown") +
        "). Turn on Windows/browser location services or choose your hall/hostel on the map."
      );
    }

    const campuses = state.campuses || await apiFetch("/locations/campuses");
    const campus = campuses.find(item => item.slug === "main-campus") || campuses[0];
    if (!campus) throw new Error("No WEWE campus is configured.");

    const point = await apiFetch("/locations/me/delivery-points", {
      method: "POST",
      body: JSON.stringify({
        campus_id: campus.id,
        kind: "OTHER",
        name: "My current location",
        directions: "Browser GPS location (accuracy ±" + Math.round(accuracyMeters) + " m)",
        latitude,
        longitude,
        google_place_id: null,
        is_private: true
      })
    });

    state.checkoutPoints = [...state.checkoutPoints.filter(item => item.id !== point.id), point];
    const select = $('form[data-form="checkout"]')?.elements.delivery_point_id;
    if (select) {
      [...select.options].filter(option => option.textContent === "My current location").forEach(option => option.remove());
      const option = document.createElement("option");
      option.value = point.id;
      option.textContent = "My current location · ±" + Math.round(accuracyMeters) + " m";
      select.appendChild(option);
      select.value = point.id;
    }

    state.checkoutSelectedExternal = null;
    const label = $("#selectedDeliveryLocation");
    if (label) label.textContent = "My current location · GPS ±" + Math.round(accuracyMeters) + " m";

    if (state.checkoutMap) {
      centerCheckoutMap(point);
      if (state.checkoutMap.setView && window.L?.marker) {
        if (state.checkoutMarker) state.checkoutMap.removeLayer(state.checkoutMarker);
        if (state.checkoutAccuracyCircle) state.checkoutMap.removeLayer(state.checkoutAccuracyCircle);

        state.checkoutAccuracyCircle = window.L.circle([latitude, longitude], {
          radius: accuracyMeters,
          weight: 2,
          fillOpacity: 0.08
        }).addTo(state.checkoutMap);

        state.checkoutMarker = window.L.marker([latitude, longitude])
          .addTo(state.checkoutMap)
          .bindTooltip("My current location · ±" + Math.round(accuracyMeters) + " m", { direction: "top" })
          .openTooltip();
      }
    }

    await updateCheckoutQuote();
  }
  async function showCheckout() {
    if (!state.user) return showAuth();
    const cart = await ensureCart();
    if (!cart.items?.length) return showToast("Add at least one item before checkout.");
    setModal('<div class="modal-head"><div><div class="section-kicker">Secure checkout</div><h2>Choose delivery</h2></div><button class="close-modal" data-action="close-modal">×</button></div><div id="checkoutContents"><p class="api-state">Loading campus locations…</p></div>', true);
    let saved, campuses, pickupPoints, publicPoints;
    try {
      [saved, campuses, pickupPoints] = await Promise.all([
        apiFetch("/locations/me/delivery-points"),
        apiFetch("/locations/campuses"),
        apiFetch("/locations/pickup-points")
      ]);
      const mainCampus = campuses.find(item => item.slug === "main-campus") || campuses[0];
      const halls = mainCampus
        ? await apiFetch("/locations/halls?campus_id=" + encodeURIComponent(mainCampus.id))
        : [];
      state.checkoutHallKinds = new Map(halls.map(hall => [hall.id, hall.kind]));
      publicPoints = mainCampus ? await apiFetch("/locations/delivery-points?campus_id=" + encodeURIComponent(mainCampus.id)) : [];
    } catch (error) {
      $("#checkoutContents").innerHTML = '<div class="api-state api-error">' + escapeHtml(error.message) + '<p><button class="button-outline" data-action="checkout">Try again</button></p></div>';
      throw error;
    }
    state.campuses = campuses;
    state.checkoutPoints = [...new Map([...publicPoints, ...saved].map(point => [point.id, point])).values()];
    const profile = await apiFetch("/users/me/profile");
    const hallPoints = state.checkoutPoints.filter(point => state.checkoutHallKinds.get(point.hall_id) === "HALL");
    const hostelPoints = state.checkoutPoints.filter(point => state.checkoutHallKinds.get(point.hall_id) === "HOSTEL");
    const areaPoints = state.checkoutPoints.filter(point => !point.hall_id && !point.is_private);
    const savedPoints = state.checkoutPoints.filter(point => point.is_private && !point.hall_id);
    const option = point => '<option value="' + escapeHtml(point.id) + '">' + escapeHtml(point.name) + (point.directions ? ' — ' + escapeHtml(point.directions) : "") + '</option>';
    const deliveryOptions =
      '<option value="">Choose a delivery destination</option>' +
      (hallPoints.length ? '<optgroup label="Makerere University halls">' + hallPoints.map(option).join("") + '</optgroup>' : "") +
      (hostelPoints.length ? '<optgroup label="Student hostels">' + hostelPoints.map(option).join("") + '</optgroup>' : "") +
      (areaPoints.length ? '<optgroup label="Kampala service areas">' + areaPoints.map(option).join("") + '</optgroup>' : "") +
      (savedPoints.length ? '<optgroup label="My saved locations">' + savedPoints.map(option).join("") + '</optgroup>' : "");
    $("#checkoutContents").innerHTML = '<form data-form="checkout" class="api-form">' +
      '<div class="delivery-map-shell"><div class="map-toolbar"><div><b>Where should we deliver?</b><small>Select a hall, hostel or nearby Kampala service area from the list. The map shows only your selected destination.</small></div><button type="button" class="button-outline" data-action="use-current-location">Use my current location</button></div><div id="checkoutAutocomplete" class="checkout-autocomplete"></div><div id="checkoutMap" class="checkout-map"></div><p id="selectedDeliveryLocation" class="selected-location">Choose a delivery destination</p></div>' +
      '<label class="field">Fulfilment<select name="delivery_method"><option value="DELIVERY">Campus delivery</option><option value="PICKUP">Pickup</option></select></label>' +
      '<div data-checkout-delivery><label class="field">Delivery destination<select name="delivery_point_id">' + deliveryOptions + '</select></label><button type="button" class="text-link" data-action="new-address">Add a delivery point</button></div>' +
      '<div data-checkout-pickup class="hidden"><label class="field">Pickup point<select name="pickup_point_id">' + pickupPoints.map(point => '<option value="' + escapeHtml(point.id) + '">' + escapeHtml(point.name) + (point.directions ? ' — ' + escapeHtml(point.directions) : "") + '</option>').join("") + '</select></label></div>' +
      '<div class="field"><span>Payment method</span><div class="payment-options"><label class="payment-option selected"><input type="radio" name="payment_method" value="MTN_MOMO" checked> <b>MTN Mobile Money</b><small>Pay securely from your MTN line.</small></label><label class="payment-option"><input type="radio" name="payment_method" value="AIRTEL_MONEY"> <b>Airtel Money</b><small>Pay securely from your Airtel line.</small></label></div></div>' +
      '<label class="field">Email for payment receipt<input name="email" type="email" value="' + escapeHtml(state.user?.email || "") + '" placeholder="you@example.com" required autocomplete="email"></label>' +
      '<label class="field" data-payment-phone>Mobile money phone<input name="phone" type="tel" placeholder="+256700000000" required autocomplete="tel"></label>' +
      '<div id="checkoutQuote" class="checkout-quote"><p class="api-state">Calculating delivery route…</p></div><p class="form-message" aria-live="polite"></p><button class="button-primary">Place order</button></form>';
    if (profile.preferred_delivery_point_id && $('select[name="delivery_point_id"]')) {
      $('select[name="delivery_point_id"]').value = profile.preferred_delivery_point_id;
    }
    toggleCheckoutFields();
    await initializeCheckoutMap(state.checkoutPoints);
    if (profile.preferred_delivery_point_id) selectCheckoutPoint(profile.preferred_delivery_point_id);
  }

  function toggleCheckoutFields() {
    const form = $('form[data-form="checkout"]');
    if (!form) return;
    const pickup = form.elements.delivery_method.value === "PICKUP";
    $("[data-checkout-delivery]", form).classList.toggle("hidden", pickup);
    $("[data-checkout-pickup]", form).classList.toggle("hidden", !pickup);
    $("[data-payment-phone]", form).classList.remove("hidden");
    updateCheckoutQuote().catch(error => showToast(error.message));
  }

  async function updateCheckoutQuote() {
    const form = $('form[data-form="checkout"]');
    const box = $("#checkoutQuote");
    if (!form || !box) return;
    const method = form.elements.delivery_method.value;
    const destination = method === "PICKUP" ? form.elements.pickup_point_id.value : form.elements.delivery_point_id.value;
    if (!destination) { box.textContent = "Choose a destination to calculate delivery."; return; }
    box.textContent = "Calculating delivery…";
    const payload = { delivery_method: method, ...(method === "PICKUP" ? { pickup_point_id: destination } : { delivery_point_id: destination }) };
    try {
      const quote = await apiFetch("/orders/delivery-quote", { method: "POST", body: JSON.stringify(payload) });
      const routeRows = (quote.fulfillments || []).map(item => {
        const distance = Number(item.route_distance_km);
        const distanceText = Number.isFinite(distance) ? distance.toFixed(1) + " km" : "Route unavailable";
        return '<p><span>' + escapeHtml(item.retailer_name || "Retailer") + ' · ' + distanceText + '</span><b>' + money(item.delivery_fee_ugx) + '</b></p>';
      }).join("");
      const discountRow = Number(quote.multi_retailer_discount_ugx || 0) > 0 ? '<p><span>Multi-retailer discount</span><b>−' + money(quote.multi_retailer_discount_ugx) + '</b></p>' : '';
      const grossRow = Number(quote.multi_retailer_discount_ugx || 0) > 0 ? '<p><span>Delivery before discount</span><b>' + money(quote.gross_delivery_fee_ugx) + '</b></p>' : '';
      box.innerHTML = '<div class="checkout-totals"><p>Subtotal <b>' + money(quote.subtotal_ugx) + '</b></p>' + routeRows + grossRow + discountRow + '<p>Delivery fee <b>' + money(quote.delivery_fee_ugx) + '</b></p><p class="checkout-total"><span>Total</span><b>' + money(quote.total_ugx) + '</b></p><small class="route-note">' + (quote.routing_provider ? escapeHtml(quote.routing_provider) + ' road routing · WEWE delivery pricing' : 'Pickup has no delivery fee.') + '</small></div>';
      form.dataset.quoteTotal = String(quote.total_ugx);
    } catch (error) {
      box.innerHTML = '<div class="api-state api-error"><b>Delivery fee could not be calculated.</b><span>' + escapeHtml(error.message || "Please choose another delivery point or try again.") + '</span><button type="button" class="button-outline" data-action="retry-delivery-quote">Try again</button></div>';
      delete form.dataset.quoteTotal;
      throw error;
    }
  }

  async function placeOrder(form) {
    const method = form.elements.delivery_method.value;
    const delivery = {
      delivery_method: method,
      ...(method === "PICKUP" ? { pickup_point_id: form.elements.pickup_point_id.value } : { delivery_point_id: form.elements.delivery_point_id.value })
    };
    if (method === "DELIVERY" && !delivery.delivery_point_id) throw new Error("Choose or add a delivery point.");
    if (method === "PICKUP" && !delivery.pickup_point_id) throw new Error("Choose an available pickup point.");
    const submit = $('button[type="submit"], button:not([type])', form);
    submit.disabled = true;
    form.dataset.idempotencyKey ||= crypto.randomUUID();
    const order = await apiFetch("/orders", { method: "POST", headers: { "Idempotency-Key": form.dataset.idempotencyKey }, body: JSON.stringify(delivery) });
    let payment;
    try {
      const paymentBody = {
        method: form.elements.payment_method.value,
        phone: normalizeUgandanPaymentPhone(form.elements.phone.value),
        email: form.elements.email.value.trim()
      };
      form.dataset.paymentIdempotencyKey ||= crypto.randomUUID();
      payment = await apiFetch(`/orders/${encodeURIComponent(order.id)}/payments`, { method: "POST", headers: { "Idempotency-Key": form.dataset.paymentIdempotencyKey }, body: JSON.stringify(paymentBody) });
    } catch (error) {
      const method = form.elements.payment_method.value;
      const phone = form.elements.phone.value.trim();
      $("#modalContent").innerHTML = `<div class="modal-head"><div><div class="section-kicker">Order created</div><h2>${escapeHtml(order.order_number)}</h2></div><button class="close-modal" data-action="close-modal">×</button></div><p>Your order was created and the server calculated its totals, but the online payment could not be started.</p><div class="checkout-totals"><p>Subtotal <b>${money(order.subtotal_ugx)}</b></p><p>Delivery <b>${money(order.delivery_fee_ugx)}</b></p><p>Total <b>${money(order.total_ugx)}</b></p></div><p class="api-error">Payment error: ${escapeHtml(error.message)}</p><button class="button-primary" data-action="retry-online-payment" data-order-id="${escapeHtml(order.id)}" data-method="${escapeHtml(method)}" data-phone="${escapeHtml(phone)}" data-email="${escapeHtml(form.elements.email.value.trim())}">Retry online payment</button>`;
      await ensureCart();
      return;
    }
    state.cart = { items: [] };
    syncCartBadge();
    const checkoutUrl = safeImage(payment?.checkout_url);
    $("#modalContent").innerHTML = `<div class="modal-head"><div><div class="section-kicker">Order placed</div><h2>${escapeHtml(order.order_number)}</h2></div><button class="close-modal" data-action="close-modal">×</button></div><p>The server calculated these totals:</p><div class="checkout-totals"><p>Subtotal <b>${money(order.subtotal_ugx)}</b></p><p>Delivery <b>${money(order.delivery_fee_ugx)}</b></p><p>Total <b>${money(order.total_ugx)}</b></p><p>Status ${statusBadge(order.status)} · Payment ${statusBadge(payment?.status || order.payment_status)}</p></div>${checkoutUrl ? `<p><a href="${escapeHtml(checkoutUrl)}" target="_blank" rel="noopener noreferrer">Continue mobile payment</a></p>` : ""}<p id="paymentProgress" class="api-state">Waiting for mobile-money confirmation…</p><button class="button-primary" data-action="close-modal">Continue shopping</button>`;
    watchPaymentStatus(payment.id);
  }

  async function watchPaymentStatus(paymentId) {
    const progress = $("#paymentProgress");
    if (!progress) return;
    const deadline = Date.now() + 60000;
    while (Date.now() < deadline) {
      await new Promise(resolve => setTimeout(resolve, 3000));
      try {
        const payment = await apiFetch(`/payments/${encodeURIComponent(paymentId)}`);
        const current = $("#paymentProgress");
        if (!current) return;
        if (payment.status === "SUCCESSFUL") {
          current.className = "api-state api-success";
          current.textContent = "Payment confirmed. Your order is being processed.";
          return;
        }
        if (payment.status === "FAILED") {
          current.className = "api-state api-error";
          current.textContent = "Payment failed. You can start a new payment attempt.";
          return;
        }
        if (payment.status === "UNKNOWN") {
          current.className = "api-state api-error";
          current.textContent = "Payment status is being reconciled. Please do not retry yet.";
          return;
        }
        current.textContent = "Waiting for mobile-money confirmation…";
      } catch {
        // A transient polling failure must not change the payment state or create a retry.
      }
    }
    const current = $("#paymentProgress");
    if (current) current.textContent = "Still waiting for confirmation. You can close this window; the payment status remains on the order.";
  }

  async function retryOnlinePayment(orderId, method, phone, email) {
    if (!["MTN_MOMO", "AIRTEL_MONEY"].includes(method)) throw new Error("Choose an online mobile-money payment method.");
    if (!phone) throw new Error("Enter the mobile-money phone number.");
    if (!email) throw new Error("Enter an email address for the payment receipt.");
    const normalizedPhone = normalizeUgandanPaymentPhone(phone);
    const idempotencyKey = crypto.randomUUID();
    const payment = await apiFetch(`/orders/${encodeURIComponent(orderId)}/payments`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ method, phone: normalizedPhone, email })
    });
    const checkoutUrl = safeImage(payment?.checkout_url);
    $("#modalContent").innerHTML = `<div class="modal-head"><div><div class="section-kicker">Payment retry</div><h2>Continue payment</h2></div><button class="close-modal" data-action="close-modal">×</button></div><p>${escapeHtml(payment?.status || "Payment initiated")}</p>${checkoutUrl ? `<p><a class="button-primary" href="${escapeHtml(checkoutUrl)}" target="_blank" rel="noopener noreferrer">Continue mobile payment</a></p>` : ""}<p id="paymentProgress" class="api-state">Waiting for mobile-money confirmation…</p><button class="button-outline" data-action="close-modal">Close</button>`;
    if (payment?.id) watchPaymentStatus(payment.id);
  }


  async function showNewAddress() {
    const campuses = state.campuses || await apiFetch("/locations/campuses");
    state.addressForCheckout = Boolean($("#checkoutContents"));
    setModal(`<div class="modal-head"><h2>Add delivery point</h2><button class="close-modal" data-action="close-modal">×</button></div><form data-form="address" class="api-form"><label class="field">Campus<select name="campus_id" required>${campuses.map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join("")}</select></label><label class="field">Location type<select name="kind"><option value="ROOM">Room</option><option value="BUILDING">Building</option><option value="OTHER">Other</option></select></label><label class="field">Location name<input name="name" required minlength="2" maxlength="180"></label><label class="field">Directions<textarea name="directions" maxlength="500"></textarea></label><p class="form-message" aria-live="polite"></p><button class="button-primary">Save delivery point</button></form>`, false);
  }

  async function saveAddress(form) {
    const body = Object.fromEntries(new FormData(form));
    body.is_private = true;
    await apiFetch("/locations/me/delivery-points", { method: "POST", body: JSON.stringify(body) });
    showToast("Delivery point saved.");
    if (state.addressForCheckout) await showCheckout();
    else await renderDashboard();
  }

  function showDashboard(show = true) {
    $("#dashboard").classList.toggle("hidden", !show);
    $("#storefront").classList.toggle("hidden", show);
    $("#footer").classList.toggle("hidden", show);
    $("#topbar").classList.toggle("hidden", show);
    if (!show) return;
    if (!state.user) return showAuth();
    renderDashboard().catch(error => {
      $("#dashboardContent").innerHTML = `<div class="api-state api-error">${escapeHtml(error.message)}</div>`;
    });
  }

  function dashboardMenu(role) {
    const common = [["overview","Overview"]];
    if(role==="CUSTOMER") return [...common,["orders","Orders"],["wishlist","Saved items"],["addresses","Delivery points"],["notifications","Notifications"],["profile","Profile"]];
    if(role==="RETAILER") return [...common,["earnings","Earnings"],["products","Products"],["fulfillments","Fulfilments"],["profile","Store profile"]];
    if(role==="DELIVERY_AGENT") return [...common,["available","Delivery offers"],["active","Active delivery"],["history","Delivery history"],["earnings","Earnings"],["profile","Rider profile"]];
    return [...common,["analytics","Analytics"],["users","Users"],["retailers","Retailers"],["products","Products"],["categories","Categories"],["orders","Orders"],["agents","Delivery agents"],["reviews","Reviews"],["settlements","Settlements"],["rider-payouts","Rider payouts"],["reconciliation","Reconciliation"],["settings","Settings"],["audit","Audit log"]];
  }
  async function renderDashboard() {
    if (!state.user) return showAuth();
    const user = state.user;
    const role = user.role;
    const nav = dashboardMenu(role);
    if (!nav.some(([key]) => key === state.dashboardSection)) state.dashboardSection = "overview";
    $("#sideRole").textContent = role.replaceAll("_", " ");
    $("#dashName").textContent = user.name;
    const dashboardAvatar = $("#dashAvatar");
    if (safeImage(user.profile_image_url)) {
      dashboardAvatar.innerHTML = '<img src="' + escapeHtml(safeImage(user.profile_image_url)) + '" alt="" style="width:100%;height:100%;object-fit:cover;border-radius:inherit">';
    } else {
      dashboardAvatar.textContent = (user.name || "?").slice(0, 1).toUpperCase();
    }
    $("#dashAccountRole").textContent = `${role.replaceAll("_", " ")} account`;
    $("#dashNav").innerHTML = `${nav.map(([key, label]) => `<button class="${key === state.dashboardSection ? "active" : ""}" data-action="dashboard-section" data-section="${key}">${label}</button>`).join("")}<button data-action="sign-out">Sign out</button><button data-action="storefront">Back to shop</button>`;
    $("#dashTitle").textContent = nav.find(([key]) => key === state.dashboardSection)?.[1] || "Overview";
    $("#dashSubtitle").textContent = "Live information from your WEWE account.";
    $("#dashboardContent").innerHTML = '<p class="api-state">Loading your workspace…</p>';
    const view = role === "CUSTOMER" ? await customerDashboard() :
      role === "RETAILER" ? await retailerDashboard() :
      role === "DELIVERY_AGENT" ? await agentDashboard() : await adminDashboard();
    $("#dashboardContent").innerHTML = view;
    syncIncomePolling();
  }

  function syncIncomePolling() {
    if (state.incomeRefreshTimer) clearInterval(state.incomeRefreshTimer);
    state.incomeRefreshTimer = null;
    if (!["RETAILER", "DELIVERY_AGENT"].includes(state.user?.role)) return;
    if (!["overview", "earnings"].includes(state.dashboardSection)) return;
    state.incomeRefreshTimer = setInterval(() => {
      if (!["RETAILER", "DELIVERY_AGENT"].includes(state.user?.role) || !["overview", "earnings"].includes(state.dashboardSection)) {
        syncIncomePolling();
        return;
      }
      renderDashboard().catch(() => {});
    }, 15000);
  }

  async function customerDashboard() {
    const section=state.dashboardSection, orders=await apiFetch("/orders"), notes=await apiFetch("/notifications"), points=await apiFetch("/locations/me/delivery-points");
    if(section==="orders") return dashboardPage("My orders","Track purchases, payment status and delivery progress.",renderOrders(orders,true));
    if(section==="wishlist"){const items=await apiFetch("/wishlist");return dashboardPage("Saved items","Products you want to come back to.",(items||[]).map(x=>`<div class="dashboard-list-item"><div><b>${escapeHtml(x.product_name||x.name)}</b><small>${escapeHtml(x.retailer_name||"Campus retailer")}</small></div><b>${money(x.price_ugx)}</b></div>`).join("")||dashboardEmpty("No saved products yet.","Browse the shop and save items you like."));}
    if(section==="addresses") return dashboardPage("Delivery points","Manage where WEWE should bring your orders.",`<div class="dashboard-toolbar"><button class="button-primary" data-action="new-address">Add delivery point</button></div>${points.map(x=>`<div class="dashboard-list-item"><div><b>${escapeHtml(x.name)}</b><small>${escapeHtml(x.directions||"Saved campus destination")}</small></div><button class="button-outline" data-action="delete-address" data-id="${escapeHtml(x.id)}">Remove</button></div>`).join("")||dashboardEmpty("No delivery points.","Add a hall, hostel or approved pickup destination.")}`);
    if(section==="notifications"){const notes=await apiFetch("/notifications?limit=50");return dashboardPage("Notifications","Important updates from your WEWE activity.",notes.map(x=>`<div class="notification-row"><div><b>${escapeHtml(x.event_type||"WEWE update")}</b><small>${escapeHtml(x.created_at||"")}</small><p>${escapeHtml(x.payload?.message||x.payload?.title||"You have a new WEWE update.")}</p></div>${x.read_at?"":`<button class="button-outline" data-action="read-notification" data-id="${escapeHtml(x.id)}">Mark read</button>`}</div>`).join("")||dashboardEmpty("You are all caught up.","New notifications will appear here."));}if(section==="profile"){const profile=await apiFetch("/users/me/profile");return dashboardPage("Profile & preferences","Keep your account and delivery preferences up to date.",`<form data-form="customer-profile" class="api-form dashboard-form"><label class="field">Preferred delivery point<select name="preferred_delivery_point_id"><option value="">None selected</option>${points.map(x=>`<option value="${escapeHtml(x.id)}" ${profile.preferred_delivery_point_id===x.id?"selected":""}>${escapeHtml(x.name)}</option>`).join("")}</select></label><label><input type="checkbox" name="marketing_opt_in" ${profile.marketing_opt_in?"checked":""}> Receive WEWE updates</label><button class="button-primary">Save preferences</button></form>`);}
    const preferred=points.find(x=>x.id===state.user?.preferred_delivery_point_id);
    return `<div class="dashboard-hero"><div><span class="eyebrow">Customer workspace</span><h2>Welcome back, ${escapeHtml(state.user?.name||"there")}.</h2><p>Your campus shopping activity, delivery points and orders in one place.</p></div><button class="button-primary" data-action="storefront">Continue shopping →</button></div><div class="stat-grid dashboard-stat-grid"><div class="stat-card"><span>Total orders</span><b class="stat-value">${orders.length}</b><small>Campus purchases</small></div><div class="stat-card"><span>Unread updates</span><b class="stat-value">${notes.filter(x=>!x.read_at).length}</b><small>Stay up to date</small></div><div class="stat-card"><span>Saved destination</span><b class="stat-value stat-text">${escapeHtml(preferred?.name||"Not set")}</b><small>Used at checkout</small></div><div class="stat-card"><span>Payments</span><b class="stat-value stat-text">Online</b><small>Secure checkout</small></div></div><div class="dashboard-grid-3"><div class="dashboard-panel dashboard-span-2"><div class="panel-head"><div><h2>Recent orders</h2><small>Your latest campus purchases</small></div><button class="text-link" data-action="dashboard-section" data-section="orders">View all →</button></div>${renderOrders(orders.slice(0,5),true)||dashboardEmpty("No orders yet.","Your first order will appear here.")}</div><div class="dashboard-panel"><h2>Quick actions</h2><div class="quick-actions"><button data-action="dashboard-section" data-section="addresses">📍 Delivery points</button><button data-action="dashboard-section" data-section="wishlist">♡ Saved items</button><button data-action="dashboard-section" data-section="notifications">🔔 Notifications</button><button data-action="dashboard-section" data-section="profile">⚙ Profile</button></div></div></div>`;
  }


  function renderOrders(orders, actions = false) {
    if (!orders.length) return "";
    return orders.map(order => `<div class="order-card"><div class="panel-head"><div><b>${escapeHtml(order.order_number)}</b><small>${formatDate(order.created_at)}</small></div>${statusBadge(order.status)}</div><div>${(order.items || []).map(item => `${escapeHtml(item.product_name || item.name)} × ${Number(item.quantity)}`).join(", ")}</div><div class="panel-head"><span>Payment ${statusBadge(order.payment_status)}</span><b>${money(order.total_ugx)}</b></div>${actions ? `<div class="row-actions"><button data-action="order-details" data-id="${escapeHtml(order.id)}">Details</button>${["PENDING","CONFIRMED","PREPARING"].includes(order.status) ? `<button data-action="cancel-order" data-id="${escapeHtml(order.id)}">Cancel</button>` : ""}<button data-action="reorder" data-id="${escapeHtml(order.id)}">Order again</button></div>` : ""}</div>`).join("");
  }

  async function retailerDashboard() {
    const section = state.dashboardSection;
    const [profile, fulfillments, earnings] = await Promise.all([
      apiFetch("/retailers/me"),
      apiFetch("/retailers/me/fulfillments"),
      apiFetch("/retailers/me/earnings")
    ]);
    if (section === "earnings") {
      const entries = (earnings.entries || []).map(row =>
        '<div class="dashboard-list-item"><div><b>' + escapeHtml(row.reason || "Income entry") + '</b><small>' +
        escapeHtml(row.created_at ? new Date(row.created_at).toLocaleString() : "") + ' · ' + escapeHtml(row.entry_type) +
        '</small></div><b>' + (row.entry_type === "DEBIT" ? "−" : "+") + money(row.amount_ugx) + '</b></div>'
      ).join("");
      const settlements = (earnings.settlements || []).map(row =>
        '<div class="dashboard-list-item"><div><b>' + escapeHtml(row.settlement_reference || row.id) + '</b><small>' +
        escapeHtml(row.status) + ' · ' + escapeHtml(row.created_at ? new Date(row.created_at).toLocaleDateString() : "") +
        '</small></div><b>' + money(row.amount_ugx) + '</b></div>'
      ).join("");
      const notice = earnings.recovery_due_ugx > 0
        ? '<div class="rider-info-card"><b>Account adjustment required</b><span>WEWE is tracking ' + money(earnings.recovery_due_ugx) + ' for recovery from future retailer earnings.</span></div>'
        : earnings.eligible_for_settlement
          ? '<div class="rider-info-card"><b>Eligible for scheduled settlement</b><span>Your available balance has reached the ' + money(earnings.minimum_settlement_ugx) + ' minimum.</span></div>'
          : '<div class="rider-info-card"><b>Building toward payout</b><span>Available balance: ' + money(earnings.available_to_settle_ugx) + '. Minimum: ' + money(earnings.minimum_settlement_ugx) + '.</span></div>';
      return dashboardPage("Retailer earnings","Live accounting view of what WEWE owes your store.",
        '<div class="rider-earnings-grid"><div class="rider-earnings-card"><span>WEWE owes you</span><strong>' + money(earnings.owed_by_wewe_ugx) + '</strong><small>Net unpaid earnings</small></div>' +
        '<div class="rider-earnings-card"><span>Available to settle</span><strong>' + money(earnings.available_to_settle_ugx) + '</strong><small>Not already in payout queue</small></div>' +
        '<div class="rider-earnings-card"><span>Pending payout</span><strong>' + money(earnings.pending_payout_ugx) + '</strong><small>Scheduled or submitted</small></div>' +
        '<div class="rider-earnings-card"><span>Paid out</span><strong>' + money(earnings.paid_out_ugx) + '</strong><small>Historical settled amount</small></div></div>' +
        notice + '<div class="dashboard-grid-3"><section class="dashboard-panel dashboard-span-2"><div class="panel-head"><div><h2>Income activity</h2><small>Immutable retailer payable ledger</small></div></div>' +
        (entries || dashboardEmpty("No income recorded yet.","Payable sales will appear here.")) + '</section><aside class="dashboard-panel"><h2>Settlement history</h2>' +
        (settlements || dashboardEmpty("No settlements yet.","Scheduled retailer payouts will appear here.")) + '</aside></div>');
    }
    if (section === "profile") {
      const open = profile.status === "ACTIVE";
      const campuses = await apiFetch("/locations/campuses");
      const mainCampus = campuses.find(item => item.slug === "main-campus") || campuses[0];
      const publicPoints = mainCampus
        ? await apiFetch("/locations/delivery-points?campus_id=" + encodeURIComponent(mainCampus.id))
        : [];
      const selectedLocation = profile.location_id ? profile.location : null;
      const selectedPrivateOption = selectedLocation && !publicPoints.some(point => point.id === selectedLocation.id)
        ? '<option value="' + escapeHtml(selectedLocation.id) + '" selected>' + escapeHtml(selectedLocation.name) + (selectedLocation.directions ? ' — ' + escapeHtml(selectedLocation.directions) : '') + '</option>'
        : '';
      const locationOptions = selectedPrivateOption + publicPoints.map(point =>
        '<option value="' + escapeHtml(point.id) + '" ' + (profile.location_id === point.id ? 'selected' : '') + '>' +
        escapeHtml(point.name) + (point.directions ? ' — ' + escapeHtml(point.directions) : '') + '</option>'
      ).join("");
      const locationStatus = selectedLocation
        ? '<div class="retailer-location-status"><b>Pickup location set</b><span>' + escapeHtml(selectedLocation.name) + (selectedLocation.directions ? ' · ' + escapeHtml(selectedLocation.directions) : '') + '</span></div>'
        : '<div class="retailer-location-warning"><b>Pickup location required</b><span>Set your pickup point before opening your store or requesting verification.</span></div>';
      const form = '<form data-form="retailer-profile" class="api-form dashboard-form">' +
        '<div style="display:flex;align-items:center;gap:14px;padding:12px;border:1px solid #e7e0ef;border-radius:14px;background:#faf8fd"><div style="width:64px;height:64px;border-radius:16px;overflow:hidden;display:grid;place-items:center;background:#eee8fa;color:#6c3df4;font-weight:900;font-size:23px;flex:none">' + (safeImage(profile.profile_image_url) ? '<img src="' + escapeHtml(safeImage(profile.profile_image_url)) + '" alt="Store profile picture" style="width:100%;height:100%;object-fit:cover">' : '<span>' + escapeHtml((profile.business_name || "W").slice(0, 1).toUpperCase()) + '</span>') + '</div><div><b>Store profile picture</b><small class="muted">Upload a clear photo or logo students can recognize.</small><label class="button-outline" style="display:inline-flex;margin-top:7px;cursor:pointer">Choose picture<input data-profile-image type="file" accept="image/jpeg,image/png,image/webp" hidden></label></div></div>' +
        '<label class="field">Business name<input name="business_name" value="' + escapeHtml(profile.business_name) + '" required></label>' +
        '<label class="field">Description<textarea name="description">' + escapeHtml(profile.description || "") + '</textarea></label>' +
        '<label class="field">Phone<input name="phone" value="' + escapeHtml(profile.phone || "") + '" required></label>' +
        '<div class="retailer-location-card"><div><b>Pickup location</b><small>Choose an existing campus point, or use your current GPS location for your exact shop.</small></div>' +
        '<label class="field">Campus pickup point<select name="location_id"><option value="">Choose a pickup point</option>' + locationOptions + '</select></label>' +
        '<button type="button" class="button-outline" data-action="retailer-current-location">Use my current location</button>' +
        locationStatus + '</div>' +
        '<div class="form-actions"><button class="button-primary">Save profile</button>' +
        '<button type="button" class="button-outline" data-action="retailer-availability" data-open="' + (!open) + '">' + (open ? "Close store" : "Open store") + '</button></div></form>';
      return dashboardPage("Store profile", "Manage your campus storefront details, availability and pickup location.", form);
    }
    if (section === "products") {
      const products = await apiFetch("/retailers/me/products");
      const productRows = Array.isArray(products) ? products : [];
      const items = productRows.map(product => {
        const listing = Array.isArray(product?.listings) ? product.listings.find(item => item?.retailer_product_id) || product.listings[0] : null;
        if (!product || !listing) return "";
        const listingId = listing.retailer_product_id || listing.id;
        const price = Number(listing.price_ugx || 0);
        const stock = Number(listing.stock_available || 0);
        return '<div class="dashboard-list-item"><div class="dashboard-item-main"><span class="mini-product-image placeholder">W</span><span><b>' +
          escapeHtml(product.name || "Unnamed product") + '</b><small>' + money(price) + ' · ' + stock + ' available</small></span></div>' +
          '<div class="row-actions"><button data-action="edit-retailer-product" data-listing-id="' + escapeHtml(listingId) +
          '" data-name="' + escapeHtml(product.name || "") + '" data-price="' + price + '">Edit</button>' +
          '<button data-action="deactivate-retailer-product" data-listing-id="' + escapeHtml(listingId) + '">Deactivate</button></div></div>';
      }).filter(Boolean).join("");
      const content = '<div class="dashboard-toolbar"><span class="muted">' + products.length + ' listings</span><button class="button-primary" data-action="new-product">Add product</button></div>' +
        (items || dashboardEmpty("No listings yet.", "Add your first product to start selling on WEWE."));
      return dashboardPage("Products", "Create, price, stock and manage your active campus listings.", content);
    }
    if (section === "fulfillments") {
      const items = fulfillments.map(row =>
        '<div class="order-card"><div class="panel-head"><div><b>' + escapeHtml(row.order_number || row.id) + '</b><small>' +
        (row.items || []).map(item => escapeHtml(item.name) + " × " + Number(item.quantity)).join(" · ") +
        '</small></div>' + statusBadge(row.status) + '</div><div class="row-actions">' +
        (row.status === "PENDING" ? '<button data-action="fulfillment-action" data-id="' + escapeHtml(row.id) + '" data-status="confirm">Confirm</button><button data-action="fulfillment-action" data-id="' + escapeHtml(row.id) + '" data-status="reject">Reject</button>' : '') +
        (row.status === "CONFIRMED" ? '<button data-action="fulfillment-action" data-id="' + escapeHtml(row.id) + '" data-status="preparing">Start preparing</button>' : '') +
        (row.status === "PREPARING" ? '<button data-action="fulfillment-action" data-id="' + escapeHtml(row.id) + '" data-status="ready">Mark ready</button>' : '') +
        '</div></div>'
      ).join("");
      return dashboardPage("Fulfilments", "Accept orders, prepare them and mark them ready.", items || dashboardEmpty("No fulfilments waiting.", "New orders assigned to your store will appear here."));
    }
    const products = await apiFetch("/retailers/me/products");
    const pending = fulfillments.filter(item => item.status === "PENDING").length;
    const queue = fulfillments.slice(0, 4).map(row =>
      '<div class="dashboard-list-item"><div><b>' + escapeHtml(row.order_number || row.id) + '</b><small>' + escapeHtml(row.status) + '</small></div>' + statusBadge(row.status) + '</div>'
    ).join("");
    return '<div class="dashboard-hero"><div><span class="eyebrow">Retailer workspace</span><h2>' +
      escapeHtml(profile.business_name) + ' <span class="role-pill">' + escapeHtml(profile.verification_status) +
      '</span></h2><p>Manage your campus store, listings and customer fulfilments.</p></div>' +
      '<button class="button-primary" data-action="dashboard-section" data-section="products">Manage products →</button></div>' +
      '<div class="stat-grid dashboard-stat-grid"><div class="stat-card"><span>WEWE owes you</span><b class="stat-value">' +
      money(earnings.owed_by_wewe_ugx) + '</b><small>Net unpaid retailer earnings</small></div><div class="stat-card"><span>Available to settle</span><b class="stat-value">' +
      money(earnings.available_to_settle_ugx) + '</b><small>' + (earnings.eligible_for_settlement ? "Eligible for scheduled payout" : "Building toward minimum") + '</small></div>' +
      '<div class="stat-card"><span>Pending payout</span><b class="stat-value">' + money(earnings.pending_payout_ugx) + '</b><small>In payout queue</small></div><div class="stat-card"><span>Store status</span><b class="stat-value stat-text">' +
      (profile.status === "ACTIVE" ? "Open" : "Closed") + '</b><small>Customer visibility</small></div>' +
      '<div class="stat-card"><span>Verification</span><b class="stat-value stat-text">' + escapeHtml(profile.verification_status) +
      '</b><small>Account review</small></div><div class="stat-card"><span>Listings</span><b class="stat-value">' + products.length +
      '</b><small>Catalogue items</small></div><div class="stat-card"><span>Pending fulfilments</span><b class="stat-value">' + pending +
      '</b><small>Need attention</small></div></div><div class="dashboard-grid-3"><div class="dashboard-panel dashboard-span-2">' +
      '<div class="panel-head"><div><h2>Fulfilment queue</h2><small>Orders requiring store action</small></div>' +
      '<button class="text-link" data-action="dashboard-section" data-section="fulfillments">Open queue →</button></div>' +
      (queue || dashboardEmpty("Queue is clear.", "There are no fulfilments waiting.")) +
      '</div><div class="dashboard-panel"><h2>Store controls</h2><div class="quick-actions">' +
      '<button data-action="dashboard-section" data-section="products">📦 Products</button>' +
      '<button data-action="dashboard-section" data-section="fulfillments">🧾 Fulfilments</button>' +
      '<button data-action="dashboard-section" data-section="profile">⚙ Store profile</button></div></div></div>';
  }

  function mapsDirectionsUrl(point) {
    const name = point?.name || point?.address || "";
    const lat = Number(point?.latitude), lng = Number(point?.longitude);
    const destination = Number.isFinite(lat) && Number.isFinite(lng) ? `${lat},${lng}` : name;
    return destination ? `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(destination)}` : "";
  }

  function riderJobCard(row, compact = false, offer = false) {
    const pickup = row.pickup?.name || row.retailer_name || "Collection point";
    const dropoff = row.dropoff?.name || row.delivery_point_name || "Customer destination";
    const pickupNav = mapsDirectionsUrl(row.pickup);
    const dropoffNav = mapsDirectionsUrl(row.dropoff);
    const nextAction = offer
      ? `<button class="rider-primary-action" data-action="accept-delivery" data-id="${escapeHtml(row.id)}">Accept delivery</button>`
      : row.status === "ACCEPTED"
        ? `<div class="rider-action-stack"><button class="rider-primary-action" data-action="delivery-status" data-id="${escapeHtml(row.id)}" data-status="PICKED_UP">Confirm pickup</button><button class="button-outline" data-action="release-delivery" data-id="${escapeHtml(row.id)}">Release before pickup</button></div>`
        : row.status === "PICKED_UP"
          ? `<button class="rider-primary-action" data-action="delivery-status" data-id="${escapeHtml(row.id)}" data-status="OUT_FOR_DELIVERY">Start delivery</button>`
          : row.status === "OUT_FOR_DELIVERY"
            ? `<form data-form="delivery-code" data-id="${escapeHtml(row.id)}" class="rider-code-form"><input name="confirmation_code" required minlength="4" maxlength="12" placeholder="Customer code"><button class="rider-primary-action">Complete delivery</button></form>`
            : "";
    return `<article class="rider-job-card ${compact ? "compact" : ""}">
      <div class="rider-job-top"><div><span class="rider-job-label">Delivery ${escapeHtml(row.order_number || row.id || "")}</span><h3>${escapeHtml(pickup)}</h3></div>${statusBadge(row.status)}</div>
      <div class="rider-route"><div class="rider-stop"><span class="rider-stop-dot pickup"></span><div><small>PICKUP</small><b>${escapeHtml(pickup)}</b></div>${pickupNav ? `<a href="${pickupNav}" target="_blank" rel="noopener noreferrer">Navigate</a>` : ""}</div>
      <div class="rider-route-line"></div><div class="rider-stop"><span class="rider-stop-dot dropoff"></span><div><small>DROP-OFF</small><b>${escapeHtml(dropoff)}</b></div>${dropoffNav ? `<a href="${dropoffNav}" target="_blank" rel="noopener noreferrer">Navigate</a>` : ""}</div></div>
      ${nextAction ? `<div class="rider-job-actions">${nextAction}</div>` : ""}</article>`;
  }



  async function refreshInAppNotifications() {
    if (!state.user) return;
    try {
      const rows = await apiFetch("/notifications?unread_only=true&limit=20");
      state.unreadNotifications = rows || [];
      renderNotificationBadge();
    } catch {}
  }

  function renderNotificationBadge() {
    const count = state.unreadNotifications?.length || 0;
    document.querySelectorAll("[data-notification-count]").forEach(el => {
      el.textContent = count > 99 ? "99+" : String(count);
      el.hidden = count === 0;
    });
  }

  function startNotificationPolling() {
    if (notificationRefreshTimer) clearInterval(notificationRefreshTimer);
    notificationRefreshTimer = setInterval(refreshInAppNotifications, 5000);
  }

  function stopNotificationPolling() {
    if (notificationRefreshTimer) clearInterval(notificationRefreshTimer);
    notificationRefreshTimer = null;
  }

  function stopIncomePolling() { if (state.incomeRefreshTimer) clearInterval(state.incomeRefreshTimer); state.incomeRefreshTimer = null; }

  function stopRiderLocationTracking() {
    if (state.riderLocationWatchId !== null && navigator.geolocation) navigator.geolocation.clearWatch(state.riderLocationWatchId);
    state.riderLocationWatchId = null;
  }

  async function publishRiderLocation(position) {
    const coords = position?.coords;
    if (!coords || !Number.isFinite(coords.latitude) || !Number.isFinite(coords.longitude)) return;
    await apiFetch("/deliveries/me/location", { method: "PATCH", body: JSON.stringify({
      latitude: coords.latitude, longitude: coords.longitude,
      accuracy_m: Number.isFinite(coords.accuracy) ? Math.max(0, coords.accuracy) : 0,
      heading_deg: Number.isFinite(coords.heading) && coords.heading >= 0 ? coords.heading : null,
      speed_mps: Number.isFinite(coords.speed) && coords.speed >= 0 ? coords.speed : null
    }) });
  }

  async function startRiderLocationTracking({requireInitialFix = true} = {}) {
    if (state.user?.role !== "DELIVERY_AGENT" || !navigator.geolocation) throw new Error("Location sharing is required for delivery work.");
    if (state.riderLocationWatchId !== null) return;
    const options = { enableHighAccuracy: true, maximumAge: 15000, timeout: 15000 };
    if (requireInitialFix) {
      const position = await new Promise((resolve, reject) => navigator.geolocation.getCurrentPosition(resolve, reject, options));
      await publishRiderLocation(position);
    }
    state.riderLocationWatchId = navigator.geolocation.watchPosition(
      position => publishRiderLocation(position).catch(error => { if (error.status === 409 || error.status === 403) stopRiderLocationTracking(); }),
      () => showToast("WEWE could not refresh your location. Keep location permission enabled while online."),
      options
    );
  }

  function syncRiderOfferPolling() {
    if (state.riderOfferRefreshTimer) { clearInterval(state.riderOfferRefreshTimer); state.riderOfferRefreshTimer = null; }
    if (state.user?.role === "DELIVERY_AGENT" && state.dashboardSection === "available") {
      state.riderOfferRefreshTimer = setInterval(() => {
        if (state.dashboardSection !== "available" || state.user?.role !== "DELIVERY_AGENT") return syncRiderOfferPolling();
        renderDashboard().catch(() => {});
      }, 5000);
    }
  }

  function riderOfferCard(offer) {
    const expiresIn = Math.max(0, Math.ceil((Date.parse(offer.expires_at) - Date.now()) / 1000));
    const pickup = offer.delivery?.pickup;
    return [
      '<article class="rider-dispatch-offer">',
      '<div class="rider-dispatch-offer-head"><div><span class="eyebrow">NEW DELIVERY OFFER</span><h3>', escapeHtml(offer.delivery?.retailer_name || "WEWE retailer"), '</h3></div><span class="rider-offer-timer">', expiresIn, 's</span></div>',
      '<div class="rider-dispatch-route"><div><small>PICKUP</small><b>', escapeHtml(pickup?.name || "Pickup point"), '</b>', pickup?.directions ? '<span>' + escapeHtml(pickup.directions) + '</span>' : "", '</div><strong>≈ ', Math.round(Number(offer.distance_m || 0)).toLocaleString(), ' m</strong></div>',
      '<div class="rider-dispatch-meta"><span>Order ', escapeHtml(offer.delivery?.order_number || "—"), '</span><span>Offer ', escapeHtml(offer.offer_sequence), '</span></div>',
      '<div class="rider-dispatch-actions"><button class="rider-primary-action" data-action="accept-delivery-offer" data-id="', escapeHtml(offer.id), '">Accept delivery</button><button class="button-outline" data-action="reject-delivery-offer" data-id="', escapeHtml(offer.id), '">Decline</button></div>',
      '</article>'
    ].join("");
  }
  async function agentDashboard() {
    const section = state.dashboardSection;
    const profilePromise = apiFetch("/deliveries/me/profile");
    if (section === "profile") {
      const profile = await profilePromise;
      const available = profile.availability_status === "AVAILABLE";
      return dashboardPage("Rider profile","Keep your contact and transport details ready for delivery work.",`<div class="rider-profile-grid"><div class="rider-profile-card"><div class="rider-avatar-large" style="overflow:hidden">${safeImage(profile.profile_image_url) ? '<img src="' + escapeHtml(safeImage(profile.profile_image_url)) + '" alt="Rider profile picture" style="width:100%;height:100%;object-fit:cover">' : escapeHtml((state.user.name || "?").slice(0,1).toUpperCase())}</div><div><h3>${escapeHtml(state.user.name)}</h3><span>${escapeHtml(profile.verification_status || "PENDING")} verification</span></div><label class="button-outline" style="display:inline-flex;cursor:pointer">Choose picture<input data-profile-image type="file" accept="image/jpeg,image/png,image/webp" hidden></label></div>
      <form data-form="agent-profile" class="api-form dashboard-form rider-form"><label class="field">Phone<input name="phone" value="${escapeHtml(profile.phone || "")}" autocomplete="tel"></label><label class="field">Transport mode<input name="transport_mode" value="${escapeHtml(profile.transport_mode || "")}" placeholder="Bicycle, motorcycle, car…" maxlength="40"></label><button class="rider-primary-action">Save rider profile</button></form>
      <div class="rider-status-panel"><div><small>WORK STATUS</small><strong>${available ? "You are online" : "You are offline"}</strong><span>${available ? "New delivery offers can reach you." : "Go online when you are ready to receive work."}</span></div><button class="${available ? "rider-offline-button" : "rider-online-button"}" data-action="agent-availability" data-status="${available ? "OFFLINE" : "AVAILABLE"}">${available ? "Go offline" : "Go online"}</button></div></div>`);
    }
    const [profile, earnings, active] = await Promise.all([profilePromise, apiFetch("/deliveries/me/earnings"), apiFetch("/deliveries/me")]);
    const activeJob = (active || []).find(row => row.status !== "DELIVERED" && row.status !== "CANCELLED");
    if (section === "earnings") {
      return dashboardPage("Earnings","Live view of what WEWE owes you from completed deliveries and what has already been paid.",`<div class="rider-earnings-grid"><div class="rider-earnings-card"><span>WEWE owes you</span><strong>${money(earnings.owed_by_wewe_ugx ?? earnings.pending_ugx)}</strong><small>Unpaid delivery earnings</small></div><div class="rider-earnings-card"><span>Paid</span><strong>${money(earnings.paid_ugx)}</strong><small>Recorded paid earnings</small></div></div><div class="rider-info-card"><b>${earnings.payout_status === "AWAITING_SCHEDULED_PAYOUT" ? "Awaiting scheduled payout" : "Up to date"}</b><span>Your earnings are tied to completed delivery records and payout records.</span></div>`);
    }
    if (section === "available") {
      if (profile.availability_status === "AVAILABLE") {
        try { await startRiderLocationTracking({requireInitialFix: true}); } catch {}
      }
      const offers = profile.availability_status === "AVAILABLE" ? await apiFetch("/deliveries/me/offers") : [];
      syncRiderOfferPolling();
      return dashboardPage("Delivery offers", profile.availability_status === "AVAILABLE" ? "Fresh dispatch offers appear here while you are online." : "Go online to receive delivery offers.", `<div class="rider-offer-toolbar"><div><span class="rider-live-dot"></span><b>${profile.availability_status === "AVAILABLE" ? "Online and location sharing" : "Offline"}</b></div><button class="button-outline" data-action="agent-availability" data-status="${profile.availability_status === "AVAILABLE" ? "OFFLINE" : "AVAILABLE"}">${profile.availability_status === "AVAILABLE" ? "Go offline" : "Go online"}</button></div>${profile.availability_status !== "AVAILABLE" ? '<div class="rider-empty"><h3>You are offline</h3><p>Switch to online to become eligible for new delivery offers.</p></div>' : ((offers || []).map(riderOfferCard).join("") || '<div class="rider-empty"><h3>Waiting for dispatch</h3><p>Keep location sharing enabled. WEWE will offer eligible ready deliveries to you.</p></div>')}`);
    }
    if (section === "active") {
      return dashboardPage("Active delivery","One delivery at a time, with the next action made obvious.",activeJob ? riderJobCard(activeJob) : '<div class="rider-empty"><h3>No active delivery</h3><p>When you accept a delivery, the pickup and drop-off steps will appear here.</p><button class="rider-primary-action" data-action="dashboard-section" data-section="available">View delivery offers</button></div>');
    }
    if (section === "history") {
      const rows = await apiFetch("/deliveries/me/history");
      return dashboardPage("Delivery history","Review completed deliveries and their recorded status.",(rows || []).map(row => riderJobCard(row, true)).join("") || '<div class="rider-empty"><h3>No completed deliveries yet</h3><p>Your completed delivery history will appear here.</p></div>');
    }
    const current = activeJob ? riderJobCard(activeJob) : '<div class="rider-empty"><div class="rider-empty-icon">✓</div><h3>Ready when you are</h3><p>Go online to receive eligible delivery offers from WEWE.</p><button class="rider-primary-action" data-action="agent-availability" data-status="AVAILABLE">Go online</button></div>';
    const availableLabel = profile.availability_status === "AVAILABLE" ? "Online" : "Offline";
    return `<div class="rider-hero"><div><span class="eyebrow">WEWE delivery desk</span><h2>Welcome, ${escapeHtml(state.user.name.split(" ")[0] || state.user.name)}.</h2><p>Stay available, accept a job, follow the pickup-to-drop-off flow and keep customers updated.</p></div><div class="rider-online-control ${profile.availability_status === "AVAILABLE" ? "online" : ""}"><span class="rider-live-dot"></span><b>${availableLabel}</b><button data-action="agent-availability" data-status="${profile.availability_status === "AVAILABLE" ? "OFFLINE" : "AVAILABLE"}">${profile.availability_status === "AVAILABLE" ? "Go offline" : "Go online"}</button></div></div>
      <div class="rider-stats"><div><span>Current status</span><strong>${escapeHtml(profile.availability_status)}</strong><small>Work availability</small></div><div><span>Paid earnings</span><strong>${money(earnings.paid_ugx)}</strong><small>Recorded paid amount</small></div><div><span>Pending earnings</span><strong>${money(earnings.pending_ugx)}</strong><small>Awaiting payout</small></div><div><span>Active job</span><strong>${activeJob ? "1" : "0"}</strong><small>Assigned deliveries</small></div></div>
      <div class="rider-layout"><section><div class="rider-section-head"><div><h3>${activeJob ? "Your active delivery" : "Your next job"}</h3><p>${activeJob ? "Complete the current step before taking another job." : "Your delivery workspace is ready."}</p></div><button class="text-link" data-action="dashboard-section" data-section="available">View offers →</button></div>${current}</section><aside class="rider-side-card"><h3>Rider shortcuts</h3><button data-action="dashboard-section" data-section="available">🚚 Delivery offers</button><button data-action="dashboard-section" data-section="history">🧾 Delivery history</button><button data-action="dashboard-section" data-section="earnings">UGX Earnings</button><button data-action="dashboard-section" data-section="profile">⚙ Rider profile</button></aside></div>`;
  }

  async function newCategory() {
    setModal(`<div class="modal-head"><div><div class="section-kicker">Administration</div><h2>Add category</h2></div><button class="close-modal" data-action="close-modal">×</button></div><form data-form="new-category" class="api-form"><label class="field">Category name<input name="name" required minlength="2" maxlength="100"></label><label class="field">Slug<input name="slug" required minlength="2" maxlength="120" pattern="[a-z0-9]+(?:-[a-z0-9]+)*" placeholder="e.g. campus-food"></label><label class="field">Sort order<input name="sort_order" type="number" min="0" step="1" value="0"></label><p class="form-message" aria-live="polite"></p><button class="button-primary">Create category</button></form>`);
  }

  async function createCategory(form) {
    const values = Object.fromEntries(new FormData(form));
    await apiFetch("/admin/categories", { method: "POST", body: JSON.stringify({
      name: values.name.trim(),
      slug: values.slug.trim().toLowerCase(),
      sort_order: Number(values.sort_order || 0)
    }) });
    showToast("Category created.");
    closeModal();
    await renderDashboard();
    await loadCatalog();
  }

  async function showAdminDeliveryAssignment(assignmentId) {
    const agents = await apiFetch("/admin/delivery-agents?verification_status=VERIFIED");
    const available = (agents || []).filter(agent => agent.availability_status === "AVAILABLE");
    setModal(`<div class="modal-head"><div><div class="section-kicker">Dispatch</div><h2>Assign delivery</h2></div><button class="close-modal" data-action="close-modal">×</button></div>${available.length ? available.map(agent => `<button class="dashboard-list-item admin-assign-agent" data-action="admin-assign-delivery" data-assignment-id="${escapeHtml(assignmentId)}" data-agent-id="${escapeHtml(agent.user_id)}"><span><b>${escapeHtml(agent.name)}</b><small>${escapeHtml(agent.transport_mode || "Delivery agent")} · ${escapeHtml(agent.phone || "")}</small></span><b>Assign</b></button>`).join("") : '<div class="dashboard-empty"><h3>No verified rider is available</h3><p>Only verified, active and available riders can be assigned.</p></div>'}`);
  }

  async function adminOrderAction(orderId, status) {
    const reason = prompt(status === "CANCELLED" ? "Reason for cancelling this order:" : "Reason for failing this order:");
    if (reason === null) return;
    if (reason.trim().length < 3) throw new Error("Please provide a reason of at least 3 characters.");
    await apiFetch(`/admin/orders/${encodeURIComponent(orderId)}/status`, { method: "PATCH", body: JSON.stringify({ status, reason: reason.trim() }) });
    showToast(status === "CANCELLED" ? "Order cancelled." : "Order marked failed.");
    return renderDashboard();
  }

  function dashboardPage(title,subtitle,content){return `<div class="dashboard-page-head"><div><span class="eyebrow">WEWE workspace</span><h2>${escapeHtml(title)}</h2><p>${escapeHtml(subtitle)}</p></div></div><div class="dashboard-panel dashboard-content-panel">${content}</div>`;}
  function dashboardEmpty(title,subtitle){return `<div class="dashboard-empty"><div class="empty-icon">W</div><h3>${escapeHtml(title)}</h3><p>${escapeHtml(subtitle)}</p></div>`;}
  function dashboardTable(columns,rows,actions){return `<div class="dashboard-table"><div class="dashboard-table-head">${columns.map(c=>`<span>${escapeHtml(c)}</span>`).join("")}<span>Actions</span></div>${rows.map(r=>`<div class="dashboard-table-row">${r.cells.map(cell=>`<span>${cell}</span>`).join("")}<span class="row-actions">${actions(r.raw)}</span></div>`).join("")}</div>`;}
  function sectionLabel(s){return ({users:"Users",retailers:"Retailers",products:"Products",orders:"Orders",agents:"Delivery agents",reviews:"Reviews",analytics:"Analytics",categories:"Categories",settlements:"Settlements",settings:"Settings",audit:"Audit log", "rider-payouts":"Rider payouts", reconciliation:"Financial reconciliation"})[s]||"Workspace";}
  async function adminDashboard(){
    const section=state.dashboardSection;
    if(section==="overview"){const [m,statuses,pending]=await Promise.all([apiFetch("/admin/metrics"),apiFetch("/admin/reports/order-statuses"),apiFetch("/admin/retailers?verification_status=PENDING")]);return `<div class="dashboard-hero admin-hero"><div><span class="eyebrow">Admin control center</span><h2>Platform overview</h2><p>Monitor marketplace health and resolve operational issues from one workspace.</p></div><div class="admin-hero-actions"><button class="button-primary" data-action="dashboard-section" data-section="retailers">Review retailers</button><button class="button-outline" data-action="dashboard-section" data-section="settlements">Settlements</button></div></div><div class="stat-grid dashboard-stat-grid"><div class="stat-card"><span>Users</span><b class="stat-value">${m.users??m.total_users??0}</b><small>Registered accounts</small></div><div class="stat-card"><span>Orders</span><b class="stat-value">${m.orders??m.total_orders??0}</b><small>Platform orders</small></div><div class="stat-card"><span>Active retailers</span><b class="stat-value">${m.active_retailers??0}</b><small>Verified and active</small></div><div class="stat-card"><span>Pending verification</span><b class="stat-value">${m.pending_retailers??pending.length}</b><small>Needs review</small></div></div><div class="dashboard-grid-3"><div class="dashboard-panel dashboard-span-2"><div class="panel-head"><div><h2>Order health</h2><small>Current status distribution</small></div><button class="text-link" data-action="dashboard-section" data-section="orders">Open orders →</button></div><div class="status-bars">${(Array.isArray(statuses)?statuses:Object.entries(statuses||{}).map(([status,count])=>({status,count}))).map(x=>`<div class="status-bar-row"><div><span>${escapeHtml(x.status||x.key||"Unknown")}</span><b>${x.count??x.total??0}</b></div><div class="status-bar"><i style="width:${Math.min(100,Number(x.count??x.total??0))}%"></i></div></div>`).join("")}</div></div><div class="dashboard-panel"><h2>Quick actions</h2><div class="quick-actions"><button data-action="dashboard-section" data-section="users">👥 Users</button><button data-action="dashboard-section" data-section="products">📦 Products</button><button data-action="dashboard-section" data-section="analytics">📊 Analytics</button><button data-action="dashboard-section" data-section="audit">🛡 Audit log</button></div></div></div>`;}
    if(section==="analytics"){
      const [metrics, products, categories, deliveries, retailers] = await Promise.all([
        apiFetch("/admin/metrics"),
        apiFetch("/admin/reports/popular-products?limit=8"),
        apiFetch("/admin/reports/popular-categories?limit=8"),
        apiFetch("/admin/reports/deliveries?limit=8"),
        apiFetch("/admin/reports/retailers?limit=8")
      ]);
      const deliveredOrders = Number(metrics.completed_deliveries || 0);
      const totalOrders = Number(metrics.orders || 0);
      const inProgress = Number(metrics.deliveries_in_progress || 0);
      const grossSales = Number(metrics.gross_sales_ugx || 0);
      const aov = deliveredOrders ? Math.round(grossSales / deliveredOrders) : 0;
      const deliveryRate = totalOrders ? Math.round((deliveredOrders / totalOrders) * 100) : 0;
      const productMax = Math.max(1, ...products.map(x => Number(x.units_sold || 0)));
      const categoryMax = Math.max(1, ...categories.map(x => Number(x.units_sold || 0)));
      const retailerMax = Math.max(1, ...retailers.map(x => Number(x.orders || 0)));

      const rankList = (items, valueKey, formatter, max, empty) => items.length ? items.map((x, i) => {
        const value = Number(x[valueKey] || 0);
        const width = Math.max(3, Math.round((value / max) * 100));
        return `<div class="analytics-rank">
          <div class="analytics-rank-top"><span><b>${i + 1}</b>${escapeHtml(x.name || x.business_name || "Unnamed")}</span><strong>${formatter(value)}</strong></div>
          <div class="analytics-track"><i style="width:${width}%"></i></div>
        </div>`;
      }).join("") : `<div class="analytics-empty">${escapeHtml(empty)}</div>`;

      const salesRows = products.map(x => `<tr><td>${escapeHtml(x.name)}</td><td>${Number(x.units_sold || 0).toLocaleString()}</td><td>${money(x.sales_ugx)}</td></tr>`).join("");
      const deliveryRows = deliveries.map(x => `<tr><td>${escapeHtml(x.name)}</td><td>${Number(x.completed_deliveries || 0).toLocaleString()}</td><td>${money(x.earnings_ugx)}</td></tr>`).join("");
      const retailerRows = retailers.map(x => `<tr><td>${escapeHtml(x.business_name || x.name || "Retailer")}</td><td>${Number(x.orders || x.completed_orders || 0).toLocaleString()}</td><td>${money(x.sales_ugx || x.revenue_ugx || 0)}</td></tr>`).join("");

      return dashboardPage("Analytics & reports","A visual view of platform performance. Figures reflect the data currently recorded in WEWE.",`
        <div class="analytics-toolbar">
          <div><span class="analytics-live-dot"></span><b>Live platform data</b><span>All-time totals from completed records</span></div>
          <button class="button-outline" data-action="dashboard-section" data-section="analytics">↻ Refresh</button>
        </div>

        <div class="analytics-kpis">
          <article class="analytics-kpi"><span>Gross sales</span><strong>${money(grossSales)}</strong><small>Delivered orders</small></article>
          <article class="analytics-kpi"><span>Total orders</span><strong>${totalOrders.toLocaleString()}</strong><small>All order statuses</small></article>
          <article class="analytics-kpi"><span>Average order value</span><strong>${money(aov)}</strong><small>Based on delivered orders</small></article>
          <article class="analytics-kpi"><span>Delivery completion</span><strong>${deliveryRate}%</strong><small>${deliveredOrders.toLocaleString()} completed</small></article>
        </div>

        <div class="analytics-grid analytics-grid-main">
          <section class="analytics-card analytics-span-2">
            <div class="analytics-card-head"><div><h3>Top products</h3><p>Products generating the most delivered units</p></div><span class="analytics-badge">Units sold</span></div>
            <div class="analytics-bars">${rankList(products, "units_sold", v => v.toLocaleString(), productMax, "No delivered product sales yet.")}</div>
          </section>
          <section class="analytics-card">
            <div class="analytics-card-head"><div><h3>Order pipeline</h3><p>Current operational load</p></div></div>
            <div class="analytics-pipeline">
              <div><span>All orders</span><b>${totalOrders.toLocaleString()}</b></div>
              <div><span>In delivery</span><b>${inProgress.toLocaleString()}</b></div>
              <div><span>Delivered</span><b>${deliveredOrders.toLocaleString()}</b></div>
              <div class="analytics-pipeline-track"><i style="width:${Math.min(100, deliveryRate)}%"></i></div>
            </div>
          </section>
        </div>

        <div class="analytics-grid">
          <section class="analytics-card">
            <div class="analytics-card-head"><div><h3>Sales by category</h3><p>Delivered units by marketplace category</p></div></div>
            <div class="analytics-bars">${rankList(categories, "units_sold", v => v.toLocaleString(), categoryMax, "No category sales yet.")}</div>
          </section>
          <section class="analytics-card">
            <div class="analytics-card-head"><div><h3>Retailer performance</h3><p>Current activity across retailers</p></div></div>
            <div class="analytics-bars">${rankList(retailers, "orders", v => v.toLocaleString(), retailerMax, "No retailer performance data yet.")}</div>
          </section>
        </div>

        <div class="analytics-grid">
          <section class="analytics-card">
            <div class="analytics-card-head"><div><h3>Product sales detail</h3><p>Delivered units and sales value</p></div></div>
            <div class="analytics-table-wrap"><table class="analytics-table"><thead><tr><th>Product</th><th>Units</th><th>Sales</th></tr></thead><tbody>${salesRows || '<tr><td colspan="3" class="analytics-empty">No data available</td></tr>'}</tbody></table></div>
          </section>
          <section class="analytics-card">
            <div class="analytics-card-head"><div><h3>Delivery performance</h3><p>Completed deliveries and recorded earnings</p></div></div>
            <div class="analytics-table-wrap"><table class="analytics-table"><thead><tr><th>Agent</th><th>Deliveries</th><th>Earnings</th></tr></thead><tbody>${deliveryRows || '<tr><td colspan="3" class="analytics-empty">No data available</td></tr>'}</tbody></table></div>
          </section>
        </div>

        <section class="analytics-card">
          <div class="analytics-card-head"><div><h3>Retailer sales detail</h3><p>Performance from the retailer report</p></div></div>
          <div class="analytics-table-wrap"><table class="analytics-table"><thead><tr><th>Retailer</th><th>Orders</th><th>Sales</th></tr></thead><tbody>${retailerRows || '<tr><td colspan="3" class="analytics-empty">No data available</td></tr>'}</tbody></table></div>
        </section>
      `);
    }
    if(section==="categories"){const rows=await apiFetch("/categories");return dashboardPage("Categories","Keep the marketplace taxonomy organized.",`<div class="dashboard-toolbar"><button class="button-primary" data-action="new-category">Add category</button></div>${rows.map(x=>`<div class="dashboard-list-item"><b>${escapeHtml(x.name)}</b><small>${escapeHtml(x.description||"Marketplace category")}</small></div>`).join("")||dashboardEmpty("No categories.","Create the first marketplace category.")}`);}
    if(section==="settlements"){const data=await apiFetch("/admin/settlements"),rows=Array.isArray(data)?data:data.items||[];return dashboardPage("Retailer settlements","Technical settlement operations only. Commercial eligibility and economics remain frozen until approved.",rows.length?dashboardTable(["Reference","Retailer","Amount","Status"],rows.map(raw=>({raw,cells:[escapeHtml(raw.settlement_reference||raw.id),escapeHtml(raw.retailer_id||""),money(raw.amount_ugx),statusBadge(raw.status)]})),raw=>raw.status==="DRAFT"?`<button data-action="settlement-submit" data-id="${escapeHtml(raw.id)}">Submit</button>`:raw.status==="SUBMITTED"?`<button data-action="settlement-review" data-id="${escapeHtml(raw.id)}">Review</button>`:""):dashboardEmpty("No settlement records.","Settlement records will appear here when created by the authorized workflow."));}
    if(section==="rider-payouts"){
      const rows=await apiFetch("/admin/rider-payouts");
      return dashboardPage("Rider payouts","Scheduled payout batches for delivery-agent earnings.",
        '<div class="dashboard-toolbar"><button class="button-primary" data-action="generate-rider-payouts">Generate rider payout batches</button></div>'+
        (rows.length ? dashboardTable(["Batch","Rider","Amount","Status"],rows.map(raw=>({raw,cells:[escapeHtml(raw.batch_reference||raw.id),escapeHtml(raw.agent_id||""),money(raw.amount_ugx),statusBadge(raw.status)]})),raw=>raw.status==="DRAFT"?'<button data-action="rider-payout-submit" data-id="'+escapeHtml(raw.id)+'">Submit</button>':raw.status==="SUBMITTED"?'<button data-action="rider-payout-settle" data-id="'+escapeHtml(raw.id)+'">Mark paid</button>':"") : dashboardEmpty("No rider payout batches.","Generate batches on the configured rider payout day.")));
    }
    if(section==="reconciliation"){
      const r=await apiFetch("/admin/reconciliation");
      return dashboardPage("Financial reconciliation","Control totals for retailer obligations, rider earnings and pending payout instructions.",
        '<div class="dashboard-toolbar"><button class="button-outline" data-action="dashboard-section" data-section="reconciliation">↻ Refresh</button></div>'+
        '<div class="stat-grid dashboard-stat-grid">'+
        '<div class="stat-card"><span>Retailer ledger balance</span><b class="stat-value">'+money(r.retailer?.ledger_balance_ugx||0)+'</b><small>Credits less debits</small></div>'+
        '<div class="stat-card"><span>Retailer pending payouts</span><b class="stat-value">'+money(r.retailer?.pending_settlement_ugx||0)+'</b><small>Controlled settlement instructions</small></div>'+
        '<div class="stat-card"><span>Rider pending earnings</span><b class="stat-value">'+money(r.riders?.pending_earnings_ugx||0)+'</b><small>Awaiting payout</small></div>'+
        '<div class="stat-card"><span>Tracked obligations</span><b class="stat-value">'+money(r.controls?.third_party_obligations_tracked||0)+'</b><small>Accounting control total</small></div></div>');
    }
    const paths={users:"/admin/users",retailers:"/admin/retailers",products:"/admin/products",orders:"/admin/orders",agents:"/admin/delivery-agents",reviews:"/admin/reviews",settings:"/admin/settings",audit:"/admin/audit-logs"};const data=await apiFetch(paths[section]);const rows=Array.isArray(data)?data:data.items||[];if(!rows.length)return dashboardPage(sectionLabel(section),`Manage ${sectionLabel(section).toLowerCase()} from one place.`,dashboardEmpty("Nothing here yet.","There are no records requiring action."));
    return dashboardPage(sectionLabel(section),`Manage ${sectionLabel(section).toLowerCase()} from one place.`,dashboardTable(["Item","Status","Details"],rows.map(raw=>({raw,cells:[`<b>${escapeHtml(raw.name||raw.business_name||raw.order_number||raw.action||raw.key||raw.id)}</b>`,escapeHtml(raw.verification_status||raw.status||""),escapeHtml(raw.email||raw.payment_status||raw.category_name||raw.resource_type||raw.availability_status||raw.value||"")]})),raw=>{
      const id=raw.id;
      if(section==="users") return `<button data-action="user-status" data-id="${escapeHtml(id)}" data-status="${raw.status==="ACTIVE"?"SUSPENDED":"ACTIVE"}">${raw.status==="ACTIVE"?"Suspend":"Activate"}</button>`;
      if(section==="retailers"&&raw.verification_status!=="VERIFIED") return `<button data-action="verify-retailer" data-id="${escapeHtml(raw.retailer_id||raw.id)}">Verify</button>`;
      if(section==="agents"&&raw.verification_status!=="VERIFIED") return `<button data-action="verify-agent" data-id="${escapeHtml(raw.user_id||raw.id)}">Verify</button>`;
      if(section==="products") return `<button data-action="moderate-product" data-id="${escapeHtml(id)}" data-status="${raw.status==="ACTIVE"?"REMOVED":"ACTIVE"}">${raw.status==="ACTIVE"?"Remove":"Activate"}</button>`;
      if(section==="orders") {
        const deliveryButtons=(raw.deliveries||[]).map(delivery => delivery.status==="UNASSIGNED"
          ? `<button data-action="admin-show-delivery-assignment" data-assignment-id="${escapeHtml(delivery.id)}">Assign rider</button>`
          : delivery.status==="ACCEPTED"
            ? `<button data-action="admin-release-delivery" data-id="${escapeHtml(delivery.id)}">Release rider</button>`
            : "").join("");
        const statusButton=["PENDING","CONFIRMED","PREPARING","READY"].includes(raw.status)
          ? `<button data-action="admin-order-cancel" data-id="${escapeHtml(id)}">Cancel</button>` : "";
        return statusButton + deliveryButtons;
      }
      if(section==="reviews") return `<button data-action="moderate-review" data-id="${escapeHtml(id)}" data-status="${raw.status==="VISIBLE"?"HIDDEN":"VISIBLE"}">${raw.status==="VISIBLE"?"Hide":"Publish"}</button>`;
      if(section==="settings" && raw.key==="delivery_fee_ugx") return `<button data-action="edit-delivery-fee">Edit</button>`;
      return "";
    }));
  }


  function stopOrderTracking() {
    if (state.orderTrackingTimer) clearInterval(state.orderTrackingTimer);
    state.orderTrackingTimer = null;
  }

  function orderTrackingView(tracking) {
    const deliveries = tracking?.deliveries || [];
    if (!deliveries.length) return '<div class="tracking-live-card"><b>No delivery assignment yet</b><small>WEWE will show rider tracking once a delivery assignment exists.</small></div>';
    return deliveries.map(delivery => {
      const location = delivery.location;
      const rider = delivery.rider;
      let locationHtml;
      if (delivery.status === "DELIVERED") locationHtml = '<div class="tracking-location-muted"><b>Delivered</b><small>Live rider location is no longer shared for this completed delivery.</small></div>';
      else if (delivery.location_status === "LIVE" && location) {
        const mapsUrl = mapsDirectionsUrl(location);
        locationHtml = '<div class="tracking-location-live"><span class="rider-live-dot"></span><div><b>Rider location is live</b><small>' + Number(location.accuracy_m || 0).toFixed(0) + ' m accuracy · updated ' + formatDate(location.updated_at) + '</small></div>' +
          (mapsUrl ? '<a class="button-outline tracking-map-link" href="' + escapeHtml(mapsUrl) + '" target="_blank" rel="noopener noreferrer">Open in Maps</a>' : '') +
          '</div><div class="tracking-coordinates"><span>Latitude <b>' + Number(location.latitude).toFixed(6) + '</b></span><span>Longitude <b>' + Number(location.longitude).toFixed(6) + '</b></span></div>';
      } else if (delivery.location_status === "STALE") locationHtml = '<div class="tracking-location-muted"><b>Updating rider location…</b><small>The last location is too old to display. WEWE is waiting for a fresh GPS update.</small></div>';
      else if (rider) locationHtml = '<div class="tracking-location-muted"><b>Waiting for rider location</b><small>The rider is assigned, but a fresh GPS position is not available yet.</small></div>';
      else locationHtml = '<div class="tracking-location-muted"><b>Finding your rider</b><small>WEWE is dispatching this delivery to an eligible nearby rider.</small></div>';
      return '<article class="tracking-live-card"><div class="tracking-card-head"><div><span class="section-kicker">Delivery</span><h3>' + escapeHtml(delivery.retailer_name || "Campus retailer") + '</h3></div>' + statusBadge(delivery.status) + '</div>' +
        (rider ? '<div class="tracking-rider"><div><b>' + escapeHtml(rider.name) + '</b><small>' + escapeHtml(rider.transport_mode || "Delivery agent") + '</small></div></div>' : '') +
        locationHtml + '<div class="tracking-route"><div><span>Pickup</span><b>' + escapeHtml(delivery.pickup?.name || "Retailer pickup") + '</b></div><span class="tracking-arrow">→</span><div><span>Drop-off</span><b>' + escapeHtml(delivery.dropoff?.name || "Your delivery point") + '</b></div></div></article>';
    }).join("");
  }

  function renderOrderModal(order, tracking) {
    const stages = ["PENDING", "CONFIRMED", "PREPARING", "READY", "OUT_FOR_DELIVERY", "DELIVERED"];
    const currentStage = stages.indexOf(order.status);
    const timeline = stages.map((stage, index) => '<div class="tracking-step ' + (index <= currentStage ? "done" : "") + ' ' + (stage === order.status ? "current" : "") + '"><span>' + (index <= currentStage ? "✓" : index + 1) + '</span><div><b>' + escapeHtml(stage.replaceAll("_", " ")) + '</b><small>' + (stage === order.status ? "Current status" : index < currentStage ? "Completed" : "Waiting") + '</small></div></div>').join("");
    return '<div class="modal-head"><div><div class="section-kicker">Order</div><h2>' + escapeHtml(order.order_number) + '</h2></div><button class="close-modal" data-action="close-modal">×</button></div>' +
      '<p>' + statusBadge(order.status) + ' ' + statusBadge(order.payment_status) + '</p><div class="tracking-timeline">' + timeline + '</div>' +
      '<section class="order-tracking-panel"><div class="panel-head"><div><h3>Live delivery tracking</h3><small>Updates automatically while your delivery is active.</small></div><span class="tracking-refresh-dot"></span></div>' + orderTrackingView(tracking) + '</section>' +
      (order.items || []).map(item => '<div class="listing-row"><span>' + escapeHtml(item.product_name) + ' × ' + Number(item.quantity) + '</span><b>' + money(item.line_total_ugx) + '</b></div>').join("") +
      '<div class="checkout-totals"><p>Subtotal <b>' + money(order.subtotal_ugx) + '</b></p><p>Delivery <b>' + money(order.delivery_fee_ugx) + '</b></p><p>Total <b>' + money(order.total_ugx) + '</b></p></div>';
  }

  async function showOrder(orderId) {
    stopOrderTracking();
    const [order, tracking] = await Promise.all([apiFetch("/orders/" + encodeURIComponent(orderId)), apiFetch("/orders/" + encodeURIComponent(orderId) + "/tracking")]);
    setModal(renderOrderModal(order, tracking), true);
    if ((tracking.deliveries || []).some(item => ["ACCEPTED", "PICKED_UP", "OUT_FOR_DELIVERY"].includes(item.status))) {
      state.orderTrackingTimer = setInterval(async () => {
        try {
          const [freshOrder, freshTracking] = await Promise.all([apiFetch("/orders/" + encodeURIComponent(orderId)), apiFetch("/orders/" + encodeURIComponent(orderId) + "/tracking")]);
          if (!$("#modalBackdrop")?.classList.contains("open")) return stopOrderTracking();
          $("#modalContent").innerHTML = renderOrderModal(freshOrder, freshTracking);
          if (!(freshTracking.deliveries || []).some(item => ["ACCEPTED", "PICKED_UP", "OUT_FOR_DELIVERY"].includes(item.status))) stopOrderTracking();
        } catch {}
      }, 5000);
    }
  }

  async function newProduct() {
    const categories = state.categories.length ? state.categories : await apiFetch("/categories");
    setModal(`<div class="modal-head"><h2>Add a product</h2><button class="close-modal" data-action="close-modal">×</button></div><form data-form="new-product" class="api-form"><label class="field">Product name<input name="name" required minlength="2" maxlength="220"></label><label class="field">Description<textarea name="description"></textarea></label><label class="field">Category<select name="category_id" required>${categories.map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join("")}</select></label><label class="field">Current price (UGX)<input name="price_ugx" type="number" min="1" step="1" required></label><label class="field">Old price (UGX) <small class="muted">Optional — used to show a discount</small><input name="original_price_ugx" type="number" min="1" step="1" placeholder="e.g. 50000"></label><label class="field">Stock quantity<input name="stock_quantity" type="number" min="0" step="1" required></label><label class="field">Product photos<input name="images" type="file" accept="image/jpeg,image/png,image/webp" multiple><small class="muted">JPEG, PNG or WebP · up to 12 photos · max 5 MiB each.</small></label><p class="form-message" aria-live="polite"></p><button class="button-primary">Create product</button></form>`);
  }

  async function createProduct(form) {
    const values = Object.fromEntries(new FormData(form));
    const files = [...(form.elements.images?.files || [])];
    if (files.length > 12) throw new Error("Choose no more than 12 product photos.");
    for (const file of files) {
      if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) throw new Error("Only JPEG, PNG and WebP product photos are supported.");
      if (file.size > 5 * 1024 * 1024) throw new Error("Each product photo must be 5 MiB or smaller.");
    }
    const product = await apiFetch("/retailers/me/products", { method: "POST", body: JSON.stringify({
      name: values.name,
      description: values.description || null,
      category_id: values.category_id,
      price_ugx: Number(values.price_ugx),
      original_price_ugx: values.original_price_ugx ? Number(values.original_price_ugx) : null,
      stock_quantity: Number(values.stock_quantity),
      image_urls: []
    }) });
    const listingId = product?.listings?.[0]?.retailer_product_id;
    let uploadFailures = 0;
    if (listingId) {
      for (const file of files) {
        try {
          const formData = new FormData();
          formData.append("file", file, file.name);
          formData.append("alt_text", values.name);
          await apiFetch(`/retailers/me/products/${encodeURIComponent(listingId)}/images`, { method: "POST", body: formData });
        } catch {
          uploadFailures += 1;
        }
      }
    }
    showToast(uploadFailures ? "Product created, but one or more photos failed to upload." : "Product created successfully.");
    closeModal();
    await renderDashboard();
  }

  async function editRetailerProduct(button) {
    setModal(`<div class="modal-head"><h2>Update listing</h2><button class="close-modal" data-action="close-modal">×</button></div><form data-form="edit-retailer-product" data-listing-id="${escapeHtml(button.dataset.listingId)}" class="api-form"><p>${escapeHtml(button.dataset.name)}</p><label class="field">Current price (UGX)<input name="price_ugx" type="number" min="1" step="1" value="${Number(button.dataset.price)}" required></label><label class="field">Old price (UGX) <small class="muted">Optional — must be higher than the current price</small><input name="original_price_ugx" type="number" min="1" step="1" value="${button.dataset.originalPrice ? Number(button.dataset.originalPrice) : ""}"></label><p class="form-message" aria-live="polite"></p><button class="button-primary">Save pricing</button></form>`);
  }

  async function updateRetailerProduct(form) {
    const values = Object.fromEntries(new FormData(form));
    const price = Number(values.price_ugx);
    const original = values.original_price_ugx ? Number(values.original_price_ugx) : null;
    if (original !== null && original <= price) throw new Error("Old price must be higher than the current price.");
    await apiFetch(`/retailers/me/products/${encodeURIComponent(form.dataset.listingId)}`, { method: "PATCH", body: JSON.stringify({ price_ugx: price, original_price_ugx: original }) });
    showToast("Product pricing updated.");
    closeModal();
    await renderDashboard();
  }

  async function submitForm(form) {
    const message = $(".form-message", form);
    const submit = $('button[type="submit"], button:not([type])', form);
    if (submit) submit.disabled = true;
    try {
      const action = form.dataset.form;
      if (action === "login") await login(form);
      else if (action === "register") await register(form);
      else if (action === "rider-application") await submitRiderApplication(form);
      else if (action === "checkout") await placeOrder(form);
      else if (action === "address") await saveAddress(form);
      else if (action === "review") await submitReview(form);
      else if (action === "customer-profile") await saveCustomerProfile(form);
      else if (action === "retailer-profile") await saveRetailerProfile(form);
      else if (action === "agent-profile") await saveAgentProfile(form);
      else if (action === "new-product") await createProduct(form);
      else if (action === "edit-retailer-product") await updateRetailerProduct(form);
      else if (action === "new-category") await createCategory(form);
      else if (action === "delivery-code") await updateDelivery(form.dataset.id, "DELIVERED", new FormData(form).get("confirmation_code"));
    } catch (error) {
      if (message) message.textContent = error.message;
      else showToast(error.message);
    } finally {
      if (submit && document.contains(submit)) submit.disabled = false;
    }
  }

  async function saveCustomerProfile(form) {
    const values = Object.fromEntries(new FormData(form));
    values.marketing_opt_in = form.elements.marketing_opt_in.checked;
    values.preferred_delivery_point_id = values.preferred_delivery_point_id || null;
    await apiFetch("/users/me/profile", { method: "PATCH", body: JSON.stringify(values) });
    showToast("Preferences saved.");
  }

  async function saveRetailerProfile(form) {
    const values = Object.fromEntries(new FormData(form));
    await apiFetch("/retailers/me", { method: "PATCH", body: JSON.stringify(values) });
    showToast("Store profile saved.");
  }

  async function uploadProfileImage(input) {
    const file = input.files?.[0];
    if (!file) return;
    if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) throw new Error("Only JPEG, PNG and WebP profile pictures are supported.");
    if (file.size > 5 * 1024 * 1024) throw new Error("Profile picture must be 5 MiB or smaller.");
    const formData = new FormData();
    formData.append("file", file, file.name);
    const endpoint = state.user?.role === "RETAILER" ? "/retailers/me/profile-image" : "/deliveries/me/profile-image";
    await apiFetch(endpoint, { method: "POST", body: formData });
    showToast("Profile picture updated.");
    await renderDashboard();
  }

  async function saveAgentProfile(form) {
    const values = Object.fromEntries(new FormData(form));
    await apiFetch("/deliveries/me/profile", { method: "PATCH", body: JSON.stringify(values) });
    showToast("Agent profile saved.");
  }

  async function updateDelivery(id, status, code) {
    await apiFetch(`/deliveries/${encodeURIComponent(id)}/status`, { method: "POST", body: JSON.stringify({ status, ...(code ? { confirmation_code: code } : {}) }) });
    showToast("Delivery updated.");
    await renderDashboard();
  }

  async function performAction(button) {
    const action = button.dataset.action;
    if (action === "close-modal") return closeModal();
    if (action === "toggle-password") return togglePassword(button);
    if (action === "show-register") return showAuth(true);
    if (action === "become-rider") return showRiderApplication();
    if (action === "show-login") return showAuth(false);
    if (action === "retry-catalog") return loadCatalog();
    if (action === "clear-search") { state.search = ""; state.activeCategory = "all"; state.availability = "all"; $("#searchInput").value = ""; $("#availabilityFilter").value = "all"; renderCategories(); return renderCatalog(); }
    if (action === "storefront") return showDashboard(false);
    if (action === "sign-out") return signOut();
    if (action === "dashboard-section") {
      state.dashboardSection = button.dataset.section;
      return renderDashboard();
    }
    if (action === "category") {
      state.activeCategory = button.dataset.categoryId;
      renderCategories();
      return renderCatalog();
    }
    if (action === "product-details") return showProduct(button.dataset.productId);
    if (action === "add-cart") {
      const detailQuantity = $("#detailQuantity")?.value;
      await addToCart(button.dataset.listingId, detailQuantity || button.dataset.quantity || 1);
      if ($("#cartContents")) await renderCartContents();
      return;
    }
    if (action === "toggle-wishlist") return toggleWishlist(button.dataset.productId);
    if (action === "cart-quantity") return cartQuantity(button.dataset.itemId, Number(button.dataset.quantity));
    if (action === "remove-cart") return removeCartItem(button.dataset.itemId);
    if (action === "checkout") return showCheckout();
    if (action === "use-current-location") return useCurrentLocation();
    if (action === "select-delivery-point") return selectCheckoutPoint(button.dataset.id);
    if (action === "retry-delivery-quote") return updateCheckoutQuote();
    if (action === "new-address") return showNewAddress();
    if (action === "retailer-details") return showRetailer(button.dataset.retailerSlug);
    if (action === "retry-online-payment") return retryOnlinePayment(button.dataset.orderId, button.dataset.method, button.dataset.phone, button.dataset.email);
    if (action === "order-details") return showOrder(button.dataset.id);
    if (action === "new-category") return newCategory();
    if (action === "admin-order-cancel") return adminOrderAction(button.dataset.id, "CANCELLED");
    if (action === "admin-order-fail") return adminOrderAction(button.dataset.id, "FAILED");
    if (action === "admin-show-delivery-assignment") return showAdminDeliveryAssignment(button.dataset.assignmentId);
    if (action === "admin-assign-delivery") {
      await apiFetch(`/admin/deliveries/${encodeURIComponent(button.dataset.assignmentId)}/assign`, { method: "POST", body: JSON.stringify({ agent_user_id: button.dataset.agentId }) });
      showToast("Delivery assigned.");
      closeModal();
      return renderDashboard();
    }
    if (action === "admin-release-delivery") {
      if (!confirm("Release this rider assignment before pickup?")) return;
      await apiFetch(`/admin/deliveries/${encodeURIComponent(button.dataset.id)}/release`, { method: "POST", body: JSON.stringify({}) });
      showToast("Delivery released for redispatch.");
      return renderDashboard();
    }
    if (action === "release-delivery") {
      if (!confirm("Release this delivery before pickup? It will return to dispatch.")) return;
      await apiFetch(`/deliveries/${encodeURIComponent(button.dataset.id)}/release`, { method: "POST", body: JSON.stringify({}) });
      showToast("Delivery released.");
      return renderDashboard();
    }
    if (action === "cancel-order") {
      await apiFetch(`/orders/${encodeURIComponent(button.dataset.id)}/cancel`, { method: "POST", body: JSON.stringify({}) });
      showToast("Order cancelled.");
      return renderDashboard();
    }
    if (action === "reorder") {
      await apiFetch(`/orders/${encodeURIComponent(button.dataset.id)}/reorder`, { method: "POST", body: JSON.stringify({}) });
      state.cart = await apiFetch("/cart");
      syncCartBadge();
      showToast("Items from that order were added to your cart.");
      return;
    }
    if (action === "delete-address") {
      await apiFetch(`/locations/me/delivery-points/${encodeURIComponent(button.dataset.id)}`, { method: "DELETE" });
      showToast("Delivery point removed.");
      return renderDashboard();
    }
    if (action === "read-notification") {
      await apiFetch(`/notifications/${encodeURIComponent(button.dataset.id)}/read`, { method: "POST" });
      return renderDashboard();
    }
    if (action === "fulfillment-action") {
      const reason = button.dataset.status === "reject" ? prompt("Reason for rejecting this fulfilment (optional):") : null;
      await apiFetch(`/retailers/me/fulfillments/${encodeURIComponent(button.dataset.id)}/${button.dataset.status}`, { method: "POST", body: JSON.stringify(reason ? { reason } : {}) });
      showToast(button.dataset.status === "reject" ? "Fulfilment rejected." : button.dataset.status === "confirm" ? "Fulfilment confirmed." : `Fulfilment marked ${button.dataset.status}.`);
      return renderDashboard();
    }
    if (action === "retailer-current-location") {
      if (!navigator.geolocation) throw new Error("Your browser does not provide location services.");
      const position = await new Promise((resolve, reject) => navigator.geolocation.getCurrentPosition(resolve, reject, {
        enableHighAccuracy: true, timeout: 15000, maximumAge: 30000
      }));
      const latitude = Number(position.coords.latitude);
      const longitude = Number(position.coords.longitude);
      if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) throw new Error("The browser returned an invalid location.");
      const campuses = await apiFetch("/locations/campuses");
      const campus = campuses.find(item => item.slug === "main-campus") || campuses[0];
      if (!campus) throw new Error("No WEWE campus is configured.");
      const profile = await apiFetch("/retailers/me");
      await apiFetch("/retailers/me/pickup-location", {
        method: "POST",
        body: JSON.stringify({
          campus_id: campus.id,
          kind: "PICKUP_POINT",
          name: profile.business_name + " pickup",
          directions: "Exact location captured from the retailer's device",
          latitude,
          longitude,
          google_place_id: null,
          is_private: true
        })
      });
      showToast("Exact pickup location saved.");
      return renderDashboard();
    }
    if (action === "retailer-availability") {
      await apiFetch("/retailers/me/availability", { method: "PATCH", body: JSON.stringify({ is_open: button.dataset.open === "true" }) });
      return renderDashboard();
    }
    if (action === "agent-availability") {
      const nextStatus = button.dataset.status;
      if (nextStatus === "AVAILABLE") {
        if (!navigator.geolocation) throw new Error("Location sharing is required for delivery work.");
        let initialPosition;
        try {
          initialPosition = await new Promise((resolve, reject) => navigator.geolocation.getCurrentPosition(
            resolve,
            reject,
            { enableHighAccuracy: true, maximumAge: 15000, timeout: 15000 }
          ));
        } catch (error) {
          stopRiderLocationTracking();
          throw new Error(error.code === 1 ? "Location permission is required before you can go online." : "Unable to get your current location.");
        }
        await apiFetch("/deliveries/me/availability", { method: "PATCH", body: JSON.stringify({ availability_status: nextStatus }) });
        try {
          await publishRiderLocation(initialPosition);
          await startRiderLocationTracking({requireInitialFix: false});
        } catch (error) {
          await apiFetch("/deliveries/me/availability", { method: "PATCH", body: JSON.stringify({ availability_status: "OFFLINE" }) }).catch(() => {});
          stopRiderLocationTracking();
          throw error;
        }
      } else {
        await apiFetch("/deliveries/me/availability", { method: "PATCH", body: JSON.stringify({ availability_status: nextStatus }) });
        stopRiderLocationTracking();
      }
      return renderDashboard();
    }
    if (action === "accept-delivery-offer") {
      await apiFetch(`/deliveries/offers/${encodeURIComponent(button.dataset.id)}/accept`, { method: "POST", body: JSON.stringify({}) });
      showToast("Delivery accepted.");
      return renderDashboard();
    }
    if (action === "reject-delivery-offer") {
      await apiFetch(`/deliveries/offers/${encodeURIComponent(button.dataset.id)}/reject`, { method: "POST", body: JSON.stringify({}) });
      showToast("Offer declined.");
      return renderDashboard();
    }
    if (action === "accept-delivery") {
      await apiFetch(`/deliveries/${encodeURIComponent(button.dataset.id)}/accept`, { method: "POST", body: JSON.stringify({}) });
      showToast("Delivery accepted.");
      return renderDashboard();
    }
    if (action === "delivery-status") return updateDelivery(button.dataset.id, button.dataset.status);
    if (action === "new-product") return newProduct();
    if (action === "edit-retailer-product") return editRetailerProduct(button);
    if (action === "deactivate-retailer-product") {
      if (!confirm("Deactivate this product listing? It will no longer appear in the storefront.")) return;
      await apiFetch(`/retailers/me/products/${encodeURIComponent(button.dataset.listingId)}`, { method: "DELETE" });
      showToast("Product listing deactivated.");
      return renderDashboard();
    }
    if (action === "edit-delivery-fee") {
      const amount = prompt("Delivery fee amount in UGX:", "3500");
      if (amount === null) return;
      const numeric = Number(amount);
      if (!Number.isInteger(numeric) || numeric < 0 || numeric > 100000) throw new Error("Enter an integer from 0 to 100000 UGX.");
      await apiFetch("/admin/settings/delivery_fee_ugx", { method: "PUT", body: JSON.stringify({ value: { amount: numeric } }) });
      showToast("Delivery fee setting updated.");
      return renderDashboard();
    }
    if (action === "moderate-review") {
      await apiFetch("/admin/reviews/" + encodeURIComponent(button.dataset.id) + "/moderation", { method: "PATCH", body: JSON.stringify({ status: button.dataset.status }) });
      showToast("Review moderation updated.");
      return renderDashboard();
    }
    if (action === "generate-rider-payouts") {
      await apiFetch("/admin/rider-payouts/generate", { method: "POST" });
      showToast("Rider payout batches generated.");
      return renderDashboard();
    }
    if (action === "rider-payout-submit") {
      await apiFetch("/admin/rider-payouts/" + encodeURIComponent(button.dataset.id) + "/submit", { method: "POST" });
      showToast("Rider payout submitted.");
      return renderDashboard();
    }
    if (action === "rider-payout-settle") {
      const reference = prompt("Enter the payout/provider reference:");
      if (!reference) return;
      await apiFetch("/admin/rider-payouts/" + encodeURIComponent(button.dataset.id) + "/settle", { method: "POST", body: JSON.stringify({ payout_reference: reference.trim() }) });
      showToast("Rider payout marked paid.");
      return renderDashboard();
    }
    if (action === "settlement-submit") {
      await apiFetch("/admin/settlements/" + encodeURIComponent(button.dataset.id) + "/submit", { method: "POST", body: JSON.stringify({}) });
      showToast("Settlement submitted.");
      return renderDashboard();
    }
    if (action === "settlement-review") {
      await apiFetch("/admin/settlements/" + encodeURIComponent(button.dataset.id) + "/review", { method: "POST", body: JSON.stringify({}) });
      showToast("Settlement moved to review.");
      return renderDashboard();
    }
    if (action === "user-status") {
      await apiFetch(`/admin/users/${encodeURIComponent(button.dataset.id)}/status`, { method: "PATCH", body: JSON.stringify({ status: button.dataset.status }) });
      return renderDashboard();
    }
    if (action === "verify-retailer") {
      const retailerId = button.dataset.id;
      if (!retailerId) return showToast("Missing retailer ID.");
      try {
        await apiFetch("/admin/retailers/" + encodeURIComponent(retailerId) + "/verification", { method: "PATCH", body: JSON.stringify({ status: "VERIFIED" }) });
        showToast("Retailer verified successfully.");
        return renderDashboard();
      } catch (error) {
        showToast(error.message || "Retailer verification failed.");
        return renderDashboard();
      }
    }
    if (action === "verify-agent") {
      await apiFetch(`/admin/delivery-agents/${encodeURIComponent(button.dataset.id)}/verification`, { method: "PATCH", body: JSON.stringify({ status: "VERIFIED" }) });
      return renderDashboard();
    }
    if (action === "moderate-product") {
      await apiFetch(`/admin/products/${encodeURIComponent(button.dataset.id)}/moderation`, { method: "PATCH", body: JSON.stringify({ status: button.dataset.status }) });
      return renderDashboard();
    }
  }

  function installRiderStyles() {
    if ($("#riderUiStyles")) return;
    const style = document.createElement("style");
    style.id = "riderUiStyles";
    style.textContent = `
      .rider-hero{display:flex;align-items:center;justify-content:space-between;gap:22px;padding:28px;border-radius:22px;background:linear-gradient(135deg,#281044,#7041f5);color:#fff;box-shadow:0 18px 45px rgba(55,24,91,.16);margin-bottom:18px}.rider-hero h2{margin:6px 0;font-size:30px}.rider-hero p{margin:0;color:#e8e0f5;max-width:720px}.rider-online-control{display:flex;align-items:center;gap:9px;padding:10px 12px;border-radius:14px;background:rgba(255,255,255,.10);white-space:nowrap}.rider-online-control button{border:0;border-radius:9px;padding:8px 10px;background:#fff;color:#39205e;font-weight:900}.rider-live-dot{width:9px;height:9px;border-radius:50%;background:#a8a0b5;display:inline-block}.rider-online-control.online .rider-live-dot,.rider-offer-toolbar .rider-live-dot{background:#30d18a;box-shadow:0 0 0 5px rgba(48,209,138,.14)}.rider-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:13px;margin-bottom:18px}.rider-stats>div,.rider-earnings-card{background:#fff;border:1px solid #e7e0ef;border-radius:17px;padding:17px;box-shadow:0 7px 22px rgba(45,25,90,.045)}.rider-stats span,.rider-earnings-card span{display:block;color:#83788e;font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.5px}.rider-stats strong,.rider-earnings-card strong{display:block;color:#302040;font-size:19px;margin-top:8px}.rider-stats small,.rider-earnings-card small{display:block;color:#a096aa;font-size:10px;margin-top:5px}.rider-layout{display:grid;grid-template-columns:minmax(0,1.7fr) minmax(230px,.65fr);gap:17px}.rider-section-head{display:flex;align-items:flex-end;justify-content:space-between;gap:12px;margin-bottom:10px}.rider-section-head h3{margin:0;font-size:17px}.rider-section-head p{margin:4px 0 0;color:#91879c;font-size:10px}.rider-side-card,.rider-info-card{background:#fff;border:1px solid #e7e0ef;border-radius:17px;padding:18px;box-shadow:0 7px 22px rgba(45,25,90,.045)}.rider-side-card h3{margin:0 0 10px;font-size:15px}.rider-side-card button{display:block;width:100%;border:1px solid #e7e0ef;background:#faf8fd;border-radius:11px;padding:12px;text-align:left;margin-top:8px;color:#564b63;font-weight:800}.rider-job-card{background:#fff;border:1px solid #e4dced;border-radius:18px;padding:18px;box-shadow:0 8px 25px rgba(45,25,90,.05);margin-bottom:12px}.rider-job-card.compact{padding:14px}.rider-job-top{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.rider-job-label{display:block;color:#8d8299;font-size:9px;font-weight:900;text-transform:uppercase;letter-spacing:.6px}.rider-job-top h3{margin:5px 0 0;font-size:16px}.rider-route{margin:18px 0 3px}.rider-stop{display:grid;grid-template-columns:12px 1fr auto;gap:11px;align-items:center}.rider-stop small{display:block;color:#95899f;font-size:8px;font-weight:900;letter-spacing:.7px}.rider-stop b{display:block;color:#40354b;font-size:12px;margin-top:3px}.rider-stop a{font-size:10px;font-weight:900;color:#6840cf;text-decoration:none;padding:7px 9px;background:#f2edfc;border-radius:9px}.rider-stop-dot{width:10px;height:10px;border-radius:50%;background:#6c3df4}.rider-stop-dot.dropoff{background:#2b9b72}.rider-route-line{height:25px;border-left:2px dashed #d8cfe3;margin-left:4px}.rider-job-actions{margin-top:15px}.rider-primary-action{width:100%;border:0;border-radius:11px;padding:13px 15px;background:#6c3df4;color:#fff;font-weight:900;cursor:pointer}.rider-code-form{display:flex;gap:8px}.rider-code-form input{min-width:0;flex:1;border:1px solid #ddd4e7;border-radius:10px;padding:11px}.rider-code-form .rider-primary-action{width:auto;white-space:nowrap}.rider-offer-toolbar{display:flex;justify-content:space-between;align-items:center;padding:13px 14px;background:#faf8fd;border:1px solid #e7e0ef;border-radius:13px;margin-bottom:12px}.rider-offer-toolbar>div{display:flex;align-items:center;gap:8px;font-size:11px}.rider-empty{text-align:center;padding:44px 20px;border:1px dashed #d9cfe5;border-radius:17px;background:#fff}.rider-empty h3{margin:7px 0 4px;font-size:16px}.rider-empty p{margin:0 auto 15px;max-width:450px;color:#8e8498;font-size:11px}.rider-empty-icon{width:46px;height:46px;border-radius:14px;background:#efe9fb;color:#6c3df4;display:grid;place-items:center;margin:auto;font-weight:900}.rider-earnings-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:14px;margin-bottom:14px}.rider-info-card{display:flex;flex-direction:column;gap:5px}.rider-info-card span{font-size:11px;color:#8d8397}.rider-profile-grid{display:grid;grid-template-columns:1fr 1.4fr;gap:14px}.rider-profile-card,.rider-status-panel{background:#fff;border:1px solid #e7e0ef;border-radius:17px;padding:18px;display:flex;align-items:center;gap:13px}.rider-profile-card{grid-column:1/-1}.rider-avatar-large{width:54px;height:54px;border-radius:17px;background:#eee8fa;color:#6c3df4;display:grid;place-items:center;font-size:22px;font-weight:900}.rider-profile-card h3{margin:0 0 4px}.rider-profile-card span{color:#8e8399;font-size:10px}.rider-status-panel{grid-column:1/-1;justify-content:space-between}.rider-status-panel div{display:flex;flex-direction:column;gap:3px}.rider-status-panel small{color:#8f849a;font-size:8px;font-weight:900;letter-spacing:.6px}.rider-status-panel span{color:#8c8297;font-size:10px}.rider-online-button,.rider-offline-button{border:0;border-radius:10px;padding:11px 14px;font-weight:900}.rider-online-button{background:#6c3df4;color:#fff}.rider-offline-button{background:#eee8f4;color:#4e4359}.rider-apply-intro{display:flex;gap:12px;padding:14px;border-radius:14px;background:#faf8fd;border:1px solid #e7e0ef;margin-bottom:15px}.rider-apply-icon{width:44px;height:44px;border-radius:13px;background:#eee8fa;display:grid;place-items:center;font-size:21px;flex:none}.rider-apply-intro p{margin:0 0 5px;color:#4c4157;font-size:12px;line-height:1.5}.rider-apply-intro small,.rider-apply-note{color:#91869d;font-size:10px;line-height:1.5}.rider-apply-note{text-align:center}.rider-apply-success{text-align:center;padding:28px 12px}.rider-apply-success>div{width:52px;height:52px;border-radius:16px;background:#e5f6ee;color:#18734f;display:grid;place-items:center;margin:0 auto 12px;font-weight:900;font-size:22px}.rider-apply-success h3{margin:0 0 7px}.rider-apply-success p{color:#8d8397;font-size:11px;max-width:470px;margin:0 auto 17px}.rider-form{max-width:100%}.rider-status-panel{margin-top:0}@media(max-width:900px){.rider-hero{align-items:flex-start;flex-direction:column}.rider-stats{grid-template-columns:repeat(2,1fr)}.rider-layout,.rider-profile-grid{grid-template-columns:1fr}.rider-profile-card,.rider-status-panel{grid-column:auto}}@media(max-width:600px){.rider-stats,.rider-earnings-grid{grid-template-columns:1fr}.rider-job-card{padding:15px}.rider-code-form{flex-direction:column}.rider-code-form .rider-primary-action{width:100%}.rider-stop{grid-template-columns:10px 1fr}.rider-stop a{grid-column:2;justify-self:start}.rider-online-control{width:100%;justify-content:space-between}}
    `;
    document.head.appendChild(style);
  }

  function installRiderEntryPoints() {
    if (document.querySelector("[data-rider-entry]")) return;
    const heroActions = document.querySelector(".hero-actions");
    if (heroActions) {
      const button = document.createElement("button");
      button.className = "button-outline";
      button.dataset.riderEntry = "true";
      button.dataset.action = "become-rider";
      button.textContent = "Deliver with WEWE";
      heroActions.appendChild(button);
    }
    const footerLinks = document.querySelector(".footer-links");
    if (footerLinks) {
      const button = document.createElement("button");
      button.className = "text-link";
      button.dataset.riderEntry = "true";
      button.dataset.action = "become-rider";
      button.textContent = "Become a delivery agent";
      footerLinks.prepend(button);
    }
  }

  function installStyles() {
    const account = $("#accountButton");
    if (account) account.classList.remove("hidden");
    const mobileCart = $("#mobileCartNav");
    const mobileAccount = $("#mobileAccountNav");
    if (mobileCart) mobileCart.addEventListener("click", showCart);
    if (mobileAccount) mobileAccount.addEventListener("click", () => state.user ? showDashboard(true) : showAuth());
  }

  function bindEvents() {
    // Bind storefront controls defensively so one missing optional element
    // can never prevent catalog loading or authentication from initializing.
    const on = (selector, event, handler) => {
      const element = $(selector);
      if (element) element.addEventListener(event, handler);
      return element;
    };

    document.addEventListener("click", event => {
      const target = event.target instanceof Element ? event.target : null;
      if (!target) return;

      const button = target.closest("[data-action]");
      if (button) {
        event.preventDefault();
        performAction(button).catch(error => showToast(error.message));
        return;
      }

      if (target === $("#modalBackdrop")) closeModal();
    });

    document.addEventListener("change", async event => {
    const input = event.target.closest("[data-profile-image]");
    if (!input) return;
    try {
      input.disabled = true;
      await uploadProfileImage(input);
    } catch (error) {
      showToast(error.message);
    } finally {
      input.disabled = false;
      input.value = "";
    }
  });

  document.addEventListener("submit", event => {
      const form = event.target instanceof Element ? event.target.closest("form[data-form]") : null;
      if (!form) return;
      event.preventDefault();
      submitForm(form);
    });

    on("#accountButton", "click", () => state.user ? showDashboard(true) : showAuth());
    on("#mobileAccount", "click", () => state.user ? showDashboard(true) : showAuth());
    on("#mobileAccountNav", "click", () => state.user ? showDashboard(true) : showAuth());
    on("#cartButton", "click", showCart);
    on("#locationButton", "click", () => {
      if (!state.user) return showAuth();
      state.dashboardSection = state.user.role === "CUSTOMER" ? "addresses" : "overview";
      showDashboard(true);
    });
    on("#sellCta", "click", () => state.user ? showDashboard(true) : showAuth(true, "RETAILER"));

    installRiderEntryPoints();

    on("#searchInput", "input", event => {
      state.search = event.target.value.trim();
      renderCatalog();
    });
    on("#sortFilter", "change", event => {
      state.sort = event.target.value;
      renderCatalog();
    });
    on("#availabilityFilter", "change", event => {
      state.availability = event.target.value === "nearby" ? "all" : event.target.value;
      if (event.target.value === "nearby") showToast("Nearby distance filtering is not provided by the current API.");
      renderCatalog();
    });

    on("#modalContent", "change", event => {
      if (event.target.closest('form[data-form="checkout"]')) {
        if (event.target.name === "delivery_point_id") selectCheckoutPoint(event.target.value);
        else toggleCheckoutFields();
      }
      if (event.target.closest('form[data-form="register"]')) updateRegistrationFields();
    });

    on("#logo", "click", () => showDashboard(false));
    document.querySelectorAll(".logo").forEach(logo => {
      logo.addEventListener("click", event => {
        // Let normal hash navigation work for storefront/footer logos.
        // Only dashboard-specific logo controls should switch workspaces.
        if (logo.id === "logo") {
          event.preventDefault();
          showDashboard(false);
        }
      });
    });

    on("#nearbyButton", "click", () => document.querySelector("#retailers")?.scrollIntoView({ behavior: "smooth" }));
    on("#retailerMore", "click", () => document.querySelector("#retailers")?.scrollIntoView({ behavior: "smooth" }));
    on("#allCategories", "click", () => {
      state.activeCategory = "all";
      renderCategories();
      renderCatalog();
      document.querySelector("#products")?.scrollIntoView({ behavior: "smooth" });
    });

    window.addEventListener("storage", event => {
      if (event.key === ACCESS_KEY || event.key === REFRESH_KEY) {
        resetUserScopedUI();
        renderCatalog();
        if (!localStorage.getItem(ACCESS_KEY)) {
          $("#dashboard")?.classList.add("hidden");
          $("#storefront")?.classList.remove("hidden");
          $("#footer")?.classList.remove("hidden");
          $("#topbar")?.classList.remove("hidden");
        } else {
          loadCurrentUser().catch(error => showToast(error.message));
        }
      }
    });
  }

  async function initialize() {
    startHeroSlider();
    installRiderStyles();
    installStyles();
    bindEvents();
    updateAccountButton();
    await loadCatalog();
    const accessToken = localStorage.getItem(ACCESS_KEY);
    if (accessToken) {
      try {
        await loadCurrentUser();
      } catch (error) {
        clearPrivateState();
        showToast(error.message);
      }
    }
  }

  initialize();
})();
