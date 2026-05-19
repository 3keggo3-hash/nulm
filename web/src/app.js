const config = window.__NULM_DASHBOARD__ || {};
const token = config.token || "";
const apiBaseUrl = config.apiBaseUrl || "";

const app = document.getElementById("app");

const statuses = [
  { key: "pending", label: "Pending" },
  { key: "running", label: "Running" },
  { key: "completed", label: "Completed" },
  { key: "failed", label: "Failed" },
  { key: "cancelled", label: "Cancelled" },
];

function apiUrl(path) {
  const separator = path.includes("?") ? "&" : "?";
  return `${apiBaseUrl}${path}${separator}token=${encodeURIComponent(token)}`;
}

async function loadDashboard() {
  const response = await fetch(apiUrl("/api/status"));
  if (!response.ok) {
    throw new Error(`Dashboard API returned ${response.status}`);
  }
  return response.json();
}

async function postAction(path, body = { reason: "dashboard" }) {
  await fetch(apiUrl(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  await render();
}

async function sendMessage() {
  const box = document.getElementById("messageText");
  const message = box.value.trim();
  if (!message) {
    return;
  }
  await postAction("/api/messages", { message });
  box.value = "";
}

function escapeHtml(value) {
  return String(value || "").replace(/[&<>"']/g, (char) => {
    const entities = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    };
    return entities[char];
  });
}

function metricCard(value, label, status = "") {
  const dot = status ? `<span class="status-dot status-${escapeHtml(status)}"></span>` : "";
  return `
    <div class="metric">
      <div class="metric-value">${escapeHtml(value)}</div>
      <div class="metric-label">${dot}${escapeHtml(label)}</div>
    </div>
  `;
}

function renderMetrics(summary) {
  const byStatus = summary.by_status || {};
  let html = metricCard(summary.total || 0, "Total Tasks");
  for (const status of statuses) {
    const count = byStatus[status.key] || 0;
    if (count > 0) {
      html += metricCard(count, status.label, status.key);
    }
  }
  return html;
}

function renderTasks(tasks) {
  if (!tasks.length) {
    return '<div class="empty">No tasks recorded.</div>';
  }
  return `
    <table>
      <thead>
        <tr><th>ID</th><th>Status</th><th>Title</th><th></th></tr>
      </thead>
      <tbody>
        ${tasks
          .map(
            (row) => `
              <tr>
                <td><code>${escapeHtml(row.id)}</code></td>
                <td>
                  <span class="status-dot status-${escapeHtml(row.status)}"></span>
                  ${escapeHtml(row.status)}
                </td>
                <td>${escapeHtml(row.title || "")}</td>
                <td class="actions">
                  <button class="danger" data-action="/api/tasks/${escapeHtml(row.id)}/cancel">
                    Cancel
                  </button>
                </td>
              </tr>
            `
          )
          .join("")}
      </tbody>
    </table>
  `;
}

function renderApprovals(approvals) {
  if (!approvals.length) {
    return '<div class="empty">No approvals pending.</div>';
  }
  return `
    <table>
      <thead>
        <tr><th>ID</th><th>Status</th><th>Title</th><th></th></tr>
      </thead>
      <tbody>
        ${approvals
          .map(
            (row) => `
              <tr>
                <td><code>${escapeHtml(row.id)}</code></td>
                <td>
                  <span class="status-dot status-${escapeHtml(row.status)}"></span>
                  ${escapeHtml(row.status)}
                </td>
                <td>${escapeHtml(row.title || "")}</td>
                <td class="actions">
                  <button class="primary" data-action="/api/approvals/${escapeHtml(row.id)}/approve">
                    Approve
                  </button>
                  <button data-action="/api/approvals/${escapeHtml(row.id)}/allow_always">
                    Allow Always
                  </button>
                  <button class="danger" data-action="/api/approvals/${escapeHtml(row.id)}/reject">
                    Reject
                  </button>
                </td>
              </tr>
            `
          )
          .join("")}
      </tbody>
    </table>
  `;
}

function renderMessages(messages) {
  if (!messages.length) {
    return '<div class="empty">No messages.</div>';
  }
  return messages
    .map(
      (row) => `
        <article class="message">
          <div>
            <strong>${escapeHtml(row.status)}</strong>
            <span class="timestamp">${escapeHtml(row.updated_at || row.created_at || "")}</span>
          </div>
          <div>${escapeHtml(row.message || "")}</div>
          <div class="muted">${escapeHtml(row.response || "")}</div>
        </article>
      `
    )
    .join("");
}

function bindActions() {
  document.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", () => postAction(button.dataset.action));
  });
  document.getElementById("refresh")?.addEventListener("click", render);
  document.getElementById("sendMessage")?.addEventListener("click", sendMessage);
}

async function render() {
  app.innerHTML = `
    <header>
      <div>
        <h1>Control Plane</h1>
        <div class="muted">Loading dashboard state...</div>
      </div>
      <button id="refresh">Refresh</button>
    </header>
    <main>
      <div class="empty">Loading...</div>
    </main>
  `;

  try {
    const data = await loadDashboard();
    app.innerHTML = `
      <header>
        <div>
          <h1>Control Plane</h1>
          <div class="muted">${escapeHtml(data.state_dir || "")}</div>
        </div>
        <button id="refresh">Refresh</button>
      </header>
      <main>
        <div class="metrics">${renderMetrics(data.summary || {})}</div>
        <div class="grid">
          <section>
            <h2>Tasks</h2>
            ${renderTasks(data.tasks || [])}
          </section>
          <section>
            <h2>Approvals</h2>
            ${renderApprovals(data.approvals || [])}
          </section>
          <section class="messages">
            <h2>Messages</h2>
            <textarea
              id="messageText"
              placeholder="Send an instruction or note to the agent"
            ></textarea>
            <div class="actions">
              <button class="primary" id="sendMessage">Send</button>
            </div>
            ${renderMessages(data.messages || [])}
          </section>
        </div>
      </main>
    `;
  } catch (error) {
    app.innerHTML = `
      <header>
        <div>
          <h1>Control Plane</h1>
          <div class="muted">Dashboard API unavailable</div>
        </div>
        <button id="refresh">Refresh</button>
      </header>
      <main>
        <div class="empty">${escapeHtml(error.message)}</div>
      </main>
    `;
  }
  bindActions();
}

render();
