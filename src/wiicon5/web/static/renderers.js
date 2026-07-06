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

  const DISPLAY_LABELS = {
    active: "активен",
    approved: "утвержден",
    blocked: "заблокирован",
    candidate: "кандидат",
    city: "город",
    context_artifact_lookup: "поиск в контексте диалога",
    count: "подсчет",
    data: "данные",
    data_acquisition: "получение данных",
    deprecated: "устарел",
    deterministic_count_entities: "детерминированный подсчет объектов",
    deterministic_entity_list_renderer: "рендер списка объектов",
    deterministic_table_renderer: "рендер таблицы",
    document_kind: "вид документа",
    document_type: "тип документа",
    draft: "черновик",
    fixed_query: "фиксированный запрос",
    group_by: "группировка",
    ignored: "игнорируется",
    inactive: "неактивен",
    learned: "обученный",
    learned_query: "обученный запрос",
    limit: "ограничение строк",
    measure: "метрика",
    metadata: "метаданные",
    metadata_index: "индекс метаданных",
    metadata_xml: "XML метаданные",
    mcp: "MCP",
    name: "наименование",
    number: "номер",
    object_name: "имя объекта",
    object_type: "тип объекта",
    onboarding: "обучение",
    onboarding_candidate: "кандидат обучения",
    onboarding_index: "индекс обучения",
    period: "период",
    period_granularity: "детализация периода",
    preview: "предпросмотр",
    product: "номенклатура",
    posted: "проведен",
    presentation: "формирование ответа",
    query_synthesis: "синтез запроса",
    query_synthesis_ok: "синтез запроса",
    rejected: "отклонен",
    semantic_binding_query: "запрос по binding метаданных",
    semantic_document_count_query: "подсчет документов по метаданным",
    semantic_document_list_query: "список документов по метаданным",
    semantic_measure_query: "запрос метрики по binding метаданных",
    smoke: "проверочный запуск",
    stable: "стабилен",
    transform: "преобразование данных",
    unknown: "неизвестно",
    verified: "проверен",
    warehouse: "склад",
    warehouse_type: "тип склада",
    year: "год",
  };

  const SUMMARY_LABELS = {
    by_status: "по статусам",
    total: "всего",
  };

  function displayLabel(value) {
    const text = String(value == null ? "" : value);
    return DISPLAY_LABELS[text] || text;
  }

  function summaryLabel(value) {
    const text = String(value == null ? "" : value);
    return SUMMARY_LABELS[text] || displayLabel(text);
  }

  function summaryValue(value) {
    if (value && typeof value === "object" && !Array.isArray(value)) {
      return Object.entries(value)
        .map(([key, item]) => `${summaryLabel(key)}: ${summaryValue(item)}`)
        .join("; ");
    }
    return displayLabel(value);
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
    return Object.entries(summary).map(([key, value]) => `${summaryLabel(key)}: ${summaryValue(value)}`).join("; ");
  }

  function renderSummaryBlock(summary) {
    const text = summaryText(summary);
    return text ? `<p>${escapeHtml(text)}</p>` : "<p>Команда выполнена.</p>";
  }

  function renderNotice(text) {
    return text ? `<p class="workbench-hint">${escapeHtml(text)}</p>` : "";
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
    return `<span class="status-pill">${escapeHtml(displayLabel(status || "unknown"))}</span>`;
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

  function renderInfoSection(title, body) {
    if (!body) {
      return "";
    }
    return `<section class="entity-section"><h4>${escapeHtml(title)}</h4>${body}</section>`;
  }

  function compactList(values, limit) {
    const result = [];
    for (const value of Array.isArray(values) ? values : []) {
      const text = String(value || "").trim();
      if (text && !result.includes(text)) {
        result.push(text);
      }
      if (result.length >= (limit || 10)) {
        break;
      }
    }
    return result;
  }

  function portLabel(port) {
    const item = port || {};
    const required = item.required === false ? "необязательный" : "обязательный";
    const defaultText = item.default === undefined || item.default === null ? "" : `, по умолчанию: ${displayLabel(item.default)}`;
    const description = item.description ? ` — ${item.description}` : "";
    return `${item.name || "port"}: ${item.type || "unknown"} (${required}${defaultText})${description}`;
  }

  function renderPortList(ports, emptyText) {
    const items = Array.isArray(ports) ? ports : [];
    if (!items.length) {
      return `<p class="muted">${escapeHtml(emptyText || "Нет.")}</p>`;
    }
    return `<ul class="compact-list">${items.map((port) => `<li>${escapeHtml(portLabel(port))}</li>`).join("")}</ul>`;
  }

  function outputTypes(skill) {
    return (Array.isArray(skill.outputs) ? skill.outputs : []).map((output) => output && output.type).filter(Boolean);
  }

  function inputTypes(skill) {
    return (Array.isArray(skill.inputs) ? skill.inputs : []).map((input) => input && input.type).filter(Boolean);
  }

  function visibleCapabilities(skill) {
    return compactList((skill.capabilities || []).filter((item) => !String(item || "").startsWith("produce:")), 12);
  }

  function producedArtifacts(skill) {
    const fromOutputs = outputTypes(skill);
    const fromCapabilities = (skill.capabilities || [])
      .map((item) => String(item || ""))
      .filter((item) => item.startsWith("produce:"))
      .map((item) => item.slice("produce:".length));
    return compactList([...fromOutputs, ...fromCapabilities], 8);
  }

  function skillPurpose(skill) {
    const strategy = skill.implementation_strategy || skill.runtime || "";
    if (strategy === "deterministic_entity_list_renderer") {
      return "Формирует читаемый ответ пользователю из уже найденного списка ссылок на объекты. Не выполняет запросы к 1С и не меняет факты.";
    }
    if (strategy === "deterministic_table_renderer") {
      return "Формирует читаемый ответ пользователю из табличного результата. Не выполняет запросы к 1С и не пересчитывает данные.";
    }
    if (strategy === "deterministic_count_entities") {
      return "Считает количество элементов в уже полученном списке объектов. Нужен для вопросов вида «сколько найдено».";
    }
    if (strategy === "context_artifact_lookup") {
      return "Берет уже разрешенную сущность из контекста диалога, чтобы следующий навык мог использовать ее без повторного поиска.";
    }
    if (strategy === "semantic_binding_query") {
      return "Получает объекты 1С через MCP, используя binding к метаданным текущей конфигурации и семантические фильтры.";
    }
    if (strategy === "semantic_measure_query") {
      return "Получает числовую метрику или остатки через MCP, используя binding к регистрам/таблицам текущей конфигурации.";
    }
    if (strategy === "semantic_document_count_query") {
      return "Строит read-only запрос к документам 1С и возвращает количество документов с группировкой по периоду.";
    }
    if (strategy === "semantic_document_list_query") {
      return "Строит read-only запрос к документам 1С и возвращает список документов выбранного типа за период.";
    }
    if (strategy === "learned_query") {
      return "Навык, созданный агентом по успешному запросу. Повторно использует сохраненную схему выборки и проверяет зависимость от метаданных конфигурации.";
    }
    return skill.description || "Описание навыка не заполнено.";
  }

  function skillApplicability(skill) {
    const outputs = producedArtifacts(skill);
    const inputs = inputTypes(skill);
    const filters = compactList(skill.supported_filter_roles || [], 12).map(displayLabel);
    const capabilities = visibleCapabilities(skill);
    const parts = [];
    if (outputs.length) {
      parts.push(`когда плану нужен результат типа ${outputs.join(", ")}`);
    }
    if (inputs.length) {
      parts.push(`и уже доступны входы ${inputs.join(", ")}`);
    }
    if (filters.length) {
      parts.push(`поддерживаемые фильтры: ${filters.join(", ")}`);
    }
    if (capabilities.length) {
      parts.push(`ключевые признаки: ${capabilities.map(displayLabel).join(", ")}`);
    }
    if (!parts.length && skill.description) {
      parts.push(skill.description);
    }
    return parts.length ? `<p>${escapeHtml(parts.join("; "))}.</p>` : "";
  }

  function implementationFacts(skill) {
    const implementation = skill.implementation && typeof skill.implementation === "object" ? skill.implementation : {};
    const metrics = Array.isArray(implementation.metrics) ? implementation.metrics.map((metric) => metric.label || metric.expression).filter(Boolean).join(", ") : "";
    const dependencies = Array.isArray(implementation.metadata_dependencies) ? implementation.metadata_dependencies.join(", ") : "";
    return renderFacts({
      "Роль": displayLabel(skill.semantic_role || ""),
      "Тип навыка": displayLabel(skill.kind || ""),
      "Стратегия": displayLabel(skill.implementation_strategy || skill.runtime || ""),
      "Источник данных": implementation.source || "",
      "Метрики": metrics,
      "Зависимости метаданных": dependencies,
      "Файл контракта": skill.source_path || displayLabel(skill.source || ""),
    });
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

  function linkedDraftId(candidate) {
    const item = candidate || {};
    if (item.draft_id) {
      return item.draft_id;
    }
    const payload = item.payload && typeof item.payload === "object" ? item.payload : {};
    if (payload.draft_id) {
      return payload.draft_id;
    }
    const draft = payload.draft && typeof payload.draft === "object" ? payload.draft : {};
    return draft.draft_id || "";
  }

  function isSynthesisCandidate(candidate) {
    const item = candidate || {};
    const id = candidateId(item);
    return id.startsWith("syn_") || Boolean(item.answer || item.query || item.trace_path || item.final_artifact_type);
  }

  function renderSkillCard(skill) {
    const item = skill || {};
    const id = item.skill_id || item.id || "";
    const outputs = producedArtifacts(item);
    return `<article class="entity-card skill-card" data-skill-id="${escapeHtml(id)}">
      <div class="entity-card-header">
        <div>
          <div class="entity-kind">Навык</div>
          <h3>${escapeHtml(item.title || id || "Навык")}</h3>
        </div>
        ${renderStatusPill(item.status || item.lifecycle_status || "active")}
      </div>
      ${renderInfoSection("Что делает", `<p>${escapeHtml(skillPurpose(item))}</p>`)}
      ${renderInfoSection("Когда выбирается", skillApplicability(item))}
      ${renderInfoSection("Что принимает", renderPortList(item.inputs, "Входные данные не требуются."))}
      ${renderInfoSection("Что возвращает", renderPortList(item.outputs, "Выходной артефакт не описан."))}
      ${outputs.length ? renderTags(outputs) : ""}
      ${renderInfoSection("Технический контракт", implementationFacts(item))}
      ${renderTags(item.tags)}
      ${item.description ? renderJsonDetails("Исходное описание контракта", { description: item.description, capabilities: item.capabilities || [] }) : ""}
      <div class="entity-actions">
        ${actionButton("Открыть", "open-skill", "skill-id", id, "primary-button")}
        ${actionButton("Отметить проверенным", "skill-promote", "skill-id", id, "secondary-button")}
        ${actionButton("Заблокировать", "skill-block", "skill-id", id, "ghost-button")}
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
          <h3>${escapeHtml(item.title || id || "Черновик")}</h3>
        </div>
        ${renderStatusPill(item.status || item.source_kind || "draft")}
      </div>
      ${questions.length ? `<p class="entity-summary">${escapeHtml(questions.join("; "))}</p>` : ""}
      ${renderFacts({ Идентификатор: id, Источник: displayLabel(item.source_kind || ""), Обновлен: item.updated_at || "" })}
      <div class="entity-actions">
        ${actionButton("Открыть", "open-draft", "draft-id", id, "primary-button")}
        ${actionButton("Предпросмотр", "draft-preview", "draft-id", id, "secondary-button")}
        ${actionButton("Проверить", "draft-smoke", "draft-id", id, "secondary-button")}
        ${actionButton("Утвердить", "draft-approve", "draft-id", id, "secondary-button")}
        ${actionButton("Опубликовать", "draft-publish", "draft-id", id, "secondary-button")}
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
    const draftId = synthesis ? linkedDraftId(item) : "";
    const createLabel = draftId ? "Открыть черновик" : "Создать черновик";
    return `<article class="entity-card candidate-card" data-candidate-id="${escapeHtml(id)}">
      <div class="entity-card-header">
        <div>
          <div class="entity-kind">${synthesis ? "Кандидат от агента" : "Кандидат обучения"}</div>
          <h3>${escapeHtml(question)}</h3>
        </div>
        ${renderStatusPill(item.status || "candidate")}
      </div>
      ${answer ? `<p class="entity-summary">${escapeHtml(answer)}</p>` : `<p class="muted">Откройте кандидата или создайте черновик, чтобы проверить навык.</p>`}
      ${renderFacts({ Идентификатор: id, Черновик: draftId, Строк: rowCount, Источник: displayLabel(source), Трассировка: item.trace_path || "" })}
      ${renderTags(objects)}
      <div class="entity-actions">
        ${actionButton(createLabel, createAction, "candidate-id", id, "primary-button")}
        ${actionButton("Отклонить", rejectAction, "candidate-id", id, "secondary-button")}
        ${item.trace_path ? actionButton("Открыть трассировку", "open-trace", "trace-path", item.trace_path, "secondary-button") : ""}
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
      return `<div class="empty-state"><h3>Черновиков пока нет</h3><p>Создайте черновик из кандидата или вручную через мастер.</p></div>`;
    }
    return `<div class="summary-kpi">Черновиков: ${escapeHtml(summaryCount(data.summary, drafts.length))}</div>
      <div class="card-list entity-list">${drafts.slice(0, 50).map(renderDraftCard).join("")}</div>`;
  }

  function renderCandidatesResponse(data) {
    const candidates = data.candidates || [];
    const notice = renderNotice(data.notice);
    if (!candidates.length) {
      return `${notice}<div class="empty-state"><h3>Кандидатов пока нет</h3><p>Они появятся после успешных ответов агента через синтез запроса или после первоначального обучения.</p></div>`;
    }
    return `<div class="summary-kpi">Кандидатов: ${escapeHtml(summaryCount(data.summary, candidates.length))}</div>
      ${notice}
      <p class="workbench-hint">Выберите кандидата, проверьте смысл и создайте черновик без ручного копирования идентификатора.</p>
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
    return `<p>${preview && preview.ok ? "Предпросмотр построен." : "Предпросмотр содержит замечания."}</p>${renderIssueList(preview && preview.issues)}`;
  }

  function renderSmokeResult(smoke) {
    return `<p>Проверочный запуск ${smoke && smoke.ok ? "успешен" : "не прошел"}; строк: ${escapeHtml((smoke && smoke.row_count) || 0)}.</p>`;
  }

  function renderPublicationResult(publication) {
    return `<p>Публикация кандидата: ${publication && publication.ok ? "готова" : "есть блокеры"}.</p>${renderIssueList(publication && publication.issues)}`;
  }

  function renderLifecycleResult(lifecycle) {
    return `<p>Жизненный цикл: ${escapeHtml(displayLabel((lifecycle && lifecycle.before_status) || ""))} -> ${escapeHtml(displayLabel((lifecycle && lifecycle.after_status) || ""))}</p>${renderIssueList(lifecycle && lifecycle.issues)}`;
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
      return `${renderNotice(data.notice)}${renderDraftCard(data.draft)}`;
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
