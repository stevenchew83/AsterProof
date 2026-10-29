/* Standalone solution blocks: previews stay in memory; PDF export posts current fields. */
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
  form.addEventListener("submit", function () {
    const pdfStatus = root.querySelector("[data-pdf-status]");
    if (pdfStatus) pdfStatus.textContent = "PDF requested. Keep this tab open until the download starts.";
    blocks().forEach(function (block) {
      const order = block.querySelector('[name$="-ORDER"]');
      if (!order.value) order.value = 1;
    });
  });
  Array.from(list.querySelectorAll("[data-block-form]")).sort(function (left, right) {
    return Number(left.querySelector('[name$="-ORDER"]').value) - Number(right.querySelector('[name$="-ORDER"]').value);
  }).forEach(function (block) { list.appendChild(block); });
  refresh();
  if (document.readyState === "complete") render();
  else window.addEventListener("load", render, {once: true});
}());
