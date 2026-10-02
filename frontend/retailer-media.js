(() => {
  "use strict";

  const API_BASE = document.querySelector('meta[name="wewe-api-base"]')?.content || "http://localhost:8000/api/v1";
  const ACCESS_KEY = "wewe_access_token";
  const MAX_FILES = 12;
  const MAX_BYTES = 5 * 1024 * 1024;
  const ACCEPTED = new Set(["image/jpeg", "image/png", "image/webp"]);

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, c => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;"
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

    const form = new FormData();
    form.append("file", file, file.name);
    if (altText.trim()) form.append("alt_text", altText.trim());

    const request = window.weweApiFetch;
    if (typeof request !== "function") throw new Error("WEWE is still loading. Please try again.");
    return request(`/retailers/me/products/${encodeURIComponent(listingId)}/images`, {
      method: "POST",
      body: form
    });
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

  function systemHealthStyles() {
    if (document.querySelector("#wewe-system-health-styles")) return;
    const style = document.createElement("style");
    style.id = "wewe-system-health-styles";
    style.textContent = `
      .wewe-health-panel{margin-bottom:16px;border:1px solid #e7e0ef;border-radius:18px;background:#fff;box-shadow:0 7px 22px rgba(45,25,90,.045);overflow:hidden}
      .wewe-health-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;padding:18px 20px;border-bottom:1px solid #eee9f3}
      .wewe-health-head h2{margin:0;font-size:17px;color:#342643}.wewe-health-head p{margin:4px 0 0;color:#91879c;font-size:10px}
      .wewe-health-status{display:inline-flex;align-items:center;gap:7px;padding:6px 9px;border-radius:99px;font-size:9px;font-weight:900}
      .wewe-health-status.healthy{background:#e8f7ef;color:#18794e}.wewe-health-status.degraded{background:#fff2df;color:#9a5a00}
      .wewe-health-status::before{content:"";width:7px;height:7px;border-radius:50%;background:currentColor}
      .wewe-health-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;padding:16px 20px}
      .wewe-health-card{border:1px solid #eee9f3;border-radius:13px;padding:13px;background:#fbfaff}
      .wewe-health-card h3{margin:0 0 9px;font-size:12px;color:#4b3b58}.wewe-health-meta{display:flex;justify-content:space-between;gap:10px;font-size:10px;color:#82778e}.wewe-health-meta strong{color:#38274a}
      .wewe-health-workers{border-top:1px solid #eee9f3;padding:0 20px 8px}
      .wewe-health-worker{display:grid;grid-template-columns:1.5fr .8fr 1fr 1fr;gap:10px;align-items:center;padding:11px 0;border-bottom:1px solid #f0ebf4;font-size:10px}
      .wewe-health-worker:last-child{border-bottom:0}.wewe-health-worker small{display:block;color:#9a90a4;margin-top:2px}
      .wewe-health-worker-error{grid-column:1/-1;color:#a34a43;background:#fff5f4;border-radius:8px;padding:7px 9px}
      .wewe-health-action{border:1px solid #d8cef0;background:#fff;color:#5b3db2;border-radius:9px;padding:7px 10px;font-size:10px;font-weight:800;cursor:pointer}
      .wewe-health-action:hover{background:#f8f5ff}.wewe-health-loading{padding:22px 20px;color:#8c8297;font-size:11px}
      @media(max-width:700px){.wewe-health-grid{grid-template-columns:1fr}.wewe-health-worker{grid-template-columns:1fr 1fr}.wewe-health-worker-error{grid-column:1/-1}}
    `;
    document.head.appendChild(style);
  }

  function healthBadge(status) {
    const normalized = String(status || "UNKNOWN").toLowerCase();
    return `<span class="wewe-health-status ${normalized === "healthy" ? "healthy" : "degraded"}">${escapeHtml(status || "UNKNOWN")}</span>`;
  }

  function healthTime(value) {
    if (!value) return "Never";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "Unknown" : date.toLocaleString();
  }

  async function loadSystemHealth() {
    const request = window.weweApiFetch;
    if (typeof request !== "function") throw new Error("WEWE is still loading. Please try again.");
    const health = await request("/admin/system-health");
    const content = document.querySelector("#dashboardContent");
    if (!content) return;
    const workers = Array.isArray(health.workers) ? health.workers : [];
    const storage = health.storage || {};
    content.innerHTML = `
      <section class="wewe-health-panel">
        <div class="wewe-health-head">
          <div><div class="section-kicker">Operations</div><h2>System health</h2><p>Worker heartbeats and object-storage reachability for administrators.</p></div>
          <div style="display:flex;align-items:center;gap:8px">${healthBadge(health.overall_status)}<button class="wewe-health-action" data-wewe-health-refresh>Refresh</button></div>
        </div>
        <div class="wewe-health-grid">
          <div class="wewe-health-card"><h3>Object storage</h3><div class="wewe-health-meta"><span>Provider</span><strong>${escapeHtml(storage.provider || "—")}</strong></div><div class="wewe-health-meta" style="margin-top:6px"><span>Status</span><strong>${escapeHtml(storage.status || "UNKNOWN")}</strong></div></div>
          <div class="wewe-health-card"><h3>Worker monitoring</h3><div class="wewe-health-meta"><span>Stale after</span><strong>${Number(health.worker_stale_after_seconds || 0)}s</strong></div><div class="wewe-health-meta" style="margin-top:6px"><span>Degraded</span><strong>${health.degraded_workers?.length || 0}</strong></div></div>
        </div>
        <div class="wewe-health-workers">
          ${workers.length ? workers.map(worker => `
            <div class="wewe-health-worker">
              <div><b>${escapeHtml(worker.worker_name)}</b><small>Heartbeat: ${escapeHtml(healthTime(worker.last_heartbeat_at))}</small></div>
              <div>${healthBadge(worker.status)}</div>
              <div><small>Last success</small>${escapeHtml(healthTime(worker.last_success_at))}</div>
              <div><small>Failures</small>${Number(worker.last_failed || 0).toLocaleString()}</div>
              ${worker.last_error ? `<div class="wewe-health-worker-error">${escapeHtml(worker.last_error)}</div>` : ""}
            </div>`).join("") : '<div class="wewe-health-loading">No worker health records exist yet. This is degraded until workers report their first heartbeat.</div>'}
        </div>
      </section>`;
  }

  function enhanceAdminHealth() {
    const role = document.querySelector("#sideRole")?.textContent?.trim();
    const nav = document.querySelector("#dashNav");
    if (!nav || role !== "ADMIN") return;
    systemHealthStyles();
    if (!nav.querySelector("[data-wewe-system-health]")) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "System health";
      button.dataset.weweSystemHealth = "true";
      nav.appendChild(button);
    }
  }

  document.addEventListener("click", event => {
    const healthButton = event.target.closest("[data-wewe-system-health]");
    const refreshButton = event.target.closest("[data-wewe-health-refresh]");
    if (healthButton) {
      event.preventDefault();
      document.querySelectorAll("#dashNav button").forEach(button => button.classList.remove("active"));
      healthButton.classList.add("active");
      const content = document.querySelector("#dashboardContent");
      if (content) content.innerHTML = '<div class="wewe-health-loading">Loading operational health…</div>';
      loadSystemHealth().catch(error => {
        if (content) content.innerHTML = `<div class="api-state api-error">${escapeHtml(error.message)}</div>`;
      });
    }
    if (refreshButton) {
      event.preventDefault();
      const content = document.querySelector("#dashboardContent");
      if (content) content.innerHTML = '<div class="wewe-health-loading">Refreshing operational health…</div>';
      loadSystemHealth().catch(error => {
        if (content) content.innerHTML = `<div class="api-state api-error">${escapeHtml(error.message)}</div>`;
      });
    }
  });

  const adminHealthObserver = new MutationObserver(() => enhanceAdminHealth());
  adminHealthObserver.observe(document.body, { childList: true, subtree: true });
  enhanceAdminHealth();

})();