document.addEventListener("DOMContentLoaded", () => {
  const receiptList = document.getElementById("receipt-list");
  const receiptEmpty = document.getElementById("receipt-empty");
  const receiptCount = document.getElementById("receipt-count");
  const receiptDate = document.getElementById("receipt-date");
  const mobileBarCount = document.getElementById("mobile-bar-count");
  const statusMsg = document.getElementById("status-msg");
  const shareButtons = ["btn-whatsapp", "btn-email", "btn-clear", "btn-shopping"].map(id => document.getElementById(id));

  if (receiptDate) {
    receiptDate.textContent = new Date().toLocaleDateString(undefined, {
      weekday: "long", day: "numeric", month: "short"
    });
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  function setStatus(message, type) {
    statusMsg.textContent = message;
    statusMsg.className = "status-msg " + (type || "");
    if (message) {
      setTimeout(() => { statusMsg.textContent = ""; statusMsg.className = "status-msg"; }, 5000);
    }
  }

  function itemCount() { return receiptList.children.length; }

  function refreshEmptyState() {
    const n = itemCount();
    receiptEmpty.style.display = n ? "none" : "block";
    receiptCount.textContent = `${n} item${n === 1 ? "" : "s"}`;
    if (mobileBarCount) mobileBarCount.textContent = n;
    shareButtons.forEach(btn => { if (btn) btn.disabled = n === 0; });
    if (n === 0) exitShoppingMode();
  }

  function syncChipState(itemId, selected) {
    document.querySelectorAll(`.item-chip[data-item-id="${itemId}"]`).forEach(chip => {
      chip.classList.toggle("selected", selected);
      chip.setAttribute("aria-pressed", selected ? "true" : "false");
    });
    document.querySelectorAll(`.freq-chip[data-item-id="${itemId}"]`).forEach(chip => {
      chip.classList.toggle("selected", selected);
      chip.setAttribute("aria-pressed", selected ? "true" : "false");
    });
  }

  function makeReceiptLi(itemId, name, unit, quantity) {
    const li = document.createElement("li");
    li.dataset.entryItemId = itemId;
    li.dataset.entryName = name;
    li.dataset.entryUnit = unit;
    li.innerHTML = `
      <span class="shopping-check"><svg class="icon icon-sm" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></span>
      <span class="entry-name">${escapeHtml(name)}</span>
      <span class="qty-stepper">
        <button type="button" class="qty-minus" aria-label="Decrease ${escapeHtml(name)} quantity">−</button>
        <span class="qty-val">${escapeHtml(String(quantity))} ${escapeHtml(unit)}</span>
        <button type="button" class="qty-plus" aria-label="Increase ${escapeHtml(name)} quantity">+</button>
        <button type="button" class="remove-btn" aria-label="Remove ${escapeHtml(name)}">
          <svg class="icon icon-sm" viewBox="0 0 24 24"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </span>`;
    wireReceiptLi(li);
    return li;
  }

  function addToReceipt(itemId, name, unit, quantity) {
    const li = makeReceiptLi(itemId, name, unit, quantity || "1");
    receiptList.appendChild(li);
    refreshEmptyState();
  }

  function removeFromReceipt(itemId) {
    const li = receiptList.querySelector(`li[data-entry-item-id="${itemId}"]`);
    if (li) li.remove();
    refreshEmptyState();
  }

  // ---------- Quantity stepper + remove wiring (delegated per-line) ----------
  function wireReceiptLi(li) {
    const itemId = li.dataset.entryItemId;

    li.querySelector(".qty-plus").addEventListener("click", (e) => {
      e.stopPropagation();
      stepQuantity(itemId, "increment", li);
    });
    li.querySelector(".qty-minus").addEventListener("click", (e) => {
      e.stopPropagation();
      stepQuantity(itemId, "decrement", li);
    });
    li.querySelector(".remove-btn").addEventListener("click", async (e) => {
      e.stopPropagation();
      try {
        const res = await fetch("/list/toggle", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ item_id: itemId }),
        });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || "Could not remove item.");
        removeFromReceipt(itemId);
        syncChipState(itemId, false);
        resetChipQuantity(itemId);
      } catch (err) {
        setStatus(err.message, "error");
      }
    });

    // shopping-mode tap-to-check
    li.addEventListener("click", () => {
      if (!receiptList.classList.contains("shopping-mode")) return;
      li.classList.toggle("done");
      updateShoppingProgress();
    });
  }

  function resetChipQuantity(itemId) {
    const chip = document.querySelector(`.item-chip[data-item-id="${itemId}"]`);
    if (!chip) return;
    chip.dataset.qty = "1";
    const qtyText = chip.querySelector(".qty-text");
    if (qtyText) qtyText.textContent = `1 ${chip.dataset.itemUnit}`;
  }

  async function updateItemQuantity(itemId, action, opts) {
    opts = opts || {};
    try {
      const res = await fetch("/list/update-quantity", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ item_id: itemId, action }),
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || "Could not update quantity.");
      if (data.removed) {
        removeFromReceipt(itemId);
        syncChipState(itemId, false);
        resetChipQuantity(itemId);
      } else {
        const li = opts.li || receiptList.querySelector(`li[data-entry-item-id="${itemId}"]`);
        const chip = opts.chip || document.querySelector(`.item-chip[data-item-id="${itemId}"]`);
        const unit = (li && li.dataset.entryUnit) || (chip && chip.dataset.itemUnit) || "";
        if (li) li.querySelector(".qty-val").textContent = `${data.quantity} ${unit}`;
        if (chip) {
          chip.dataset.qty = data.quantity;
          const qtyText = chip.querySelector(".qty-text");
          if (qtyText) qtyText.textContent = `${data.quantity} ${unit}`;
        }
      }
    } catch (err) {
      setStatus(err.message, "error");
    }
  }

  function stepQuantity(itemId, action, li) {
    return updateItemQuantity(itemId, action, { li });
  }

  receiptList.querySelectorAll("li").forEach(wireReceiptLi);

  // ---------- Frequently-added pill toggling (simple button, no quantity control) ----------
  function wireSelectable(chip) {
    chip.addEventListener("click", async () => {
      const itemId = chip.dataset.itemId;
      const name = chip.dataset.itemName;
      const unit = chip.dataset.itemUnit;
      const willSelect = !chip.classList.contains("selected");

      syncChipState(itemId, willSelect);
      if (willSelect) addToReceipt(itemId, name, unit, "1");
      else removeFromReceipt(itemId);

      try {
        const res = await fetch("/list/toggle", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ item_id: itemId, quantity: "1" }),
        });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || "Could not update list.");
      } catch (err) {
        syncChipState(itemId, !willSelect);
        if (willSelect) removeFromReceipt(itemId);
        else addToReceipt(itemId, name, unit, "1");
        setStatus(err.message, "error");
      }
    });
  }

  // ---------- Grocery card toggling (div-based card, keyboard accessible, with inline qty stepper) ----------
  function wireGroceryCard(chip) {
    const itemId = chip.dataset.itemId;

    function toggle() {
      const name = chip.dataset.itemName;
      const unit = chip.dataset.itemUnit;
      const willSelect = !chip.classList.contains("selected");

      syncChipState(itemId, willSelect);
      if (willSelect) {
        chip.dataset.qty = "1";
        const qtyText = chip.querySelector(".qty-text");
        if (qtyText) qtyText.textContent = `1 ${unit}`;
        addToReceipt(itemId, name, unit, "1");
      } else {
        removeFromReceipt(itemId);
      }

      fetch("/list/toggle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ item_id: itemId, quantity: "1" }),
      })
        .then((res) => res.json())
        .then((data) => {
          if (!data.ok) throw new Error(data.error || "Could not update list.");
        })
        .catch((err) => {
          syncChipState(itemId, !willSelect);
          if (willSelect) removeFromReceipt(itemId);
          else addToReceipt(itemId, name, unit, "1");
          setStatus(err.message, "error");
        });
    }

    chip.addEventListener("click", (e) => {
      if (e.target.closest(".qty-control") || e.target.closest(".item-delete") || e.target.closest(".item-hide")) return;
      toggle();
    });

    chip.addEventListener("keydown", (e) => {
      if (e.target.closest(".qty-control") || e.target.closest(".item-delete") || e.target.closest(".item-hide")) return;
      if (e.key === "Enter" || e.key === " " || e.key === "Spacebar") {
        e.preventDefault();
        toggle();
      }
    });

    const minusBtn = chip.querySelector(".qty-minus");
    const plusBtn = chip.querySelector(".qty-plus");
    if (minusBtn) {
      minusBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        updateItemQuantity(itemId, "decrement", { chip });
      });
    }
    if (plusBtn) {
      plusBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        updateItemQuantity(itemId, "increment", { chip });
      });
    }

    const deleteBtn = chip.querySelector(".item-delete");
    if (deleteBtn) {
      deleteBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        const name = chip.dataset.itemName;
        if (!window.confirm(`Remove "${name}" from your items? This can't be undone.`)) return;

        fetch(`/item/delete/${itemId}`, { method: "POST" })
          .then((res) => res.json())
          .then((data) => {
            if (!data.ok) throw new Error(data.error || "Could not delete item.");
            if (chip.classList.contains("selected")) {
              removeFromReceipt(itemId);
            }
            chip.remove();
          })
          .catch((err) => setStatus(err.message, "error"));
      });
    }

    const hideBtn = chip.querySelector(".item-hide");
    if (hideBtn) {
      hideBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        const name = chip.dataset.itemName;

        fetch(`/item/hide/${itemId}`, { method: "POST" })
          .then((res) => res.json())
          .then((data) => {
            if (!data.ok) throw new Error(data.error || "Could not hide item.");
            if (chip.classList.contains("selected")) {
              removeFromReceipt(itemId);
            }
            chip.remove();
            setStatus(`"${name}" hidden. Restore it any time from History.`, "info");
          })
          .catch((err) => setStatus(err.message, "error"));
      });
    }
  }

  document.querySelectorAll(".item-chip").forEach(wireGroceryCard);
  document.querySelectorAll(".freq-chip").forEach(wireSelectable);

  // ---------- Search ----------
  const searchInput = document.getElementById("search-input");
  const searchClear = document.getElementById("search-clear");
  const noResults = document.getElementById("search-no-results");
  const freqBlock = document.getElementById("freq-block");

  function runSearch() {
    const q = searchInput.value.trim().toLowerCase();
    searchClear.classList.toggle("visible", q.length > 0);
    if (freqBlock) freqBlock.style.display = q ? "none" : "";

    if (!q) {
      document.querySelectorAll(".item-chip").forEach(c => c.classList.remove("hidden-by-search"));
      document.querySelectorAll(".category-block").forEach(c => c.classList.remove("hidden-by-search"));
      noResults.classList.remove("visible");
      return;
    }

    let anyVisible = false;
    document.querySelectorAll(".category-block").forEach(block => {
      let blockHasMatch = false;
      block.querySelectorAll(".item-chip").forEach(chip => {
        const match = chip.dataset.search.includes(q);
        chip.classList.toggle("hidden-by-search", !match);
        if (match) blockHasMatch = true;
      });
      block.classList.toggle("hidden-by-search", !blockHasMatch);
      if (blockHasMatch) anyVisible = true;
    });
    noResults.classList.toggle("visible", !anyVisible);
  }

  searchInput.addEventListener("input", runSearch);
  searchClear.addEventListener("click", () => {
    searchInput.value = "";
    runSearch();
    searchInput.focus();
  });

  // ---------- Clear list (optimistic, with undo) ----------
  const undoToast = document.getElementById("undo-toast");
  const undoBtn = document.getElementById("undo-btn");
  let clearTimer = null;
  let clearedSnapshot = null;

  document.getElementById("btn-clear").addEventListener("click", () => {
    if (itemCount() === 0) return;

    clearedSnapshot = Array.from(receiptList.children).map(li => ({
      itemId: li.dataset.entryItemId,
      name: li.dataset.entryName,
      unit: li.dataset.entryUnit,
      html: li.outerHTML,
    }));
    const selectedIds = clearedSnapshot.map(e => e.itemId);

    receiptList.innerHTML = "";
    refreshEmptyState();
    selectedIds.forEach(id => syncChipState(id, false));

    undoToast.classList.add("visible");
    clearTimer = setTimeout(async () => {
      undoToast.classList.remove("visible");
      try {
        await fetch("/list/clear", { method: "POST" });
      } catch (err) { /* silent — list is already visually cleared */ }
      clearedSnapshot = null;
    }, 5000);
  });

  undoBtn.addEventListener("click", () => {
    if (!clearedSnapshot) return;
    clearTimeout(clearTimer);
    clearedSnapshot.forEach(entry => {
      const wrapper = document.createElement("div");
      wrapper.innerHTML = entry.html;
      const li = wrapper.firstElementChild;
      wireReceiptLi(li);
      receiptList.appendChild(li);
      syncChipState(entry.itemId, true);
    });
    clearedSnapshot = null;
    undoToast.classList.remove("visible");
    refreshEmptyState();
    setStatus("List restored.", "success");
  });

  // ---------- WhatsApp send ----------
  document.getElementById("btn-whatsapp").addEventListener("click", async () => {
    const number = document.getElementById("whatsapp-number").value.trim();
    if (itemCount() === 0) { setStatus("Select a few items first.", "error"); return; }
    try {
      const res = await fetch("/list/whatsapp-link", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ number }),
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error);
      window.open(data.link, "_blank");
      setStatus("Opening WhatsApp…", "success");
    } catch (err) {
      setStatus(err.message, "error");
    }
  });

  // ---------- Email send ----------
  document.getElementById("btn-email").addEventListener("click", async () => {
    const email = document.getElementById("email-address").value.trim();
    if (itemCount() === 0) { setStatus("Select a few items first.", "error"); return; }
    const btn = document.getElementById("btn-email");
    btn.disabled = true;
    const originalLabel = btn.textContent;
    btn.textContent = "Sending…";
    try {
      const res = await fetch("/list/send-email", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error);
      setStatus("List emailed successfully.", "success");
    } catch (err) {
      setStatus(err.message, "error");
    } finally {
      btn.disabled = itemCount() === 0;
      btn.textContent = originalLabel;
    }
  });

  // ---------- Shopping mode ----------
  const btnShopping = document.getElementById("btn-shopping");
  const exitShopping = document.getElementById("exit-shopping");
  const shoppingProgress = document.getElementById("shopping-progress");
  const sendBlock = document.getElementById("send-block");

  function updateShoppingProgress() {
    const total = receiptList.children.length;
    const done = receiptList.querySelectorAll("li.done").length;
    shoppingProgress.textContent = `${done} / ${total} completed`;
  }

  function enterShoppingMode() {
    if (itemCount() === 0) return;
    receiptList.classList.add("shopping-mode");
    shoppingProgress.style.display = "block";
    btnShopping.style.display = "none";
    exitShopping.style.display = "block";
    sendBlock.style.display = "none";
    updateShoppingProgress();
  }

  function exitShoppingMode() {
    receiptList.classList.remove("shopping-mode");
    receiptList.querySelectorAll("li.done").forEach(li => li.classList.remove("done"));
    shoppingProgress.style.display = "none";
    btnShopping.style.display = "";
    exitShopping.style.display = "none";
    sendBlock.style.display = "";
  }

  btnShopping.addEventListener("click", enterShoppingMode);
  exitShopping.addEventListener("click", exitShoppingMode);

  // ---------- Mobile bottom sheet ----------
  const receiptWrap = document.getElementById("receipt-wrap");
  const mobileBar = document.getElementById("mobile-bar");
  const sheetClose = document.getElementById("sheet-close");
  const sheetBackdrop = document.getElementById("sheet-backdrop");

  function openSheet() {
    receiptWrap.classList.add("open");
    sheetBackdrop.classList.add("open");
  }
  function closeSheet() {
    receiptWrap.classList.remove("open");
    sheetBackdrop.classList.remove("open");
  }

  if (mobileBar) mobileBar.addEventListener("click", openSheet);
  if (sheetClose) sheetClose.addEventListener("click", closeSheet);
  if (sheetBackdrop) sheetBackdrop.addEventListener("click", closeSheet);

  // ---------- Add custom item modal ----------
  const modal = document.getElementById("modal-backdrop");
  const modalError = document.getElementById("modal-error");
  let activeCategoryId = null;

  document.querySelectorAll(".add-item-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      activeCategoryId = btn.dataset.addCategory;
      modalError.style.display = "none";
      document.getElementById("new-item-name").value = "";
      document.getElementById("new-item-qty").value = "1";
      document.getElementById("new-item-unit").value = "pcs";
      modal.classList.add("open");
      document.getElementById("new-item-name").focus();
    });
  });

  document.getElementById("modal-cancel").addEventListener("click", () => modal.classList.remove("open"));
  modal.addEventListener("click", (e) => { if (e.target === modal) modal.classList.remove("open"); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && modal.classList.contains("open")) modal.classList.remove("open"); });

  document.getElementById("modal-save").addEventListener("click", async () => {
    const name = document.getElementById("new-item-name").value.trim();
    const qty = document.getElementById("new-item-qty").value.trim() || "1";
    const unit = document.getElementById("new-item-unit").value.trim() || "pcs";

    if (name.length < 2) {
      modalError.textContent = "Item name must be at least 2 characters.";
      modalError.style.display = "block";
      return;
    }

    try {
      const res = await fetch("/item/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, unit, category_id: activeCategoryId, quantity: qty }),
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error);

      const grid = document.querySelector(`.item-grid[data-category-id="${activeCategoryId}"]`);
      const addBtn = grid.querySelector(".add-item-chip");
      const finalQty = data.item.quantity || qty;
      const chip = document.createElement("div");
      chip.className = "item-chip selected";
      chip.setAttribute("role", "button");
      chip.setAttribute("tabindex", "0");
      chip.dataset.itemId = data.item.id;
      chip.dataset.itemName = data.item.name;
      chip.dataset.itemUnit = data.item.unit;
      chip.dataset.search = data.item.name.toLowerCase();
      chip.dataset.qty = finalQty;
      chip.setAttribute("aria-pressed", "true");
      chip.innerHTML = `
        <button type="button" class="item-delete" data-item-id="${data.item.id}" aria-label="Delete ${escapeHtml(data.item.name)} from your items">
          <svg class="icon icon-sm" viewBox="0 0 24 24"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
        <span class="row">
          <span class="name">${escapeHtml(data.item.name)}</span>
          <span class="check" aria-hidden="true"><svg class="icon icon-sm" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></span>
        </span>
        <span class="unit-label">${escapeHtml(data.item.unit)}</span>
        <span class="qty-control">
          <button type="button" class="qty-btn qty-minus" aria-label="Decrease ${escapeHtml(data.item.name)} quantity">−</button>
          <span class="qty-text">${escapeHtml(String(finalQty))} ${escapeHtml(data.item.unit)}</span>
          <button type="button" class="qty-btn qty-plus" aria-label="Increase ${escapeHtml(data.item.name)} quantity">+</button>
        </span>`;
      grid.insertBefore(chip, addBtn);
      wireGroceryCard(chip);

      addToReceipt(data.item.id, data.item.name, data.item.unit, finalQty);

      modal.classList.remove("open");
      setStatus(`"${data.item.name}" added.`, "success");
    } catch (err) {
      modalError.textContent = err.message;
      modalError.style.display = "block";
    }
  });

  refreshEmptyState();
});
