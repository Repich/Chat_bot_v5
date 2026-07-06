(function () {
  "use strict";

  const api = window.WiiconApi;
  const renderers = window.WiiconRenderers;

  function parseJsonInput(id, fallback) {
    const element = window.WiiconApp.optionalElement(id);
    const value = element ? element.value.trim() : "";
    if (!value) {
      return fallback;
    }
    return JSON.parse(value);
  }

  function readValue(id) {
    const element = window.WiiconApp.optionalElement(id);
    return element ? String(element.value || "").trim() : "";
  }

  function readChecked(id) {
    const element = window.WiiconApp.optionalElement(id);
    return Boolean(element && element.checked);
  }

  function buttonElement(button) {
    return button && button.currentTarget ? button.currentTarget : button;
  }

  function closestDraftCard(button) {
    const element = buttonElement(button);
    return element && element.closest ? element.closest("[data-draft-id]") : null;
  }

  function readDraftCardValue(button, selector) {
    const card = closestDraftCard(button);
    const element = card ? card.querySelector(selector) : null;
    return element ? String(element.value || "").trim() : "";
  }

  function readDraftComment(button) {
    return readDraftCardValue(button, ".draft-comment-input") || readValue("approvalCommentInput");
  }

  function parseDraftSmokeParams(button) {
    const raw = readDraftCardValue(button, ".draft-smoke-params-input") || readValue("smokeParamsInput");
    return raw ? JSON.parse(raw) : {};
  }

  function showDraftCardError(button, message) {
    const card = closestDraftCard(button);
    if (!card) {
      const summary = window.WiiconApp.optionalElement("workbenchSummary");
      if (summary) {
        summary.innerHTML = `<p class="message error">${renderers.escapeHtml(message)}</p>`;
      } else {
        window.WiiconApp.showFatalUiError(new Error(message));
      }
      window.WiiconApp.showInfo(message);
      return;
    }
    const error = card.querySelector(".draft-inline-error");
    if (error) {
      error.textContent = message;
      error.classList.remove("hidden");
    }
    const result = localDraftResult(button);
    if (result) {
      result.innerHTML = `<p><strong>Действие не выполнено:</strong> ${renderers.escapeHtml(message)}</p>`;
      result.className = "draft-action-feedback error";
      result.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
    const commentInput = card.querySelector(".draft-comment-input");
    if (commentInput) {
      try {
        commentInput.focus({ preventScroll: true });
      } catch (error_) {
        commentInput.focus();
      }
    }
    window.WiiconApp.showInfo(message);
  }

  function localDraftResult(button) {
    const card = closestDraftCard(button);
    return card ? card.querySelector(".draft-action-feedback") || card.querySelector(".draft-action-result-local") : null;
  }

  function showDraftActionProgress(button, message) {
    const target = localDraftResult(button);
    if (!target) {
      return false;
    }
    target.innerHTML = `<p>${renderers.escapeHtml(message)}</p>`;
    target.className = "draft-action-feedback pending";
    target.scrollIntoView({ block: "nearest", behavior: "smooth" });
    return true;
  }

  function showDraftActionResult(button, data) {
    const target = localDraftResult(button);
    if (!target) {
      return false;
    }
    target.innerHTML = renderers.renderDraftActionResult(data) || `<p>${renderers.escapeHtml(data.notice || "Действие выполнено.")}</p>`;
    const blocked = data && data.publication && data.publication.ok === false;
    target.className = `draft-action-feedback ${blocked ? "warning" : "success"}`;
    target.scrollIntoView({ block: "nearest", behavior: "smooth" });
    return true;
  }

  function clearDraftCardError(button) {
    const card = closestDraftCard(button);
    const error = card ? card.querySelector(".draft-inline-error") : null;
    if (error) {
      error.textContent = "";
      error.classList.add("hidden");
    }
  }

  function setValue(id, value) {
    const element = window.WiiconApp.optionalElement(id);
    if (element) {
      element.value = value || "";
    }
  }

  function setCurrentDraftId(draftId) {
    window.WiiconState.workbench.selectedDraftId = draftId || "";
    setValue("draftDetailsInput", draftId || "");
  }

  function setCurrentSkillId(skillId) {
    window.WiiconState.workbench.selectedSkillId = skillId || "";
    setValue("skillDetailsInput", skillId || "");
    setValue("skillLifecycleIdInput", skillId || "");
  }

  function setCurrentCandidateId(candidateId, kind) {
    window.WiiconState.workbench.selectedCandidateId = candidateId || "";
    if (kind === "synthesis") {
      setValue("synthesisCandidateIdInput", candidateId || "");
    } else if (kind === "onboarding") {
      setValue("candidateIdInput", candidateId || "");
    }
  }

  function currentDraftId() {
    const state = window.WiiconState;
    return readValue("draftDetailsInput") || state.workbench.selectedDraftId || "";
  }

  function currentSkillId() {
    const state = window.WiiconState;
    return readValue("skillLifecycleIdInput") || readValue("skillDetailsInput") || state.workbench.selectedSkillId || "";
  }

  const DRAFT_ACTION_LABELS = {
    approve: "Утверждение черновика",
    preview: "Предпросмотр черновика",
    reject: "Отклонение черновика",
    smoke: "Проверочный запуск черновика",
    "publish-candidate": "Публикация кандидата",
  };

  const DRAFT_ACTION_NOTICES = {
    approve: "Решение по проверке сохранено. Следующий шаг: опубликовать черновик как кандидата навыка.",
    preview: "Предпросмотр построен. Проверьте запрос 1С и замечания, затем запустите проверочный запуск.",
    reject: "Черновик отклонен.",
    smoke: "Проверочный запуск выполнен. Если результат корректный, заполните комментарий и утвердите проверку.",
    "publish-candidate": "Черновик опубликован как кандидат навыка. Следующий шаг: открыть кандидата или перевести навык по жизненному циклу.",
  };

  const CANDIDATE_ACTION_LABELS = {
    "create-draft": "создать черновик",
    reject: "отклонить",
    "ignore-similar": "игнорировать похожие",
  };

  const SKILL_ACTION_LABELS = {
    block: "блокировка",
    deprecate: "пометка устаревшим",
    promote: "изменение статуса навыка",
    rollback: "откат",
  };

  const STEP_LABELS = {
    approval: "утверждение",
    candidate: "кандидат",
    draft: "черновик",
    preview: "предпросмотр",
    smoke: "проверка",
    verified: "проверен",
  };

  function buildTopMetricDraftFromForm() {
    const raw = readValue("draftJsonInput");
    if (raw) {
      return JSON.parse(raw);
    }
    const sourceAlias = readValue("draftSourceAliasInput") || "Источник";
    const title = readValue("draftTitleInput") || "Новый навык";
    const question = readValue("draftExampleQuestionInput") || title;
    const sourceObject = readValue("draftSourceObjectInput");
    const groupRole = readValue("draftGroupRoleInput") || "group";
    const groupField = readValue("draftGroupFieldInput");
    const measureRole = readValue("draftMeasureRoleInput") || "metric";
    const measureField = readValue("draftMeasureFieldInput");
    const measureLabel = readValue("draftMeasureLabelInput") || "Значение";
    const confirmed = readChecked("draftFieldsConfirmedInput");
    const draft = {
      title,
      description: readValue("draftDescriptionInput"),
      example_questions: [question],
      data_sources: [
        {
          alias: sourceAlias,
          object_name: sourceObject,
          trust: confirmed ? "verified" : "candidate",
        },
      ],
      field_mappings: [
        {
          role: groupRole,
          source_alias: sourceAlias,
          field_name: groupField,
          confirmed,
        },
        {
          role: measureRole,
          source_alias: sourceAlias,
          field_name: measureField,
          confirmed,
        },
      ],
      calculation: {
        kind: "top_n_by_metric",
        source_alias: sourceAlias,
        group_by: [groupRole],
        measures: [
          {
            role: "metric",
            expression: measureRole,
            aggregate: readValue("draftAggregationInput") || "sum",
            label: measureLabel,
          },
        ],
        sort: [{ field: measureLabel, direction: "desc" }],
        limit: Number(readValue("draftLimitInput") || 0) || undefined,
      },
    };
    const filterRole = readValue("draftFilterRoleInput");
    const filterField = readValue("draftFilterFieldInput");
    const filterParameter = readValue("draftFilterParameterInput");
    if (filterRole && filterField) {
      draft.field_mappings.push({
        role: filterRole,
        source_alias: sourceAlias,
        field_name: filterField,
        confirmed,
      });
      draft.calculation.filters = [
        {
          role: filterRole,
          parameter: filterParameter || filterRole,
          operator: readValue("draftFilterOperatorInput") || "equals",
        },
      ];
    }
    return draft;
  }

  function applyMetadataSource(objectName) {
    setValue("draftSourceObjectInput", objectName);
    window.WiiconApp.showInfo(`Источник черновика заполнен: ${objectName}`);
  }

  function applyMetadataField(fieldName, target) {
    const idByTarget = {
      group: "draftGroupFieldInput",
      metric: "draftMeasureFieldInput",
      filter: "draftFilterFieldInput",
    };
    setValue(idByTarget[target] || "draftGroupFieldInput", fieldName);
    window.WiiconApp.showInfo(`Поле добавлено в черновик: ${fieldName}`);
  }

  async function loadSkillCatalog(button) {
    return runWorkbenchAction(button, "Загрузка навыков", () => api.fetchAdmin("/api/admin/skills/catalog"), (data) => {
      window.WiiconState.workbench.lastCatalog = data;
      return data;
    });
  }

  async function loadSkillDetails(button) {
    const skillId = readValue("skillDetailsInput") || currentSkillId();
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

  async function loadDraftList(button) {
    return runWorkbenchAction(button, "Загрузка черновиков", () => api.fetchAdmin("/api/admin/workbench/drafts"), (data) => data);
  }

  async function loadDraftDetails(button) {
    const draftId = currentDraftId();
    return loadDraftDetailsById(draftId, button);
  }

  async function loadDraftDetailsById(draftId, button) {
    if (!draftId) {
      throw new Error("Укажите идентификатор черновика.");
    }
    return runWorkbenchAction(button, "Загрузка черновика", () => api.fetchAdmin(`/api/admin/workbench/drafts/${encodeURIComponent(draftId)}`), (data) => {
      setCurrentDraftId(draftId);
      setLifecycleStep("draft");
      return data;
    });
  }

  async function createDraft(button) {
    const draft = buildTopMetricDraftFromForm();
    return runWorkbenchAction(
      button,
      "Создание черновика",
      () => api.fetchAdmin("/api/admin/workbench/drafts", { method: "POST", body: { actor: "web-workbench", draft } }),
      (data) => {
        const draftId = data.draft && data.draft.draft_id ? data.draft.draft_id : "";
        if (draftId) {
          setCurrentDraftId(draftId);
        }
        setLifecycleStep("draft");
        return data;
      }
    );
  }

  async function postDraftAction(action, button) {
    const label = DRAFT_ACTION_LABELS[action] || "Действие с черновиком";
    const draftId = currentDraftId();
    if (!draftId) {
      showDraftCardError(button, "Укажите идентификатор черновика.");
      return null;
    }
    let smokeParams = {};
    if (action === "smoke") {
      try {
        smokeParams = parseDraftSmokeParams(button);
      } catch (error) {
        showDraftCardError(button, `Некорректный JSON тестовых параметров: ${error.message}`);
        return null;
      }
    }
    const needsComment = action === "approve" || action === "reject" || action === "publish-candidate";
    const comment = needsComment ? readDraftComment(button) : "";
    if (needsComment && !comment) {
      showDraftCardError(button, "Заполните комментарий в карточке черновика: что проверено человеком и почему действие можно выполнить.");
      return null;
    }
    clearDraftCardError(button);
    const summary = window.WiiconApp.requiredElement("workbenchSummary");
    const output = window.WiiconApp.requiredElement("workbenchOutput");
    if (!showDraftActionProgress(button, `${label}: выполняется...`)) {
      summary.textContent = `${label}: выполняется...`;
    }
    return window.WiiconApp.withButtonState(button, label, async () => {
      const payload = { actor: "web-workbench" };
      if (action === "smoke") {
        payload.params = smokeParams;
      }
      if (action === "approve" || action === "reject" || action === "publish-candidate") {
        payload.actor = "web-approver";
        payload.comment = comment;
        if (window.WiiconState.workbench.latestSmokeId) {
          payload.smoke_id = window.WiiconState.workbench.latestSmokeId;
        }
        if (action === "publish-candidate") {
          payload.approve = true;
        }
      }
      const data = await api.fetchAdmin(`/api/admin/workbench/drafts/${encodeURIComponent(draftId)}/${action}`, { method: "POST", body: payload });
      if (data.smoke && data.smoke.smoke_id) {
        window.WiiconState.workbench.latestSmokeId = data.smoke.smoke_id;
      }
      const draftData = await api.fetchAdmin(`/api/admin/workbench/drafts/${encodeURIComponent(draftId)}`);
      const rendered = Object.assign({}, data, {
        draft: draftData.draft,
        notice: data.notice || DRAFT_ACTION_NOTICES[action] || "Действие выполнено.",
      });
      if (action === "preview") {
        setLifecycleStep("preview");
      } else if (action === "smoke") {
        setLifecycleStep("smoke");
      } else if (action === "approve") {
        setLifecycleStep("approval");
      } else if (action === "publish-candidate") {
        setLifecycleStep("candidate");
      }
      if (!showDraftActionResult(button, rendered)) {
        summary.innerHTML = renderers.renderSummary(rendered);
      }
      output.innerHTML = renderers.renderJsonDetails("Технический JSON", rendered);
      window.WiiconState.workbench.lastError = null;
      return rendered;
    }).catch((error) => {
      window.WiiconState.workbench.lastError = error;
      showDraftCardError(button, error.message || String(error));
      output.innerHTML = renderers.renderJsonDetails("Ошибка", error.details || { message: String(error.message || error) });
      return null;
    });
  }

  async function deleteDraftById(draftId, button) {
    if (!draftId) {
      throw new Error("Укажите идентификатор черновика.");
    }
    const confirmed = window.confirm(`Удалить черновик ${draftId}? Это действие нельзя отменить.`);
    if (!confirmed) {
      return null;
    }
    setCurrentDraftId(draftId);
    return runWorkbenchAction(
      button,
      "Удаление черновика",
      () => api.fetchAdmin(`/api/admin/workbench/drafts/${encodeURIComponent(draftId)}?actor=web-workbench`, {
        method: "DELETE",
      }),
      async (data) => {
        setCurrentDraftId("");
        setLifecycleStep("draft");
        const list = await api.fetchAdmin("/api/admin/workbench/drafts");
        return Object.assign({}, list, {
          notice: `Черновик ${draftId} удален.`,
          action_result: data,
        });
      }
    );
  }

  async function loadOnboardingCandidates(button) {
    return runWorkbenchAction(button, "Загрузка кандидатов обучения", () => api.fetchAdmin("/api/admin/workbench/onboarding/candidates"), (data) => data);
  }

  async function postCandidateAction(action, button) {
    const candidateId = readValue("candidateIdInput");
    return postCandidateActionById(candidateId, action, button);
  }

  async function postCandidateActionById(candidateId, action, button) {
    if (!candidateId) {
      throw new Error("Укажите идентификатор кандидата.");
    }
    setCurrentCandidateId(candidateId, "onboarding");
    return runWorkbenchAction(
      button,
      `Кандидат обучения: ${CANDIDATE_ACTION_LABELS[action] || action}`,
      () => api.fetchAdmin(`/api/admin/workbench/onboarding/candidates/${encodeURIComponent(candidateId)}/${action}`, {
        method: "POST",
        body: { actor: "web-workbench", comment: readValue("approvalCommentInput") },
      }),
      (data) => {
        const draftId = data.draft && data.draft.draft_id ? data.draft.draft_id : "";
        if (draftId) {
          setCurrentDraftId(draftId);
          setLifecycleStep("draft");
        }
        return data;
      }
    );
  }

  async function loadSynthesisCandidates(button) {
    return runWorkbenchAction(button, "Загрузка кандидатов агента", () => api.fetchAdmin("/api/admin/workbench/synthesis/candidates?status=candidate"), (data) => data);
  }

  async function postSynthesisCandidateAction(action, button) {
    const candidateId = readValue("synthesisCandidateIdInput");
    return postSynthesisCandidateActionById(candidateId, action, button);
  }

  async function postSynthesisCandidateActionById(candidateId, action, button) {
    if (!candidateId) {
      throw new Error("Укажите идентификатор кандидата агента.");
    }
    setCurrentCandidateId(candidateId, "synthesis");
    return runWorkbenchAction(
      button,
      `Кандидат агента: ${CANDIDATE_ACTION_LABELS[action] || action}`,
      () => api.fetchAdmin(`/api/admin/workbench/synthesis/candidates/${encodeURIComponent(candidateId)}/${action}`, {
        method: "POST",
        body: { actor: "web-workbench", comment: readValue("approvalCommentInput") },
      }),
      async (data) => {
        const draftId = data.draft && data.draft.draft_id ? data.draft.draft_id : "";
        if (draftId) {
          setCurrentDraftId(draftId);
          setLifecycleStep("draft");
        }
        if (action === "create-draft") {
          return Object.assign({}, data, {
            notice:
              data.notice ||
              `Черновик ${draftId || ""} готов. Следующий шаг: откройте черновик, проверьте смысл и запустите предпросмотр.`,
          });
        }
        if (action === "reject" || action === "ignore-similar") {
          const list = await api.fetchAdmin("/api/admin/workbench/synthesis/candidates?status=candidate");
          return Object.assign({}, list, {
            notice: action === "reject" ? `Кандидат ${candidateId} отклонен.` : `Похожие кандидаты для ${candidateId} будут игнорироваться.`,
            action_result: data,
          });
        }
        return data;
      }
    );
  }

  async function postSkillLifecycleAction(action, button) {
    const skillId = currentSkillId();
    return postSkillLifecycleActionById(skillId, action, button);
  }

  async function postSkillLifecycleActionById(skillId, action, button) {
    if (!skillId) {
      throw new Error("Укажите идентификатор навыка.");
    }
    setCurrentSkillId(skillId);
    const regressionCaseIds = readValue("skillRegressionCasesInput")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    return runWorkbenchAction(
      button,
      `Навык: ${SKILL_ACTION_LABELS[action] || action}`,
      () => api.fetchAdmin(`/api/admin/skills/${encodeURIComponent(skillId)}/${action}`, {
        method: "POST",
        body: {
          actor: "web-lifecycle",
          reason: readValue("skillLifecycleReasonInput"),
          target_status: readValue("skillTargetStatusInput"),
          regression_case_ids: regressionCaseIds,
          successful_runs: Number(readValue("skillSuccessfulRunsInput") || 0),
          admin_approval: readChecked("skillAdminApprovalInput"),
        },
      }),
      (data) => {
        if (action === "promote") {
          setLifecycleStep("verified");
        }
        return data;
      }
    );
  }

  async function runRegressionReplay(button) {
    return runWorkbenchAction(
      button,
      "Повтор регрессионных проверок",
      () => api.fetchAdmin("/api/admin/regression/run", {
        method: "POST",
        body: {
          actor: "web-regression",
          cases: readValue("regressionCasesPathInput"),
          session_prefix: readValue("regressionSessionPrefixInput") || "web-regression",
        },
      }),
      (data) => data
    );
  }

  function runWorkbenchAction(button, title, action, afterSuccess) {
    return window.WiiconApp.runWorkbenchAction(button, title, action, afterSuccess);
  }

  function showTracePath(tracePath) {
    if (!tracePath) {
      throw new Error("Путь трассировки пустой.");
    }
    const summary = window.WiiconApp.requiredElement("workbenchSummary");
    const output = window.WiiconApp.requiredElement("workbenchOutput");
    summary.innerHTML = `<div class="empty-state"><h3>Трассировка кандидата</h3><p>${renderers.escapeHtml(tracePath)}</p></div>`;
    output.innerHTML = renderers.renderJsonDetails("Путь трассировки", { trace_path: tracePath });
    window.WiiconApp.showInfo("Путь трассировки открыт.");
  }

  function setLifecycleStep(step) {
    const order = ["draft", "preview", "smoke", "approval", "candidate", "verified"];
    const index = order.indexOf(step);
    document.querySelectorAll("#workbenchStepper .step").forEach((element) => {
      const stepIndex = order.indexOf(element.dataset.step);
      element.classList.toggle("active", stepIndex === index);
      element.classList.toggle("done", index >= 0 && stepIndex < index);
    });
    const badge = window.WiiconApp.optionalElement("workbenchStatusBadge");
    if (badge) {
      badge.textContent = STEP_LABELS[step] || "ожидание";
    }
  }

  function renderWorkbenchSummary(data) {
    return renderers.renderSummary(data);
  }

  window.WiiconWorkbench = {
    applyMetadataSource,
    applyMetadataField,
    buildTopMetricDraftFromForm,
    setCurrentDraftId,
    setCurrentSkillId,
    setCurrentCandidateId,
    loadSkillCatalog,
    loadSkillDetails,
    loadSkillDetailsById,
    loadDraftList,
    loadDraftDetails,
    loadDraftDetailsById,
    createDraft,
    postDraftAction,
    deleteDraftById,
    loadOnboardingCandidates,
    postCandidateAction,
    postCandidateActionById,
    loadSynthesisCandidates,
    postSynthesisCandidateAction,
    postSynthesisCandidateActionById,
    postSkillLifecycleAction,
    postSkillLifecycleActionById,
    runRegressionReplay,
    runWorkbenchAction,
    showTracePath,
    renderWorkbenchSummary,
    setLifecycleStep,
  };
})();
