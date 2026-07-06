(function () {
  "use strict";

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function formatJson(value) {
    return JSON.stringify(value, null, 2);
  }

  function renderJsonDetails(title, value) {
    return `<details><summary>${escapeHtml(title || "Технический JSON")}</summary><pre>${escapeHtml(formatJson(value))}</pre></details>`;
  }

  function renderMarkdownContent(text) {
    const escaped = escapeHtml(text || "");
    const lines = escaped.split(/\r?\n/);
    let inList = false;
    const html = [];
    for (const line of lines) {
      if (line.startsWith("# ")) {
        if (inList) {
          html.push("</ul>");
          inList = false;
        }
        html.push(`<h1>${line.slice(2)}</h1>`);
      } else if (line.startsWith("## ")) {
        if (inList) {
          html.push("</ul>");
          inList = false;
        }
        html.push(`<h2>${line.slice(3)}</h2>`);
      } else if (line.startsWith("### ")) {
        if (inList) {
          html.push("</ul>");
          inList = false;
        }
        html.push(`<h3>${line.slice(4)}</h3>`);
      } else if (line.startsWith("- ")) {
        if (!inList) {
          html.push("<ul>");
          inList = true;
        }
        html.push(`<li>${line.slice(2)}</li>`);
      } else if (line.trim() === "") {
        if (inList) {
          html.push("</ul>");
          inList = false;
        }
      } else {
        if (inList) {
          html.push("</ul>");
          inList = false;
        }
        html.push(`<p>${line}</p>`);
      }
    }
    if (inList) {
      html.push("</ul>");
    }
    return html.join("");
  }

  function renderSimpleTable(rows) {
    if (!Array.isArray(rows) || rows.length === 0) {
      return "<p class=\"muted\">Данных нет.</p>";
    }
    const columns = Object.keys(rows[0] || {});
    const head = columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("");
    const body = rows
      .map((row) => `<tr>${columns.map((column) => `<td>${escapeHtml(cellText(row[column]))}</td>`).join("")}</tr>`)
      .join("");
    return `<table class="data-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
  }

  function cellText(value) {
    if (value && typeof value === "object") {
      return value.Представление || value.presentation || value.name || JSON.stringify(value);
    }
    return value == null ? "" : value;
  }

  function renderSkillCard(skill) {
    const item = skill || {};
    return `<article class="mini-card">
      <strong>${escapeHtml(item.title || item.skill_id || "Навык")}</strong>
      <span class="muted">${escapeHtml(item.skill_id || "")}</span>
      <span>${escapeHtml(item.status || item.source_path || "")}</span>
    </article>`;
  }

  function renderDraftCard(draft) {
    const item = draft || {};
    return `<article class="mini-card">
      <strong>${escapeHtml(item.title || item.draft_id || "Draft")}</strong>
      <span class="muted">${escapeHtml(item.draft_id || "")}</span>
      <span>${escapeHtml((item.example_questions || []).join("; "))}</span>
    </article>`;
  }

  function renderMetadataObjectCard(object) {
    const item = object || {};
    const fields = Array.isArray(item.fields) ? item.fields : [];
    return `<article class="mini-card">
      <strong>${escapeHtml(item.full_name || item.name || "Объект")}</strong>
      <span class="muted">${escapeHtml(item.synonym || item.kind || "")}</span>
      <span>${escapeHtml(fields.slice(0, 12).map((field) => field.name || field).join(", "))}</span>
    </article>`;
  }

  function renderSummary(data) {
    if (!data || typeof data !== "object") {
      return `<p>${escapeHtml(data || "Нет данных.")}</p>`;
    }
    if (data.summary) {
      return `<p>${escapeHtml(summaryText(data.summary))}</p>`;
    }
    if (data.skill) {
      return renderSkillCard(data.skill);
    }
    if (data.draft) {
      return renderDraftCard(data.draft);
    }
    if (data.preview) {
      const preview = data.preview;
      return `<p>${preview.ok ? "Preview построен." : "Preview содержит замечания."}</p>${renderIssueList(preview.issues)}`;
    }
    if (data.smoke) {
      return `<p>Smoke ${data.smoke.ok ? "успешен" : "не прошел"}; строк: ${escapeHtml(data.smoke.row_count || 0)}.</p>`;
    }
    if (data.publication) {
      return `<p>Публикация candidate: ${data.publication.ok ? "готова" : "есть блокеры"}.</p>${renderIssueList(data.publication.issues)}`;
    }
    if (data.lifecycle) {
      return `<p>Lifecycle: ${escapeHtml(data.lifecycle.before_status || "")} -> ${escapeHtml(data.lifecycle.after_status || "")}</p>${renderIssueList(data.lifecycle.issues)}`;
    }
    if (Array.isArray(data.skills)) {
      return `<p>Навыков: ${data.skills.length}</p>${data.skills.slice(0, 20).map(renderSkillCard).join("")}`;
    }
    if (Array.isArray(data.drafts)) {
      return `<p>Черновиков: ${data.drafts.length}</p>${data.drafts.slice(0, 20).map(renderDraftCard).join("")}`;
    }
    if (Array.isArray(data.objects)) {
      return `<p>Объектов: ${data.objects.length}</p>${data.objects.slice(0, 30).map(renderMetadataObjectCard).join("")}`;
    }
    if (Array.isArray(data.candidates)) {
      return `<p>Кандидатов: ${data.candidates.length}</p>${data.candidates.slice(0, 20).map((item) => `<article class="mini-card"><strong>${escapeHtml(item.candidate_id || item.semantic_role || "candidate")}</strong><span>${escapeHtml(item.status || item.type || "")}</span></article>`).join("")}`;
    }
    return `<p>Команда выполнена.</p>`;
  }

  function summaryText(summary) {
    if (!summary || typeof summary !== "object") {
      return "";
    }
    return Object.entries(summary).map(([key, value]) => `${key}: ${typeof value === "object" ? JSON.stringify(value) : value}`).join("; ");
  }

  function renderIssueList(issues) {
    if (!Array.isArray(issues) || issues.length === 0) {
      return "";
    }
    return `<ul>${issues.map((issue) => `<li>${escapeHtml(issue.message || issue.code || JSON.stringify(issue))}</li>`).join("")}</ul>`;
  }

  window.WiiconRenderers = {
    escapeHtml,
    formatJson,
    renderJsonDetails,
    renderMarkdownContent,
    renderSimpleTable,
    renderSkillCard,
    renderDraftCard,
    renderMetadataObjectCard,
    renderSummary,
  };
})();
