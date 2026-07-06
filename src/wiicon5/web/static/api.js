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
      const message = data.message || data.error || `HTTP ${response.status}`;
      throw new ApiError(message, { status: response.status, url, payload: data });
    }
    return data;
  }

  function fetchAdmin(url, options) {
    const request = Object.assign({}, options || {});
    request.headers = adminHeaders(request.headers);
    return fetchJson(url, request);
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
    fetchText,
  };
})();
