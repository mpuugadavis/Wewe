(() => {
  "use strict";

  const API_BASE = document.querySelector('meta[name="wewe-api-base"]')?.content || "http://localhost:8000/api/v1";
  const ACCESS_KEY = "wewe_access_token";
  const REFRESH_KEY = "wewe_refresh_token";
  const $ = (selector, root = document) => root.querySelector(selector);
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
    addressForCheckout: false,
    mapsApiKey: null,
    checkoutMap: null,
    checkoutMarker: null,
    checkoutAutocomplete: null,
    refreshPromise: null
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
      const url = new URL(value, location.href);
      const isHttps = url.protocol === "https:";
      const isLocalMinio = url.protocol === "http:" &&
        (url.hostname === "localhost" || url.hostname === "127.0.0.1") &&
        url.port === "9000";
      return (isHttps || isLocalMinio) && !url.username && !url.password ? url.href : "";
    } catch {
      return "";
    }
  }

  function money(value) {
    return `UGX ${Number(value || 0).toLocaleString("en-UG")}`;
  }

  function messageFrom(payload, status) {
    const detail = payload?.detail;
    if (typeof detail === "string") return detail;
    if (detail?.message) return detail.message;
    if (Array.isArray(detail)) return detail.map(item => item.msg).filter(Boolean).join("; ");
    return payload?.message || `Request failed (${status}). Please try again.`;
  }

  function clearPrivateState() {
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
      const image = safeImage(product.images?.[0]);
      const productId = escapeHtml(product.id);
      const listingId = escapeHtml(listing.retailer_product_id);
      const wished = state.wishlist.has(product.id);
      const stock = Number(listing.stock_available || 0);
      const stockLabel = stock < 1 ? "Out of stock" : stock <= 5 ? stock + " left" : "In stock";
      const stockClass = stock < 1 ? "out" : stock <= 5 ? "low" : "";
      return `<article class="product-card" data-product-id="${productId}" data-listing-id="${listingId}">
        <div class="product-image ${image ? "" : "image-placeholder"}">${image ? `<img src="${escapeHtml(image)}" alt="${escapeHtml(product.name)}" loading="lazy">` : '<span>WEWE</span>'}
          <button class="wish-button ${wished ? "is-wished" : ""}" aria-label="${wished ? "Remove from" : "Add to"} wishlist" data-action="toggle-wishlist" data-product-id="${productId}">${wished ? "♥" : "♡"}</button>
          <button class="quick-add" data-action="add-cart" data-listing-id="${listingId}" ${stock < 1 ? "disabled" : ""}>${stock < 1 ? "Unavailable" : "Quick add"}</button>
        </div>
        <div class="product-info">
          <div class="product-seller">${escapeHtml(listing.retailer_name || "Campus retailer")}</div>
          <button class="product-title" data-action="product-details" data-product-id="${productId}">${escapeHtml(product.name)}</button>
          <div class="product-meta"><span class="stock-pill ${stockClass}">${stockLabel}</span><span class="muted">Campus listing</span></div>
          <div class="product-price-row"><strong>${money(listing.price_ugx)}</strong><button class="add-button" data-action="add-cart" data-listing-id="${listingId}" ${stock < 1 ? "disabled" : ""}>${stock < 1 ? "Unavailable" : "Add to cart"}</button></div>
        </div>
      </article>`;
    }).join("") : '<div class="empty-state"><div class="empty-icon">⌕</div><h3>No products found</h3><p>Try another search, category or availability filter.</p><button class="button-outline" data-action="clear-search">Clear filters</button></div>';
    syncCartBadge();
  }

  function renderCategories() {
    const categories = [{ id: "all", name: "Everything" }, ...state.categories];
    $("#categoryList").innerHTML = categories.map(category => `<button class="category ${state.activeCategory === category.id ? "active" : ""}" data-action="category" data-category-id="${escapeHtml(category.id)}"><span class="cat-icon">◇</span><span>${escapeHtml(category.name)}</span></button>`).join("");
  }

  function renderRetailers() {
    $("#sellerRow").innerHTML = state.retailers.length ? state.retailers.map(retailer => {
      const image = safeImage(retailer.logo_url || retailer.image_url);
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

  function showAuth(register = false, role = "CUSTOMER") {
    const title = register ? "Create your WEWE account" : "Welcome back";
    setModal(`<div class="modal-head"><div><div class="section-kicker">WEWE account</div><h2>${title}</h2></div><button class="close-modal" data-action="close-modal" aria-label="Close">×</button></div>
      <form data-form="${register ? "register" : "login"}" class="api-form">
        ${register ? '<label class="field">Full name<input name="name" required minlength="2" autocomplete="name"></label>' : ""}
        ${register ? `<label class="field">Account type<select name="role"><option value="CUSTOMER" ${role === "CUSTOMER" ? "selected" : ""}>Customer</option><option value="RETAILER" ${role === "RETAILER" ? "selected" : ""}>Retailer</option><option value="DELIVERY_AGENT" ${role === "DELIVERY_AGENT" ? "selected" : ""}>Delivery agent</option></select></label>` : ""}
        <label class="field">Email or phone<input name="email" type="text" required autocomplete="username"></label>
        ${register ? '<label class="field">Phone<input name="phone" type="tel" autocomplete="tel"></label><label class="field hidden" data-register-business>Business name<input name="business_name" maxlength="180"></label><label class="field hidden" data-register-transport>Transport mode<input name="transport_mode" maxlength="40"></label>' : ""}
        <label class="field">Password<input name="password" type="password" required minlength="${register ? "12" : "1"}" autocomplete="${register ? "new-password" : "current-password"}"></label>
        <p class="form-message" aria-live="polite"></p><button class="button-primary" type="submit">${register ? "Create account" : "Sign in"}</button>
      </form><button class="text-link" data-action="${register ? "show-login" : "show-register"}">${register ? "Already registered? Sign in" : "New to WEWE? Create an account"}</button>`, false);
    if (register) updateRegistrationFields();
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
    $("#productListings").innerHTML = listings.length ? listings.map(listing => `<div class="listing-row"><span><b>${escapeHtml(listing.retailer_name)}</b><small>${Number(listing.stock_available) > 0 ? `${Number(listing.stock_available)} available` : "Out of stock"}</small></span><b>${money(listing.price_ugx)}</b><button class="add-button" data-action="add-cart" data-listing-id="${escapeHtml(listing.retailer_product_id)}" ${Number(listing.stock_available) < 1 ? "disabled" : ""}>Add</button></div>`).join("") : '<p>No active listings.</p>';
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

  async function initializeCheckoutMap(points) {
    const mapElement = $("#checkoutMap");
    if (!mapElement) return;
    try {
      const loaded = await loadGoogleMaps();
      if (!loaded) {
        mapElement.innerHTML = '<div class="map-unavailable"><b>Google Maps preview</b><span>Configure the restricted Maps browser key to enable the live map.</span></div>';
        return;
      }
      const { Map } = await google.maps.importLibrary("maps");
      const { AdvancedMarkerElement } = await google.maps.importLibrary("marker");
      const defaultCenter = { lat: 0.3350, lng: 32.5700 };
      state.checkoutMap = new Map(mapElement, {
        center: defaultCenter,
        zoom: 15,
        mapId: "DEMO_MAP_ID",
        disableDefaultUI: false,
        streetViewControl: false,
        fullscreenControl: true
      });
      const usable = points.filter(point => Number.isFinite(Number(point.latitude)) && Number.isFinite(Number(point.longitude)));
      usable.forEach(point => {
        const marker = new AdvancedMarkerElement({
          map: state.checkoutMap,
          position: { lat: Number(point.latitude), lng: Number(point.longitude) },
          title: point.name
        });
        marker.addListener("click", () => selectCheckoutPoint(point.id));
      });
      if (usable[0]) {
        state.checkoutMap.setCenter({ lat: Number(usable[0].latitude), lng: Number(usable[0].longitude) });
      }
      try {
        const { PlaceAutocompleteElement } = await google.maps.importLibrary("places");
        const host = $("#checkoutAutocomplete");
        if (host) {
          state.checkoutAutocomplete = new PlaceAutocompleteElement({ placeholder: "Search a hostel, hall or address" });
          state.checkoutAutocomplete.setAttribute("included-region-codes", "ug");
          host.replaceChildren(state.checkoutAutocomplete);
          state.checkoutAutocomplete.addEventListener("gmp-select", async ({ placePrediction }) => {
            const place = placePrediction.toPlace();
            await place.fetchFields({ fields: ["displayName", "formattedAddress", "location", "id"] });
            if (!place.location) return;
            const campusId = state.campuses?.find(item => item.slug === "main-campus")?.id || state.campuses?.[0]?.id;
            if (!campusId) throw new Error("No WEWE campus is configured.");
            const point = await apiFetch("/locations/me/delivery-points", {
              method: "POST",
              body: JSON.stringify({
                campus_id: campusId,
                kind: "OTHER",
                name: place.displayName || "Selected Google Maps location",
                directions: place.formattedAddress || "",
                latitude: place.location.lat(),
                longitude: place.location.lng(),
                google_place_id: place.id || null,
                is_private: true
              })
            });
            state.checkoutPoints = [...state.checkoutPoints.filter(item => item.id !== point.id), point];
            const select = $('form[data-form="checkout"]')?.elements.delivery_point_id;
            if (select) {
              const option = document.createElement("option");
              option.value = point.id;
              option.textContent = point.name;
              select.appendChild(option);
              select.value = point.id;
            }
            state.checkoutMap.setCenter({ lat: Number(point.latitude), lng: Number(point.longitude) });
            state.checkoutMap.setZoom(17);
            const label = $("#selectedDeliveryLocation");
            if (label) label.textContent = point.name + (point.directions ? " · " + point.directions : "");
            await updateCheckoutQuote();
          });
        }
      } catch {
        // The map remains fully usable without Places autocomplete.
      }
    } catch (error) {
      mapElement.innerHTML = '<div class="map-unavailable"><b>Map unavailable</b><span>' + escapeHtml(error.message) + '</span></div>';
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
    if (state.checkoutMap && point.latitude && point.longitude) {
      state.checkoutMap.setCenter({ lat: Number(point.latitude), lng: Number(point.longitude) });
      state.checkoutMap.setZoom(17);
    }
    updateCheckoutQuote().catch(error => showToast(error.message));
  }

  async function useCurrentLocation() {
    if (!navigator.geolocation) throw new Error("Your browser does not provide location services.");
    const position = await new Promise((resolve, reject) => navigator.geolocation.getCurrentPosition(resolve, reject, {
      enableHighAccuracy: true,
      timeout: 10000,
      maximumAge: 30000
    }));
    const latitude = Number(position.coords.latitude);
    const longitude = Number(position.coords.longitude);
    const campuses = state.campuses || await apiFetch("/locations/campuses");
    const campus = campuses.find(item => item.slug === "main-campus") || campuses[0];
    if (!campus) throw new Error("No WEWE campus is configured.");
    const point = await apiFetch("/locations/me/delivery-points", {
      method: "POST",
      body: JSON.stringify({
        campus_id: campus.id,
        kind: "OTHER",
        name: "My current location",
        directions: "Browser GPS location",
        latitude,
        longitude,
        google_place_id: null,
        is_private: true
      })
    });
    state.checkoutPoints = [...state.checkoutPoints.filter(item => item.id !== point.id), point];
    const select = $('form[data-form="checkout"]')?.elements.delivery_point_id;
    if (select) {
      const option = document.createElement("option");
      option.value = point.id;
      option.textContent = "My current location";
      select.appendChild(option);
      select.value = point.id;
    }
    state.checkoutSelectedExternal = null;
    const label = $("#selectedDeliveryLocation");
    if (label) label.textContent = "My current location · GPS coordinates";
    if (state.checkoutMap) {
      state.checkoutMap.setCenter({ lat: latitude, lng: longitude });
      state.checkoutMap.setZoom(17);
      if (window.google?.maps) {
        const { AdvancedMarkerElement } = await google.maps.importLibrary("marker");
        state.checkoutMarker = new AdvancedMarkerElement({ map: state.checkoutMap, position: { lat: latitude, lng: longitude }, title: "My current location" });
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
      publicPoints = mainCampus ? await apiFetch("/locations/delivery-points?campus_id=" + encodeURIComponent(mainCampus.id)) : [];
    } catch (error) {
      $("#checkoutContents").innerHTML = '<div class="api-state api-error">' + escapeHtml(error.message) + '<p><button class="button-outline" data-action="checkout">Try again</button></p></div>';
      throw error;
    }
    state.campuses = campuses;
    state.checkoutPoints = [...new Map([...publicPoints, ...saved].map(point => [point.id, point])).values()];
    const profile = await apiFetch("/users/me/profile");
    $("#checkoutContents").innerHTML = '<form data-form="checkout" class="api-form">' +
      '<div class="delivery-map-shell"><div class="map-toolbar"><div><b>Where should we deliver?</b><small>Choose a Makerere hall/hostel, search Google Maps, or use your current location.</small></div><button type="button" class="button-outline" data-action="use-current-location">Use my current location</button></div><div id="checkoutAutocomplete" class="checkout-autocomplete"></div><div id="checkoutMap" class="checkout-map"></div><p id="selectedDeliveryLocation" class="selected-location">Choose a delivery point</p></div>' +
      '<label class="field">Fulfilment<select name="delivery_method"><option value="DELIVERY">Campus delivery</option><option value="PICKUP">Pickup</option></select></label>' +
      '<div data-checkout-delivery><label class="field">Delivery point<select name="delivery_point_id"><option value="">Choose a hall, hostel or saved point</option>' + state.checkoutPoints.map(point => '<option value="' + escapeHtml(point.id) + '">' + escapeHtml(point.name) + (point.directions ? ' — ' + escapeHtml(point.directions) : "") + '</option>').join("") + '</select></label><div class="quick-location-grid">' + state.checkoutPoints.slice(0, 12).map(point => '<button type="button" class="location-chip" data-action="select-delivery-point" data-id="' + escapeHtml(point.id) + '">' + escapeHtml(point.name) + '</button>').join("") + '</div><button type="button" class="text-link" data-action="new-address">Add a delivery point</button></div>' +
      '<div data-checkout-pickup class="hidden"><label class="field">Pickup point<select name="pickup_point_id">' + pickupPoints.map(point => '<option value="' + escapeHtml(point.id) + '">' + escapeHtml(point.name) + (point.directions ? ' — ' + escapeHtml(point.directions) : "") + '</option>').join("") + '</select></label></div>' +
      '<div class="field"><span>Payment method</span><div class="payment-options"><label class="payment-option selected"><input type="radio" name="payment_method" value="MTN_MOMO" checked> <b>MTN Mobile Money</b><small>Pay securely from your MTN line.</small></label><label class="payment-option"><input type="radio" name="payment_method" value="AIRTEL_MONEY"> <b>Airtel Money</b><small>Pay securely from your Airtel line.</small></label></div></div>' +
      '<label class="field" data-payment-phone>Mobile money phone<input name="phone" type="tel" placeholder="+256700000000" required autocomplete="tel"></label>' +
      '<div id="checkoutQuote" class="checkout-quote"><p class="api-state">Calculating delivery route…</p></div><p class="form-message" aria-live="polite"></p><button class="button-primary">Place order</button></form>';
    if (profile.preferred_delivery_point_id && $('select[name="delivery_point_id"]')) {
      $('select[name="delivery_point_id"]').value = profile.preferred_delivery_point_id;
    }
    toggleCheckoutFields();
    initializeCheckoutMap(state.checkoutPoints);
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
    const quote = await apiFetch("/orders/delivery-quote", { method: "POST", body: JSON.stringify(payload) });
    const routeRows = (quote.fulfillments || []).map(item => '<p><span>' + escapeHtml(item.retailer_name || "Retailer") + ' · ' + Number(item.route_distance_km || 0).toFixed(1) + ' km</span><b>' + money(item.delivery_fee_ugx) + '</b></p>').join("");
    box.innerHTML = '<div class="checkout-totals"><p>Subtotal <b>' + money(quote.subtotal_ugx) + '</b></p>' + routeRows + '<p>Delivery fee <b>' + money(quote.delivery_fee_ugx) + '</b></p><p class="checkout-total"><span>Total</span><b>' + money(quote.total_ugx) + '</b></p><small class="route-note">' + (quote.routing_provider ? 'Google/road routing is used when configured; WEWE applies its own UGX pricing formula.' : 'Pickup has no delivery fee.') + '</small></div>';
    form.dataset.quoteTotal = String(quote.total_ugx);
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
        phone: form.elements.phone.value.trim()
      };
      form.dataset.paymentIdempotencyKey ||= crypto.randomUUID();
      payment = await apiFetch(`/orders/${encodeURIComponent(order.id)}/payments`, { method: "POST", headers: { "Idempotency-Key": form.dataset.paymentIdempotencyKey }, body: JSON.stringify(paymentBody) });
    } catch (error) {
      const method = form.elements.payment_method.value;
      const phone = form.elements.phone.value.trim();
      $("#modalContent").innerHTML = `<div class="modal-head"><div><div class="section-kicker">Order created</div><h2>${escapeHtml(order.order_number)}</h2></div><button class="close-modal" data-action="close-modal">×</button></div><p>Your order was created and the server calculated its totals, but the online payment could not be started.</p><div class="checkout-totals"><p>Subtotal <b>${money(order.subtotal_ugx)}</b></p><p>Delivery <b>${money(order.delivery_fee_ugx)}</b></p><p>Total <b>${money(order.total_ugx)}</b></p></div><p class="api-error">Payment error: ${escapeHtml(error.message)}</p><button class="button-primary" data-action="retry-online-payment" data-order-id="${escapeHtml(order.id)}" data-method="${escapeHtml(method)}" data-phone="${escapeHtml(phone)}">Retry online payment</button>`;
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

  async function retryOnlinePayment(orderId, method, phone) {
    if (!["MTN_MOMO", "AIRTEL_MONEY"].includes(method)) throw new Error("Choose an online mobile-money payment method.");
    if (!phone) throw new Error("Enter the mobile-money phone number.");
    const idempotencyKey = crypto.randomUUID();
    const payment = await apiFetch(`/orders/${encodeURIComponent(orderId)}/payments`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ method, phone })
    });
    const checkoutUrl = safeImage(payment?.checkout_url);
    $("#modalContent").innerHTML = `<div class="modal-head"><div><div class="section-kicker">Payment retry</div><h2>Continue payment</h2></div><button class="close-modal" data-action="close-modal">×</button></div><p>${escapeHtml(payment?.status || "Payment initiated")}</p>${checkoutUrl ? `<p><a class="button-primary" href="${escapeHtml(checkoutUrl)}" target="_blank" rel="noopener noreferrer">Continue mobile payment</a></p>` : ""}<button class="button-outline" data-action="close-modal">Close</button>`;
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
    const common = [["overview", "Overview"]];
    if (role === "CUSTOMER") return [...common, ["orders", "Orders"], ["wishlist", "Wishlist"], ["addresses", "Delivery points"], ["notifications", "Notifications"], ["profile", "Profile"]];
    if (role === "RETAILER") return [...common, ["products", "Products"], ["fulfillments", "Fulfilments"], ["profile", "Store profile"]];
    if (role === "DELIVERY_AGENT") return [...common, ["available", "Available deliveries"], ["deliveries", "My deliveries"], ["history", "Delivery history"], ["earnings", "Earnings"], ["profile", "Profile"]];
    return [...common, ["users", "Users"], ["retailers", "Retailers"], ["products", "Products"], ["orders", "Orders"], ["agents", "Delivery agents"], ["settings", "Settings"], ["audit", "Audit log"]];
  }

  async function renderDashboard() {
    if (!state.user) return showAuth();
    const user = state.user;
    const role = user.role;
    const nav = dashboardMenu(role);
    if (!nav.some(([key]) => key === state.dashboardSection)) state.dashboardSection = "overview";
    $("#sideRole").textContent = role.replaceAll("_", " ");
    $("#dashName").textContent = user.name;
    $("#dashAvatar").textContent = (user.name || "?").slice(0, 1).toUpperCase();
    $("#dashAccountRole").textContent = `${role.replaceAll("_", " ")} account`;
    $("#dashNav").innerHTML = `${nav.map(([key, label]) => `<button class="${key === state.dashboardSection ? "active" : ""}" data-action="dashboard-section" data-section="${key}">${label}</button>`).join("")}<button data-action="sign-out">Sign out</button><button data-action="storefront">Back to shop</button>`;
    $("#dashTitle").textContent = nav.find(([key]) => key === state.dashboardSection)?.[1] || "Overview";
    $("#dashSubtitle").textContent = "Live information from your WEWE account.";
    $("#dashboardContent").innerHTML = '<p class="api-state">Loading your workspace…</p>';
    const view = role === "CUSTOMER" ? await customerDashboard() :
      role === "RETAILER" ? await retailerDashboard() :
      role === "DELIVERY_AGENT" ? await agentDashboard() : await adminDashboard();
    $("#dashboardContent").innerHTML = view;
  }

  async function customerDashboard() {
    const section = state.dashboardSection;
    if (section === "overview") {
      const [orders, profile, points, notifications] = await Promise.all([
        apiFetch("/orders"), apiFetch("/users/me/profile"), apiFetch("/locations/me/delivery-points"), apiFetch("/notifications?limit=5")
      ]);
      const preferredPoint = points.find(point => point.id === profile.preferred_delivery_point_id);
      return `<div class="stat-grid"><div class="stat-card"><span>Orders</span><b class="stat-value">${orders.length}</b></div><div class="stat-card"><span>Unread notifications</span><b class="stat-value">${notifications.filter(item => !item.read_at).length}</b></div><div class="stat-card"><span>Delivery point</span><b>${escapeHtml(preferredPoint?.name || "Not selected")}</b></div></div><div class="dashboard-panel"><h2>Recent orders</h2>${renderOrders(orders.slice(0, 5), true)}</div>`;
    }
    if (section === "orders") return `<div class="dashboard-panel"><h2>Your orders</h2>${renderOrders(await apiFetch("/orders"), true)}</div>`;
    if (section === "wishlist") {
      const items = await apiFetch("/wishlist");
      return `<div class="dashboard-panel"><h2>Saved products</h2>${(items || []).map(item => {
        const id = item.product_id || item.id;
        const product = state.products.find(row => row.id === id);
        return `<div class="listing-row"><b>${escapeHtml(product?.name || item.name || "Saved product")}</b>${product ? `<button data-action="product-details" data-product-id="${escapeHtml(id)}">Details</button>` : ""}<button data-action="toggle-wishlist" data-product-id="${escapeHtml(id)}">Remove</button></div>`;
      }).join("") || '<p>No saved products.</p>'}</div>`;
    }
    if (section === "addresses") {
      const points = await apiFetch("/locations/me/delivery-points");
      return `<div class="dashboard-panel"><div class="panel-head"><h2>Delivery points</h2><button class="button-outline" data-action="new-address">Add point</button></div>${points.map(point => `<div class="listing-row"><span><b>${escapeHtml(point.name)}</b><small>${escapeHtml(point.directions || "")}</small></span><button data-action="delete-address" data-id="${escapeHtml(point.id)}">Remove</button></div>`).join("") || "<p>No saved points.</p>"}</div>`;
    }
    if (section === "notifications") {
      const notes = await apiFetch("/notifications?limit=100");
      return `<div class="dashboard-panel"><h2>Notifications</h2>${notes.map(note => {
        const codes = note.payload?.delivery_confirmation_codes;
        const codeRows = codes && typeof codes === "object" ? Object.entries(codes).map(([fulfillmentId, code]) => `<p>Delivery confirmation code: <b>${escapeHtml(code)}</b><small>Fulfilment ${escapeHtml(fulfillmentId)}</small></p>`).join("") : "";
        const summary = note.payload?.order_number ? `Order ${note.payload.order_number}` : "";
        return `<div class="notification-row"><b>${escapeHtml(note.event_type || "Update")}</b><p>${escapeHtml(summary)}</p>${codeRows}<small>${formatDate(note.created_at)}</small>${note.read_at ? "" : `<button data-action="read-notification" data-id="${escapeHtml(note.id)}">Mark read</button>`}</div>`;
      }).join("") || "<p>You have no notifications.</p>"}</div>`;
    }
    if (section === "profile") {
      const profile = await apiFetch("/users/me/profile");
      const points = await apiFetch("/locations/me/delivery-points");
      return `<div class="dashboard-panel"><h2>Profile preferences</h2><p>${escapeHtml(state.user.name)} · ${escapeHtml(state.user.email || "")}</p><form data-form="customer-profile" class="api-form"><label class="field">Preferred delivery point<select name="preferred_delivery_point_id"><option value="">None selected</option>${points.map(point => `<option value="${escapeHtml(point.id)}" ${profile.preferred_delivery_point_id === point.id ? "selected" : ""}>${escapeHtml(point.name)}</option>`).join("")}</select></label><label><input type="checkbox" name="marketing_opt_in" ${profile.marketing_opt_in ? "checked" : ""}> Receive marketing updates</label><button class="button-primary">Save preferences</button></form></div>`;
    }
    return "";
  }

  function renderOrders(orders, actions = false) {
    if (!orders.length) return "<p>No orders yet.</p>";
    return orders.map(order => `<div class="order-card"><div class="panel-head"><div><b>${escapeHtml(order.order_number)}</b><small>${formatDate(order.created_at)}</small></div>${statusBadge(order.status)}</div><div>${(order.items || []).map(item => `${escapeHtml(item.product_name || item.name)} × ${Number(item.quantity)}`).join(", ")}</div><div class="panel-head"><span>Payment ${statusBadge(order.payment_status)}</span><b>${money(order.total_ugx)}</b></div>${actions ? `<div class="row-actions"><button data-action="order-details" data-id="${escapeHtml(order.id)}">Details</button>${["PENDING", "CONFIRMED", "PROCESSING"].includes(order.status) ? `<button data-action="cancel-order" data-id="${escapeHtml(order.id)}">Cancel</button>` : ""}<button data-action="reorder" data-id="${escapeHtml(order.id)}">Order again</button></div>` : ""}</div>`).join("");
  }

  async function retailerDashboard() {
    const section = state.dashboardSection;
    if (section === "profile") {
      const profile = await apiFetch("/retailers/me");
      const isOpen = profile.status === "ACTIVE";
      return `<div class="dashboard-panel"><h2>Store profile</h2><form data-form="retailer-profile" class="api-form"><label class="field">Business name<input name="business_name" value="${escapeHtml(profile.business_name)}" required></label><label class="field">Description<textarea name="description">${escapeHtml(profile.description || "")}</textarea></label><label class="field">Phone<input name="phone" value="${escapeHtml(profile.phone || "")}" required></label><button class="button-primary">Save profile</button></form><button class="button-outline" data-action="retailer-availability" data-open="${!isOpen}">${isOpen ? "Close store" : "Open store"}</button></div>`;
    }
    if (section === "products") {
      const products = await apiFetch("/retailers/me/products");
      const own = products.flatMap(product => product.listings.map(listing => ({ product, listing })));
      return `<div class="dashboard-panel"><div class="panel-head"><h2>Your product listings</h2><button class="button-outline" data-action="new-product">Add product</button></div>${own.map(({ product, listing }) => `<div class="listing-row"><span><b>${escapeHtml(product.name)}</b><small>${money(listing.price_ugx)} · ${Number(listing.stock_available)} available</small></span><div class="row-actions"><button data-action="edit-retailer-product" data-listing-id="${escapeHtml(listing.retailer_product_id)}" data-name="${escapeHtml(product.name)}" data-price="${Number(listing.price_ugx)}">Update price</button><button data-action="deactivate-retailer-product" data-listing-id="${escapeHtml(listing.retailer_product_id)}">Deactivate</button></div></div>`).join("") || "<p>Use the Add product form to list products.</p>"}</div>`;
    }
    if (section === "fulfillments") {
      const rows = await apiFetch("/retailers/me/fulfillments");
      return `<div class="dashboard-panel"><h2>Fulfilments</h2>${rows.map(row => `<div class="order-card"><div class="panel-head"><b>${escapeHtml(row.order_number || row.id)}</b>${statusBadge(row.status)}</div><p>${(row.items || []).map(item => `${escapeHtml(item.name)} × ${Number(item.quantity)}`).join(", ")}</p><div class="row-actions">${row.status === "PENDING" ? `<button data-action="fulfillment-action" data-id="${escapeHtml(row.id)}" data-status="confirm">Confirm</button><button data-action="fulfillment-action" data-id="${escapeHtml(row.id)}" data-status="reject">Reject</button>` : ""}${row.status === "CONFIRMED" ? `<button data-action="fulfillment-action" data-id="${escapeHtml(row.id)}" data-status="preparing">Start preparing</button>` : ""}${row.status === "PREPARING" ? `<button data-action="fulfillment-action" data-id="${escapeHtml(row.id)}" data-status="ready">Mark ready</button>` : ""}</div></div>`).join("") || "<p>No fulfilments waiting.</p>"}</div>`;
    }
    if (section === "overview") {
      const [profile, fulfillments] = await Promise.all([apiFetch("/retailers/me"), apiFetch("/retailers/me/fulfillments")]);
      return `<div class="stat-grid"><div class="stat-card"><span>Store</span><b class="stat-value">${profile.status === "ACTIVE" ? "Open" : "Closed"}</b></div><div class="stat-card"><span>Verification</span><b>${escapeHtml(profile.verification_status)}</b></div><div class="stat-card"><span>Pending fulfilments</span><b class="stat-value">${fulfillments.filter(item => item.status === "PENDING").length}</b></div></div><div class="dashboard-panel"><h2>Store actions</h2><button class="button-outline" data-action="dashboard-section" data-section="products">Manage products</button><button class="button-outline" data-action="dashboard-section" data-section="fulfillments">Review fulfilments</button></div>`;
    }
    return "";
  }

  async function agentDashboard() {
    const section = state.dashboardSection;
    if (section === "profile") {
      const profile = await apiFetch("/deliveries/me/profile");
      return `<div class="dashboard-panel"><h2>Agent profile</h2><form data-form="agent-profile" class="api-form"><label class="field">Phone<input name="phone" value="${escapeHtml(profile.phone || "")}"></label><label class="field">Transport mode<input name="transport_mode" value="${escapeHtml(profile.transport_mode || "")}"></label><button class="button-primary">Save profile</button></form><button class="button-outline" data-action="agent-availability" data-status="${profile.availability_status === "AVAILABLE" ? "OFFLINE" : "AVAILABLE"}">Set ${profile.availability_status === "AVAILABLE" ? "offline" : "available"}</button></div>`;
    }
    if (section === "overview" || section === "earnings") {
      const [profile, earnings] = await Promise.all([apiFetch("/deliveries/me/profile"), apiFetch("/deliveries/me/earnings")]);
      if (section === "earnings") return `<div class="dashboard-panel"><h2>Earnings</h2><pre>${escapeHtml(JSON.stringify(earnings, null, 2))}</pre></div>`;
      return `<div class="stat-grid"><div class="stat-card"><span>Availability</span><b class="stat-value">${escapeHtml(profile.availability_status)}</b></div><div class="stat-card"><span>Paid earnings</span><b class="stat-value">${money(earnings.paid_ugx)}</b></div><div class="stat-card"><span>Pending earnings</span><b class="stat-value">${money(earnings.pending_ugx)}</b></div></div><div class="dashboard-panel"><button class="button-outline" data-action="dashboard-section" data-section="available">Find a delivery</button></div>`;
    }
    if (section === "available") {
      const rows = await apiFetch("/deliveries/available");
      return `<div class="dashboard-panel"><h2>Available deliveries</h2>${rows.map(row => `<div class="order-card"><div class="panel-head"><b>${escapeHtml(row.order_number || row.id)}</b>${statusBadge(row.status)}</div><p>${escapeHtml(row.pickup?.name || row.retailer_name || "Collection location")} → ${escapeHtml(row.dropoff?.name || "Customer delivery destination")}</p><button data-action="accept-delivery" data-id="${escapeHtml(row.id)}">Accept delivery</button></div>`).join("") || "<p>No deliveries are currently available.</p>"}</div>`;
    }
    const rows = await apiFetch(section === "history" ? "/deliveries/me/history" : "/deliveries/me");
    return `<div class="dashboard-panel"><h2>${section === "history" ? "Completed deliveries" : "My deliveries"}</h2>${rows.map(row => `<div class="order-card"><div class="panel-head"><b>${escapeHtml(row.order_number || row.id)}</b>${statusBadge(row.status)}</div><p>${escapeHtml(row.pickup?.name || row.retailer_name || "Collection location")} → ${escapeHtml(row.dropoff?.name || "Delivery destination")}</p>${row.status !== "DELIVERED" ? `<div class="row-actions">${row.status === "ACCEPTED" ? `<button data-action="delivery-status" data-id="${escapeHtml(row.id)}" data-status="PICKED_UP">Mark picked up</button>` : ""}${row.status === "PICKED_UP" ? `<button data-action="delivery-status" data-id="${escapeHtml(row.id)}" data-status="OUT_FOR_DELIVERY">Out for delivery</button>` : ""}${row.status === "OUT_FOR_DELIVERY" ? `<form data-form="delivery-code" data-id="${escapeHtml(row.id)}" class="inline-form"><input name="confirmation_code" required minlength="4" maxlength="12" placeholder="Customer code" aria-label="Customer confirmation code"><button data-status="DELIVERED">Confirm delivery</button></form>` : ""}</div>` : ""}</div>`).join("") || "<p>No assigned deliveries.</p>"}</div>`;
  }

  async function adminDashboard() {
    const section = state.dashboardSection;
    if (section === "overview") {
      const [metrics, statuses] = await Promise.all([apiFetch("/admin/metrics"), apiFetch("/admin/reports/order-statuses")]);
      return `<div class="dashboard-panel"><h2>Platform metrics</h2><pre>${escapeHtml(JSON.stringify(metrics, null, 2))}</pre><h3>Order status report</h3><pre>${escapeHtml(JSON.stringify(statuses, null, 2))}</pre></div>`;
    }
    const paths = {
      users: "/admin/users", retailers: "/admin/retailers", products: "/admin/products",
      orders: "/admin/orders", agents: "/admin/delivery-agents", settings: "/admin/settings", audit: "/admin/audit-logs"
    };
    const data = await apiFetch(paths[section]);
    const rows = Array.isArray(data) ? data : data.items || [];
    return `<div class="dashboard-panel"><h2>${escapeHtml(section)}</h2>${rows.length ? `<div class="admin-table">${rows.map(row => {
      const name = row.name || row.business_name || row.order_number || row.key || row.id;
      const id = row.id;
      let action = "";
      if (section === "users") action = `<button data-action="user-status" data-id="${escapeHtml(id)}" data-status="${row.status === "ACTIVE" ? "SUSPENDED" : "ACTIVE"}">${row.status === "ACTIVE" ? "Suspend" : "Activate"}</button>`;
      if (section === "retailers" && row.verification_status !== "VERIFIED") action = `<button data-action="verify-retailer" data-id="${escapeHtml(id)}">Verify</button>`;
      if (section === "agents" && row.verification_status !== "VERIFIED") action = `<button data-action="verify-agent" data-id="${escapeHtml(id)}">Verify</button>`;
      if (section === "products") action = `<button data-action="moderate-product" data-id="${escapeHtml(id)}" data-status="${row.status === "ACTIVE" ? "REMOVED" : "ACTIVE"}">${row.status === "ACTIVE" ? "Remove" : "Activate"}</button>`;
      return `<div class="admin-row"><span><b>${escapeHtml(name)}</b><small>${escapeHtml(row.email || row.status || row.verification_status || "")}</small></span>${action}</div>`;
    }).join("")}</div>` : `<pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>`}</div>`;
  }

  async function showOrder(orderId) {
    const order = await apiFetch(`/orders/${encodeURIComponent(orderId)}`);
    const stages = ["PENDING", "CONFIRMED", "PROCESSING", "READY", "OUT_FOR_DELIVERY", "DELIVERED"];
    const currentStage = stages.indexOf(order.status);
    const tracking = stages.map((stage, index) => `<div class="tracking-step ${index <= currentStage ? "done" : ""} ${stage === order.status ? "current" : ""}"><span>${index <= currentStage ? "✓" : index + 1}</span><div><b>${escapeHtml(stage.replaceAll("_", " "))}</b><small>${stage === order.status ? "Current status" : index < currentStage ? "Completed" : "Waiting"}</small></div></div>`).join("");
    setModal(`<div class="modal-head"><div><div class="section-kicker">Order</div><h2>${escapeHtml(order.order_number)}</h2></div><button class="close-modal" data-action="close-modal">×</button></div><p>${statusBadge(order.status)} ${statusBadge(order.payment_status)}</p><div class="tracking-timeline">${tracking}</div>${(order.items || []).map(item => `<div class="listing-row"><span>${escapeHtml(item.product_name)} × ${Number(item.quantity)}</span><b>${money(item.line_total_ugx)}</b></div>`).join("")}<div class="checkout-totals"><p>Subtotal <b>${money(order.subtotal_ugx)}</b></p><p>Delivery <b>${money(order.delivery_fee_ugx)}</b></p><p>Total <b>${money(order.total_ugx)}</b></p></div>`);
  }

  async function newProduct() {
    const categories = state.categories.length ? state.categories : await apiFetch("/categories");
    setModal(`<div class="modal-head"><h2>Add a product</h2><button class="close-modal" data-action="close-modal">×</button></div><form data-form="new-product" class="api-form"><label class="field">Product name<input name="name" required minlength="2" maxlength="220"></label><label class="field">Description<textarea name="description"></textarea></label><label class="field">Category<select name="category_id" required>${categories.map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join("")}</select></label><label class="field">Price (UGX)<input name="price_ugx" type="number" min="1" step="1" required></label><label class="field">Stock quantity<input name="stock_quantity" type="number" min="0" step="1" required></label><label class="field">Image URL (HTTPS)<input name="image_url" type="url" placeholder="https://…"></label><p class="form-message" aria-live="polite"></p><button class="button-primary">Create product</button></form>`);
  }

  async function createProduct(form) {
    const values = Object.fromEntries(new FormData(form));
    const body = {
      name: values.name,
      description: values.description || null,
      category_id: values.category_id,
      price_ugx: Number(values.price_ugx),
      stock_quantity: Number(values.stock_quantity),
      image_urls: values.image_url ? [values.image_url] : []
    };
    await apiFetch("/retailers/me/products", { method: "POST", body: JSON.stringify(body) });
    showToast("Product created.");
    closeModal();
    await renderDashboard();
  }

  async function editRetailerProduct(button) {
    setModal(`<div class="modal-head"><h2>Update listing</h2><button class="close-modal" data-action="close-modal">×</button></div><form data-form="edit-retailer-product" data-listing-id="${escapeHtml(button.dataset.listingId)}" class="api-form"><p>${escapeHtml(button.dataset.name)}</p><label class="field">Price (UGX)<input name="price_ugx" type="number" min="1" step="1" value="${Number(button.dataset.price)}" required></label><p class="form-message" aria-live="polite"></p><button class="button-primary">Save price</button></form>`);
  }

  async function updateRetailerProduct(form) {
    const price = Number(new FormData(form).get("price_ugx"));
    await apiFetch(`/retailers/me/products/${encodeURIComponent(form.dataset.listingId)}`, { method: "PATCH", body: JSON.stringify({ price_ugx: price }) });
    showToast("Product price updated.");
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
      else if (action === "checkout") await placeOrder(form);
      else if (action === "address") await saveAddress(form);
      else if (action === "review") await submitReview(form);
      else if (action === "customer-profile") await saveCustomerProfile(form);
      else if (action === "retailer-profile") await saveRetailerProfile(form);
      else if (action === "agent-profile") await saveAgentProfile(form);
      else if (action === "new-product") await createProduct(form);
      else if (action === "edit-retailer-product") await updateRetailerProduct(form);
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
    if (action === "show-register") return showAuth(true);
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
    if (action === "new-address") return showNewAddress();
    if (action === "retailer-details") return showRetailer(button.dataset.retailerSlug);
    if (action === "retry-online-payment") return retryOnlinePayment(button.dataset.orderId, button.dataset.method, button.dataset.phone);
    if (action === "order-details") return showOrder(button.dataset.id);
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
    if (action === "retailer-availability") {
      await apiFetch("/retailers/me/availability", { method: "PATCH", body: JSON.stringify({ is_open: button.dataset.open === "true" }) });
      return renderDashboard();
    }
    if (action === "agent-availability") {
      await apiFetch("/deliveries/me/availability", { method: "PATCH", body: JSON.stringify({ availability_status: button.dataset.status }) });
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
    if (action === "user-status") {
      await apiFetch(`/admin/users/${encodeURIComponent(button.dataset.id)}/status`, { method: "PATCH", body: JSON.stringify({ status: button.dataset.status }) });
      return renderDashboard();
    }
    if (action === "verify-retailer") {
      await apiFetch(`/admin/retailers/${encodeURIComponent(button.dataset.id)}/verification`, { method: "PATCH", body: JSON.stringify({ status: "VERIFIED" }) });
      return renderDashboard();
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

  function installStyles() {
    const account = $("#accountButton");
    if (account) account.classList.remove("hidden");
    const mobileCart = $("#mobileCartNav");
    const mobileAccount = $("#mobileAccountNav");
    if (mobileCart) mobileCart.addEventListener("click", showCart);
    if (mobileAccount) mobileAccount.addEventListener("click", () => state.user ? showDashboard(true) : showAuth());
  }

  function bindEvents() {
    document.addEventListener("click", event => {
      const button = event.target.closest("[data-action]");
      if (button) {
        event.preventDefault();
        performAction(button).catch(error => showToast(error.message));
        return;
      }
      if (event.target === $("#modalBackdrop")) closeModal();
    });
    document.addEventListener("submit", event => {
      const form = event.target.closest("form[data-form]");
      if (!form) return;
      event.preventDefault();
      submitForm(form);
    });
    $("#accountButton").addEventListener("click", () => state.user ? showDashboard(true) : showAuth());
    $("#mobileAccount").addEventListener("click", () => state.user ? showDashboard(true) : showAuth());
    $("#cartButton").addEventListener("click", showCart);
    $("#locationButton").addEventListener("click", () => {
      if (!state.user) return showAuth();
      state.dashboardSection = state.user.role === "CUSTOMER" ? "addresses" : "overview";
      showDashboard(true);
    });
    $("#sellCta").addEventListener("click", () => state.user ? showDashboard(true) : showAuth(true, "RETAILER"));
    $("#searchInput").addEventListener("input", event => {
      state.search = event.target.value.trim();
      renderCatalog();
    });
    $("#sortFilter").addEventListener("change", event => {
      state.sort = event.target.value;
      renderCatalog();
    });
    $("#availabilityFilter").addEventListener("change", event => {
      state.availability = event.target.value === "nearby" ? "all" : event.target.value;
      if (event.target.value === "nearby") showToast("Nearby distance filtering is not provided by the current API.");
      renderCatalog();
    });
    $("#modalContent").addEventListener("change", event => {
      if (event.target.closest('form[data-form="checkout"]')) toggleCheckoutFields();
      if (event.target.closest('form[data-form="register"]')) updateRegistrationFields();
    });
    $("#logo")?.addEventListener("click", () => showDashboard(false));
    document.querySelectorAll(".logo").forEach(logo => logo.addEventListener("click", () => showDashboard(false)));
    $("#nearbyButton").addEventListener("click", () => document.querySelector("#retailers").scrollIntoView({ behavior: "smooth" }));
    $("#retailerMore").addEventListener("click", () => document.querySelector("#retailers").scrollIntoView({ behavior: "smooth" }));
    $("#allCategories").addEventListener("click", () => {
      state.activeCategory = "all";
      renderCategories();
      renderCatalog();
      document.querySelector("#products").scrollIntoView({ behavior: "smooth" });
    });
    window.addEventListener("storage", event => {
      if (event.key === ACCESS_KEY || event.key === REFRESH_KEY) {
        resetUserScopedUI();
        renderCatalog();
        if (!localStorage.getItem(ACCESS_KEY)) {
          $("#dashboard").classList.add("hidden");
          $("#storefront").classList.remove("hidden");
          $("#footer").classList.remove("hidden");
          $("#topbar").classList.remove("hidden");
        }
        else loadCurrentUser().catch(error => showToast(error.message));
      }
    });
  }

  async function initialize() {
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
