/* Presentation and keyboard behavior only. Commerce requests remain in app.js. */
(() => {
  "use strict";
  const backdrop = document.getElementById("modalBackdrop");
  const modal = document.getElementById("modalContent");
  if (!backdrop || !modal) return;
  let wasOpen = false;
  let returnFocus = null;
  let lastTrigger = null;
  let lastTriggerTime = 0;
  // Safari/WebKit does not focus every button on a mouse click. Remember the
  // actual opener before app.js handles the click and creates the dialog.
  document.addEventListener("click", event => {
    if (backdrop.classList.contains("open") || !(event.target instanceof Element)) return;
    lastTrigger = event.target.closest('button,a[href],input,select,textarea,[tabindex="0"]');
    lastTriggerTime = Date.now();
  }, true);
  const background = [...document.body.children].filter(element =>
    ![backdrop, document.getElementById("toast")].includes(element) &&
    !["SCRIPT", "STYLE"].includes(element.tagName));
  const previousInert = new Map();
  const focusable = () => [...modal.querySelectorAll(
    'a[href],button:not([disabled]),input:not([disabled]):not([type="hidden"]),select:not([disabled]),textarea:not([disabled]),[tabindex="0"]'
  )].filter(element => element.getClientRects().length && !element.closest("[inert]"));
  function synchronize() {
    const open = backdrop.classList.contains("open");
    if (open && !wasOpen) {
      returnFocus = lastTrigger?.isConnected && Date.now() - lastTriggerTime < 10000
        ? lastTrigger : document.activeElement;
      lastTrigger = null;
      background.forEach(element => {
        previousInert.set(element, element.inert);
        element.inert = true;
      });
    }
    if (open) {
      const heading = modal.querySelector("h2");
      if (heading) {
        heading.id = "weweDialogTitle";
        modal.setAttribute("aria-labelledby", heading.id);
        modal.removeAttribute("aria-label");
      } else {
        modal.removeAttribute("aria-labelledby");
        modal.setAttribute("aria-label", "WEWE");
      }
      if (!wasOpen || !modal.contains(document.activeElement)) {
        modal.tabIndex = -1;
        (focusable()[0] || modal).focus({ preventScroll: true });
      }
    } else if (wasOpen) {
      background.forEach(element => { element.inert = previousInert.get(element) || false; });
      previousInert.clear();
      if (returnFocus?.isConnected && returnFocus.getClientRects().length) returnFocus.focus({ preventScroll: true });
      returnFocus = null;
    }
    wasOpen = open;
  }
  new MutationObserver(synchronize).observe(backdrop, { attributes: true, attributeFilter: ["class"] });
  new MutationObserver(synchronize).observe(modal, { childList: true, subtree: true });
  document.addEventListener("keydown", event => {
    if (event.key !== "Tab" || !backdrop.classList.contains("open")) return;
    const elements = focusable();
    if (!elements.length) { event.preventDefault(); modal.focus(); return; }
    const first = elements[0], last = elements[elements.length - 1];
    if (event.shiftKey && (document.activeElement === first || document.activeElement === modal)) {
      event.preventDefault(); last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault(); first.focus();
    }
  });
  synchronize();
})();
