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
    window.WiiconApp.showInfo(`Источник draft заполнен: ${objectName}`);
  }

  function applyMetadataField(fieldName, target) {
    const idByTarget = {
      group: "draftGroupFieldInput",
      metric: "draftMeasureFieldInput",
      filter: "draftFilterFieldInput",
    };
    setValue(idByTarget[target] || "draftGroupFieldInput", fieldName);
    window.WiiconApp.showInfo(`Поле добавлено в draft: ${fieldName}`);
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
      throw new Error("Укажите Skill ID.");
    }
    return runWorkbenchAction(button, "Загрузка навыка", () => api.fetchAdmin(`/api/admin/skills/catalog/${encodeURIComponent(skillId)}`), (data) => {
      setCurrentSkillId(skillId);
      return data;
    });
  }

  async function loadDraftList(button) {
    return runWorkbenchAction(button, "Загрузка drafts", () => api.fetchAdmin("/api/admin/workbench/drafts"), (data) => data);
  }

  async function loadDraftDetails(button) {
    const draftId = currentDraftId();
    return loadDraftDetailsById(draftId, button);
  }

  async function loadDraftDetailsById(draftId, button) {
    if (!draftId) {
      throw new Error("Укажите Draft ID.");
    }
    return runWorkbenchAction(button, "Загрузка draft", () => api.fetchAdmin(`/api/admin/workbench/drafts/${encodeURIComponent(draftId)}`), (data) => {
      setCurrentDraftId(draftId);
      setLifecycleStep("draft");
      return data;
    });
  }

  async function createDraft(button) {
    const draft = buildTopMetricDraftFromForm();
    return runWorkbenchAction(
      button,
      "Создание draft",
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
    const draftId = currentDraftId();
    if (!draftId) {
      throw new Error("Укажите Draft ID.");
    }
    const payload = { actor: "web-workbench" };
    if (action === "smoke") {
      payload.params = parseJsonInput("smokeParamsInput", {});
    }
    if (action === "approve" || action === "reject" || action === "publish-candidate") {
      payload.actor = "web-approver";
      payload.comment = readValue("approvalCommentInput");
      payload.smoke_id = window.WiiconState.workbench.latestSmokeId;
      if (action === "publish-candidate") {
        payload.approve = true;
      }
    }
    const label = `Draft ${action}`;
    return runWorkbenchAction(
      button,
      label,
      () => api.fetchAdmin(`/api/admin/workbench/drafts/${encodeURIComponent(draftId)}/${action}`, { method: "POST", body: payload }),
      (data) => {
        if (data.smoke && data.smoke.smoke_id) {
          window.WiiconState.workbench.latestSmokeId = data.smoke.smoke_id;
        }
        if (action === "preview") {
          setLifecycleStep("preview");
        } else if (action === "smoke") {
          setLifecycleStep("smoke");
        } else if (action === "approve") {
          setLifecycleStep("approval");
        } else if (action === "publish-candidate") {
          setLifecycleStep("candidate");
        }
        return data;
      }
    );
  }

  async function loadOnboardingCandidates(button) {
    return runWorkbenchAction(button, "Загрузка onboarding candidates", () => api.fetchAdmin("/api/admin/workbench/onboarding/candidates"), (data) => data);
  }

  async function postCandidateAction(action, button) {
    const candidateId = readValue("candidateIdInput");
    return postCandidateActionById(candidateId, action, button);
  }

  async function postCandidateActionById(candidateId, action, button) {
    if (!candidateId) {
      throw new Error("Укажите candidate ID.");
    }
    setCurrentCandidateId(candidateId, "onboarding");
    return runWorkbenchAction(
      button,
      `Onboarding candidate ${action}`,
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
    return runWorkbenchAction(button, "Загрузка agent candidates", () => api.fetchAdmin("/api/admin/workbench/synthesis/candidates"), (data) => data);
  }

  async function postSynthesisCandidateAction(action, button) {
    const candidateId = readValue("synthesisCandidateIdInput");
    return postSynthesisCandidateActionById(candidateId, action, button);
  }

  async function postSynthesisCandidateActionById(candidateId, action, button) {
    if (!candidateId) {
      throw new Error("Укажите agent candidate ID.");
    }
    setCurrentCandidateId(candidateId, "synthesis");
    return runWorkbenchAction(
      button,
      `Agent candidate ${action}`,
      () => api.fetchAdmin(`/api/admin/workbench/synthesis/candidates/${encodeURIComponent(candidateId)}/${action}`, {
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

  async function postSkillLifecycleAction(action, button) {
    const skillId = currentSkillId();
    return postSkillLifecycleActionById(skillId, action, button);
  }

  async function postSkillLifecycleActionById(skillId, action, button) {
    if (!skillId) {
      throw new Error("Укажите Skill ID.");
    }
    setCurrentSkillId(skillId);
    const regressionCaseIds = readValue("skillRegressionCasesInput")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    return runWorkbenchAction(
      button,
      `Skill ${action}`,
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
      "Regression replay",
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
      throw new Error("Trace path пустой.");
    }
    const summary = window.WiiconApp.requiredElement("workbenchSummary");
    const output = window.WiiconApp.requiredElement("workbenchOutput");
    summary.innerHTML = `<div class="empty-state"><h3>Trace кандидата</h3><p>${renderers.escapeHtml(tracePath)}</p></div>`;
    output.innerHTML = renderers.renderJsonDetails("Trace path", { trace_path: tracePath });
    window.WiiconApp.showInfo("Trace path открыт.");
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
      badge.textContent = step || "ожидание";
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
