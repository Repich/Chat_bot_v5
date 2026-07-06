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
    container.innerHTML = messages.map((message) => renderMessage(message.role, message.content)).join("");
    container.scrollTop = container.scrollHeight;
  }

  function renderMessage(role, content) {
    const cssRole = role === "user" ? "user" : role === "error" ? "error" : "assistant";
    return `<div class="message ${cssRole}">${renderers.escapeHtml(content || "")}</div>`;
  }

  function appendMessage(role, content) {
    const container = requiredElement("messages");
    container.insertAdjacentHTML("beforeend", renderMessage(role, content));
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
    appendMessage("user", message);
    const payload = { message, session_id: sessionId };
    const productRef = requiredElement("productRefInput").value.trim();
    if (productRef) {
      payload.product_ref = JSON.parse(productRef);
    }
    try {
      const data = await api.fetchJson("/chat", { method: "POST", body: payload });
      const result = data.result || {};
      appendMessage("assistant", result.message || renderers.formatJson(result));
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
      const fieldButtons = fields.slice(0, 40).map((field) => {
        const fieldName = field.name || field;
        return `<button class="ghost-button metadata-field-button" type="button" data-field-name="${renderers.escapeHtml(fieldName)}">${renderers.escapeHtml(fieldName)}</button>`;
      }).join("");
      return `<article class="card metadata-object-card" data-object-name="${renderers.escapeHtml(name)}">
        ${renderers.renderMetadataObjectCard(object)}
        <div class="button-grid wide">
          <button class="secondary-button metadata-source-button" type="button" data-object-name="${renderers.escapeHtml(name)}">Использовать как источник</button>
          <button class="secondary-button metadata-open-button" type="button" data-object-name="${renderers.escapeHtml(name)}">Открыть</button>
        </div>
        <div class="field-picker">${fieldButtons}</div>
      </article>`;
    }).join("");
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
    optionalBind("draftListButton", "click", (event) => window.WiiconWorkbench.loadDraftList(event.currentTarget));
    optionalBind("draftDetailsButton", "click", (event) => window.WiiconWorkbench.loadDraftDetails(event.currentTarget));
    optionalBind("createDraftButton", "click", (event) => window.WiiconWorkbench.createDraft(event.currentTarget));
    optionalBind("previewDraftButton", "click", (event) => window.WiiconWorkbench.postDraftAction("preview", event.currentTarget));
    optionalBind("smokeDraftButton", "click", (event) => window.WiiconWorkbench.postDraftAction("smoke", event.currentTarget));
    optionalBind("publishDraftButton", "click", (event) => window.WiiconWorkbench.postDraftAction("publish-candidate", event.currentTarget));
    optionalBind("onboardingCandidatesButton", "click", (event) => window.WiiconWorkbench.loadOnboardingCandidates(event.currentTarget));
    optionalBind("candidateCreateDraftButton", "click", (event) => window.WiiconWorkbench.postCandidateAction("create-draft", event.currentTarget));
    optionalBind("candidateRejectButton", "click", (event) => window.WiiconWorkbench.postCandidateAction("reject", event.currentTarget));
    optionalBind("synthesisCandidatesButton", "click", (event) => window.WiiconWorkbench.loadSynthesisCandidates(event.currentTarget));
    optionalBind("synthesisCreateDraftButton", "click", (event) => window.WiiconWorkbench.postSynthesisCandidateAction("create-draft", event.currentTarget));
    optionalBind("synthesisRejectButton", "click", (event) => window.WiiconWorkbench.postSynthesisCandidateAction("reject", event.currentTarget));
    optionalBind("synthesisIgnoreSimilarButton", "click", (event) => window.WiiconWorkbench.postSynthesisCandidateAction("ignore-similar", event.currentTarget));
    optionalBind("skillPromoteButton", "click", (event) => window.WiiconWorkbench.postSkillLifecycleAction("promote", event.currentTarget));
    optionalBind("skillRollbackButton", "click", (event) => window.WiiconWorkbench.postSkillLifecycleAction("rollback", event.currentTarget));
    optionalBind("skillDeprecateButton", "click", (event) => window.WiiconWorkbench.postSkillLifecycleAction("deprecate", event.currentTarget));
    optionalBind("skillBlockButton", "click", (event) => window.WiiconWorkbench.postSkillLifecycleAction("block", event.currentTarget));
    optionalBind("runRegressionButton", "click", (event) => window.WiiconWorkbench.runRegressionReplay(event.currentTarget));
    optionalBind("clearWorkbenchOutputButton", "click", () => {
      requiredElement("workbenchSummary").textContent = "Мастерская навыков очищена.";
      requiredElement("workbenchOutput").innerHTML = "";
    });
    requiredElement("workbenchSummary").addEventListener("click", (event) => {
      const actionButton = event.target.closest("[data-action]");
      if (!actionButton) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      const action = actionButton.dataset.action;
      const candidateId = actionButton.dataset.candidateId || "";
      const draftId = actionButton.dataset.draftId || "";
      const skillId = actionButton.dataset.skillId || "";
      const tracePath = actionButton.dataset.tracePath || "";
      if (action === "open-trace") {
        window.WiiconWorkbench.showTracePath(tracePath);
        return;
      }
      if (action === "open-skill") {
        window.WiiconWorkbench.loadSkillDetailsById(skillId, actionButton);
        return;
      }
      if (action === "skill-promote" || action === "skill-block") {
        const lifecycleAction = action === "skill-promote" ? "promote" : "block";
        window.WiiconWorkbench.postSkillLifecycleActionById(skillId, lifecycleAction, actionButton);
        return;
      }
      if (action === "open-draft") {
        window.WiiconWorkbench.loadDraftDetailsById(draftId, actionButton);
        return;
      }
      if (action === "draft-delete") {
        window.WiiconWorkbench.deleteDraftById(draftId, actionButton);
        return;
      }
      if (action.startsWith("draft-")) {
        const draftAction = action.replace("draft-", "");
        const backendAction = draftAction === "publish" ? "publish-candidate" : draftAction;
        window.WiiconWorkbench.setCurrentDraftId(draftId);
        window.WiiconWorkbench.postDraftAction(backendAction, actionButton);
        return;
      }
      if (action.startsWith("synthesis-")) {
        const synthesisAction = action.replace("synthesis-", "");
        window.WiiconWorkbench.postSynthesisCandidateActionById(candidateId, synthesisAction, actionButton);
        return;
      }
      if (action.startsWith("onboarding-")) {
        const onboardingAction = action.replace("onboarding-", "");
        window.WiiconWorkbench.postCandidateActionById(candidateId, onboardingAction, actionButton);
      }
    });

    optionalBind("metadataSearchButton", "click", (event) => loadMetadataSearch(event.currentTarget));
    optionalBind("metadataObjectButton", "click", (event) => loadMetadataObject(event.currentTarget));
    requiredElement("metadataResults").addEventListener("click", (event) => {
      const sourceButton = event.target.closest(".metadata-source-button");
      if (sourceButton) {
        window.WiiconWorkbench.applyMetadataSource(sourceButton.dataset.objectName);
        return;
      }
      const openButton = event.target.closest(".metadata-open-button");
      if (openButton) {
        requiredElement("metadataObjectInput").value = openButton.dataset.objectName;
        loadMetadataObject(openButton);
        return;
      }
      const fieldButton = event.target.closest(".metadata-field-button");
      if (fieldButton) {
        window.WiiconWorkbench.applyMetadataField(fieldButton.dataset.fieldName, "group");
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

    optionalBind("backendHistoryButton", "click", (event) => loadHistory("backend", event.currentTarget));
    optionalBind("frontendHistoryButton", "click", (event) => loadHistory("frontend", event.currentTarget));
    optionalBind("startOnboardingButton", "click", (event) => startOnboarding(event.currentTarget));
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
