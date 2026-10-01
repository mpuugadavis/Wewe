(() => {
  "use strict";

  const API_BASE = document.querySelector('meta[name="wewe-api-base"]')?.content || "http://localhost:8000/api/v1";
  const ACCESS_KEY = "wewe_access_token";
  const MAX_FILES = 12;
  const MAX_BYTES = 5 * 1024 * 1024;
  const ACCEPTED = new Set(["image/jpeg", "image/png", "image/webp"]);

  function token() {
    return localStorage.getItem(ACCESS_KEY);
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", """: "&quot;", "'": "&#39;"
    }[c]));
  }

  function toast(message) {
    if (typeof window.showToast === "function") return window.showToast(message);
    const node = document.querySelector("#toast");
    if (!node) return;
    node.textContent = message;
    node.classList.add("show");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => node.classList.remove("show"), 3600);
  }

  function addStyles() {
    if (document.querySelector("#wewe-retailer-media-styles")) return;
    const style = document.createElement("style");
    style.id = "wewe-retailer-media-styles";
    style.textContent = `
      .wewe-media-action{display:inline-flex;align-items:center;gap:6px;border:1px solid #ddd6e6;background:#fff;color:#5b3db2;border-radius:10px;padding:8px 10px;font-size:11px;font-weight:800}
      .wewe-media-action:hover{border-color:#bdaef0;background:#f8f5ff}
      .wewe-media-modal{display:grid;gap:16px}
      .wewe-media-drop{border:1.5px dashed #cfc3e4;background:#f8f5ff;border-radius:15px;padding:22px;text-align:center}
      .wewe-media-drop input{display:block;width:100%;margin-top:12px}
      .wewe-media-help{font-size:11px;color:#81798b}
      .wewe-media-preview{display:grid;grid-template-columns:repeat(auto-fill,minmax(90px,1fr));gap:9px}
      .wewe-media-preview img{width:100%;height:90px;object-fit:cover;border-radius:10px;background:#eeeaf5}
      .wewe-media-progress{font-size:11px;color:#5b3db2;min-height:18px}
    `;
    document.head.appendChild(style);
  }

  function refreshRetailerProducts() {
    const nav = [...document.querySelectorAll('#dashNav [data-action="dashboard-section"]')]
      .find(button => button.dataset.section === "products");
    if (nav) nav.click();
  }

  async function uploadFile(listingId, file, altText) {
    if (!ACCEPTED.has(file.type)) throw new Error("Only JPEG, PNG, and WebP images are allowed.");
    if (file.size <= 0 || file.size > MAX_BYTES) throw new Error("Each image must be between 1 byte and 5 MiB.");
    const access = token();
    if (!access) throw new Error("Your session has expired. Please sign in again.");

    const form = new FormData();
    form.append("file", file, file.name);
    if (altText.trim()) form.append("alt_text", altText.trim());

    const response = await fetch(`${API_BASE}/retailers/me/products/${encodeURIComponent(listingId)}/images`, {
      method: "POST",
      headers: { Authorization: `Bearer ${access}` },
      body: form
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      const message = payload?.error?.message || payload?.detail?.message || payload?.detail || `Image upload failed (${response.status}).`;
      throw new Error(String(message));
    }
    return payload;
  }

  function openUpload(listingId, productName) {
    const backdrop = document.querySelector("#modalBackdrop");
    const modal = document.querySelector("#modalContent");
    if (!backdrop || !modal) return;
    modal.classList.remove("modal-wide");
    modal.innerHTML = `
      <div class="modal-head">
        <div><div class="section-kicker">Product media</div><h2>Add product images</h2><p class="muted">${escapeHtml(productName)}</p></div>
        <button class="close-modal" data-action="close-modal" aria-label="Close">×</button>
      </div>
      <div class="wewe-media-modal">
        <form id="wewe-media-form" class="api-form">
          <label class="field">Alt text <input name="alt_text" maxlength="250" placeholder="Describe the product image"></label>
          <div class="wewe-media-drop">
            <strong>Select product images</strong>
            <div class="wewe-media-help">JPEG, PNG or WebP · maximum 5 MiB each · up to 12 images per product</div>
            <input name="files" type="file" accept="image/jpeg,image/png,image/webp" multiple required>
          </div>
          <div id="wewe-media-preview" class="wewe-media-preview"></div>
          <div id="wewe-media-progress" class="wewe-media-progress" aria-live="polite"></div>
          <p class="form-message" aria-live="polite"></p>
          <button class="button-primary" type="submit">Upload images</button>
        </form>
      </div>`;
    backdrop.classList.add("open");
    document.body.classList.add("modal-open");

    const form = modal.querySelector("#wewe-media-form");
    const input = form.elements.files;
    const preview = modal.querySelector("#wewe-media-preview");
    input.addEventListener("change", () => {
      preview.replaceChildren();
      [...input.files].slice(0, MAX_FILES).forEach(file => {
        const img = document.createElement("img");
        img.alt = file.name;
        img.src = URL.createObjectURL(file);
        img.onload = () => URL.revokeObjectURL(img.src);
        preview.appendChild(img);
      });
    });

    form.addEventListener("submit", async event => {
      event.preventDefault();
      const files = [...input.files];
      const message = modal.querySelector(".form-message");
      const progress = modal.querySelector("#wewe-media-progress");
      const submit = form.querySelector("button[type=submit]");
      message.textContent = "";
      if (!files.length) {
        message.textContent = "Choose at least one image.";
        return;
      }
      if (files.length > MAX_FILES) {
        message.textContent = `Choose no more than ${MAX_FILES} images at a time.`;
        return;
      }
      submit.disabled = true;
      try {
        for (let index = 0; index < files.length; index += 1) {
          progress.textContent = `Uploading image ${index + 1} of ${files.length}…`;
          await uploadFile(listingId, files[index], form.elements.alt_text.value);
        }
        progress.textContent = "All images uploaded successfully.";
        toast("Product images uploaded.");
        setTimeout(() => {
          backdrop.classList.remove("open");
          document.body.classList.remove("modal-open");
          refreshRetailerProducts();
        }, 500);
      } catch (error) {
        message.textContent = error.message;
        progress.textContent = "";
      } finally {
        submit.disabled = false;
      }
    });
  }

  function enhanceProductsPanel() {
    const panel = document.querySelector("#dashboardContent .dashboard-panel");
    if (!panel) return;
    const heading = panel.querySelector("h2");
    if (!heading || heading.textContent.trim() !== "Your product listings") return;
    panel.querySelectorAll(".listing-row").forEach(row => {
      if (row.querySelector(".wewe-media-action")) return;
      const edit = row.querySelector('[data-action="edit-retailer-product"]');
      if (!edit?.dataset.listingId) return;
      const name = edit.dataset.name || "Product";
      const actions = row.querySelector(".row-actions");
      if (!actions) return;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "wewe-media-action";
      button.textContent = "Add images";
      button.dataset.weweUploadListing = edit.dataset.listingId;
      button.dataset.weweUploadName = name;
      actions.prepend(button);
    });
  }

  document.addEventListener("click", event => {
    const button = event.target.closest("[data-wewe-upload-listing]");
    if (!button) return;
    event.preventDefault();
    openUpload(button.dataset.weweUploadListing, button.dataset.weweUploadName);
  });

  const observer = new MutationObserver(() => enhanceProductsPanel());
  observer.observe(document.body, { childList: true, subtree: true });
  addStyles();
  enhanceProductsPanel();
})();