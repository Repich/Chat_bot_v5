(function () {
  "use strict";

  const api = window.WiiconApi;
  const renderers = window.WiiconRenderers;

  const state = {
    view: "chat",
    sessionId: "web-test",
    storage: null,
    sessions: [],
    docs: {
      items: [],
      selectedPath: "",
    },
    knowledge: {
      loaded: false,
      snapshots: [],
    },
    admin: {
      token: "",
      tokenRequired: false,
    },
    workbench: {
      selectedSkillId: "",
      selectedDraftId: "",
      selectedCandidateId: "",
      latestSmokeId: "",
      latestPreview: null,
      lastError: null,
      busy: false,
    },
    learning: {
      loaded: false,
    },
  };

  window.WiiconState = state;

  function requiredElement(id) {
    const element = document.getElementById(id);
    if (!element) {
      throw new Error(`Не найден обязательный элемент интерфейса: ${id}`);
    }
    return element;
  }

  function optionalElement(id) {
    return document.getElementById(id);
  }

  function optionalBind(id, eventName, handler) {
    const element = optionalElement(id);
    if (!element) {
      console.warn(`Не найден необязательный элемент интерфейса: ${id}`);
      return null;
    }
    element.addEventListener(eventName, handler);
    return element;
  }

  function createStorage() {
    try {
      const testKey = "__wiicon5_storage_test__";
      window.localStorage.setItem(testKey, testKey);
      window.localStorage.removeItem(testKey);
      return window.localStorage;
    } catch (error) {
      const memory = {};
      return {
        getItem: (key) => (Object.prototype.hasOwnProperty.call(memory, key) ? memory[key] : null),
        setItem: (key, value) => {
          memory[key] = String(value);
        },
        removeItem: (key) => {
          delete memory[key];
        },
      };
    }
  }

  function showFatalUiError(error) {
    const element = optionalElement("globalError");
    const message = error && error.message ? error.message : String(error || "");
    if (element) {
      element.textContent = `Ошибка интерфейса: ${message}`;
      element.classList.remove("hidden");
    }
  }

  function clearGlobalError() {
    const element = optionalElement("globalError");
    if (element) {
      element.textContent = "";
      element.classList.add("hidden");
    }
  }

  function showInfo(message) {
    const status = optionalElement("appStatus");
    if (status) {
      status.textContent = message || "готов";
    }
  }

  async function withButtonState(button, label, action) {
    const element = button && button.currentTarget ? button.currentTarget : button;
    const originalText = element && element.textContent ? element.textContent : "";
    if (element) {
      element.disabled = true;
      element.textContent = label ? `${label}...` : "Выполняется...";
    }
    try {
      const result = await action();
      if (element) {
        element.textContent = "Готово";
        window.setTimeout(() => {
          element.textContent = originalText;
          element.disabled = false;
        }, 700);
      }
      return result;
    } catch (error) {
      if (element) {
        element.textContent = "Ошибка";
        window.setTimeout(() => {
          element.textContent = originalText;
          element.disabled = false;
        }, 1200);
      }
      throw error;
    }
  }

  async function runAction(button, title, action, afterSuccess) {
    clearGlobalError();
    try {
      return await withButtonState(button, title, async () => {
        const data = await action();
        return afterSuccess ? afterSuccess(data) : data;
      });
    } catch (error) {
      showFatalUiError(error);
      throw error;
    }
  }

  async function runWorkbenchAction(button, title, action, afterSuccess) {
    state.workbench.busy = true;
    const summary = requiredElement("workbenchSummary");
    const output = requiredElement("workbenchOutput");
    summary.textContent = `${title}...`;
    output.innerHTML = "";
    try {
      const data = await runAction(button, title, action, afterSuccess);
      summary.innerHTML = window.WiiconWorkbench.renderWorkbenchSummary(data);
      output.innerHTML = renderers.renderJsonDetails("Технический JSON", data);
      state.workbench.lastError = null;
      return data;
    } catch (error) {
      state.workbench.lastError = error;
      summary.innerHTML = `<p class="message error">${renderers.escapeHtml(error.message || error)}</p>`;
      output.innerHTML = renderers.renderJsonDetails("Ошибка", error.details || { message: String(error.message || error) });
      return null;
    } finally {
      state.workbench.busy = false;
    }
  }

  function setView(view) {
    state.view = view;
    document.querySelectorAll(".nav-button").forEach((button) => {
      button.classList.toggle("active", button.dataset.view === view);
    });
    document.querySelectorAll("[data-view-panel]").forEach((panel) => {
      panel.classList.toggle("active", panel.dataset.viewPanel === view);
    });
    if (view === "docs" && state.docs.items.length === 0) {
      loadDocumentationIndex();
    }
    if (view === "learning" && !state.learning.loaded) {
      loadLearningReport();
    }
    if (view === "knowledge" && !state.knowledge.loaded) {
      loadKnowledgeStatus();
    }
  }

  async function loadUiConfig() {
    const data = await api.fetchJson("/api/ui/config");
    const config = data.config || {};
    const version = config.version || "";
    requiredElement("appVersion").textContent = version;
    state.admin.tokenRequired = Boolean(config.admin && config.admin.token_required);
    const hint = optionalElement("adminTokenHint");
    if (hint) {
      hint.textContent = state.admin.tokenRequired
        ? "Административные разделы требуют токен. Сохраните токен здесь, после этого кнопки мастерской навыков будут отправлять его в заголовках."
        : "Административный токен не требуется текущей конфигурацией.";
    }
    const adminStatus = optionalElement("adminStatusOutput");
    if (adminStatus) {
      adminStatus.textContent = renderers.formatJson(config);
    }
  }

  async function loadOnboardingStatus() {
    try {
      const data = await api.fetchAdmin("/api/admin/onboarding/status");
      renderOnboardingStatus(data.status || {});
    } catch (error) {
      renderOnboardingStatus({ error: error.message || String(error) });
    }
  }

  function renderOnboardingStatus(status) {
    const banner = optionalElement("trainingBanner");
    const output = optionalElement("onboardingStatus");
    if (status.error) {
      if (banner) {
        banner.textContent = state.admin.tokenRequired && !state.admin.token
          ? "Административный токен не задан. Мастерская навыков и обучение будут недоступны до ввода токена."
          : `Статус обучения не загружен: ${status.error}`;
        banner.className = "training-banner visible";
      }
      if (output) {
        output.textContent = status.error;
      }
      return;
    }
    const trained = Boolean(status.trained);
    const text = trained
      ? `Обучение выполнено: ${status.object_count || 0} объектов, ${status.template_count || 0} шаблонов.`
      : "Первоначальное обучение не выполнено. Возможны неверные ответы.";
    if (banner) {
      banner.textContent = text;
      banner.className = trained ? "training-banner visible trained" : "training-banner visible";
    }
    if (output) {
      output.textContent = renderers.formatJson(status);
    }
  }

  function currentSessionId() {
    const input = requiredElement("sessionIdInput");
    state.sessionId = input.value.trim() || "web-test";
    input.value = state.sessionId;
    state.storage.setItem("wiicon5.currentSession", state.sessionId);
    return state.sessionId;
  }

  function rememberSession(sessionId) {
    const key = "wiicon5.sessions";
    const current = JSON.parse(state.storage.getItem(key) || "[]");
    const next = [sessionId].concat(current.filter((item) => item !== sessionId)).slice(0, 20);
    state.storage.setItem(key, JSON.stringify(next));
  }

  async function loadSessions() {
    let serverSessions = [];
    try {
      const data = await api.fetchJson("/api/conversations");
      serverSessions = data.sessions || [];
    } catch (error) {
      serverSessions = [];
    }
    const saved = JSON.parse(state.storage.getItem("wiicon5.sessions") || "[]").map((id) => ({
      session_id: id,
      message_count: 0,
      preview: "локально",
    }));
    const byId = new Map();
    saved.concat(serverSessions).forEach((item) => byId.set(item.session_id, item));
    state.sessions = Array.from(byId.values());
    renderSessions();
  }

  function renderSessions() {
    const list = requiredElement("sessionList");
    if (!state.sessions.length) {
      list.textContent = "Сохраненных сессий пока нет.";
      return;
    }
    list.innerHTML = state.sessions.map((session) => {
      const active = session.session_id === state.sessionId ? " active" : "";
      return `<button class="session-button${active}" type="button" data-session-id="${renderers.escapeHtml(session.session_id)}">
        <strong>${renderers.escapeHtml(session.session_id)}</strong>
        <span class="muted">${renderers.escapeHtml(session.message_count || 0)} сообщ.; ${renderers.escapeHtml(session.preview || "")}</span>
      </button>`;
    }).join("");
  }

  async function loadConversation() {
    const sessionId = currentSessionId();
    rememberSession(sessionId);
    await loadSessions();
    try {
      const data = await api.fetchJson(`/api/conversation?session_id=${encodeURIComponent(sessionId)}`);
      renderConversation(data.messages || []);
    } catch (error) {
      appendMessage("error", error.message || String(error));
    }
  }

  function renderConversation(messages) {
    const container = requiredElement("messages");
    if (!messages.length) {
      container.innerHTML = "<div class=\"message assistant\">Новая сессия создана. Задайте вопрос по WIICON или WIIC.</div>";
      return;
    }
    container.innerHTML = messages.map((message) => renderMessage(message.role, message.content, message.ts)).join("");
    container.scrollTop = container.scrollHeight;
  }

  function formatMessageTime(timestamp) {
    if (!timestamp) {
      return null;
    }
    const date = new Date(timestamp);
    if (Number.isNaN(date.getTime())) {
      return null;
    }
    return {
      iso: date.toISOString(),
      short: new Intl.DateTimeFormat("ru-RU", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      }).format(date),
      full: new Intl.DateTimeFormat("ru-RU", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      }).format(date),
    };
  }

  function renderMessage(role, content, timestamp) {
    const cssRole = role === "user" ? "user" : role === "error" ? "error" : "assistant";
    const time = formatMessageTime(timestamp);
    const timeLabel = role === "user" ? "Отправлено" : role === "error" ? "Ошибка" : "Ответ";
    const timeHtml = time
      ? `<time class="message-time" datetime="${renderers.escapeHtml(time.iso)}" title="${renderers.escapeHtml(time.full)}">${timeLabel} ${renderers.escapeHtml(time.short)}</time>`
      : "";
    return `<div class="message ${cssRole}"><div class="message-content">${renderers.escapeHtml(content || "")}</div>${timeHtml}</div>`;
  }

  function appendMessage(role, content, timestamp) {
    const container = requiredElement("messages");
    container.insertAdjacentHTML("beforeend", renderMessage(role, content, timestamp || new Date().toISOString()));
    container.scrollTop = container.scrollHeight;
  }

  async function submitChat(event) {
    event.preventDefault();
    const input = requiredElement("messageInput");
    const message = input.value.trim();
    if (!message) {
      return;
    }
    const sessionId = currentSessionId();
    input.value = "";
    appendMessage("user", message, new Date().toISOString());
    const payload = { message, session_id: sessionId };
    const productRef = requiredElement("productRefInput").value.trim();
    if (productRef) {
      payload.product_ref = JSON.parse(productRef);
    }
    try {
      const data = await api.fetchJson("/chat", { method: "POST", body: payload });
      const result = data.result || {};
      const responseMessages = Array.isArray(data.messages) ? data.messages : [];
      const assistantMessage = responseMessages.slice().reverse().find((item) => item.role === "assistant");
      appendMessage(
        "assistant",
        result.message || renderers.formatJson(result),
        assistantMessage && assistantMessage.ts ? assistantMessage.ts : new Date().toISOString(),
      );
      rememberSession(sessionId);
      await loadSessions();
      startTitleBlink("Новое сообщение");
    } catch (error) {
      appendMessage("error", error.message || String(error));
      showFatalUiError(error);
    }
  }

  function startTitleBlink(prefix) {
    if (document.hasFocus()) {
      return;
    }
    const originalTitle = document.title;
    let visible = false;
    const timer = window.setInterval(() => {
      visible = !visible;
      document.title = visible ? `${prefix} - ${originalTitle}` : originalTitle;
    }, 900);
    const stop = () => {
      window.clearInterval(timer);
      document.title = originalTitle;
      window.removeEventListener("focus", stop);
      document.removeEventListener("visibilitychange", stop);
    };
    window.addEventListener("focus", stop);
    document.addEventListener("visibilitychange", stop);
  }

  async function loadMetadataSearch(button) {
    const term = requiredElement("metadataSearchInput").value.trim();
    return runAction(button, "Поиск", () => api.fetchAdmin(`/api/admin/metadata/search?q=${encodeURIComponent(term)}`), (data) => {
      renderMetadataResults(data.objects || []);
      return data;
    });
  }

  async function loadMetadataObject(button) {
    const fullName = requiredElement("metadataObjectInput").value.trim();
    if (!fullName) {
      throw new Error("Укажите полное имя объекта метаданных.");
    }
    return runAction(button, "Загрузка объекта", () => api.fetchAdmin(`/api/admin/metadata/object?full_name=${encodeURIComponent(fullName)}`), (data) => {
      renderMetadataResults([data.object]);
      return data;
    });
  }

  function renderMetadataResults(objects) {
    const container = requiredElement("metadataResults");
    if (!objects.length) {
      container.textContent = "Ничего не найдено.";
      return;
    }
    container.innerHTML = objects.map((object) => {
      const name = object.full_name || object.name || "";
      const fields = Array.isArray(object.fields) ? object.fields : [];
      const fieldTags = fields.slice(0, 40).map((field) => {
        const fieldName = field.name || field;
        return `<span class="tag">${renderers.escapeHtml(fieldName)}</span>`;
      }).join("");
      return `<article class="card metadata-object-card" data-object-name="${renderers.escapeHtml(name)}">
        ${renderers.renderMetadataObjectCard(object)}
        <div class="button-grid wide">
          <button class="secondary-button metadata-open-button" type="button" data-object-name="${renderers.escapeHtml(name)}">Открыть</button>
        </div>
        <div class="tag-row">${fieldTags}</div>
      </article>`;
    }).join("");
  }

  async function loadKnowledgeStatus(button) {
    return runAction(button, "Статус", () => api.fetchJson("/api/knowledge/status"), (data) => {
      state.knowledge.loaded = true;
      const status = data.status || {};
      const config = data.config || {};
      const current = status.current || null;
      state.knowledge.snapshots = status.snapshots || [];
      const output = requiredElement("knowledgeStatus");
      if (!config.enabled) {
        output.innerHTML = "<strong>Отключена</strong><br><span class=\"muted\">Включите knowledge.enabled в bot.yaml этого экземпляра.</span>";
      } else if (!current) {
        output.innerHTML = "<strong>Документация не загружена</strong><br><span class=\"muted\">Выполните синхронизацию или импорт локального экспорта.</span>";
      } else {
        output.innerHTML = `<strong>${renderers.escapeHtml(current.page_count || 0)} страниц</strong><br>
          <span class="muted">${renderers.escapeHtml(current.chunk_count || 0)} фрагментов; снимок ${renderers.escapeHtml(current.snapshot_id || "")}</span><br>
          <span class="muted">Добавлено ${renderers.escapeHtml(current.added || 0)}, изменено ${renderers.escapeHtml(current.updated || 0)}, удалено ${renderers.escapeHtml(current.removed || 0)}</span>`;
      }
      const select = requiredElement("knowledgeSnapshotSelect");
      select.innerHTML = state.knowledge.snapshots.map((item) => {
        const selected = current && item.snapshot_id === current.snapshot_id ? " selected" : "";
        return `<option value="${renderers.escapeHtml(item.snapshot_id || "")}"${selected}>${renderers.escapeHtml(item.created_at || item.snapshot_id || "")}: ${renderers.escapeHtml(item.page_count || 0)} стр.</option>`;
      }).join("");
      return data;
    }).catch((error) => {
      requiredElement("knowledgeStatus").textContent = error.message || String(error);
      return null;
    });
  }

  async function searchKnowledge(button) {
    const term = requiredElement("knowledgeSearchInput").value.trim();
    if (!term) {
      throw new Error("Введите вопрос или термин для поиска.");
    }
    return runAction(button, "Поиск", () => api.fetchJson(`/api/knowledge/search?q=${encodeURIComponent(term)}`), (data) => {
      renderKnowledgeHits(data.hits || []);
      return data;
    });
  }

  function renderKnowledgeHits(hits) {
    const output = requiredElement("knowledgeResults");
    if (!hits.length) {
      output.innerHTML = "<div class=\"empty-state\"><h3>Ничего не найдено</h3><p>Попробуйте термин из интерфейса или название бизнес-процесса.</p></div>";
      return;
    }
    output.innerHTML = hits.map((hit) => `<article class="entity-card knowledge-hit">
      <div class="entity-card-header">
        <div><div class="entity-kind">${renderers.escapeHtml((hit.ancestor_titles || []).join(" / ") || "WIIC")}</div><h3>${renderers.escapeHtml(hit.title || "Страница")}</h3></div>
        <span class="status-pill${hit.stale ? " warning" : ""}">${hit.stale ? "возможно устарела" : "актуальность не просрочена"}</span>
      </div>
      ${hit.heading ? `<h4>${renderers.escapeHtml(hit.heading)}</h4>` : ""}
      <p class="entity-summary">${renderers.escapeHtml(hit.snippet || "")}</p>
      <div class="entity-actions">
        <button class="primary-button knowledge-page-button" type="button" data-page-id="${renderers.escapeHtml(hit.page_id || "")}">Открыть страницу</button>
        ${hit.source_url ? `<a class="secondary-link" href="${renderers.escapeHtml(hit.source_url)}" target="_blank" rel="noopener noreferrer">Открыть в BWiki</a>` : ""}
      </div>
    </article>`).join("");
  }

  async function openKnowledgePage(pageId, button) {
    return runAction(button, "Открытие", () => api.fetchJson(`/api/knowledge/page?page_id=${encodeURIComponent(pageId)}`), (data) => {
      const page = data.page || {};
      const source = page.source_url
        ? `<p><a href="${renderers.escapeHtml(page.source_url)}" target="_blank" rel="noopener noreferrer">Открыть исходную страницу в BWiki</a></p>`
        : "";
      const meta = `<p class="muted">Версия ${renderers.escapeHtml(page.version || 0)}; обновлено ${renderers.escapeHtml(page.updated_at || "дата неизвестна")}</p>`;
      requiredElement("knowledgeContent").innerHTML = `<h1>${renderers.escapeHtml(page.title || "Страница")}</h1>${meta}${source}${renderers.renderMarkdownContent(page.content || "")}`;
      return data;
    });
  }

  async function syncKnowledge(button) {
    return runAction(button, "Синхронизация", () => api.fetchAdmin("/api/admin/knowledge/sync", { method: "POST", body: {} }), async (data) => {
      state.knowledge.loaded = false;
      await loadKnowledgeStatus();
      showInfo("База знаний обновлена");
      return data;
    });
  }

  async function activateKnowledgeSnapshot(button) {
    const snapshotId = requiredElement("knowledgeSnapshotSelect").value;
    if (!snapshotId) {
      throw new Error("Нет доступного снимка для переключения.");
    }
    return runAction(button, "Переключение", () => api.fetchAdmin("/api/admin/knowledge/activate", {
      method: "POST",
      body: { snapshot_id: snapshotId },
    }), async (data) => {
      state.knowledge.loaded = false;
      await loadKnowledgeStatus();
      showInfo("Активный снимок изменен");
      return data;
    });
  }

  async function loadDocumentationIndex(button) {
    return runAction(button, "Документация", () => api.fetchJson("/api/docs"), (data) => {
      state.docs.items = data.docs || [];
      const select = requiredElement("docsSelect");
      select.innerHTML = state.docs.items.map((item) => `<option value="${renderers.escapeHtml(item.path)}">${renderers.escapeHtml(item.section)} / ${renderers.escapeHtml(item.title)}</option>`).join("");
      const index = optionalElement("docsIndex");
      if (index) {
        index.innerHTML = state.docs.items.slice(0, 100).map((item) => `<button class="session-button docs-index-button" type="button" data-doc-path="${renderers.escapeHtml(item.path)}"><strong>${renderers.escapeHtml(item.title)}</strong><span class="muted">${renderers.escapeHtml(item.section)}</span></button>`).join("");
      }
      return data;
    }).catch((error) => {
      showFatalUiError(error);
      return null;
    });
  }

  async function openSelectedDocumentation(button) {
    const path = requiredElement("docsSelect").value || state.docs.selectedPath;
    if (!path) {
      return null;
    }
    state.docs.selectedPath = path;
    return runAction(button, "Открытие", () => api.fetchJson(`/api/docs/content?path=${encodeURIComponent(path)}`), (data) => {
      requiredElement("docsContent").innerHTML = renderers.renderMarkdownContent(data.content || "");
      return data;
    });
  }

  async function loadHistory(kind, button) {
    const url = kind === "backend" ? "/history/backend" : "/history/frontend";
    return runAction(button, "История", () => api.fetchText(url), (text) => {
      requiredElement("historyOutput").textContent = text;
      return text;
    });
  }

  async function startOnboarding(button) {
    const configDump = requiredElement("configDumpInput").value.trim();
    if (!configDump) {
      throw new Error("Укажите путь к выгрузке конфигурации.");
    }
    return runAction(button, "Обучение", () => api.fetchAdmin("/api/admin/onboarding/run", {
      method: "POST",
      body: { config_dump: configDump },
    }), (data) => {
      renderOnboardingStatus(data.status || {});
      return data;
    });
  }

  async function loadLearningReport(button) {
    return runAction(button, "Отчет обучения", () => api.fetchAdmin("/api/admin/learning/report"), (data) => {
      state.learning.loaded = true;
      renderLearningReport(data);
      return data;
    }).catch((error) => {
      renderLearningReportError(error);
      return null;
    });
  }

  function renderLearningReport(data) {
    const summary = data.summary || {};
    const skills = Array.isArray(data.skills) ? data.skills : [];
    const root = optionalElement("learningRoot");
    if (root) {
      root.textContent = data.bot_instance_root || "";
    }
    requiredElement("learningSummary").innerHTML = [
      learningKpi("Создано", summary.auto_learned_created_total || 0),
      learningKpi("Активно", summary.auto_learned_active_total || 0),
      learningKpi("Переиспользовалось", summary.auto_learned_reused_total || 0),
      learningKpi("Ни разу не использовано", summary.auto_learned_never_reused_total || 0),
      learningKpi("С ошибками", summary.auto_learned_failed_total || 0),
      learningKpi("Автоблокировано", summary.auto_learned_auto_blocked_total || 0, "danger"),
    ].join("");
    requiredElement("learningSkills").innerHTML = skills.length
      ? skills.map(renderLearningSkill).join("")
      : "<div class=\"empty-state\"><h3>Автоматических навыков пока нет</h3><p>Они появятся после успешных ответов агента, которые удалось обобщить.</p></div>";
    requiredElement("learningOutput").innerHTML = renderers.renderJsonDetails("Технический отчет", data);
  }

  function renderLearningReportError(error) {
    const message = error && error.message ? error.message : String(error || "");
    requiredElement("learningSummary").innerHTML = `<p class="message error">${renderers.escapeHtml(message)}</p>`;
    requiredElement("learningSkills").innerHTML = "";
    requiredElement("learningOutput").innerHTML = renderers.renderJsonDetails("Ошибка", error && error.details ? error.details : { message });
  }

  function learningKpi(label, value, tone) {
    const className = tone === "danger" && Number(value) > 0 ? "learning-kpi danger" : "learning-kpi";
    return `<div class="${className}"><span>${renderers.escapeHtml(label)}</span><strong>${renderers.escapeHtml(value)}</strong></div>`;
  }

  function renderLearningSkill(skill) {
    const health = skill.runtime_health || {};
    const blocked = Boolean(health.auto_blocked);
    const reusedFor = Array.isArray(skill.reused_for) ? skill.reused_for : [];
    return `<article class="entity-card learning-skill-card${blocked ? " blocked" : ""}" data-skill-id="${renderers.escapeHtml(skill.skill_id || "")}">
      <div class="entity-card-header">
        <div>
          <div class="entity-kind">${blocked ? "Автоматически заблокирован" : "Активный auto-learned навык"}</div>
          <h3>${renderers.escapeHtml(skill.skill_id || "Навык")}</h3>
        </div>
        <span class="status-pill">${blocked ? "заблокирован" : "активен"}</span>
      </div>
      <p class="entity-summary">${renderers.escapeHtml(skill.created_from_question || "Вопрос создания не зафиксирован.")}</p>
      <dl class="entity-facts">
        <div><dt>Создан</dt><dd>${renderers.escapeHtml(skill.created_by || "")}</dd></div>
        <div><dt>Тип</dt><dd>${renderers.escapeHtml(skill.kind || "")}</dd></div>
        <div><dt>Переиспользований</dt><dd>${renderers.escapeHtml(health.reuse_count || 0)}</dd></div>
        <div><dt>Успешно</dt><dd>${renderers.escapeHtml(health.success_count || 0)}</dd></div>
        <div><dt>Ошибок</dt><dd>${renderers.escapeHtml(health.failure_count || 0)}</dd></div>
        <div><dt>Последняя ошибка</dt><dd>${renderers.escapeHtml(health.last_error || "")}</dd></div>
      </dl>
      ${reusedFor.length ? `<section class="entity-section"><h4>Последние вопросы</h4><ul class="compact-list">${reusedFor.slice(-5).map((item) => `<li>${renderers.escapeHtml(item)}</li>`).join("")}</ul></section>` : ""}
      <div class="entity-actions">
        <button class="primary-button" type="button" data-action="open-skill" data-skill-id="${renderers.escapeHtml(skill.skill_id || "")}">Открыть навык</button>
      </div>
    </article>`;
  }

  function saveAdminToken() {
    state.admin.token = requiredElement("adminTokenInput").value.trim();
    state.storage.setItem(api.ADMIN_TOKEN_STORAGE_KEY, state.admin.token);
    showInfo(state.admin.token ? "Административный токен сохранен" : "Административный токен пустой");
    loadOnboardingStatus();
  }

  function clearAdminToken() {
    state.admin.token = "";
    requiredElement("adminTokenInput").value = "";
    state.storage.removeItem(api.ADMIN_TOKEN_STORAGE_KEY);
    showInfo("Административный токен очищен");
    loadOnboardingStatus();
  }

  function handleWorkbenchActionClick(event) {
    const actionButton = event.target && event.target.closest ? event.target.closest("[data-action]") : null;
    const actionArea = actionButton && (actionButton.closest("#view-workbench") || actionButton.closest("#view-learning"));
    if (!actionButton || !actionArea) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    const action = actionButton.dataset.action;
    const skillId = actionButton.dataset.skillId || "";
    const tracePath = actionButton.dataset.tracePath || "";
    if (action === "open-trace") {
      window.WiiconWorkbench.showTracePath(tracePath);
      return;
    }
    if (action === "open-skill") {
      setView("workbench");
      window.WiiconWorkbench.loadSkillDetailsById(skillId, actionButton);
      return;
    }
    if (action === "skill-save") {
      window.WiiconWorkbench.saveSkillById(skillId, actionButton);
      return;
    }
    if (action === "skill-delete") {
      window.WiiconWorkbench.deleteSkillById(skillId, actionButton);
      return;
    }
  }

  function bindEvents() {
    requiredElement("topNav").addEventListener("click", (event) => {
      const button = event.target.closest("[data-view]");
      if (button) {
        setView(button.dataset.view);
      }
    });
    requiredElement("chatForm").addEventListener("submit", submitChat);
    requiredElement("messageInput").addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        requiredElement("chatForm").requestSubmit();
      }
    });
    requiredElement("sessionList").addEventListener("click", (event) => {
      const button = event.target.closest("[data-session-id]");
      if (!button) {
        return;
      }
      requiredElement("sessionIdInput").value = button.dataset.sessionId;
      loadConversation();
    });
    optionalBind("newSessionButton", "click", () => {
      const id = `web-${Math.random().toString(36).slice(2, 10)}`;
      requiredElement("sessionIdInput").value = id;
      state.sessionId = id;
      rememberSession(id);
      renderConversation([]);
      loadSessions();
    });
    optionalBind("reloadHistoryButton", "click", loadConversation);

    optionalBind("skillCatalogButton", "click", (event) => window.WiiconWorkbench.loadSkillCatalog(event.currentTarget));
    optionalBind("skillDetailsButton", "click", (event) => window.WiiconWorkbench.loadSkillDetails(event.currentTarget));
    optionalBind("clearWorkbenchOutputButton", "click", () => {
      requiredElement("workbenchSummary").textContent = "Мастерская навыков очищена.";
      requiredElement("workbenchOutput").innerHTML = "";
    });
    document.addEventListener("click", handleWorkbenchActionClick);

    optionalBind("metadataSearchButton", "click", (event) => loadMetadataSearch(event.currentTarget));
    optionalBind("metadataObjectButton", "click", (event) => loadMetadataObject(event.currentTarget));
    requiredElement("metadataResults").addEventListener("click", (event) => {
      const openButton = event.target.closest(".metadata-open-button");
      if (openButton) {
        requiredElement("metadataObjectInput").value = openButton.dataset.objectName;
        loadMetadataObject(openButton);
        return;
      }
    });

    optionalBind("docsReloadButton", "click", (event) => loadDocumentationIndex(event.currentTarget));
    optionalBind("docsOpenButton", "click", (event) => openSelectedDocumentation(event.currentTarget));
    requiredElement("docsIndex").addEventListener("click", (event) => {
      const button = event.target.closest("[data-doc-path]");
      if (!button) {
        return;
      }
      requiredElement("docsSelect").value = button.dataset.docPath;
      openSelectedDocumentation(button);
    });

    optionalBind("knowledgeStatusReloadButton", "click", (event) => loadKnowledgeStatus(event.currentTarget));
    optionalBind("knowledgeSearchButton", "click", (event) => searchKnowledge(event.currentTarget));
    optionalBind("knowledgeSyncButton", "click", (event) => syncKnowledge(event.currentTarget));
    optionalBind("knowledgeActivateButton", "click", (event) => activateKnowledgeSnapshot(event.currentTarget));
    optionalBind("knowledgeSearchInput", "keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        searchKnowledge(requiredElement("knowledgeSearchButton"));
      }
    });
    requiredElement("knowledgeResults").addEventListener("click", (event) => {
      const button = event.target.closest("[data-page-id]");
      if (button) {
        openKnowledgePage(button.dataset.pageId, button);
      }
    });

    optionalBind("backendHistoryButton", "click", (event) => loadHistory("backend", event.currentTarget));
    optionalBind("frontendHistoryButton", "click", (event) => loadHistory("frontend", event.currentTarget));
    optionalBind("startOnboardingButton", "click", (event) => startOnboarding(event.currentTarget));
    optionalBind("learningReportButton", "click", (event) => loadLearningReport(event.currentTarget));
    optionalBind("saveAdminTokenButton", "click", saveAdminToken);
    optionalBind("clearAdminTokenButton", "click", clearAdminToken);
  }

  async function initApp() {
    state.storage = createStorage();
    state.admin.token = state.storage.getItem(api.ADMIN_TOKEN_STORAGE_KEY) || "";
    requiredElement("adminTokenInput").value = state.admin.token;
    state.sessionId = state.storage.getItem("wiicon5.currentSession") || requiredElement("sessionIdInput").value || "web-test";
    requiredElement("sessionIdInput").value = state.sessionId;
    bindEvents();
    await loadUiConfig();
    await loadSessions();
    await loadConversation();
    await loadDocumentationIndex();
    await loadOnboardingStatus();
    setView("chat");
  }

  window.addEventListener("error", (event) => {
    showFatalUiError(event.error || event.message);
  });

  window.addEventListener("unhandledrejection", (event) => {
    showFatalUiError(event.reason || event);
  });

  window.WiiconApp = {
    requiredElement,
    optionalElement,
    optionalBind,
    createStorage,
    showFatalUiError,
    showInfo,
    withButtonState,
    runAction,
    runWorkbenchAction,
    loadDocumentationIndex,
    openSelectedDocumentation,
    startTitleBlink,
    loadLearningReport,
  };

  try {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", initApp);
    } else {
      initApp();
    }
  } catch (error) {
    showFatalUiError(error);
  }
})();
