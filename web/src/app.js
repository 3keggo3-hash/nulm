const config = window.__NULM_DASHBOARD__ || {};
const token = config.token || "";
const apiBaseUrl = config.apiBaseUrl || "";

const app = document.getElementById("app");

const taskStatuses = [
  { key: "pending", label: "Pending" },
  { key: "queued", label: "Queued" },
  { key: "planning", label: "Planning" },
  { key: "running", label: "Running" },
  { key: "in_progress", label: "In Progress" },
  { key: "blocked", label: "Blocked" },
  { key: "approval_pending", label: "Approval Pending" },
  { key: "testing", label: "Testing" },
  { key: "failed", label: "Failed" },
  { key: "completed", label: "Completed" },
  { key: "cancelled", label: "Cancelled" },
];

const tabs = [
  { key: "overview", label: "Overview" },
  { key: "activity", label: "Activity" },
  { key: "approvals", label: "Approvals" },
  { key: "messages", label: "Messages" },
];

let activeTab = "overview";
let lastError = "";

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
  const response = await fetch(apiUrl(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let message = `Dashboard API returned ${response.status}`;
    try {
      const payload = await response.json();
      message = payload.error || message;
    } catch {
      // Keep the status message when the response is not JSON.
    }
    throw new Error(message);
  }
  lastError = "";
  await render();
}

async function sendMessage() {
  const box = document.getElementById("messageText");
  const message = box.value.trim();
  if (!message) {
    return;
  }
  await runAction(() => postAction("/api/messages", { message }));
  box.value = "";
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => {
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

function formatStatusLabel(status) {
  const match = taskStatuses.find((item) => item.key === status);
  return match ? match.label : String(status || "unknown");
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

function sectionUnavailable(section, label) {
  if (!section || section.available !== false) {
    return "";
  }
  return `<div class="notice">${escapeHtml(label)} unavailable: ${escapeHtml(section.error)}</div>`;
}

function renderMetrics(data) {
  const summary = data.summary || {};
  const byStatus = summary.by_status || {};
  const pendingApprovals = (data.approvals || []).filter((row) => row.status === "pending").length;
  const failureCount = data.activity?.failure_count || 0;
  const workspace = data.workspace || {};
  let html = metricCard(summary.total || 0, "Total Tasks");
  html += metricCard(pendingApprovals, "Pending Approvals", "approval_pending");
  html += metricCard(failureCount, "Recent Failures", failureCount ? "failed" : "completed");
  html += metricCard(workspace.profile?.tool_profile || "unknown", "Tool Profile");
  for (const status of taskStatuses) {
    const count = byStatus[status.key] || 0;
    if (count > 0) {
      html += metricCard(count, status.label, status.key);
    }
  }
  return html;
}

function renderTabs() {
  return `
    <nav class="tabs" aria-label="Dashboard sections">
      ${tabs
        .map(
          (tab) => `
            <button
              class="tab ${tab.key === activeTab ? "active" : ""}"
              data-tab="${escapeHtml(tab.key)}"
            >
              ${escapeHtml(tab.label)}
            </button>
          `
        )
        .join("")}
    </nav>
  `;
}

function renderWorkspace(workspace) {
  if (!workspace || workspace.available === false) {
    return '<div class="empty">Workspace metadata unavailable.</div>';
  }
  return `
    <div class="detail-grid">
      <div>
        <div class="label">Active Project</div>
        <code>${escapeHtml(workspace.active_project_dir)}</code>
      </div>
      <div>
        <div class="label">Approval</div>
        <span>${workspace.approval?.auto_approve ? "auto" : "manual"}</span>
        <span class="muted">
          ${workspace.approval?.client_managed_approval ? "client-managed" : "server-managed"}
        </span>
      </div>
      <div>
        <div class="label">Risk Auto-Approve</div>
        <span>${escapeHtml(workspace.approval?.auto_approve_risk_level || "none")}</span>
      </div>
      <div>
        <div class="label">Allowed Roots</div>
        <code>${escapeHtml((workspace.allowed_roots || []).join(", "))}</code>
      </div>
    </div>
  `;
}

function renderTasks(tasks) {
  if (!tasks.length) {
    return '<div class="empty">No tasks recorded.</div>';
  }
  return `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>ID</th><th>Status</th><th>Title</th><th>Updated</th><th>Control</th>
          </tr>
        </thead>
        <tbody>
          ${tasks
            .map(
              (row) => `
                <tr>
                  <td><code>${escapeHtml(row.id)}</code></td>
                  <td>
                    <span class="status-dot status-${escapeHtml(row.status)}"></span>
                    ${escapeHtml(formatStatusLabel(row.status))}
                  </td>
                  <td>
                    <strong>${escapeHtml(row.title || "")}</strong>
                    <div class="muted">${escapeHtml(row.summary || "")}</div>
                  </td>
                  <td class="timestamp">${escapeHtml(row.updated_at || row.created_at || "")}</td>
                  <td>
                    <div class="control-stack">
                      <select data-status-for="${escapeHtml(row.id)}">
                        ${taskStatuses
                          .map(
                            (status) => `
                              <option
                                value="${escapeHtml(status.key)}"
                                ${status.key === row.status ? "selected" : ""}
                              >
                                ${escapeHtml(status.label)}
                              </option>
                            `
                          )
                          .join("")}
                      </select>
                      <input
                        type="text"
                        placeholder="Reason"
                        data-reason-for="${escapeHtml(row.id)}"
                      >
                      <div class="actions">
                        <button class="primary" data-status-action="${escapeHtml(row.id)}">
                          Update
                        </button>
                        <button
                          class="danger"
                          data-action="/api/tasks/${escapeHtml(row.id)}/cancel"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  </td>
                </tr>
              `
            )
            .join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderApprovals(approvals) {
  if (!approvals.length) {
    return '<div class="empty">No approvals recorded.</div>';
  }
  return `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>ID</th><th>Status</th><th>Request</th><th>Command</th><th>Decision</th>
          </tr>
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
                    <div class="timestamp">${escapeHtml(row.expires_at || "")}</div>
                  </td>
                  <td>
                    <strong>${escapeHtml(row.title || "")}</strong>
                    <div class="muted">${escapeHtml(row.reason || row.summary || "")}</div>
                    <div class="timestamp">${escapeHtml(row.metadata?.task_id || "")}</div>
                  </td>
                  <td>
                    <div>${escapeHtml(row.tool || "")}</div>
                    <code>${escapeHtml(row.command || "")}</code>
                  </td>
                  <td>
                    <div class="control-stack">
                      <input
                        type="text"
                        placeholder="Decision reason"
                        data-reason-for="${escapeHtml(row.id)}"
                      >
                      <div class="actions">
                        <button
                          class="primary"
                          data-action="/api/approvals/${escapeHtml(row.id)}/approve"
                        >
                          Approve
                        </button>
                        <button data-action="/api/approvals/${escapeHtml(row.id)}/allow_always">
                          Allow Always
                        </button>
                        <button
                          class="danger"
                          data-action="/api/approvals/${escapeHtml(row.id)}/reject"
                        >
                          Reject
                        </button>
                      </div>
                    </div>
                  </td>
                </tr>
              `
            )
            .join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderRecentToolCalls(recent) {
  if (!recent || recent.available === false) {
    return sectionUnavailable(recent, "Recent tool calls");
  }
  const records = recent.records || [];
  if (!records.length) {
    return '<div class="empty">No recent tool calls.</div>';
  }
  return `
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>Time</th><th>Tool</th><th>Result</th><th>Policy</th><th>Duration</th></tr>
        </thead>
        <tbody>
          ${records
            .map(
              (row) => `
                <tr>
                  <td class="timestamp">${escapeHtml(row.timestamp)}</td>
                  <td><code>${escapeHtml(row.tool_name)}</code></td>
                  <td>
                    <span class="status-dot status-${row.ok === false ? "failed" : "completed"}">
                    </span>
                    ${escapeHtml(row.ok === false ? "failed" : "ok")}
                    <div class="muted">${escapeHtml(row.message || row.code || "")}</div>
                  </td>
                  <td>
                    ${escapeHtml(row.decision_action || "n/a")}
                    <div class="muted">${escapeHtml(row.decision_risk_level || "")}</div>
                  </td>
                  <td>${escapeHtml(row.duration_ms || 0)} ms</td>
                </tr>
              `
            )
            .join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderUsage(usage) {
  if (!usage || usage.available === false) {
    return sectionUnavailable(usage, "Usage");
  }
  const telemetry = usage.telemetry || {};
  const topTools = usage.top_cost_tools || [];
  return `
    <div class="detail-grid">
      <div>
        <div class="label">Estimated Tokens</div>
        <strong>${escapeHtml(telemetry.total_estimated_tokens || 0)}</strong>
      </div>
      <div>
        <div class="label">Average Duration</div>
        <strong>${escapeHtml(telemetry.avg_duration_ms || 0)} ms</strong>
      </div>
      <div>
        <div class="label">Truncated Results</div>
        <strong>${escapeHtml(telemetry.truncated_results || 0)}</strong>
      </div>
      <div>
        <div class="label">Top Cost Tools</div>
        ${topTools.map((row) => `<code>${escapeHtml(row.tool_name)}</code>`).join(" ")}
      </div>
    </div>
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

function renderTabContent(data) {
  if (activeTab === "activity") {
    return `
      <div class="grid">
        <section>
          <h2>Recent Tool Calls</h2>
          ${renderRecentToolCalls(data.recent_tool_calls)}
        </section>
        <section>
          <h2>Usage</h2>
          ${renderUsage(data.usage)}
        </section>
      </div>
    `;
  }
  if (activeTab === "approvals") {
    return `
      <section>
        <h2>Approvals</h2>
        ${renderApprovals(data.approvals || [])}
      </section>
    `;
  }
  if (activeTab === "messages") {
    return `
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
    `;
  }
  return `
    <div class="grid">
      <section>
        <h2>Tasks</h2>
        ${renderTasks(data.tasks || [])}
      </section>
      <section>
        <h2>Workspace</h2>
        ${renderWorkspace(data.workspace)}
      </section>
    </div>
  `;
}

function reasonFor(recordId) {
  return document.querySelector(`[data-reason-for="${CSS.escape(recordId)}"]`)?.value || "";
}

async function runAction(action) {
  try {
    await action();
  } catch (error) {
    lastError = error.message;
    await render();
  }
}

function bindActions() {
  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      activeTab = button.dataset.tab;
      render();
    });
  });
  document.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const parts = button.dataset.action.split("/");
      const recordId = parts[3] || "";
      runAction(() => postAction(button.dataset.action, { reason: reasonFor(recordId) }));
    });
  });
  document.querySelectorAll("[data-status-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const recordId = button.dataset.statusAction;
      const status = document.querySelector(`[data-status-for="${CSS.escape(recordId)}"]`)?.value;
      runAction(() =>
        postAction(`/api/tasks/${recordId}/status`, {
          status,
          reason: reasonFor(recordId),
        })
      );
    });
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
        ${lastError ? `<div class="notice danger">${escapeHtml(lastError)}</div>` : ""}
        <div class="metrics">${renderMetrics(data)}</div>
        ${renderTabs()}
        ${renderTabContent(data)}
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
