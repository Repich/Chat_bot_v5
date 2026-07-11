/*
 * Run this script in the developer console of the authorized BWiki root page.
 * It reads the current page and descendants through same-origin Confluence REST
 * and downloads a local JSON file. It never reads or exports browser cookies.
 */
(async function exportWiicTree() {
  "use strict";

  const rootPageId = new URL(window.location.href).searchParams.get("pageId") || "177957241";
  const expand = "body.storage,version,ancestors,space,history,metadata.labels";
  const pages = [];
  const queue = [rootPageId];
  const seen = new Set();

  async function fetchJson(path, params) {
    const url = new URL(path, window.location.origin);
    Object.entries(params || {}).forEach(([key, value]) => url.searchParams.set(key, value));
    const response = await window.fetch(url.toString(), {
      method: "GET",
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      throw new Error(`BWiki HTTP ${response.status}: ${url.pathname}`);
    }
    return response.json();
  }

  while (queue.length) {
    const pageId = queue.shift();
    if (seen.has(pageId)) {
      continue;
    }
    seen.add(pageId);
    const page = await fetchJson(`/rest/api/content/${encodeURIComponent(pageId)}`, { expand });
    pages.push(page);
    let start = 0;
    while (true) {
      const children = await fetchJson(`/rest/api/content/${encodeURIComponent(pageId)}/child/page`, {
        expand,
        limit: "100",
        start: String(start),
      });
      const results = Array.isArray(children.results) ? children.results : [];
      results.forEach((child) => {
        if (child && child.id && !seen.has(String(child.id))) {
          queue.push(String(child.id));
        }
      });
      if (results.length < Number(children.limit || 100)) {
        break;
      }
      start += results.length;
    }
    console.info(`WIIC export: ${pages.length} pages loaded, ${queue.length} queued`);
  }

  const payload = {
    exported_at: new Date().toISOString(),
    source_url: window.location.href,
    root_page_id: rootPageId,
    pages,
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `wiic-bwiki-${rootPageId}-${new Date().toISOString().slice(0, 10)}.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(link.href);
  console.info(`WIIC export complete: ${pages.length} pages`);
})();
