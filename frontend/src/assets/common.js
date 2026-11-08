function getApiBase() {
  return localStorage.getItem("carbon_api_base") || "";
}

function setApiBase(value) {
  if (value) localStorage.setItem("carbon_api_base", value);
}

function bindApiBaseInput() {
  const input = document.getElementById("apiBase");
  if (!input) return;
  input.value = getApiBase();
  input.addEventListener("change", () => setApiBase(input.value.trim()));
}

function showResult(id, data) {
  const target = document.getElementById(id);
  if (!target) return;
  target.textContent = typeof data === "string" ? data : JSON.stringify(data, null, 2);
}

function ensureToast() {
  let toast = document.getElementById("globalToast");
  if (toast) return toast;
  toast = document.createElement("div");
  toast.id = "globalToast";
  toast.className = "global-toast";
  document.body.appendChild(toast);
  return toast;
}

function toast(message, type = "ok") {
  const el = ensureToast();
  el.textContent = message;
  el.className = `global-toast show ${type}`;
  clearTimeout(window.__toastTimer);
  window.__toastTimer = setTimeout(() => {
    el.className = "global-toast";
  }, 2200);
}

function setLoading(button, loading) {
  if (!button) return;
  if (loading) {
    button.dataset.origin = button.textContent;
    button.textContent = "处理中...";
    button.disabled = true;
    button.classList.add("is-loading");
  } else {
    button.textContent = button.dataset.origin || button.textContent;
    button.disabled = false;
    button.classList.remove("is-loading");
  }
}

async function callApi(path, method = "GET", body = null) {
  const options = {
    method,
    headers: { "Content-Type": "application/json" }
  };
  if (body !== null) options.body = JSON.stringify(body);

  const base = getApiBase().replace(/\/+$/, "");
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const response = await fetch(base ? `${base}${normalizedPath}` : normalizedPath, options);
  const text = await response.text();
  let payload;
  try {
    payload = JSON.parse(text);
  } catch (_error) {
    payload = text;
  }

  if (!response.ok) {
    const detail = typeof payload === "object" ? JSON.stringify(payload, null, 2) : String(payload);
    throw new Error(`请求失败 [${response.status}]：${detail}`);
  }
  return payload;
}
