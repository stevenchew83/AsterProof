(function () {
  var form = document.getElementById("solution-editor-form");
  if (!form) return;

  var previewRoot = document.getElementById("solution-live-preview");
  var blockList = document.getElementById("solution-block-list");
  var addBlockButton = document.getElementById("solution-add-block");
  var totalFormsInput = document.getElementById("id_blocks-TOTAL_FORMS");
  var emptyTemplate = document.getElementById("solution-block-empty-form");
  var mediaBaseUrl = (window.ASTERPROOF_SOLUTION_MEDIA && window.ASTERPROOF_SOLUTION_MEDIA.baseUrl) || "";
  var uploadUrl = (window.ASTERPROOF_SOLUTION_MEDIA && window.ASTERPROOF_SOLUTION_MEDIA.uploadUrl) || "";
  var plainBlockTypeId = (
    window.ASTERPROOF_SOLUTION_PREVIEW && window.ASTERPROOF_SOLUTION_PREVIEW.plainBlockTypeId
  ) || "";
  var previewTimer = null;
  var workspace = document.getElementById("solution-editor-workspace");
  var saveStatus = document.getElementById("solution-save-status");
  var saveButton = document.getElementById("solution-save");
  var submitButtons = Array.from(document.querySelectorAll('button[type="submit"][form="solution-editor-form"]'));
  var lastRemoved = null;
  var pendingUploads = 0;
  var submitting = false;
  var initialSnapshot = "";
  var initialStatus = saveStatus.textContent;
  var previewVersion = 0;
  var wideLayout = window.matchMedia("(min-width: 1200px)");

  function formSnapshot() {
    return JSON.stringify(Array.from(new FormData(form).entries()).filter(function (entry) {
      return entry[0] !== "csrfmiddlewaretoken";
    }).sort(function (left, right) { return left[0].localeCompare(right[0]); }));
  }

  function hasChanges() {
    return form.dataset.bound === "true" || formSnapshot() !== initialSnapshot;
  }

  function updateSaveState() {
    var dirty = hasChanges();
    saveStatus.dataset.dirty = String(dirty);
    form.dispatchEvent(new CustomEvent("asterproof:solution-save-state"));
    saveStatus.textContent = pendingUploads ? "Uploading image\u2026" : (dirty ? "Unsaved changes" : initialStatus);
    submitButtons.forEach(function (button) { button.disabled = pendingUploads > 0; });
  }

  function setView(mode) {
    if (mode === "split" && !wideLayout.matches) mode = "write";
    workspace.dataset.view = mode;
    document.querySelectorAll("[data-editor-view]").forEach(function (button) {
      button.setAttribute("aria-pressed", String(button.dataset.editorView === mode));
    });
    if (mode !== "write") scheduleRenderPreview();
  }

  function normalizeOrder() {
    visibleBlocks().forEach(function (node, index) {
      node.querySelector(".solution-order-input").value = String(index + 1);
    });
  }

  function moveBlock(node, direction) {
    var rows = visibleBlocks(), index = rows.indexOf(node);
    var target = rows[index + (direction === "up" ? -1 : 1)];
    if (!target) return;
    if (direction === "up") blockList.insertBefore(node, target);
    else blockList.insertBefore(target, node);
    normalizeOrder(); refreshBlockNumbers(); updateSaveState(); scheduleRenderPreview();
  }

  function removeBlock(node) {
    var rows = visibleBlocks(), index = rows.indexOf(node);
    lastRemoved = { node: node, next: rows[index + 1] || null };
    var checkbox = node.querySelector(".solution-delete-input");
    if (checkbox) checkbox.checked = true;
    node.classList.add("d-none");
    document.getElementById("solution-removed-feedback").classList.remove("d-none");
    normalizeOrder(); refreshBlockNumbers(); updateSaveState(); scheduleRenderPreview();
    document.getElementById("solution-undo-remove").focus();
  }

  function insertMath(node, display) {
    var input = node.querySelector('textarea[name$="-body_source"]');
    var start = input.selectionStart, end = input.selectionEnd;
    var selected = input.value.slice(start, end);
    var before = display ? "\\[\n" : "$", after = display ? "\n\\]" : "$";
    input.setRangeText(before + selected + after, start, end, "end");
    input.focus();
    input.setSelectionRange(start + before.length, start + before.length + selected.length);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }

  document.querySelectorAll("[data-editor-view]").forEach(function (button) {
    button.addEventListener("click", function () { setView(button.dataset.editorView); });
  });
  wideLayout.addEventListener("change", function () {
    if (!wideLayout.matches && workspace.dataset.view === "split") setView("write");
  });
  document.getElementById("solution-undo-remove").addEventListener("click", function () {
    if (!lastRemoved) return;
    var node = lastRemoved.node;
    node.querySelector(".solution-delete-input").checked = false;
    node.classList.remove("d-none");
    if (lastRemoved.next && lastRemoved.next.parentNode === blockList) blockList.insertBefore(node, lastRemoved.next);
    else blockList.appendChild(node);
    lastRemoved = null;
    document.getElementById("solution-removed-feedback").classList.add("d-none");
    normalizeOrder(); refreshBlockNumbers(); updateSaveState(); scheduleRenderPreview();
    node.querySelector('textarea[name$="-body_source"]').focus();
  });
  form.addEventListener("input", function () { updateSaveState(); scheduleRenderPreview(); });
  form.addEventListener("change", updateSaveState);
  form.addEventListener("submit", function (event) {
    if (pendingUploads || submitting) { event.preventDefault(); return; }
    submitting = true;
    var action = event.submitter && event.submitter.value;
    saveStatus.textContent = action === "publish" ? "Publishing\u2026" : "Saving\u2026";
  });
  window.addEventListener("beforeunload", function (event) {
    if (!submitting && (pendingUploads || hasChanges())) { event.preventDefault(); event.returnValue = ""; }
  });
  document.addEventListener("keydown", function (event) {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
      if (form.closest(".d-none")) return;
      event.preventDefault();
      if (!pendingUploads && !submitting) form.requestSubmit(saveButton);
    }
    if (event.key === "Escape") document.querySelectorAll(".solution-actions-menu[open]").forEach(function (menu) { menu.open = false; });
  });


  function getCookie(name) {
    var match = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
    return match ? decodeURIComponent(match[2]) : "";
  }

  /** CSRF is HttpOnly in base settings — cookie is not readable from JS; use the form token. */
  function getCsrfToken() {
    var input = form.querySelector('input[name="csrfmiddlewaretoken"]');
    if (input && input.value) return input.value;
    return getCookie("csrftoken");
  }

  function visibleBlocks() {
    return Array.from(blockList.querySelectorAll("[data-block-form]")).filter(function (node) {
      var deleteInput = node.querySelector(".solution-delete-input");
      return !node.hidden && !node.classList.contains("d-none") && (!deleteInput || !deleteInput.checked);
    });
  }

  function orderedVisibleBlocks() {
    return visibleBlocks()
      .map(function (node, index) {
        var orderInput = node.querySelector(".solution-order-input");
        var orderValue = Number.parseInt(orderInput && orderInput.value ? orderInput.value : "", 10);
        return {
          index: index,
          node: node,
          orderValue: Number.isFinite(orderValue) && orderValue > 0 ? orderValue : index + 1
        };
      })
      .sort(function (left, right) {
        if (left.orderValue !== right.orderValue) return left.orderValue - right.orderValue;
        return left.index - right.index;
      })
      .map(function (entry) {
        return entry.node;
      });
  }

  function refreshBlockNumbers() {
    var rows = visibleBlocks(), words = 0;
    rows.forEach(function (node, index) {
      var numberNode = node.querySelector("[data-block-number]");
      var orderInput = node.querySelector(".solution-order-input");
      if (numberNode) numberNode.textContent = String(index + 1).padStart(2, "0");
      if (orderInput && !orderInput.value) orderInput.value = String(index + 1);
      node.querySelector('[data-move-block="up"]').disabled = index === 0;
      node.querySelector('[data-move-block="down"]').disabled = index === rows.length - 1;
      var body = node.querySelector('textarea[name$="-body_source"]').value.trim();
      words += body ? body.split(/\s+/).length : 0;
    });
    document.getElementById("solution-writing-stats").textContent = rows.length + (rows.length === 1 ? " block" : " blocks") + " \u00b7 " + words + " words";
  }

  function typesetPlainPreviewBodies() {
    if (!window.MathJax || typeof window.MathJax.typesetPromise !== "function") return Promise.resolve();
    var targets = Array.from(previewRoot.querySelectorAll("[data-mathjax-scope]"));
    if (!targets.length) return Promise.resolve();
    if (typeof window.MathJax.typesetClear === "function") {
      window.MathJax.typesetClear(targets);
    }
    return window.MathJax.typesetPromise(targets).catch(function () {
      return Promise.resolve();
    });
  }

  function previewBlockTitle(node, index) {
    var titleInput = node.querySelector('input[name$="-title"]');
    var typeSelect = node.querySelector('select[name$="-block_type"]');
    var rawTitle = titleInput ? titleInput.value.trim() : "";
    var rawType = typeSelect && typeSelect.selectedOptions.length ? typeSelect.selectedOptions[0].text.trim() : "";
    if (rawTitle) return rawTitle;
    if (rawType && rawType !== "---------") return rawType;
    return "Block " + String(index + 1);
  }

  function selectedBlockTypeId(node) {
    var typeSelect = node.querySelector('select[name$="-block_type"]');
    return typeSelect ? String(typeSelect.value || "").trim() : "";
  }

  function isPlainBlockType(node) {
    return Boolean(plainBlockTypeId) && selectedBlockTypeId(node) === plainBlockTypeId;
  }

  function renderPreviewNow() {
    var rows = orderedVisibleBlocks();
    var version = ++previewVersion;
    document.getElementById("solution-preview-title").textContent = form.querySelector('[name="solution-title"]').value.trim() || "My solution";
    var summary = document.getElementById("solution-preview-summary");
    summary.textContent = form.querySelector('[name="solution-summary"]').value.trim();
    summary.hidden = !summary.textContent;
    previewRoot.setAttribute("aria-busy", "true");
    previewRoot.innerHTML = "";
    if (!rows.length) {
      var emptyState = document.createElement("div");
      emptyState.className = "solution-preview-placeholder";
      emptyState.textContent = "Add at least one block to preview your solution.";
      previewRoot.appendChild(emptyState);
      previewRoot.setAttribute("aria-busy", "false");
      return Promise.resolve();
    }

    var pending = Promise.resolve();
    rows.forEach(function (node, index) {
      pending = pending.then(function () {
        if (version !== previewVersion) return;
        var bodyInput = node.querySelector('textarea[name$="-body_source"]');
        var typeSelect = node.querySelector('select[name$="-block_type"]');
        var bodyFormatSelect = node.querySelector('select[name$="-body_format"]');
        var isPlain = isPlainBlockType(node);
        var raw = bodyInput ? bodyInput.value : "";
        var isLatexBody = bodyFormatSelect && bodyFormatSelect.value === "latex";
        if (!raw.trim()) {
          var placeholder = document.createElement("p");
          placeholder.className = "solution-preview-placeholder";
          placeholder.textContent = "Your argument will appear here as you write.";
          previewRoot.appendChild(placeholder);
          return;
        }
        if (isPlain) {
          var plainBody = document.createElement("div");
          plainBody.className = "solution-preview-body mb-0";
          if (isLatexBody) {
            previewRoot.appendChild(plainBody);
            return window.AsterProofSolutionLatex.renderInto(plainBody, raw, mediaBaseUrl);
          }
          plainBody.setAttribute("data-mathjax-scope", "true");
          plainBody.textContent = raw;
          previewRoot.appendChild(plainBody);
          return Promise.resolve();
        }

        var card = document.createElement("div");
        card.className = "solution-preview-block";
        var cardBody = document.createElement("div");
        cardBody.className = "solution-preview-block-content";

        var head = document.createElement("div");
        head.className = "solution-preview-block-heading";
        var title = document.createElement("div");
        title.className = "fw-semibold";
        title.textContent = previewBlockTitle(node, index);
        head.appendChild(title);

        cardBody.appendChild(head);

        var body = document.createElement("div");
        body.className = "solution-preview-block-body";
        if (isLatexBody) {
          card.appendChild(cardBody);
          cardBody.appendChild(body);
          previewRoot.appendChild(card);
          return window.AsterProofSolutionLatex.renderInto(body, raw, mediaBaseUrl);
        }
        body.setAttribute("data-mathjax-scope", "true");
        body.textContent = raw;
        card.appendChild(cardBody);
        cardBody.appendChild(body);
        previewRoot.appendChild(card);
        return Promise.resolve();
      });
    });

    return pending.then(function () {
      if (version !== previewVersion) return;
      return typesetPlainPreviewBodies();
    }).then(function () {
      if (version !== previewVersion) return;
      previewRoot.setAttribute("aria-busy", "false");
      document.getElementById("solution-preview-status").textContent = "Up to date";
    }).catch(function () {
      if (version !== previewVersion) return;
      previewRoot.setAttribute("aria-busy", "false");
      document.getElementById("solution-preview-status").textContent = "Preview needs attention";
    });
  }

  function scheduleRenderPreview() {
    window.clearTimeout(previewTimer);
    previewTimer = window.setTimeout(function () {
      renderPreviewNow();
    }, 120);
  }

  function attachRowHandlers(node) {
    if (!node || node.dataset.editorBound) return;
    node.dataset.editorBound = "true";
    node.querySelectorAll("input, textarea, select").forEach(function (element) {
      element.addEventListener("input", function () { refreshBlockNumbers(); scheduleRenderPreview(); });
      element.addEventListener("change", function () {
        if (element.classList.contains("solution-order-input")) {
          orderedVisibleBlocks().forEach(function (row) { blockList.appendChild(row); });
          normalizeOrder();
        }
        refreshBlockNumbers(); scheduleRenderPreview();
      });
    });
    node.querySelector("[data-remove-block]").addEventListener("click", function () { removeBlock(node); });
    node.querySelectorAll("[data-move-block]").forEach(function (button) {
      button.addEventListener("click", function () { moveBlock(node, button.dataset.moveBlock); });
    });
    node.querySelectorAll("[data-insert-math]").forEach(function (button) {
      button.addEventListener("click", function () { insertMath(node, button.dataset.insertMath === "display"); });
    });
  }

  function clipboardImageFile(evt) {
    var cd = evt.clipboardData;
    if (!cd) return null;
    var items = cd.items;
    if (items) {
      for (var i = 0; i < items.length; i += 1) {
        if (items[i].type && items[i].type.indexOf("image/") === 0) {
          var f = items[i].getAsFile();
          if (f) return f;
        }
      }
    }
    if (cd.files && cd.files.length) return cd.files[0];
    return null;
  }

  function showUploadError(message) {
    var feedback = document.getElementById("solution-upload-feedback");
    feedback.textContent = message || "Could not upload image.";
    feedback.hidden = false;
  }

  form.addEventListener(
    "paste",
    function (evt) {
      var target = evt.target;
      if (!target || target.tagName !== "TEXTAREA" || !target.name || target.name.indexOf("-body_source") === -1) {
        return;
      }
      var row = target.closest("[data-block-form]");
      if (!row) return;
      var fmt = row.querySelector('select[name$="-body_format"]');
      if (!fmt || fmt.value !== "latex") return;
      var file = clipboardImageFile(evt);
      if (!file || !file.type || file.type.indexOf("image/") !== 0) return;
      if (!uploadUrl) return;
      evt.preventDefault();
      var fd = new FormData();
      fd.append("image", file, file.name || "paste.png");
      var csrf = getCsrfToken();
      if (!csrf) {
        showUploadError("Missing CSRF token. Refresh the page and try again.");
        return;
      }
      var headers = { "X-CSRFToken": csrf };
      pendingUploads += 1;
      document.getElementById("solution-upload-feedback").hidden = true;
      updateSaveState();
      fetch(uploadUrl, { method: "POST", body: fd, headers: headers, credentials: "same-origin" })
        .then(function (r) {
          var ct = (r.headers.get("content-type") || "").toLowerCase();
          if (ct.indexOf("application/json") === -1) {
            return r.text().then(function (text) {
              var hint =
                r.status === 403
                  ? "Request blocked (often CSRF). Refresh the page and try again."
                  : "Unexpected response (" + r.status + ").";
              throw new Error(hint);
            });
          }
          return r.json().then(function (data) {
            if (!r.ok) throw new Error((data && data.error) || r.statusText);
            return data;
          });
        })
        .then(function (data) {
          if (!data.path) throw new Error("Invalid response");
          window.AsterProofSolutionLatex.insertGraphicsAtCursor(target, data.path);
        })
        .catch(function (err) {
          showUploadError(err.message);
        }).finally(function () {
          pendingUploads -= 1;
          updateSaveState();
        });
    },
    true
  );

  function addBlock() {
    if (!emptyTemplate || !totalFormsInput) return;
    var newNode = blockList.querySelector('[data-unused-block="true"]');
    if (newNode) {
      newNode.hidden = false;
      delete newNode.dataset.unusedBlock;
    } else {
      var formIndex = Number(totalFormsInput.value || "0");
      var maxFormsInput = form.querySelector('[name="blocks-MAX_NUM_FORMS"]');
      if (maxFormsInput && formIndex >= Number(maxFormsInput.value)) { showUploadError("The block limit has been reached."); return; }
      var html = emptyTemplate.innerHTML.replace(/__prefix__/g, String(formIndex));
      var wrapper = document.createElement("div");
      wrapper.innerHTML = html.trim();
      newNode = wrapper.firstElementChild;
      blockList.appendChild(newNode);
      totalFormsInput.value = String(formIndex + 1);
    }
    attachRowHandlers(newNode);
    normalizeOrder(); refreshBlockNumbers(); updateSaveState(); scheduleRenderPreview();
    newNode.querySelector('textarea[name$="-body_source"]').focus();
  }

  var initialRows = orderedVisibleBlocks();
  initialRows.forEach(function (node) { blockList.appendChild(node); });
  var hasExistingBody = initialRows.some(function (node) { return node.querySelector('textarea[name$="-body_source"]').value.trim(); });
  initialRows.forEach(function (node) {
    var deleted = node.querySelector(".solution-delete-input");
    if (deleted && deleted.checked) { node.classList.add("d-none"); return; }
    var body = node.querySelector('textarea[name$="-body_source"]').value.trim();
    var title = node.querySelector('input[name$="-title"]').value.trim();
    var savedId = node.querySelector('input[name$="-id"]').value;
    if (hasExistingBody && !body && !title && !savedId && !node.dataset.hasErrors) {
      node.hidden = true; node.dataset.unusedBlock = "true";
    }
    attachRowHandlers(node);
  });
  if (addBlockButton) {
    addBlockButton.addEventListener("click", addBlock);
  }
  refreshBlockNumbers();
  initialSnapshot = formSnapshot();
  setView(wideLayout.matches ? "split" : "write");
  updateSaveState();
  window.AsterProofSolutionLatex.mathJaxReady().then(function () {
    return renderPreviewNow();
  });
})();
