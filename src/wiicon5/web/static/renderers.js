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

  function summaryCount(summary, fallback) {
    if (!summary || typeof summary !== "object") {
      return fallback || 0;
    }
    return summary.total || fallback || 0;
  }

  function summaryText(summary) {
    if (!summary || typeof summary !== "object") {
      return "";
    }
    return Object.entries(summary).map(([key, value]) => `${key}: ${typeof value === "object" ? JSON.stringify(value) : value}`).join("; ");
  }

  function renderSummaryBlock(summary) {
    const text = summaryText(summary);
    return text ? `<p>${escapeHtml(text)}</p>` : "<p>Команда выполнена.</p>";
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

  function actionButton(label, action, dataName, dataValue, cssClass) {
    const attrName = dataName ? ` data-${dataName}="${escapeHtml(dataValue || "")}"` : "";
    return `<button class="${cssClass || "secondary-button"}" type="button" data-action="${escapeHtml(action)}"${attrName}>${escapeHtml(label)}</button>`;
  }

  function renderStatusPill(status) {
    return `<span class="status-pill">${escapeHtml(status || "unknown")}</span>`;
  }

  function renderTags(values) {
    const items = (Array.isArray(values) ? values : []).filter(Boolean).slice(0, 8);
    if (!items.length) {
      return "";
    }
    return `<div class="tag-row">${items.map((item) => `<span class="tag">${escapeHtml(item)}</span>`).join("")}</div>`;
  }

  function renderFacts(facts) {
    const entries = Object.entries(facts || {}).filter(([, value]) => value !== undefined && value !== null && String(value) !== "");
    if (!entries.length) {
      return "";
    }
    return `<dl class="entity-facts">${entries.map(([key, value]) => `<div><dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")}</dl>`;
  }

  function metadataObjectNames(candidate) {
    if (!candidate || !Array.isArray(candidate.metadata_objects)) {
      return [];
    }
    return candidate.metadata_objects.map((item) => item && (item.full_name || item.name)).filter(Boolean);
  }

  function candidateId(candidate) {
    const item = candidate || {};
    return item.candidate_id || item.id || item.semantic_role || "";
  }

  function isSynthesisCandidate(candidate) {
    const item = candidate || {};
    const id = candidateId(item);
    return id.startsWith("syn_") || Boolean(item.answer || item.query || item.trace_path || item.final_artifact_type);
  }

  function renderSkillCard(skill) {
    const item = skill || {};
    const id = item.skill_id || item.id || "";
    return `<article class="entity-card skill-card" data-skill-id="${escapeHtml(id)}">
      <div class="entity-card-header">
        <div>
          <div class="entity-kind">Навык</div>
          <h3>${escapeHtml(item.title || id || "Навык")}</h3>
        </div>
        ${renderStatusPill(item.status || item.lifecycle_status || "active")}
      </div>
      ${renderFacts({ ID: id, Runtime: item.runtime || item.implementation_strategy || "", Источник: item.source_path || item.source || "" })}
      <div class="entity-actions">
        ${actionButton("Открыть", "open-skill", "skill-id", id, "primary-button")}
        ${actionButton("Promote", "skill-promote", "skill-id", id, "secondary-button")}
        ${actionButton("Block", "skill-block", "skill-id", id, "ghost-button")}
      </div>
    </article>`;
  }

  function renderDraftCard(draft) {
    const item = draft || {};
    const id = item.draft_id || item.id || "";
    const questions = Array.isArray(item.example_questions) ? item.example_questions : [];
    return `<article class="entity-card draft-card" data-draft-id="${escapeHtml(id)}">
      <div class="entity-card-header">
        <div>
          <div class="entity-kind">Черновик навыка</div>
          <h3>${escapeHtml(item.title || id || "Draft")}</h3>
        </div>
        ${renderStatusPill(item.status || item.source_kind || "draft")}
      </div>
      ${questions.length ? `<p class="entity-summary">${escapeHtml(questions.join("; "))}</p>` : ""}
      ${renderFacts({ ID: id, Источник: item.source_kind || "", Обновлен: item.updated_at || "" })}
      <div class="entity-actions">
        ${actionButton("Открыть", "open-draft", "draft-id", id, "primary-button")}
        ${actionButton("Preview", "draft-preview", "draft-id", id, "secondary-button")}
        ${actionButton("Smoke", "draft-smoke", "draft-id", id, "secondary-button")}
        ${actionButton("Approve", "draft-approve", "draft-id", id, "secondary-button")}
        ${actionButton("Publish", "draft-publish", "draft-id", id, "secondary-button")}
      </div>
    </article>`;
  }

  function renderMetadataObjectCard(object) {
    const item = object || {};
    const fields = Array.isArray(item.fields) ? item.fields : [];
    return `<article class="entity-card metadata-summary-card">
      <div class="entity-card-header">
        <div>
          <div class="entity-kind">Метаданные 1С</div>
          <h3>${escapeHtml(item.full_name || item.name || "Объект")}</h3>
        </div>
        ${renderStatusPill(item.trust || item.source || item.kind || "metadata")}
      </div>
      <p class="entity-summary">${escapeHtml(item.synonym || "")}</p>
      ${fields.length ? `<p class="muted">${escapeHtml(fields.slice(0, 12).map((field) => field.name || field).join(", "))}</p>` : ""}
    </article>`;
  }

  function renderCandidateCard(candidate) {
    const item = candidate || {};
    const id = candidateId(item);
    const synthesis = isSynthesisCandidate(item);
    const question = item.question || item.source_question || item.business_goal || item.semantic_role || id || "Кандидат";
    const answer = item.answer || item.preview || item.reason || item.description || "";
    const objects = metadataObjectNames(item);
    const rowCount = item.row_count == null ? "" : item.row_count;
    const source = synthesis ? (item.source || "query_synthesis") : (item.type || item.source || "onboarding");
    const createAction = synthesis ? "synthesis-create-draft" : "onboarding-create-draft";
    const rejectAction = synthesis ? "synthesis-reject" : "onboarding-reject";
    return `<article class="entity-card candidate-card" data-candidate-id="${escapeHtml(id)}">
      <div class="entity-card-header">
        <div>
          <div class="entity-kind">${synthesis ? "Кандидат от агента" : "Кандидат onboarding"}</div>
          <h3>${escapeHtml(question)}</h3>
        </div>
        ${renderStatusPill(item.status || "candidate")}
      </div>
      ${answer ? `<p class="entity-summary">${escapeHtml(answer)}</p>` : `<p class="muted">Откройте кандидата или создайте draft, чтобы проверить навык.</p>`}
      ${renderFacts({ ID: id, Строк: rowCount, Источник: source, Trace: item.trace_path || "" })}
      ${renderTags(objects)}
      <div class="entity-actions">
        ${actionButton("Создать draft", createAction, "candidate-id", id, "primary-button")}
        ${actionButton("Отклонить", rejectAction, "candidate-id", id, "secondary-button")}
        ${synthesis ? actionButton("Игнорировать похожие", "synthesis-ignore-similar", "candidate-id", id, "ghost-button") : ""}
      </div>
    </article>`;
  }

  function renderSkillsResponse(data) {
    const skills = data.skills || [];
    if (!skills.length) {
      return `<div class="empty-state"><h3>Навыков пока нет</h3><p>После публикации кандидатов они появятся в этом списке.</p></div>`;
    }
    return `<div class="summary-kpi">Навыков: ${escapeHtml(summaryCount(data.summary, skills.length))}</div>
      <div class="card-list entity-list">${skills.slice(0, 50).map(renderSkillCard).join("")}</div>`;
  }

  function renderDraftsResponse(data) {
    const drafts = data.drafts || [];
    if (!drafts.length) {
      return `<div class="empty-state"><h3>Черновиков пока нет</h3><p>Создайте draft из кандидата или вручную через мастер.</p></div>`;
    }
    return `<div class="summary-kpi">Черновиков: ${escapeHtml(summaryCount(data.summary, drafts.length))}</div>
      <div class="card-list entity-list">${drafts.slice(0, 50).map(renderDraftCard).join("")}</div>`;
  }

  function renderCandidatesResponse(data) {
    const candidates = data.candidates || [];
    if (!candidates.length) {
      return `<div class="empty-state"><h3>Кандидатов пока нет</h3><p>Они появятся после успешных ответов агента через query synthesis или после первоначального обучения.</p></div>`;
    }
    return `<div class="summary-kpi">Кандидатов: ${escapeHtml(summaryCount(data.summary, candidates.length))}</div>
      <p class="workbench-hint">Выберите кандидата, проверьте смысл и создайте draft без ручного копирования ID.</p>
      <div class="card-list entity-list">${candidates.slice(0, 50).map(renderCandidateCard).join("")}</div>`;
  }

  function renderMetadataResponse(data) {
    const objects = data.objects || [];
    if (!objects.length) {
      return `<div class="empty-state"><h3>Метаданные не найдены</h3><p>Попробуйте другой термин или полное имя объекта 1С.</p></div>`;
    }
    return `<div class="summary-kpi">Объектов: ${escapeHtml(summaryCount(data.summary, objects.length))}</div>
      <div class="card-list entity-list">${objects.slice(0, 50).map(renderMetadataObjectCard).join("")}</div>`;
  }

  function renderPreviewResult(preview) {
    return `<p>${preview && preview.ok ? "Preview построен." : "Preview содержит замечания."}</p>${renderIssueList(preview && preview.issues)}`;
  }

  function renderSmokeResult(smoke) {
    return `<p>Smoke ${smoke && smoke.ok ? "успешен" : "не прошел"}; строк: ${escapeHtml((smoke && smoke.row_count) || 0)}.</p>`;
  }

  function renderPublicationResult(publication) {
    return `<p>Публикация candidate: ${publication && publication.ok ? "готова" : "есть блокеры"}.</p>${renderIssueList(publication && publication.issues)}`;
  }

  function renderLifecycleResult(lifecycle) {
    return `<p>Lifecycle: ${escapeHtml((lifecycle && lifecycle.before_status) || "")} -> ${escapeHtml((lifecycle && lifecycle.after_status) || "")}</p>${renderIssueList(lifecycle && lifecycle.issues)}`;
  }

  function renderSummary(data) {
    if (!data || typeof data !== "object") {
      return `<p>${escapeHtml(data || "Нет данных.")}</p>`;
    }
    if (Array.isArray(data.candidates)) {
      return renderCandidatesResponse(data);
    }
    if (Array.isArray(data.skills)) {
      return renderSkillsResponse(data);
    }
    if (Array.isArray(data.drafts)) {
      return renderDraftsResponse(data);
    }
    if (Array.isArray(data.objects)) {
      return renderMetadataResponse(data);
    }
    if (data.skill) {
      return renderSkillCard(data.skill);
    }
    if (data.draft) {
      return renderDraftCard(data.draft);
    }
    if (data.preview) {
      return renderPreviewResult(data.preview);
    }
    if (data.smoke) {
      return renderSmokeResult(data.smoke);
    }
    if (data.publication) {
      return renderPublicationResult(data.publication);
    }
    if (data.lifecycle) {
      return renderLifecycleResult(data.lifecycle);
    }
    if (data.summary) {
      return renderSummaryBlock(data.summary);
    }
    return `<p>Команда выполнена.</p>`;
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
    renderCandidateCard,
    renderSummary,
  };
})();
