(function () {
  "use strict";

  const ADMIN_TOKEN_STORAGE_KEY = "wiicon5.adminToken";

  class ApiError extends Error {
    constructor(message, details) {
      super(message);
      this.name = "ApiError";
      this.details = details || {};
    }
  }

  const ERROR_MESSAGES = {
    actor_required: "Не указан исполнитель действия.",
    approval_comment_required: "Заполните комментарий: что проверено человеком и почему действие можно выполнить.",
    current_successful_smoke_required: "Перед утверждением или публикацией запустите успешную проверку черновика. Если черновик менялся после проверки, запустите проверку заново.",
    draft_not_found: "Черновик не найден. Обновите список черновиков и откройте нужную карточку снова.",
    missing_admin_approval: "Для этого изменения нужно явное подтверждение администратора.",
    missing_human_approval: "Для этого действия требуется утверждение человеком.",
    missing_regression_case: "Перед повышением статуса нужен связанный регрессионный сценарий.",
    missing_successful_regression_replay: "Перед повышением статуса нужно успешно прогнать регрессионные проверки.",
    previous_approval_rejected: "Последнее решение по черновику было отклоняющим. Для публикации нужен новый успешный цикл проверки.",
    preview_failed: "Предпросмотр запроса не прошел проверку. Исправьте черновик и повторите предпросмотр.",
    publish_approval_required: "Публикация требует явного подтверждения.",
    smoke_id_required: "Перед утверждением запустите проверку черновика.",
    wrong_approval_level: "Утверждение выполнено не для уровня публикации кандидата.",
  };

  function issueMessage(issue) {
    if (!issue || typeof issue !== "object") {
      return "";
    }
    const code = String(issue.code || "");
    return ERROR_MESSAGES[code] || issue.message || code;
  }

  function firstIssueMessage(data) {
    const containers = [data.lifecycle, data.publication, data.preview, data.smoke];
    for (const container of containers) {
      const issues = container && Array.isArray(container.issues) ? container.issues : [];
      if (issues.length) {
        return issueMessage(issues[0]);
      }
    }
    return "";
  }

  function backendErrorMessage(data, response) {
    const code = data && data.error ? String(data.error) : "";
    return (data && data.message) || ERROR_MESSAGES[code] || firstIssueMessage(data || {}) || code || `HTTP ${response.status}`;
  }

  function adminHeaders(extraHeaders) {
    const headers = Object.assign({}, extraHeaders || {});
    const state = window.WiiconState || {};
    const token = state.admin && state.admin.token ? String(state.admin.token).trim() : "";
    if (token) {
      headers["X-WIICON5-Admin-Token"] = token;
      headers.Authorization = `Bearer ${token}`;
    }
    return headers;
  }

  async function fetchJson(url, options) {
    const request = Object.assign({ method: "GET" }, options || {});
    const headers = Object.assign({}, request.headers || {});
    if (request.body && typeof request.body !== "string" && !(request.body instanceof FormData)) {
      request.body = JSON.stringify(request.body);
      headers["Content-Type"] = headers["Content-Type"] || "application/json";
    }
    request.headers = headers;
    const response = await fetch(url, request);
    const text = await response.text();
    let data = {};
    if (text) {
      try {
        data = JSON.parse(text);
      } catch (error) {
        throw new ApiError(`Некорректный JSON от сервера: ${error.message}`, {
          status: response.status,
          url,
          body_preview: text.slice(0, 500),
        });
      }
    }
    if (!response.ok || data.ok === false) {
      const message = backendErrorMessage(data, response);
      throw new ApiError(message, { status: response.status, url, payload: data });
    }
    return data;
  }

  function fetchAdmin(url, options) {
    const request = Object.assign({}, options || {});
    request.headers = adminHeaders(request.headers);
    return fetchJson(url, request);
  }

  async function fetchAdminBlob(url, options) {
    const request = Object.assign({}, options || {});
    request.headers = adminHeaders(request.headers);
    const response = await fetch(url, request);
    if (!response.ok) {
      const text = await response.text();
      let data = {};
      try {
        data = text ? JSON.parse(text) : {};
      } catch (error) {
        data = { message: text };
      }
      throw new ApiError(backendErrorMessage(data, response), { status: response.status, url, payload: data });
    }
    return response.blob();
  }

  async function fetchText(url, options) {
    const response = await fetch(url, options || {});
    const text = await response.text();
    if (!response.ok) {
      throw new ApiError(`HTTP ${response.status}`, { status: response.status, url, body_preview: text.slice(0, 500) });
    }
    return text;
  }

  window.WiiconApi = {
    ADMIN_TOKEN_STORAGE_KEY,
    ApiError,
    adminHeaders,
    fetchJson,
    fetchAdmin,
    fetchAdminBlob,
    fetchText,
  };
})();
