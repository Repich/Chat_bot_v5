from __future__ import annotations


CHAT_HTML = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>WIICON ChatBot 5</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f8;
      --panel: #ffffff;
      --line: #d7dce0;
      --text: #1b1f23;
      --muted: #5b6670;
      --accent: #0f766e;
      --accent-strong: #0b5f59;
      --danger: #b42318;
      --warning-bg: #fff7ed;
      --warning-line: #fed7aa;
      --ok-bg: #ecfdf5;
      --ok-line: #a7f3d0;
      --code: #111827;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
      overflow: hidden;
    }
    .app {
      height: 100vh;
      min-height: 0;
      display: grid;
      grid-template-rows: auto auto minmax(0, 1fr);
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 14px 18px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }
    .training-banner {
      display: none;
      border-bottom: 1px solid var(--warning-line);
      background: var(--warning-bg);
      padding: 6px 18px;
      color: #7c2d12;
      font-size: 12px;
      line-height: 1.35;
      min-height: 30px;
      align-items: center;
    }
    .training-banner.visible {
      display: flex;
    }
    .training-banner.trained {
      border-color: var(--ok-line);
      background: var(--ok-bg);
      color: #064e3b;
    }
    h1 {
      margin: 0;
      font-size: 18px;
      line-height: 1.2;
      font-weight: 650;
      letter-spacing: 0;
    }
    .title {
      display: flex;
      align-items: baseline;
      gap: 10px;
      min-width: 0;
    }
    .version {
      color: var(--muted);
      font-size: 13px;
      white-space: nowrap;
    }
    .status {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: var(--muted);
      font-size: 13px;
      white-space: nowrap;
    }
    .dot {
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: var(--accent);
    }
    main {
      width: 100%;
      max-width: 1680px;
      margin: 0 auto;
      padding: 12px 16px 16px;
      min-height: 0;
      height: 100%;
      display: grid;
      grid-template-columns: 280px minmax(0, 1fr);
      gap: 12px;
    }
    aside, .dialog {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    aside {
      padding: 12px;
      align-self: stretch;
      max-height: 100%;
      overflow: auto;
      display: grid;
      gap: 12px;
      align-content: start;
    }
    .sidebar-section {
      display: grid;
      gap: 8px;
    }
    .sidebar-title {
      margin: 0;
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
      text-transform: uppercase;
      letter-spacing: 0;
    }
    .session-actions {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
    }
    .session-list {
      display: grid;
      gap: 6px;
      max-height: 36vh;
      overflow: auto;
      padding-right: 2px;
    }
    .session-button {
      width: 100%;
      min-width: 0;
      min-height: 0;
      display: grid;
      gap: 3px;
      justify-items: start;
      text-align: left;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--text);
      padding: 8px 9px;
      font-weight: 500;
      cursor: pointer;
    }
    .session-button:hover { background: #f2f5f5; }
    .session-button.active {
      border-color: #8bc8c0;
      background: #eef8f6;
    }
    .session-name {
      width: 100%;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 13px;
      font-weight: 650;
    }
    .session-meta {
      width: 100%;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      color: var(--muted);
      font-size: 11px;
      line-height: 1.25;
    }
    .settings-panel {
      border-top: 1px solid var(--line);
      padding-top: 10px;
    }
    .settings-panel > summary {
      cursor: pointer;
      color: var(--text);
      font-size: 13px;
      font-weight: 650;
      list-style: none;
    }
    .settings-panel > summary::-webkit-details-marker { display: none; }
    .settings-panel > summary::before {
      content: "▸";
      display: inline-block;
      width: 14px;
      color: var(--muted);
    }
    .settings-panel[open] > summary::before { content: "▾"; }
    .settings-content {
      display: grid;
      gap: 12px;
      padding-top: 10px;
    }
    .tools {
      display: grid;
      gap: 8px;
    }
    .tool-row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }
    label {
      display: grid;
      gap: 6px;
      font-size: 13px;
      color: var(--muted);
    }
    input, textarea, select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--text);
      font: inherit;
      font-size: 14px;
      line-height: 1.35;
      padding: 9px 10px;
    }
    .checkbox-label {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .checkbox-label input {
      width: auto;
      margin: 0;
    }
    textarea {
      min-height: 94px;
      resize: vertical;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
    }
    .dialog {
      min-height: 0;
      height: 100%;
      display: grid;
      grid-template-rows: minmax(0, 1fr) auto;
      overflow: hidden;
    }
    .messages {
      padding: 18px;
      overflow: auto;
      display: grid;
      align-content: start;
      gap: 12px;
    }
    .empty {
      color: var(--muted);
      font-size: 14px;
      padding: 12px 0;
    }
    .message {
      max-width: 88%;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px 12px;
      background: #fff;
    }
    .message.user {
      justify-self: end;
      border-color: #b8d7d3;
      background: #eef8f6;
    }
    .message.error {
      border-color: #f0b5ae;
      background: #fff4f2;
    }
    .meta {
      margin-bottom: 6px;
      color: var(--muted);
      font-size: 12px;
    }
    .content {
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      font-size: 14px;
      line-height: 1.45;
    }
    details {
      margin-top: 8px;
      color: var(--muted);
      font-size: 12px;
    }
    pre {
      margin: 8px 0 0;
      max-height: 260px;
      overflow: auto;
      padding: 10px;
      border-radius: 6px;
      background: var(--code);
      color: #f9fafb;
      font-size: 12px;
      line-height: 1.4;
    }
    form {
      border-top: 1px solid var(--line);
      padding: 12px;
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      background: #fbfbfc;
      position: sticky;
      bottom: 0;
      z-index: 2;
    }
    form textarea {
      min-height: 48px;
      max-height: 170px;
      font-family: inherit;
      font-size: 14px;
    }
    button {
      border: 0;
      border-radius: 6px;
      background: var(--accent);
      color: #fff;
      font: inherit;
      font-weight: 600;
      padding: 0 18px;
      min-width: 110px;
      cursor: pointer;
    }
    button:hover { background: var(--accent-strong); }
    button.secondary {
      min-width: 0;
      min-height: 36px;
      padding: 0 10px;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--text);
      font-weight: 550;
    }
    button.secondary:hover { background: #f2f5f5; }
    button:disabled {
      cursor: wait;
      opacity: 0.65;
    }
    .history-panel {
      display: none;
      border-top: 1px solid var(--line);
      padding-top: 10px;
    }
    .history-panel.visible { display: block; }
    .history-title {
      margin: 0 0 8px;
      font-size: 13px;
      color: var(--muted);
      font-weight: 650;
    }
    .history-panel pre {
      max-height: 280px;
      white-space: pre-wrap;
      background: #f8fafc;
      color: var(--text);
      border: 1px solid var(--line);
    }
    .docs-panel {
      display: grid;
      gap: 8px;
    }
    .docs-actions {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 6px;
    }
    .docs-guide {
      display: grid;
      gap: 6px;
      padding: 9px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #f8fafc;
      color: var(--text);
      font-size: 12px;
      line-height: 1.35;
    }
    .docs-guide p {
      margin: 0;
      color: var(--muted);
    }
    .docs-guide ol {
      margin: 0;
      padding-left: 18px;
    }
    .docs-guide li {
      margin: 3px 0;
    }
    .docs-viewer {
      display: none;
      max-height: 46vh;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      padding: 10px;
      font-size: 13px;
      line-height: 1.45;
    }
    .docs-viewer.visible { display: block; }
    .docs-title {
      margin: 0 0 4px;
      font-size: 14px;
      font-weight: 700;
    }
    .docs-meta {
      margin: 0 0 10px;
      color: var(--muted);
      font-size: 12px;
    }
    .docs-content {
      display: grid;
      gap: 8px;
    }
    .docs-content h2,
    .docs-content h3,
    .docs-content p {
      margin: 0;
    }
    .docs-content h2 {
      font-size: 15px;
      line-height: 1.25;
    }
    .docs-content h3 {
      font-size: 14px;
      line-height: 1.25;
    }
    .docs-content ul {
      margin: 0;
      padding-left: 18px;
    }
    .docs-content pre {
      margin: 0;
      white-space: pre-wrap;
      background: #f8fafc;
      border: 1px solid var(--line);
      color: var(--code);
    }
    .docs-status {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
    }
    .danger { color: var(--danger); }
    .admin-panel {
      display: grid;
      gap: 8px;
      padding-top: 0;
      border-top: 1px solid var(--line);
    }
    .admin-title {
      margin: 0;
      color: var(--muted);
      font-size: 13px;
      font-weight: 650;
    }
    .admin-status {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
      white-space: pre-wrap;
    }
    .workbench-summary {
      display: grid;
      gap: 8px;
    }
    .workbench-heading {
      margin: 4px 0 0;
      color: var(--text);
      font-size: 13px;
      font-weight: 700;
    }
    .summary-card {
      display: grid;
      gap: 5px;
      padding: 9px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--text);
      font-size: 12px;
      line-height: 1.35;
    }
    .summary-card-title {
      font-weight: 700;
      overflow-wrap: anywhere;
    }
    .summary-card-subtitle {
      color: var(--muted);
      overflow-wrap: anywhere;
    }
    .summary-line {
      display: grid;
      grid-template-columns: 86px minmax(0, 1fr);
      gap: 6px;
      overflow-wrap: anywhere;
    }
    .summary-label {
      color: var(--muted);
      font-weight: 650;
    }
    .summary-tags {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
    }
    .summary-tag {
      max-width: 100%;
      padding: 2px 6px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: #f8fafc;
      color: var(--muted);
      overflow-wrap: anywhere;
    }
    .summary-action-row {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    .summary-action {
      min-width: 0;
      min-height: 28px;
      padding: 0 8px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #f8fafc;
      color: var(--text);
      font-size: 12px;
      font-weight: 650;
      cursor: pointer;
    }
    .summary-action:hover { background: #eef8f6; }
    .field-picker {
      display: grid;
      gap: 6px;
      padding-top: 4px;
    }
    .field-picker-row {
      display: grid;
      gap: 5px;
      padding-top: 6px;
      border-top: 1px solid var(--line);
    }
    @media (max-width: 760px) {
      body { overflow: hidden; }
      header { align-items: flex-start; flex-direction: column; }
      main {
        grid-template-columns: 1fr;
        grid-template-rows: auto minmax(0, 1fr);
        padding: 12px;
        overflow: hidden;
      }
      aside {
        max-height: 32vh;
      }
      .session-list {
        max-height: 16vh;
      }
      form { grid-template-columns: 1fr; }
      button { min-height: 42px; }
      .message { max-width: 100%; }
    }
  </style>
</head>
<body>
  <div class="app">
    <header>
      <div class="title">
        <h1>WIICON ChatBot 5</h1>
        <span class="version">v<span id="appVersion">...</span></span>
      </div>
      <div class="status"><span class="dot"></span><span id="status">готов</span></div>
    </header>
    <div id="trainingBanner" class="training-banner"></div>
    <main>
      <aside>
        <div class="sidebar-section">
          <label>Session ID
            <input id="sessionId" value="web-test" autocomplete="off">
          </label>
          <div class="session-actions">
            <button id="newSessionButton" class="secondary" type="button">Новая сессия</button>
          </div>
        </div>
        <div class="sidebar-section">
          <p class="sidebar-title">Сессии</p>
          <div id="sessionList" class="session-list"></div>
          <div id="sessionListEmpty" class="empty">Сохраненных сессий пока нет.</div>
        </div>
        <details id="settingsDetails" class="settings-panel">
          <summary>Настройки</summary>
          <div class="settings-content">
            <div class="tools">
              <button id="reloadHistoryButton" class="secondary" type="button">Обновить диалог</button>
              <div class="tool-row">
                <button id="backendHistoryButton" class="secondary" type="button">Backend</button>
                <button id="frontendHistoryButton" class="secondary" type="button">Frontend</button>
              </div>
            </div>
            <div id="historyPanel" class="history-panel">
              <p id="historyTitle" class="history-title"></p>
              <pre id="historyText"></pre>
            </div>
            <div id="documentationPanel" class="admin-panel docs-panel">
              <p class="admin-title">Документация</p>
              <div class="docs-guide">
                <p>Работа со скиллами в Workbench:</p>
                <ol>
                  <li>Откройте каталог навыков или черновики и выберите нужную карточку.</li>
                  <li>Для нового навыка найдите метаданные 1С, заполните draft и проверьте Preview.</li>
                  <li>Запустите Smoke с тестовыми параметрами, затем Approve и Candidate.</li>
                  <li>После regression replay переведите candidate в verified или stable через Lifecycle.</li>
                </ol>
                <div class="docs-actions">
                  <button id="docsOpenSkillsButton" class="secondary" type="button">Навыки</button>
                  <button id="docsOpenDraftsButton" class="secondary" type="button">Черновики</button>
                  <button id="docsOpenCandidatesButton" class="secondary" type="button">Кандидаты</button>
                  <button id="docsFocusMetadataButton" class="secondary" type="button">Метаданные</button>
                </div>
              </div>
              <label>Документ
                <select id="docsSelect"></select>
              </label>
              <div class="tool-row">
                <button id="docsRefreshButton" class="secondary" type="button">Обновить</button>
                <button id="docsOpenButton" class="secondary" type="button">Открыть</button>
              </div>
              <div id="docsStatus" class="docs-status">Документация не загружена.</div>
              <div id="docsViewer" class="docs-viewer">
                <p id="docsTitle" class="docs-title"></p>
                <p id="docsMeta" class="docs-meta"></p>
                <div id="docsContent" class="docs-content"></div>
              </div>
            </div>
            <div class="admin-panel">
              <p class="admin-title">Первоначальное обучение</p>
              <label>Выгрузка конфигурации
                <input id="configDumpPath" placeholder="/path/to/1c/config">
              </label>
              <button id="startOnboardingButton" class="secondary" type="button">Запустить обучение</button>
              <div id="onboardingStatus" class="admin-status">Статус не загружен.</div>
            </div>
            <div id="workbenchPanel" class="admin-panel">
              <p class="admin-title">Skill Workbench</p>
              <div class="tool-row">
                <button id="skillCatalogButton" class="secondary" type="button">Навыки</button>
                <button id="draftListButton" class="secondary" type="button">Черновики</button>
              </div>
              <button id="onboardingCandidatesButton" class="secondary" type="button">Onboarding candidates</button>
              <button id="synthesisCandidatesButton" class="secondary" type="button">Agent candidates</button>
              <label>Поиск метаданных
                <input id="metadataSearchInput" placeholder="Склады, Номенклатура, Регистр">
              </label>
              <button id="metadataSearchButton" class="secondary" type="button">Искать метаданные</button>
              <label>Metadata full_name
                <input id="metadataObjectInput" placeholder="РегистрНакопления.ТоварыНаСкладах">
              </label>
              <button id="metadataObjectButton" class="secondary" type="button">Открыть объект</button>
              <label>Draft ID
                <input id="draftIdInput" placeholder="draft_...">
              </label>
              <button id="draftDetailsButton" class="secondary" type="button">Открыть draft</button>
              <label>Новый draft
                <input id="draftTitleInput" placeholder="Название навыка">
              </label>
              <label>Пример вопроса
                <input id="draftExampleQuestionInput" placeholder="Какой вопрос должен закрывать навык">
              </label>
              <label>Описание
                <input id="draftDescriptionInput" placeholder="Бизнес-смысл навыка">
              </label>
              <div class="tool-row">
                <label>Источник alias
                  <input id="draftSourceAliasInput" value="Источник">
                </label>
                <label>Источник 1С
                  <input id="draftSourceObjectInput" placeholder="РегистрНакопления...Остатки">
                </label>
              </div>
              <div class="tool-row">
                <label>Группировка role
                  <input id="draftGroupRoleInput" placeholder="product">
                </label>
                <label>Группировка field
                  <input id="draftGroupFieldInput" placeholder="Номенклатура">
                </label>
              </div>
              <div class="tool-row">
                <label>Метрика role
                  <input id="draftMeasureRoleInput" placeholder="stock_balance">
                </label>
                <label>Метрика field
                  <input id="draftMeasureFieldInput" placeholder="ВНаличииОстаток">
                </label>
              </div>
              <div class="tool-row">
                <label>Метрика label
                  <input id="draftMeasureLabelInput" placeholder="Остаток">
                </label>
                <label>Агрегация
                  <select id="draftAggregateSelect">
                    <option value="sum">sum</option>
                    <option value="count">count</option>
                    <option value="max">max</option>
                    <option value="min">min</option>
                  </select>
                </label>
              </div>
              <div class="tool-row">
                <label>Фильтр role
                  <input id="draftFilterRoleInput" placeholder="warehouse_type">
                </label>
                <label>Фильтр field
                  <input id="draftFilterFieldInput" placeholder="Склад.ТипСклада">
                </label>
              </div>
              <div class="tool-row">
                <label>Фильтр parameter
                  <input id="draftFilterParameterInput" placeholder="ТипСклада">
                </label>
                <label>Фильтр operator
                  <select id="draftFilterOperatorSelect">
                    <option value="equals">equals</option>
                    <option value="not_equals">not_equals</option>
                    <option value="in">in</option>
                    <option value="contains">contains</option>
                  </select>
                </label>
              </div>
              <div class="tool-row">
                <label>Limit
                  <input id="draftLimitInput" type="number" min="1" max="100" step="1" placeholder="10">
                </label>
                <label class="checkbox-label">
                  <input id="draftFieldsConfirmedInput" type="checkbox">
                  Fields confirmed
                </label>
              </div>
              <label>Draft JSON
                <textarea id="draftJsonInput" spellcheck="false" placeholder='{"title":"...","example_questions":["..."]}'></textarea>
              </label>
              <div class="tool-row">
                <button id="createDraftButton" class="secondary" type="button">Создать</button>
                <button id="previewDraftButton" class="secondary" type="button">Preview</button>
              </div>
              <div class="tool-row">
                <button id="smokeDraftButton" class="secondary" type="button">Smoke</button>
                <button id="publishDraftButton" class="secondary" type="button">Candidate</button>
              </div>
              <label>Комментарий approval
                <input id="approvalCommentInput" placeholder="Что проверено человеком">
              </label>
              <label>Smoke params JSON
                <textarea id="smokeParamsInput" spellcheck="false" placeholder='{"Склад":"Центральный"}'></textarea>
              </label>
              <div class="tool-row">
                <button id="approveDraftButton" class="secondary" type="button">Approve</button>
                <button id="rejectDraftButton" class="secondary" type="button">Reject</button>
              </div>
              <label>Candidate ID
                <input id="candidateIdInput" placeholder="onb_...">
              </label>
              <div class="tool-row">
                <button id="candidateCreateDraftButton" class="secondary" type="button">Create draft</button>
                <button id="candidateRejectButton" class="secondary" type="button">Reject</button>
              </div>
              <label>Agent candidate ID
                <input id="synthesisCandidateIdInput" placeholder="syn_...">
              </label>
              <div class="tool-row">
                <button id="synthesisCreateDraftButton" class="secondary" type="button">Create draft</button>
                <button id="synthesisRejectButton" class="secondary" type="button">Reject</button>
              </div>
              <button id="synthesisIgnoreSimilarButton" class="secondary" type="button">Ignore similar</button>
              <p class="admin-title">Lifecycle навыка</p>
              <label>Skill ID
                <input id="skillLifecycleIdInput" placeholder="skill_...">
              </label>
              <button id="skillDetailsButton" class="secondary" type="button">Открыть skill</button>
              <label>Причина изменения
                <input id="skillLifecycleReasonInput" placeholder="Что проверено и почему меняем статус">
              </label>
              <label>Regression case IDs
                <input id="skillRegressionCasesInput" placeholder="reg_case_1, reg_case_2">
              </label>
              <label>Target status
                <select id="skillLifecycleTargetStatus">
                  <option value="">По умолчанию</option>
                  <option value="verified">verified</option>
                  <option value="stable">stable</option>
                  <option value="candidate">candidate</option>
                </select>
              </label>
              <label>Successful runs
                <input id="skillSuccessfulRunsInput" type="number" min="0" step="1" placeholder="0">
              </label>
              <label class="checkbox-label">
                <input id="skillAdminApprovalInput" type="checkbox">
                Admin approval
              </label>
              <div class="tool-row">
                <button id="skillPromoteButton" class="secondary" type="button">Promote</button>
                <button id="skillRollbackButton" class="secondary" type="button">Rollback</button>
              </div>
              <div class="tool-row">
                <button id="skillDeprecateButton" class="secondary" type="button">Deprecate</button>
                <button id="skillBlockButton" class="secondary" type="button">Block</button>
              </div>
              <p class="admin-title">Regression replay</p>
              <label>Cases path
                <input id="regressionCasesPathInput" placeholder="Пусто = bot_instance/regression">
              </label>
              <label>Session prefix
                <input id="regressionSessionPrefixInput" value="web-regression">
              </label>
              <button id="runRegressionButton" class="secondary" type="button">Run regression</button>
              <div id="workbenchSummary" class="workbench-summary"></div>
              <pre id="workbenchText" class="admin-status">Workbench не загружен.</pre>
            </div>
            <label>ProductRef JSON
              <textarea id="productRef" spellcheck="false"></textarea>
            </label>
          </div>
        </details>
      </aside>
      <section class="dialog" aria-label="chat">
        <div id="messages" class="messages">
          <div class="empty">Добрый день. Задайте вопрос по WIICON или WIIC.</div>
        </div>
        <form id="chatForm">
          <textarea id="messageInput" placeholder="Введите сообщение" required autofocus></textarea>
          <button id="sendButton" type="submit">Отправить</button>
        </form>
      </section>
    </main>
  </div>
  <script>
    const SESSION_STORAGE_KEY = "wiicon5.sessionId";
    const SESSION_LIST_STORAGE_KEY = "wiicon5.sessionList";
    const form = document.getElementById("chatForm");
    const input = document.getElementById("messageInput");
    const sendButton = document.getElementById("sendButton");
    const messages = document.getElementById("messages");
    const statusText = document.getElementById("status");
    const sessionId = document.getElementById("sessionId");
    const newSessionButton = document.getElementById("newSessionButton");
    const sessionList = document.getElementById("sessionList");
    const sessionListEmpty = document.getElementById("sessionListEmpty");
    const productRef = document.getElementById("productRef");
    const appVersion = document.getElementById("appVersion");
    const reloadHistoryButton = document.getElementById("reloadHistoryButton");
    const backendHistoryButton = document.getElementById("backendHistoryButton");
    const frontendHistoryButton = document.getElementById("frontendHistoryButton");
    const historyPanel = document.getElementById("historyPanel");
    const historyTitle = document.getElementById("historyTitle");
    const historyText = document.getElementById("historyText");
    const docsSelect = document.getElementById("docsSelect");
    const docsRefreshButton = document.getElementById("docsRefreshButton");
    const docsOpenButton = document.getElementById("docsOpenButton");
    const docsOpenSkillsButton = document.getElementById("docsOpenSkillsButton");
    const docsOpenDraftsButton = document.getElementById("docsOpenDraftsButton");
    const docsOpenCandidatesButton = document.getElementById("docsOpenCandidatesButton");
    const docsFocusMetadataButton = document.getElementById("docsFocusMetadataButton");
    const docsStatus = document.getElementById("docsStatus");
    const docsViewer = document.getElementById("docsViewer");
    const docsTitle = document.getElementById("docsTitle");
    const docsMeta = document.getElementById("docsMeta");
    const docsContent = document.getElementById("docsContent");
    const settingsDetails = document.getElementById("settingsDetails");
    const trainingBanner = document.getElementById("trainingBanner");
    const configDumpPath = document.getElementById("configDumpPath");
    const startOnboardingButton = document.getElementById("startOnboardingButton");
    const onboardingStatus = document.getElementById("onboardingStatus");
    const skillCatalogButton = document.getElementById("skillCatalogButton");
    const draftListButton = document.getElementById("draftListButton");
    const onboardingCandidatesButton = document.getElementById("onboardingCandidatesButton");
    const synthesisCandidatesButton = document.getElementById("synthesisCandidatesButton");
    const metadataSearchInput = document.getElementById("metadataSearchInput");
    const metadataSearchButton = document.getElementById("metadataSearchButton");
    const metadataObjectInput = document.getElementById("metadataObjectInput");
    const metadataObjectButton = document.getElementById("metadataObjectButton");
    const draftIdInput = document.getElementById("draftIdInput");
    const draftDetailsButton = document.getElementById("draftDetailsButton");
    const draftTitleInput = document.getElementById("draftTitleInput");
    const draftExampleQuestionInput = document.getElementById("draftExampleQuestionInput");
    const draftDescriptionInput = document.getElementById("draftDescriptionInput");
    const draftSourceAliasInput = document.getElementById("draftSourceAliasInput");
    const draftSourceObjectInput = document.getElementById("draftSourceObjectInput");
    const draftGroupRoleInput = document.getElementById("draftGroupRoleInput");
    const draftGroupFieldInput = document.getElementById("draftGroupFieldInput");
    const draftMeasureRoleInput = document.getElementById("draftMeasureRoleInput");
    const draftMeasureFieldInput = document.getElementById("draftMeasureFieldInput");
    const draftMeasureLabelInput = document.getElementById("draftMeasureLabelInput");
    const draftAggregateSelect = document.getElementById("draftAggregateSelect");
    const draftFilterRoleInput = document.getElementById("draftFilterRoleInput");
    const draftFilterFieldInput = document.getElementById("draftFilterFieldInput");
    const draftFilterParameterInput = document.getElementById("draftFilterParameterInput");
    const draftFilterOperatorSelect = document.getElementById("draftFilterOperatorSelect");
    const draftLimitInput = document.getElementById("draftLimitInput");
    const draftFieldsConfirmedInput = document.getElementById("draftFieldsConfirmedInput");
    const draftJsonInput = document.getElementById("draftJsonInput");
    const createDraftButton = document.getElementById("createDraftButton");
    const previewDraftButton = document.getElementById("previewDraftButton");
    const smokeDraftButton = document.getElementById("smokeDraftButton");
    const publishDraftButton = document.getElementById("publishDraftButton");
    const approvalCommentInput = document.getElementById("approvalCommentInput");
    const smokeParamsInput = document.getElementById("smokeParamsInput");
    const approveDraftButton = document.getElementById("approveDraftButton");
    const rejectDraftButton = document.getElementById("rejectDraftButton");
    const candidateIdInput = document.getElementById("candidateIdInput");
    const candidateCreateDraftButton = document.getElementById("candidateCreateDraftButton");
    const candidateRejectButton = document.getElementById("candidateRejectButton");
    const synthesisCandidateIdInput = document.getElementById("synthesisCandidateIdInput");
    const synthesisCreateDraftButton = document.getElementById("synthesisCreateDraftButton");
    const synthesisRejectButton = document.getElementById("synthesisRejectButton");
    const synthesisIgnoreSimilarButton = document.getElementById("synthesisIgnoreSimilarButton");
    const skillLifecycleIdInput = document.getElementById("skillLifecycleIdInput");
    const skillLifecycleReasonInput = document.getElementById("skillLifecycleReasonInput");
    const skillRegressionCasesInput = document.getElementById("skillRegressionCasesInput");
    const skillLifecycleTargetStatus = document.getElementById("skillLifecycleTargetStatus");
    const skillSuccessfulRunsInput = document.getElementById("skillSuccessfulRunsInput");
    const skillAdminApprovalInput = document.getElementById("skillAdminApprovalInput");
    const skillDetailsButton = document.getElementById("skillDetailsButton");
    const skillPromoteButton = document.getElementById("skillPromoteButton");
    const skillRollbackButton = document.getElementById("skillRollbackButton");
    const skillDeprecateButton = document.getElementById("skillDeprecateButton");
    const skillBlockButton = document.getElementById("skillBlockButton");
    const regressionCasesPathInput = document.getElementById("regressionCasesPathInput");
    const regressionSessionPrefixInput = document.getElementById("regressionSessionPrefixInput");
    const runRegressionButton = document.getElementById("runRegressionButton");
    const workbenchSummary = document.getElementById("workbenchSummary");
    const workbenchText = document.getElementById("workbenchText");
    let pending = false;
    let onboardingPollTimer = null;
    const baseTitle = document.title;
    let unreadCount = 0;
    let titleBlinkTimer = null;
    let titleBlinkOn = false;
    let latestWorkbenchSmokeId = "";
    let documentationItems = [];

    const savedSessionId = localStorage.getItem(SESSION_STORAGE_KEY);
    if (savedSessionId) sessionId.value = savedSessionId;

    function effectiveSessionId() {
      return sessionId.value.trim() || "web-test";
    }

    function readLocalSessions() {
      try {
        const parsed = JSON.parse(localStorage.getItem(SESSION_LIST_STORAGE_KEY) || "[]");
        return Array.isArray(parsed) ? parsed.filter(item => item && item.session_id) : [];
      } catch (error) {
        return [];
      }
    }

    function writeLocalSessions(items) {
      localStorage.setItem(SESSION_LIST_STORAGE_KEY, JSON.stringify(items.slice(0, 30)));
    }

    function rememberSession(id, patch = {}) {
      const session = String(id || "").trim();
      if (!session) return;
      localStorage.setItem(SESSION_STORAGE_KEY, session);
      const now = new Date().toISOString();
      const items = readLocalSessions();
      const existingIndex = items.findIndex(item => item.session_id === session);
      const existing = existingIndex >= 0 ? items.splice(existingIndex, 1)[0] : {};
      items.unshift({
        session_id: session,
        updated_at: patch.updated_at || now,
        message_count: patch.message_count ?? existing.message_count ?? 0,
        preview: patch.preview || existing.preview || "",
        local: true
      });
      writeLocalSessions(items);
    }

    function mergeSessions(localItems, serverItems) {
      const byId = new Map();
      for (const item of localItems) {
        byId.set(item.session_id, {...item, local: true});
      }
      for (const item of serverItems) {
        if (!item || !item.session_id) continue;
        const existing = byId.get(item.session_id) || {};
        byId.set(item.session_id, {
          ...existing,
          ...item,
          local: Boolean(existing.local),
          server: true
        });
      }
      return Array.from(byId.values()).sort((left, right) => {
        return String(right.updated_at || "").localeCompare(String(left.updated_at || ""));
      });
    }

    function renderSessionList(items) {
      sessionList.replaceChildren();
      const active = effectiveSessionId();
      sessionListEmpty.style.display = items.length ? "none" : "block";
      for (const item of items) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "session-button" + (item.session_id === active ? " active" : "");
        const name = document.createElement("span");
        name.className = "session-name";
        name.textContent = item.session_id;
        const meta = document.createElement("span");
        meta.className = "session-meta";
        const count = Number(item.message_count || 0);
        const source = item.server ? "в памяти" : "локально";
        meta.textContent = count ? `${count} сообщ. · ${source}` : source;
        const preview = document.createElement("span");
        preview.className = "session-meta";
        preview.textContent = item.preview || "Нет сообщений в текущем процессе.";
        button.append(name, meta, preview);
        button.addEventListener("click", () => {
          sessionId.value = item.session_id;
          rememberSession(item.session_id);
          loadConversation();
        });
        sessionList.append(button);
      }
    }

    async function loadSessionList() {
      let serverSessions = [];
      try {
        const response = await fetch("/api/conversations", {cache: "no-store"});
        const data = await response.json();
        if (response.ok && data.ok && Array.isArray(data.sessions)) {
          serverSessions = data.sessions;
        }
      } catch (error) {
        serverSessions = [];
      }
      const localSessions = readLocalSessions();
      renderSessionList(mergeSessions(localSessions, serverSessions));
    }

    function clearEmpty() {
      const empty = messages.querySelector(".empty");
      if (empty) empty.remove();
    }

    function setStatus(text) {
      statusText.textContent = text;
    }

    function shouldMarkUnread() {
      return document.hidden || !document.hasFocus();
    }

    function startTitleBlink() {
      if (titleBlinkTimer) return;
      titleBlinkTimer = window.setInterval(() => {
        titleBlinkOn = !titleBlinkOn;
        document.title = titleBlinkOn ? `(${unreadCount}) Новое сообщение` : baseTitle;
      }, 900);
    }

    function markUnread() {
      unreadCount += 1;
      startTitleBlink();
    }

    function clearUnread() {
      unreadCount = 0;
      titleBlinkOn = false;
      if (titleBlinkTimer) {
        window.clearInterval(titleBlinkTimer);
        titleBlinkTimer = null;
      }
      document.title = baseTitle;
    }

    function appendMessage(kind, title, text, raw, scroll = true) {
      clearEmpty();
      const node = document.createElement("article");
      node.className = "message " + kind;
      const meta = document.createElement("div");
      meta.className = "meta";
      meta.textContent = title;
      const content = document.createElement("div");
      content.className = "content";
      content.textContent = text || "";
      node.append(meta, content);
      if (raw) {
        const details = document.createElement("details");
        const summary = document.createElement("summary");
        summary.textContent = "details";
        const pre = document.createElement("pre");
        pre.textContent = JSON.stringify(raw, null, 2);
        details.append(summary, pre);
        node.append(details);
      }
      messages.append(node);
      if (scroll) messages.scrollTop = messages.scrollHeight;
      if ((kind === "assistant" || kind === "error") && shouldMarkUnread()) {
        markUnread();
      }
    }

    function showEmpty(text) {
      messages.replaceChildren();
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = text;
      messages.append(empty);
    }

    async function loadVersion() {
      try {
        const response = await fetch("/api/version", {cache: "no-store"});
        const data = await response.json();
        appVersion.textContent = data.version || "unknown";
      } catch (error) {
        appVersion.textContent = "unknown";
      }
    }

    function renderOnboardingStatus(status) {
      const state = status && status.state ? status.state : "unknown";
      const trained = Boolean(status && status.trained);
      const running = Boolean(status && status.running);
      const message = status && status.message ? status.message : "Статус обучения неизвестен.";
      if (status && status.config_dump && !configDumpPath.value.trim()) {
        configDumpPath.value = status.config_dump;
      }
      startOnboardingButton.disabled = running;
      const details = [];
      details.push(message);
      if (status && status.objects_count) details.push("Объектов: " + status.objects_count);
      if (status && status.query_patterns_count) details.push("Шаблонов запросов: " + status.query_patterns_count);
      if (status && status.binding_candidates_count) details.push("Кандидатов binding: " + status.binding_candidates_count);
      if (status && status.error) details.push("Ошибка: " + status.error);
      onboardingStatus.textContent = details.join("\\n");

      trainingBanner.classList.add("visible");
      trainingBanner.classList.toggle("trained", trained);
      if (trained) {
        const objects = status && status.objects_count ? status.objects_count : 0;
        const patterns = status && status.query_patterns_count ? status.query_patterns_count : 0;
        trainingBanner.textContent = `Обучение выполнено: ${objects} объектов, ${patterns} шаблонов.`;
      } else if (running) {
        trainingBanner.textContent = "Идет первоначальное обучение. До завершения агент может отвечать медленнее и ошибаться в выборе объектов конфигурации.";
      } else {
        trainingBanner.textContent = "Первоначальное обучение еще не выполнено. Возможны неверные ответы: агент пока опирается только на MCP-поиск и текущий диалог.";
      }
      setStatus(running ? "обучение" : "готов");
      return {state, running};
    }

    async function loadOnboardingStatus() {
      try {
        const response = await fetch("/api/admin/onboarding/status", {cache: "no-store"});
        const data = await response.json();
        if (!response.ok || !data.ok) throw new Error(data.error || "HTTP " + response.status);
        const rendered = renderOnboardingStatus(data.status || {});
        if (rendered.running && !onboardingPollTimer) {
          onboardingPollTimer = window.setInterval(loadOnboardingStatus, 3000);
        }
        if (!rendered.running && onboardingPollTimer) {
          window.clearInterval(onboardingPollTimer);
          onboardingPollTimer = null;
        }
      } catch (error) {
        trainingBanner.classList.add("visible");
        trainingBanner.textContent = "Статус первоначального обучения не удалось загрузить.";
        onboardingStatus.textContent = String(error && error.message ? error.message : error);
      }
    }

    async function startOnboarding() {
      const path = configDumpPath.value.trim();
      if (!path) {
        onboardingStatus.textContent = "Укажите путь к файловой выгрузке конфигурации.";
        configDumpPath.focus();
        return;
      }
      startOnboardingButton.disabled = true;
      setStatus("запуск обучения");
      try {
        const response = await fetch("/api/admin/onboarding/run", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({config_dump: path})
        });
        const data = await response.json();
        if (!response.ok || !data.ok) throw new Error(data.error || "HTTP " + response.status);
        renderOnboardingStatus(data.status || {});
        if (!onboardingPollTimer) onboardingPollTimer = window.setInterval(loadOnboardingStatus, 3000);
      } catch (error) {
        onboardingStatus.textContent = String(error && error.message ? error.message : error);
        startOnboardingButton.disabled = false;
        setStatus("готов");
      }
    }

    function asDisplayText(value) {
      if (value === null || value === undefined || value === "") return "";
      if (Array.isArray(value)) return value.map(asDisplayText).filter(Boolean).join(", ");
      if (typeof value === "object") {
        if (value["Представление"]) return String(value["Представление"]);
        if (value.name) return String(value.name);
        if (value.full_name) return String(value.full_name);
        return JSON.stringify(value);
      }
      return String(value);
    }

    function appendWorkbenchHeading(text) {
      const heading = document.createElement("p");
      heading.className = "workbench-heading";
      heading.textContent = text;
      workbenchSummary.append(heading);
      return heading;
    }

    function createSummaryCard(title, subtitle = "") {
      const card = document.createElement("div");
      card.className = "summary-card";
      const titleNode = document.createElement("div");
      titleNode.className = "summary-card-title";
      titleNode.textContent = asDisplayText(title) || "Без названия";
      card.append(titleNode);
      if (subtitle) {
        const subtitleNode = document.createElement("div");
        subtitleNode.className = "summary-card-subtitle";
        subtitleNode.textContent = asDisplayText(subtitle);
        card.append(subtitleNode);
      }
      return card;
    }

    function appendSummaryLine(card, label, value) {
      const text = asDisplayText(value);
      if (!text) return;
      const row = document.createElement("div");
      row.className = "summary-line";
      const labelNode = document.createElement("span");
      labelNode.className = "summary-label";
      labelNode.textContent = label;
      const valueNode = document.createElement("span");
      valueNode.textContent = text;
      row.append(labelNode, valueNode);
      card.append(row);
    }

    function appendSummaryTags(card, label, values) {
      const items = Array.isArray(values) ? values.map(asDisplayText).filter(Boolean) : splitCommaSeparated(values);
      if (!items.length) return;
      const row = document.createElement("div");
      row.className = "summary-line";
      const labelNode = document.createElement("span");
      labelNode.className = "summary-label";
      labelNode.textContent = label;
      const tags = document.createElement("span");
      tags.className = "summary-tags";
      items.slice(0, 12).forEach(item => {
        const tag = document.createElement("span");
        tag.className = "summary-tag";
        tag.textContent = item;
        tags.append(tag);
      });
      if (items.length > 12) {
        const extra = document.createElement("span");
        extra.className = "summary-tag";
        extra.textContent = "+" + String(items.length - 12);
        tags.append(extra);
      }
      row.append(labelNode, tags);
      card.append(row);
    }

    function renderSummaryList(title, items, renderer, emptyText = "Нет данных.") {
      appendWorkbenchHeading(title);
      if (!Array.isArray(items) || !items.length) {
        const card = createSummaryCard(emptyText);
        workbenchSummary.append(card);
        return;
      }
      items.slice(0, 20).forEach(item => workbenchSummary.append(renderer(item)));
      if (items.length > 20) {
        const card = createSummaryCard("Показаны первые 20 элементов", "Полный список доступен в JSON ниже.");
        workbenchSummary.append(card);
      }
    }

    function renderSkillCard(skill) {
      const card = createSummaryCard(skill.title || skill.skill_id, skill.description || skill.skill_id);
      appendSummaryLine(card, "Статус", skill.status);
      appendSummaryLine(card, "Источник", skill.source || skill.source_kind);
      appendSummaryLine(card, "Тип", skill.kind);
      appendSummaryTags(card, "Outputs", skill.outputs);
      appendSummaryTags(card, "Filters", skill.supported_filter_roles);
      appendSummaryLine(card, "Path", skill.source_path);
      return card;
    }

    function renderDraftCard(draft) {
      const card = createSummaryCard(draft.title || draft.draft_id, draft.description || draft.draft_id);
      appendSummaryLine(card, "Статус", draft.status);
      appendSummaryLine(card, "Источник", draft.source_kind || draft.source);
      appendSummaryTags(card, "Вопросы", draft.example_questions);
      appendSummaryTags(card, "Объекты", (draft.data_sources || []).map(item => item.object_full_name || item.full_name || item.object));
      appendSummaryTags(card, "Поля", (draft.field_mappings || []).map(item => `${item.role || "field"}: ${item.object_full_name || ""}.${item.field_name || ""}`));
      return card;
    }

    function renderCandidateCard(candidate) {
      const card = createSummaryCard(candidate.title || candidate.candidate_id, candidate.question || candidate.source_question || candidate.type);
      appendSummaryLine(card, "Статус", candidate.status);
      appendSummaryLine(card, "Тип", candidate.type || candidate.candidate_type);
      appendSummaryLine(card, "Role", candidate.semantic_role || candidate.role);
      appendSummaryLine(card, "Объект", candidate.object_full_name || candidate.object || candidate.metadata_object);
      appendSummaryLine(card, "Confidence", candidate.confidence);
      appendSummaryTags(card, "Evidence", candidate.evidence);
      return card;
    }

    function renderMetadataObjectCard(object) {
      const card = createSummaryCard(object.full_name || object.name, object.synonym || object.kind);
      appendSummaryLine(card, "Тип", object.kind || object.object_kind);
      appendSummaryLine(card, "Trust", object.trust || object.source);
      const actionRow = document.createElement("div");
      actionRow.className = "summary-action-row";
      const sourceButton = document.createElement("button");
      sourceButton.className = "summary-action";
      sourceButton.type = "button";
      sourceButton.textContent = "Use as source";
      sourceButton.addEventListener("click", () => applyMetadataSource(object.full_name || object.name || ""));
      actionRow.append(sourceButton);
      card.append(actionRow);
      appendSummaryTags(card, "Fields", (object.fields || []).map(item => `${item.name || ""}${item.category ? " (" + item.category + ")" : ""}`));
      appendSummaryTags(card, "Hints", (object.field_hints || []).map(item => item.name || item.field_name));
      appendMetadataFieldPicker(card, object);
      return card;
    }

    function appendMetadataFieldPicker(card, object) {
      const fields = Array.isArray(object.all_fields) ? object.all_fields : (Array.isArray(object.fields) ? object.fields : []);
      if (!fields.length) return;
      const picker = document.createElement("div");
      picker.className = "field-picker";
      fields.slice(0, 20).forEach(field => {
        const fieldName = field && field.name ? String(field.name) : "";
        if (!fieldName) return;
        const row = document.createElement("div");
        row.className = "field-picker-row";
        const caption = document.createElement("div");
        caption.className = "summary-card-subtitle";
        const flags = [];
        if (field.category) flags.push(field.category);
        if (field.type) flags.push(field.type);
        if (field.confirmed === false) flags.push("hint");
        caption.textContent = flags.length ? `${fieldName} - ${flags.join(", ")}` : fieldName;
        const actions = document.createElement("div");
        actions.className = "summary-action-row";
        [
          ["group", "Group"],
          ["measure", "Metric"],
          ["filter", "Filter"]
        ].forEach(([target, label]) => {
          const button = document.createElement("button");
          button.className = "summary-action";
          button.type = "button";
          button.textContent = label;
          button.addEventListener("click", () => applyMetadataField(object.full_name || object.name || "", fieldName, target));
          actions.append(button);
        });
        row.append(caption, actions);
        picker.append(row);
      });
      if (fields.length > 20) {
        const note = document.createElement("div");
        note.className = "summary-card-subtitle";
        note.textContent = "Показаны первые 20 полей. Полный список доступен в JSON ниже.";
        picker.append(note);
      }
      card.append(picker);
    }

    function renderLifecycleCard(lifecycle) {
      const skill = lifecycle.skill || {};
      const card = createSummaryCard(skill.title || skill.skill_id || "Lifecycle result");
      appendSummaryLine(card, "Before", lifecycle.before_status);
      appendSummaryLine(card, "After", lifecycle.after_status);
      appendSummaryLine(card, "OK", lifecycle.ok);
      appendSummaryTags(card, "Issues", (lifecycle.issues || []).map(item => item.message || item.code || item));
      return card;
    }

    function renderRegressionCard(regression, path) {
      const card = createSummaryCard("Regression replay", path || regression.run_id);
      appendSummaryLine(card, "OK", regression.ok);
      appendSummaryLine(card, "Всего", regression.count);
      appendSummaryLine(card, "Passed", regression.passed);
      appendSummaryLine(card, "Failed", regression.failed);
      appendSummaryTags(card, "Cases", (regression.results || []).map(item => `${item.case_id || "case"}: ${item.ok ? "ok" : "failed"}`));
      return card;
    }

    function renderWorkbenchSummary(payload) {
      workbenchSummary.replaceChildren();
      if (!payload || typeof payload !== "object") return;
      if (Array.isArray(payload.skills)) {
        if (payload.skills[0] && payload.skills[0].skill_id && !skillLifecycleIdInput.value.trim()) {
          skillLifecycleIdInput.value = payload.skills[0].skill_id;
        }
        renderSummaryList("Навыки", payload.skills, renderSkillCard);
      }
      if (payload.skill) {
        if (payload.skill.skill_id) skillLifecycleIdInput.value = payload.skill.skill_id;
        renderSummaryList("Карточка навыка", [payload.skill], renderSkillCard);
      }
      if (Array.isArray(payload.drafts)) {
        renderSummaryList("Черновики", payload.drafts, renderDraftCard);
      }
      if (payload.draft) {
        if (payload.draft.draft_id) draftIdInput.value = payload.draft.draft_id;
        renderSummaryList("Карточка draft", [payload.draft], renderDraftCard);
      }
      if (Array.isArray(payload.candidates)) {
        renderSummaryList("Кандидаты", payload.candidates, renderCandidateCard);
      }
      if (Array.isArray(payload.objects)) {
        if (payload.objects[0] && payload.objects[0].full_name && !metadataObjectInput.value.trim()) {
          metadataObjectInput.value = payload.objects[0].full_name;
        }
        renderSummaryList("Метаданные", payload.objects, renderMetadataObjectCard);
      }
      if (payload.object) {
        if (payload.object.full_name) metadataObjectInput.value = payload.object.full_name;
        renderSummaryList("Карточка объекта", [payload.object], renderMetadataObjectCard);
      }
      if (payload.lifecycle) {
        renderSummaryList("Lifecycle", [payload.lifecycle], renderLifecycleCard);
      }
      if (payload.regression) {
        renderSummaryList("Regression replay", [payload.regression], item => renderRegressionCard(item, payload.path));
      }
      if (!workbenchSummary.children.length) {
        appendWorkbenchHeading("Технический результат");
        workbenchSummary.append(createSummaryCard("Сводка недоступна для этого типа ответа", "Полный JSON показан ниже."));
      }
    }

    function showWorkbench(payload) {
      renderWorkbenchSummary(payload);
      workbenchText.textContent = JSON.stringify(payload, null, 2);
    }

    function applyMetadataSource(fullName) {
      const value = String(fullName || "").trim();
      if (!value) return;
      draftSourceObjectInput.value = value;
      if (!draftSourceAliasInput.value.trim()) draftSourceAliasInput.value = "Источник";
      workbenchText.textContent = "Источник 1С подставлен в draft builder: " + value;
    }

    function applyMetadataField(fullName, fieldName, target) {
      applyMetadataSource(fullName);
      const field = String(fieldName || "").trim();
      if (!field) return;
      if (target === "group") {
        draftGroupFieldInput.value = field;
        if (!draftGroupRoleInput.value.trim()) draftGroupRoleInput.value = field;
      } else if (target === "measure") {
        draftMeasureFieldInput.value = field;
        if (!draftMeasureRoleInput.value.trim()) draftMeasureRoleInput.value = field;
        if (!draftMeasureLabelInput.value.trim()) draftMeasureLabelInput.value = field;
      } else if (target === "filter") {
        draftFilterFieldInput.value = field;
        if (!draftFilterRoleInput.value.trim()) draftFilterRoleInput.value = field;
        if (!draftFilterParameterInput.value.trim()) draftFilterParameterInput.value = field;
      }
      workbenchText.textContent = "Поле подставлено в draft builder: " + field + " -> " + target;
    }

    async function loadSkillCatalog() {
      workbenchText.textContent = "Загрузка каталога навыков...";
      try {
        const response = await fetch("/api/admin/skills/catalog", {cache: "no-store"});
        const data = await response.json();
        showWorkbench(data);
      } catch (error) {
        workbenchText.textContent = "Не удалось загрузить каталог навыков: " + String(error.message || error);
      }
    }

    async function loadSkillDetails() {
      const skillId = skillLifecycleIdInput.value.trim();
      if (!skillId) {
        skillLifecycleIdInput.focus();
        return;
      }
      workbenchText.textContent = "Загрузка карточки навыка...";
      try {
        const response = await fetch(`/api/admin/skills/catalog/${encodeURIComponent(skillId)}`, {cache: "no-store"});
        showWorkbench(await response.json());
      } catch (error) {
        workbenchText.textContent = "Не удалось загрузить карточку навыка: " + String(error.message || error);
      }
    }

    async function loadDraftList() {
      workbenchText.textContent = "Загрузка черновиков...";
      try {
        const response = await fetch("/api/admin/workbench/drafts", {cache: "no-store"});
        const data = await response.json();
        if (data.ok && Array.isArray(data.drafts) && data.drafts[0]) {
          draftIdInput.value = data.drafts[0].draft_id || draftIdInput.value;
        }
        showWorkbench(data);
      } catch (error) {
        workbenchText.textContent = "Не удалось загрузить черновики: " + String(error.message || error);
      }
    }

    async function loadDraftDetails() {
      const draftId = draftIdInput.value.trim();
      if (!draftId) {
        draftIdInput.focus();
        return;
      }
      workbenchText.textContent = "Загрузка карточки draft...";
      try {
        const response = await fetch(`/api/admin/workbench/drafts/${encodeURIComponent(draftId)}`, {cache: "no-store"});
        showWorkbench(await response.json());
      } catch (error) {
        workbenchText.textContent = "Не удалось загрузить карточку draft: " + String(error.message || error);
      }
    }

    async function loadOnboardingCandidates() {
      workbenchText.textContent = "Загрузка onboarding candidates...";
      try {
        const response = await fetch("/api/admin/workbench/onboarding/candidates", {cache: "no-store"});
        const data = await response.json();
        if (data.ok && Array.isArray(data.candidates) && data.candidates[0]) {
          candidateIdInput.value = data.candidates[0].candidate_id || candidateIdInput.value;
        }
        showWorkbench(data);
      } catch (error) {
        workbenchText.textContent = "Не удалось загрузить onboarding candidates: " + String(error.message || error);
      }
    }

    async function loadSynthesisCandidates() {
      workbenchText.textContent = "Загрузка agent candidates...";
      try {
        const response = await fetch("/api/admin/workbench/synthesis/candidates", {cache: "no-store"});
        const data = await response.json();
        if (data.ok && Array.isArray(data.candidates) && data.candidates[0]) {
          synthesisCandidateIdInput.value = data.candidates[0].candidate_id || synthesisCandidateIdInput.value;
        }
        showWorkbench(data);
      } catch (error) {
        workbenchText.textContent = "Не удалось загрузить agent candidates: " + String(error.message || error);
      }
    }

    async function searchMetadata() {
      const term = metadataSearchInput.value.trim();
      if (!term) {
        metadataSearchInput.focus();
        return;
      }
      workbenchText.textContent = "Поиск метаданных...";
      try {
        const response = await fetch("/api/admin/metadata/search?q=" + encodeURIComponent(term), {cache: "no-store"});
        showWorkbench(await response.json());
      } catch (error) {
        workbenchText.textContent = "Не удалось выполнить поиск: " + String(error.message || error);
      }
    }

    async function loadMetadataObject() {
      const fullName = metadataObjectInput.value.trim();
      if (!fullName) {
        metadataObjectInput.focus();
        return;
      }
      workbenchText.textContent = "Загрузка объекта метаданных...";
      try {
        const response = await fetch("/api/admin/metadata/object?full_name=" + encodeURIComponent(fullName), {cache: "no-store"});
        showWorkbench(await response.json());
      } catch (error) {
        workbenchText.textContent = "Не удалось загрузить объект метаданных: " + String(error.message || error);
      }
    }

    function buildTopMetricDraftFromForm() {
      const sourceObject = draftSourceObjectInput.value.trim();
      const groupField = draftGroupFieldInput.value.trim();
      const measureField = draftMeasureFieldInput.value.trim();
      if (!sourceObject && !groupField && !measureField) return null;
      if (!sourceObject || !groupField || !measureField) {
        throw new Error("Для конструктора draft укажите источник 1С, поле группировки и поле метрики.");
      }
      const title = draftTitleInput.value.trim() || draftExampleQuestionInput.value.trim();
      if (!title) throw new Error("Укажите название draft или пример вопроса.");
      const alias = draftSourceAliasInput.value.trim() || "Источник";
      const groupRole = draftGroupRoleInput.value.trim() || "dimension";
      const measureRole = draftMeasureRoleInput.value.trim() || "metric";
      const measureLabel = draftMeasureLabelInput.value.trim() || measureRole;
      const filterRole = draftFilterRoleInput.value.trim();
      const filterField = draftFilterFieldInput.value.trim();
      const filterParameter = draftFilterParameterInput.value.trim() || filterRole;
      const limit = Number.parseInt(draftLimitInput.value, 10);
      const confirmed = draftFieldsConfirmedInput.checked;
      const fieldMappings = [
        {
          role: groupRole,
          source_alias: alias,
          field_name: groupField,
          required: true,
          confirmed
        },
        {
          role: measureRole,
          source_alias: alias,
          field_name: measureField,
          required: true,
          confirmed
        }
      ];
      const filters = [];
      if (filterRole || filterField) {
        if (!filterRole || !filterField) {
          throw new Error("Для фильтра укажите role и field.");
        }
        fieldMappings.push({
          role: filterRole,
          source_alias: alias,
          field_name: filterField,
          required: false,
          confirmed
        });
        filters.push({
          role: filterRole,
          operator: draftFilterOperatorSelect.value || "equals",
          value_source: "input",
          parameter: filterParameter || filterRole,
          required: false
        });
      }
      return {
        title,
        description: draftDescriptionInput.value.trim(),
        status: "draft",
        example_questions: [draftExampleQuestionInput.value.trim() || title],
        business_entities: [groupRole, measureRole].concat(filterRole ? [filterRole] : []),
        data_sources: [
          {
            alias,
            object_name: sourceObject,
            object_kind: "",
            purpose: "primary",
            trust: confirmed ? "verified" : "manual",
            evidence: [
              {
                source: "workbench_ui",
                reference: "manual_top_n_by_metric_form",
                trust: confirmed ? "verified" : "manual"
              }
            ]
          }
        ],
        field_mappings: fieldMappings,
        calculation: {
          kind: "top_n_by_metric",
          source_alias: alias,
          filters,
          group_by: [groupRole],
          measures: [
            {
              role: measureRole,
              expression: measureRole,
              aggregate: draftAggregateSelect.value || "sum",
              label: measureLabel
            }
          ],
          sort: [{field: measureLabel, direction: "desc"}],
          limit: Number.isFinite(limit) && limit > 0 ? Math.min(limit, 100) : 10
        },
        presentation: {
          columns: [groupRole, measureLabel],
          answer_template: "",
          empty_result_text: "Данных не найдено.",
          notes: ""
        },
        tags: ["workbench_ui", "top_n_by_metric"],
        notes: "",
        source_kind: "manual"
      };
    }

    function draftPayloadFromForm() {
      const raw = draftJsonInput.value.trim();
      if (raw) return JSON.parse(raw);
      const builtDraft = buildTopMetricDraftFromForm();
      if (builtDraft) return builtDraft;
      const title = draftTitleInput.value.trim();
      if (!title) throw new Error("Укажите название draft или JSON.");
      return {
        title,
        description: draftDescriptionInput.value.trim(),
        example_questions: [draftExampleQuestionInput.value.trim() || title],
        source_kind: "manual"
      };
    }

    function smokeParamsPayload() {
      const raw = smokeParamsInput.value.trim();
      if (!raw) return {};
      const parsed = JSON.parse(raw);
      if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") throw new Error("Smoke params JSON должен быть объектом.");
      return parsed;
    }

    async function createWorkbenchDraft() {
      try {
        const response = await fetch("/api/admin/workbench/drafts", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({actor: "web-admin", draft: draftPayloadFromForm()})
        });
        const data = await response.json();
        if (data.ok && data.draft && data.draft.draft_id) draftIdInput.value = data.draft.draft_id;
        showWorkbench(data);
      } catch (error) {
        workbenchText.textContent = "Не удалось создать draft: " + String(error.message || error);
      }
    }

    async function postDraftAction(action, extra = {}) {
      const draftId = draftIdInput.value.trim();
      if (!draftId) {
        draftIdInput.focus();
        return;
      }
      try {
        const response = await fetch(`/api/admin/workbench/drafts/${encodeURIComponent(draftId)}/${action}`, {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({actor: "web-admin", ...extra})
        });
        const data = await response.json();
        if (action === "smoke" && data.smoke && data.smoke.ok && data.smoke.smoke_id) {
          latestWorkbenchSmokeId = data.smoke.smoke_id;
        }
        showWorkbench(data);
      } catch (error) {
        workbenchText.textContent = "Действие Workbench не выполнено: " + String(error.message || error);
      }
    }

    async function postCandidateAction(action) {
      const candidateId = candidateIdInput.value.trim();
      if (!candidateId) {
        candidateIdInput.focus();
        return;
      }
      try {
        const response = await fetch(`/api/admin/workbench/onboarding/candidates/${encodeURIComponent(candidateId)}/${action}`, {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({actor: "web-admin", comment: approvalCommentInput.value.trim()})
        });
        const data = await response.json();
        if (data.ok && data.draft && data.draft.draft_id) draftIdInput.value = data.draft.draft_id;
        showWorkbench(data);
      } catch (error) {
        workbenchText.textContent = "Действие onboarding candidate не выполнено: " + String(error.message || error);
      }
    }

    async function postSynthesisCandidateAction(action) {
      const candidateId = synthesisCandidateIdInput.value.trim();
      if (!candidateId) {
        synthesisCandidateIdInput.focus();
        return;
      }
      try {
        const response = await fetch(`/api/admin/workbench/synthesis/candidates/${encodeURIComponent(candidateId)}/${action}`, {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({actor: "web-admin", comment: approvalCommentInput.value.trim()})
        });
        const data = await response.json();
        if (data.ok && data.draft && data.draft.draft_id) draftIdInput.value = data.draft.draft_id;
        showWorkbench(data);
      } catch (error) {
        workbenchText.textContent = "Действие agent candidate не выполнено: " + String(error.message || error);
      }
    }

    function splitCommaSeparated(value) {
      return String(value || "")
        .split(",")
        .map(item => item.trim())
        .filter(Boolean);
    }

    function skillLifecyclePayload() {
      const targetStatus = skillLifecycleTargetStatus.value.trim();
      const successfulRuns = Number.parseInt(skillSuccessfulRunsInput.value, 10);
      const payload = {
        actor: "web-admin",
        reason: skillLifecycleReasonInput.value.trim()
      };
      if (targetStatus) payload.target_status = targetStatus;
      const regressionCaseIds = splitCommaSeparated(skillRegressionCasesInput.value);
      if (regressionCaseIds.length) payload.regression_case_ids = regressionCaseIds;
      if (Number.isFinite(successfulRuns) && successfulRuns > 0) payload.successful_runs = successfulRuns;
      if (skillAdminApprovalInput.checked) payload.admin_approval = true;
      return payload;
    }

    async function postSkillLifecycleAction(action) {
      const skillId = skillLifecycleIdInput.value.trim();
      if (!skillId) {
        skillLifecycleIdInput.focus();
        return;
      }
      workbenchText.textContent = "Выполняется lifecycle action...";
      try {
        const response = await fetch(`/api/admin/skills/${encodeURIComponent(skillId)}/${action}`, {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify(skillLifecyclePayload())
        });
        showWorkbench(await response.json());
      } catch (error) {
        workbenchText.textContent = "Lifecycle action не выполнен: " + String(error.message || error);
      }
    }

    async function runRegressionReplay() {
      const cases = regressionCasesPathInput.value.trim();
      const sessionPrefix = regressionSessionPrefixInput.value.trim() || "web-regression";
      const payload = {actor: "web-admin", session_prefix: sessionPrefix};
      if (cases) payload.cases = cases;
      workbenchText.textContent = "Запуск regression replay...";
      try {
        const response = await fetch("/api/admin/regression/run", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify(payload)
        });
        showWorkbench(await response.json());
      } catch (error) {
        workbenchText.textContent = "Regression replay не выполнен: " + String(error.message || error);
      }
    }

    async function loadConversation() {
      const currentId = effectiveSessionId();
      rememberSession(currentId);
      setStatus("загрузка истории");
      try {
        const response = await fetch("/api/conversation?session_id=" + encodeURIComponent(currentId), {
          cache: "no-store"
        });
        const data = await response.json();
        if (!response.ok || !data.ok) {
          showEmpty("Историю сессии не удалось загрузить.");
          return;
        }
        messages.replaceChildren();
        const items = Array.isArray(data.messages) ? data.messages : [];
        if (!items.length) {
          showEmpty("Добрый день. Задайте вопрос по WIICON или WIIC.");
          rememberSession(currentId, {message_count: 0, preview: ""});
          await loadSessionList();
          return;
        }
        for (const item of items) {
          const role = item.role || "assistant";
          appendMessage(
            role === "user" ? "user" : "assistant",
            role === "user" ? "Вы" : "Агент",
            item.content || "",
            null,
            false
          );
        }
        const latest = items[items.length - 1] || {};
        rememberSession(currentId, {
          message_count: items.length,
          preview: latest.content || "",
          updated_at: latest.ts || new Date().toISOString()
        });
        await loadSessionList();
        messages.scrollTop = messages.scrollHeight;
      } catch (error) {
        showEmpty("Историю сессии не удалось загрузить.");
        await loadSessionList();
      } finally {
        setStatus("готов");
      }
    }

    async function showHistory(kind) {
      const title = kind === "backend" ? "Backend history.txt" : "Frontend history.txt";
      const url = kind === "backend" ? "/history/backend" : "/history/frontend";
      historyPanel.classList.add("visible");
      historyTitle.textContent = title;
      historyText.textContent = "Загрузка...";
      try {
        const response = await fetch(url, {cache: "no-store"});
        historyText.textContent = await response.text();
      } catch (error) {
        historyText.textContent = "Не удалось загрузить историю изменений.";
      }
    }

    async function loadDocumentationIndex(openDefault = false) {
      docsStatus.textContent = "Загрузка документации...";
      try {
        const response = await fetch("/api/docs", {cache: "no-store"});
        const data = await response.json();
        documentationItems = Array.isArray(data.docs) ? data.docs : [];
        renderDocumentationSelect();
        docsStatus.textContent = documentationItems.length
          ? "Доступно документов: " + documentationItems.length
          : "Документация не найдена.";
        if (openDefault && documentationItems.length) {
          selectPreferredDocumentation();
          await openSelectedDocumentation();
        }
      } catch (error) {
        docsStatus.textContent = "Не удалось загрузить список документации.";
      }
    }

    function renderDocumentationSelect() {
      docsSelect.replaceChildren();
      for (const item of documentationItems) {
        const option = document.createElement("option");
        option.value = item.path || "";
        option.textContent = `${item.section || "Документация"} - ${item.title || item.path}`;
        docsSelect.append(option);
      }
    }

    function selectPreferredDocumentation() {
      const preferred = [
        "docs/workbench/user_guide.md",
        "docs/workbench/overview.md",
        "docs/workbench/creating_top_stock_skill.md",
        "docs/project_overview.md"
      ];
      const found = preferred.find(path => documentationItems.some(item => item.path === path));
      if (found) docsSelect.value = found;
    }

    async function openSelectedDocumentation() {
      if (!documentationItems.length) {
        await loadDocumentationIndex(false);
      }
      const path = docsSelect.value;
      if (!path) {
        docsStatus.textContent = "Выберите документ.";
        return;
      }
      docsStatus.textContent = "Загрузка документа...";
      try {
        const response = await fetch("/api/docs/content?path=" + encodeURIComponent(path), {cache: "no-store"});
        const data = await response.json();
        if (!data.ok) {
          docsStatus.textContent = "Документ не найден.";
          return;
        }
        renderDocumentation(data.doc || {}, data.content || "");
        docsStatus.textContent = "Открыт документ: " + ((data.doc && data.doc.path) || path);
      } catch (error) {
        docsStatus.textContent = "Не удалось загрузить документ.";
      }
    }

    function renderDocumentation(doc, content) {
      docsViewer.classList.add("visible");
      docsTitle.textContent = doc.title || doc.path || "Документация";
      docsMeta.textContent = `${doc.section || "Документация"} · ${doc.path || ""}`;
      renderMarkdownContent(docsContent, content);
    }

    function renderMarkdownContent(container, content) {
      container.replaceChildren();
      let list = null;
      let codeBlock = null;
      const closeList = () => { list = null; };
      for (const rawLine of String(content || "").split("\n")) {
        const line = rawLine.replace(/\s+$/, "");
        if (line.startsWith("```")) {
          closeList();
          if (codeBlock) {
            codeBlock = null;
          } else {
            codeBlock = document.createElement("pre");
            container.append(codeBlock);
          }
          continue;
        }
        if (codeBlock) {
          codeBlock.textContent += (codeBlock.textContent ? "\n" : "") + line;
          continue;
        }
        const trimmed = line.trim();
        if (!trimmed) {
          closeList();
          continue;
        }
        if (trimmed.startsWith("### ")) {
          closeList();
          const heading = document.createElement("h3");
          heading.textContent = trimmed.slice(4);
          container.append(heading);
          continue;
        }
        if (trimmed.startsWith("## ") || trimmed.startsWith("# ")) {
          closeList();
          const heading = document.createElement("h2");
          heading.textContent = trimmed.replace(/^#+\s*/, "");
          container.append(heading);
          continue;
        }
        if (trimmed.startsWith("- ")) {
          if (!list) {
            list = document.createElement("ul");
            container.append(list);
          }
          const item = document.createElement("li");
          item.textContent = trimmed.slice(2);
          list.append(item);
          continue;
        }
        closeList();
        const paragraph = document.createElement("p");
        paragraph.textContent = trimmed;
        container.append(paragraph);
      }
    }

    function payloadProductRef() {
      const value = productRef.value.trim();
      if (!value) return undefined;
      if (value.startsWith("{")) return JSON.parse(value);
      return value;
    }

    function createNewSession() {
      const suffix = Date.now().toString(36);
      sessionId.value = "web-" + suffix;
      rememberSession(effectiveSessionId(), {message_count: 0, preview: ""});
      showEmpty("Новая сессия создана. Задайте вопрос по WIICON или WIIC.");
      loadSessionList();
      input.focus();
    }

    input.addEventListener("keydown", (event) => {
      if (event.isComposing) return;
      if (event.key !== "Enter" || event.shiftKey || event.ctrlKey || event.altKey || event.metaKey) return;
      event.preventDefault();
      if (pending) return;
      form.requestSubmit();
    });

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (pending) return;
      const message = input.value.trim();
      if (!message) return;
      const currentId = effectiveSessionId();
      rememberSession(currentId, {preview: message});
      appendMessage("user", "Вы", message);
      input.value = "";
      pending = true;
      sendButton.disabled = true;
      setStatus("выполняется");
      try {
        const payload = {
          session_id: currentId,
          message
        };
        const ref = payloadProductRef();
        if (ref !== undefined) payload.product_ref = ref;
        const response = await fetch("/chat", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify(payload)
        });
        const data = await response.json();
        if (!response.ok || !data.ok) {
          appendMessage("error", "Ошибка", data.error || "HTTP " + response.status, data);
          rememberSession(currentId, {preview: data.error || "Ошибка"});
        } else {
          appendMessage("assistant", data.result.source || "agent", data.result.message, data.result);
          rememberSession(currentId, {preview: data.result.message || message});
        }
      } catch (error) {
        appendMessage("error", "Ошибка", String(error && error.message ? error.message : error));
        rememberSession(currentId, {preview: String(error && error.message ? error.message : error)});
      } finally {
        pending = false;
        sendButton.disabled = false;
        setStatus("готов");
        loadSessionList();
        input.focus();
      }
    });

    newSessionButton.addEventListener("click", createNewSession);
    reloadHistoryButton.addEventListener("click", () => loadConversation());
    backendHistoryButton.addEventListener("click", () => showHistory("backend"));
    frontendHistoryButton.addEventListener("click", () => showHistory("frontend"));
    docsRefreshButton.addEventListener("click", () => loadDocumentationIndex(false));
    docsOpenButton.addEventListener("click", () => openSelectedDocumentation());
    docsSelect.addEventListener("change", () => openSelectedDocumentation());
    docsOpenSkillsButton.addEventListener("click", () => loadSkillCatalog());
    docsOpenDraftsButton.addEventListener("click", () => loadDraftList());
    docsOpenCandidatesButton.addEventListener("click", () => loadSynthesisCandidates());
    docsFocusMetadataButton.addEventListener("click", () => {
      metadataSearchInput.focus();
      workbenchText.textContent = "Введите объект или термин 1С в поле поиска метаданных, затем нажмите «Искать метаданные».";
    });
    startOnboardingButton.addEventListener("click", () => startOnboarding());
    skillCatalogButton.addEventListener("click", () => loadSkillCatalog());
    skillDetailsButton.addEventListener("click", () => loadSkillDetails());
    draftListButton.addEventListener("click", () => loadDraftList());
    draftDetailsButton.addEventListener("click", () => loadDraftDetails());
    onboardingCandidatesButton.addEventListener("click", () => loadOnboardingCandidates());
    synthesisCandidatesButton.addEventListener("click", () => loadSynthesisCandidates());
    metadataSearchButton.addEventListener("click", () => searchMetadata());
    metadataObjectButton.addEventListener("click", () => loadMetadataObject());
    createDraftButton.addEventListener("click", () => createWorkbenchDraft());
    previewDraftButton.addEventListener("click", () => postDraftAction("preview"));
    smokeDraftButton.addEventListener("click", () => {
      try {
        postDraftAction("smoke", {params: smokeParamsPayload()});
      } catch (error) {
        workbenchText.textContent = "Smoke params JSON не прочитан: " + String(error.message || error);
      }
    });
    approveDraftButton.addEventListener("click", () => postDraftAction("approve", {
      comment: approvalCommentInput.value.trim(),
      smoke_id: latestWorkbenchSmokeId
    }));
    rejectDraftButton.addEventListener("click", () => postDraftAction("reject", {
      comment: approvalCommentInput.value.trim()
    }));
    candidateCreateDraftButton.addEventListener("click", () => postCandidateAction("create-draft"));
    candidateRejectButton.addEventListener("click", () => postCandidateAction("reject"));
    synthesisCreateDraftButton.addEventListener("click", () => postSynthesisCandidateAction("create-draft"));
    synthesisRejectButton.addEventListener("click", () => postSynthesisCandidateAction("reject"));
    synthesisIgnoreSimilarButton.addEventListener("click", () => postSynthesisCandidateAction("ignore-similar"));
    publishDraftButton.addEventListener("click", () => postDraftAction("publish-candidate", {
      approve: true,
      comment: approvalCommentInput.value.trim(),
      smoke_id: latestWorkbenchSmokeId,
      override_previous_rejection: false
    }));
    skillPromoteButton.addEventListener("click", () => postSkillLifecycleAction("promote"));
    skillRollbackButton.addEventListener("click", () => postSkillLifecycleAction("rollback"));
    skillDeprecateButton.addEventListener("click", () => postSkillLifecycleAction("deprecate"));
    skillBlockButton.addEventListener("click", () => postSkillLifecycleAction("block"));
    runRegressionButton.addEventListener("click", () => runRegressionReplay());
    sessionId.addEventListener("change", () => loadConversation());
    sessionId.addEventListener("blur", () => {
      rememberSession(effectiveSessionId());
      loadSessionList();
    });
    window.addEventListener("focus", clearUnread);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) clearUnread();
    });

    loadVersion();
    loadDocumentationIndex(true);
    loadOnboardingStatus();
    rememberSession(effectiveSessionId());
    loadSessionList();
    loadConversation();
  </script>
</body>
</html>
"""
