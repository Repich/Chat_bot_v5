(function () {
  "use strict";

  const api = window.WiiconApi;
  const renderers = window.WiiconRenderers;

  function buttonElement(button) {
    return button && button.currentTarget ? button.currentTarget : button;
  }

  function closestSkillCard(button) {
    const element = buttonElement(button);
    return element && element.closest ? element.closest("[data-skill-id]") : null;
  }

  function readValue(id) {
    const element = window.WiiconApp.optionalElement(id);
    return element ? String(element.value || "").trim() : "";
  }

  function setValue(id, value) {
    const element = window.WiiconApp.optionalElement(id);
    if (element) {
      element.value = value || "";
    }
  }

  function setCurrentSkillId(skillId) {
    window.WiiconState.workbench.selectedSkillId = skillId || "";
    setValue("skillDetailsInput", skillId || "");
  }

  function currentSkillId() {
    const state = window.WiiconState;
    return readValue("skillDetailsInput") || state.workbench.selectedSkillId || "";
  }

  function readSkillCardValue(button, selector) {
    const card = closestSkillCard(button);
    const element = card ? card.querySelector(selector) : null;
    return element ? String(element.value || "").trim() : "";
  }

  function readSkillImplementation(button) {
    const raw = readSkillCardValue(button, ".skill-implementation-input");
    return raw ? JSON.parse(raw) : {};
  }

  function readSkillQuery(button) {
    return readSkillCardValue(button, ".skill-query-input");
  }

  async function loadSkillCatalog(button) {
    return runWorkbenchAction(button, "Загрузка навыков", () => api.fetchAdmin("/api/admin/skills/catalog"), (data) => {
      window.WiiconState.workbench.lastCatalog = data;
      return data;
    });
  }

  async function loadSkillDetails(button) {
    const skillId = currentSkillId();
    return loadSkillDetailsById(skillId, button);
  }

  async function loadSkillDetailsById(skillId, button) {
    if (!skillId) {
      throw new Error("Укажите идентификатор навыка.");
    }
    return runWorkbenchAction(button, "Загрузка навыка", () => api.fetchAdmin(`/api/admin/skills/catalog/${encodeURIComponent(skillId)}`), (data) => {
      setCurrentSkillId(skillId);
      return data;
    });
  }

  async function saveSkillById(skillId, button) {
    if (!skillId) {
      throw new Error("Укажите идентификатор навыка.");
    }
    let implementation = {};
    try {
      implementation = readSkillImplementation(button);
    } catch (error) {
      throw new Error(`Некорректный JSON настроек выполнения: ${error.message}`);
    }
    const query = readSkillQuery(button);
    const body = { actor: "web-workbench", implementation };
    if (query) {
      body.query = query;
    }
    return runWorkbenchAction(
      button,
      "Сохранение навыка",
      () => api.fetchAdmin(`/api/admin/skills/catalog/${encodeURIComponent(skillId)}`, {
        method: "PATCH",
        body,
      }),
      (data) => {
        setCurrentSkillId(skillId);
        return Object.assign({}, data, { notice: `Навык ${skillId} сохранен.` });
      }
    );
  }

  async function deleteSkillById(skillId, button) {
    if (!skillId) {
      throw new Error("Укажите идентификатор навыка.");
    }
    const confirmed = window.confirm(`Удалить навык ${skillId}? Если он понадобится снова, агент создаст новый.`);
    if (!confirmed) {
      return null;
    }
    return runWorkbenchAction(
      button,
      "Удаление навыка",
      () => api.fetchAdmin(`/api/admin/skills/catalog/${encodeURIComponent(skillId)}?actor=web-workbench`, {
        method: "DELETE",
      }),
      async (data) => {
        setCurrentSkillId("");
        const list = await api.fetchAdmin("/api/admin/skills/catalog");
        return Object.assign({}, list, {
          notice: `Навык ${skillId} удален.`,
          action_result: data,
        });
      }
    );
  }

  function showTracePath(tracePath) {
    if (!tracePath) {
      throw new Error("Путь трассировки пустой.");
    }
    const summary = window.WiiconApp.requiredElement("workbenchSummary");
    const output = window.WiiconApp.requiredElement("workbenchOutput");
    summary.innerHTML = `<div class="empty-state"><h3>Трассировка</h3><p>${renderers.escapeHtml(tracePath)}</p></div>`;
    output.innerHTML = renderers.renderJsonDetails("Путь трассировки", { trace_path: tracePath });
    window.WiiconApp.showInfo("Путь трассировки открыт.");
  }

  function runWorkbenchAction(button, title, action, afterSuccess) {
    return window.WiiconApp.runWorkbenchAction(button, title, action, afterSuccess);
  }

  function renderWorkbenchSummary(data) {
    return renderers.renderSummary(data);
  }

  window.WiiconWorkbench = {
    setCurrentSkillId,
    loadSkillCatalog,
    loadSkillDetails,
    loadSkillDetailsById,
    saveSkillById,
    deleteSkillById,
    runWorkbenchAction,
    showTracePath,
    renderWorkbenchSummary,
  };
})();
