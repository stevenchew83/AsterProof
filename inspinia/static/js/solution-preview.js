/* Public solution blocks: local recovery is optional; handoff and PDF post current fields. */
(function () {
  "use strict";
  const root = document.querySelector("[data-solution-preview]");
  if (!root) return;
  const form = document.getElementById("solution-preview-form");
  const list = document.getElementById("preview-block-list");
  const total = document.getElementById("id_blocks-TOTAL_FORMS");
  const template = document.getElementById("preview-block-empty-form");
  const add = document.getElementById("preview-add-block");
  const preview = document.getElementById("converter-block-preview");
  const statement = document.getElementById("converter-statement");
  const status = document.getElementById("converter-preview-status");
  let timer;
  let recovery;
  let pending = Promise.resolve();

  function blocks() {
    return Array.from(list.querySelectorAll("[data-block-form]")).filter(function (block) {
      return !block.querySelector('[name$="-DELETE"]').checked;
    });
  }

  function refresh() {
    list.querySelectorAll("[data-block-form]").forEach(function (block) {
      const removed = block.querySelector('[name$="-DELETE"]').checked;
      block.hidden = removed;
      block.classList.toggle("d-none", removed);
    });
    const rows = blocks();
    rows.forEach(function (block, index) {
      block.querySelector("[data-block-number]").textContent = String(index + 1).padStart(2, "0");
      block.querySelector('[name$="-ORDER"]').value = index + 1;
      block.querySelector('[data-move-block="up"]').disabled = index === 0;
      block.querySelector('[data-move-block="down"]').disabled = index === rows.length - 1;
    });
    add.disabled = rows.length >= Number(root.dataset.blockLimit);
  }

  function snapshot() {
    const document = {};
    ["title", "author_name", "problem_statement"].forEach(key => { document[key] = form.elements[key].value; });
    ["pdf_show_author", "pdf_show_date", "pdf_show_footer"].forEach(key => { document[key] = form.elements[key].checked; });
    document.blocks = blocks().slice().sort((a, b) => Number(a.querySelector('[name$="-ORDER"]').value) -
      Number(b.querySelector('[name$="-ORDER"]').value)).map(function (block) {
      const values = {};
      ["block_type", "title", "body_format", "body_source"].forEach(key => {
        values[key] = block.querySelector('[name$="-' + key + '"]').value;
      });
      return values;
    });
    return document;
  }

  function restore(document) {
    ["title", "author_name", "problem_statement"].forEach(key => { form.elements[key].value = document[key]; });
    ["pdf_show_author", "pdf_show_date", "pdf_show_footer"].forEach(key => { form.elements[key].checked = document[key]; });
    list.replaceChildren();
    document.blocks.forEach(function (values, index) {
      const holder = window.document.createElement("div");
      holder.innerHTML = template.innerHTML.replace(/__prefix__/g, index);
      const block = holder.firstElementChild;
      ["block_type", "title", "body_format", "body_source"].forEach(key => {
        block.querySelector('[name$="-' + key + '"]').value = values[key];
      });
      list.appendChild(block);
    });
    total.value = document.blocks.length;
    refresh();
    form.dispatchEvent(new Event("change", {bubbles: true}));
    render();
  }

  function render() {
    pending = pending.then(async function () {
      const math = window.MathJax;
      if (math && math.startup && math.startup.promise) await math.startup.promise;
      if (math && math.typesetClear) math.typesetClear([preview, statement]);
      document.getElementById("converter-document-title").textContent = form.elements.title.value || "My solution";
      statement.textContent = form.elements.problem_statement.value;
      statement.hidden = !statement.textContent.trim();
      preview.replaceChildren();
      const targets = [statement];
      const rows = blocks().slice().sort(function (left, right) {
        return Number(left.querySelector('[name$="-ORDER"]').value) - Number(right.querySelector('[name$="-ORDER"]').value);
      });
      rows.forEach(function (block) {
        const type = block.querySelector('[name$="-block_type"]');
        const heading = block.querySelector('[name$="-title"]').value;
        const body = block.querySelector('[name$="-body_source"]').value;
        const plainText = block.querySelector('[name$="-body_format"]').value === "plain_text";
        const section = document.createElement("section");
        section.className = "converter-preview-block";
        if (type.value && type.value !== root.dataset.plainBlockType) {
          const label = type.selectedOptions[0].textContent;
          const title = document.createElement("h3");
          title.textContent = label + (heading ? " · " + heading : "");
          section.appendChild(title);
          if (!plainText) targets.push(title);
        }
        const content = document.createElement("div");
        content.className = "converter-preview-body";
        content.textContent = body;
        section.appendChild(content);
        preview.appendChild(section);
        if (!plainText) targets.push(content);
      });
      if (math && math.typesetPromise) {
        await math.typesetPromise(targets);
        status.textContent = "Up to date";
      } else {
        status.textContent = "Text preview · math rendering unavailable";
      }
    }).catch(function () {
      status.textContent = "Preview unavailable · your text is still here";
    });
  }

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(render, 180);
    if (recovery) recovery.changed();
  }

  add.hidden = false;
  add.addEventListener("click", function () {
    if (blocks().length >= Number(root.dataset.blockLimit)) return;
    const removed = Array.from(list.querySelectorAll("[data-block-form]")).find(function (block) {
      return block.querySelector('[name$="-DELETE"]').checked;
    });
    const index = removed ? removed.querySelector('[name$="-DELETE"]').name.split("-")[1] : total.value;
    const holder = document.createElement("div");
    holder.innerHTML = template.innerHTML.replace(/__prefix__/g, index);
    const block = holder.firstElementChild;
    if (removed) removed.remove();
    else total.value = Number(total.value) + 1;
    list.appendChild(block);
    refresh(); schedule();
    block.querySelector('[name$="-body_source"]').focus();
  });

  list.addEventListener("click", function (event) {
    const button = event.target.closest("button");
    if (!button) return;
    const block = button.closest("[data-block-form]");
    if (!block) return;
    const rows = blocks(), index = rows.indexOf(block);
    if (button.hasAttribute("data-remove-block")) {
      block.querySelector('[name$="-DELETE"]').checked = true;
      block.hidden = true;
      block.classList.add("d-none");
    } else if (button.dataset.moveBlock) {
      const other = rows[index + (button.dataset.moveBlock === "up" ? -1 : 1)];
      if (!other) return;
      if (button.dataset.moveBlock === "up") list.insertBefore(block, other);
      else list.insertBefore(other, block);
    } else if (button.dataset.insertMath) {
      const input = block.querySelector('[name$="-body_source"]');
      const start = input.selectionStart, end = input.selectionEnd;
      const before = button.dataset.insertMath === "display" ? "\\[\n" : "$";
      const after = button.dataset.insertMath === "display" ? "\n\\]" : "$";
      input.setRangeText(before + input.value.slice(start, end) + after, start, end, "end");
      input.focus();
    } else return;
    refresh(); schedule();
  });

  form.addEventListener("input", schedule);
  form.addEventListener("change", schedule);
  form.addEventListener("submit", function (event) {
    if (recovery) recovery.flush();
    const pdfStatus = root.querySelector("[data-pdf-status]");
    const handoff = event.submitter && ["continue_workspace", "continue_signup"].includes(event.submitter.value);
    if (pdfStatus) pdfStatus.textContent = handoff ? "Carrying your writing into your workspace…" :
      "PDF requested. Keep this tab open until the download starts.";
    blocks().forEach(function (block) {
      const order = block.querySelector('[name$="-ORDER"]');
      if (!order.value) order.value = 1;
    });
  });
  Array.from(list.querySelectorAll("[data-block-form]")).sort(function (left, right) {
    return Number(left.querySelector('[name$="-ORDER"]').value) - Number(right.querySelector('[name$="-ORDER"]').value);
  }).forEach(function (block) { list.appendChild(block); });
  refresh();
  const startingDocument = JSON.stringify(snapshot());
  if (window.AsterProofDraftRecovery) recovery = window.AsterProofDraftRecovery.create({root, snapshot, restore});
  document.addEventListener("click", function (event) {
    const link = event.target.closest("a[href]");
    if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const url = new URL(link.href, window.location.href);
    if (url.origin !== window.location.origin) return;
    const signup = url.pathname === root.dataset.signupUrl;
    if (!signup && url.pathname !== root.dataset.loginUrl) return;
    if (JSON.stringify(snapshot()) === startingDocument && root.dataset.writerResumed !== "true") return;
    const button = root.querySelector(signup ? "[data-signup-handoff]" : "[data-workspace-handoff]");
    if (!button) return;
    event.preventDefault();
    form.requestSubmit(button);
  });
  if (document.readyState === "complete") render();
  else window.addEventListener("load", render, {once: true});
}());
