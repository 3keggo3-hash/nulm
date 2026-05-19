const config = window.__NULM_DASHBOARD__ || {};
const urlParams = new URLSearchParams(window.location.search);
const token = urlParams.get("token") || config.token || "";
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
  { key: "messages", label: "CLI" },
];

let activeTab = "overview";
let lastError = "";
let dashboardData = null;
let isRefreshing = false;
let cliFilter = "";

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
  await refreshDashboard({ showLoading: false });
}

let cliPollInterval = null;

async function sendMessage() {
  const box = document.getElementById("messageText");
  const message = box.value.trim();
  if (!message) {
    return;
  }
  const result = await postActionRaw("/api/cli", { command: message });
  if (result.session_id) {
    pollCliSession(result.session_id);
  }
  box.value = "";
}

async function postActionRaw(path, body = {}) {
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
    } catch {}
    throw new Error(message);
  }
  return response.json();
}

function pollCliSession(sessionId) {
  if (cliPollInterval) clearInterval(cliPollInterval);
  cliPollInterval = setInterval(async () => {
    try {
      const res = await fetch(apiUrl(`/api/cli/${sessionId}/stream`));
      if (!res.ok) return;
      const data = await res.json();
      if (data.status === "completed" || data.status === "failed" || data.error) {
        clearInterval(cliPollInterval);
        cliPollInterval = null;
        await refreshDashboard({ showLoading: false });
      }
    } catch {}
  }, 500);
}

let agentPollInterval = null;

function dispatchAgentTask(task, mode = "agent_loop") {
  return postActionRaw("/api/agent", { task, mode });
}

function pollAgentTask(taskId) {
  if (agentPollInterval) clearInterval(agentPollInterval);
  agentPollInterval = setInterval(async () => {
    try {
      const res = await fetch(apiUrl(`/api/agent/task/${taskId}`));
      if (!res.ok) return;
      const data = await res.json();
      if (data.status === "completed" || data.status === "failed" || data.error) {
        clearInterval(agentPollInterval);
        agentPollInterval = null;
        await refreshDashboard({ showLoading: false });
      }
    } catch {}
  }, 500);
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
  html += metricCard(failureCount, "Recent Failures", failureCount ? "failed" : "");
  html += metricCard(workspace.profile?.tool_profile || "unknown", "Tool Profile");
  for (const status of taskStatuses) {
    const count = byStatus[status.key] || 0;
    if (count > 0) {
      html += metricCard(count, status.label, status.key);
    }
  }
  return html;
}

function pendingApprovals(data) {
  return (data.approvals || []).filter((row) => row.status === "pending");
}

function renderApprovalStrip(data) {
  const approvals = pendingApprovals(data);
  if (!approvals.length) {
    return "";
  }
  const first = approvals[0];
  return `
    <section class="approval-strip" aria-label="Pending approval action center">
      <div>
        <div class="label">Action Center</div>
        <strong>${escapeHtml(approvals.length)} pending approval${approvals.length === 1 ? "" : "s"}</strong>
        <div class="muted">
          ${escapeHtml(first.title || first.tool || "Approval required")}
          ${first.command ? ` · ${escapeHtml(first.command)}` : ""}
        </div>
      </div>
      <div class="actions">
        <button class="primary" data-tab-jump="approvals">Review</button>
      </div>
    </section>
  `;
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
                  <td data-label="ID"><code>${escapeHtml(row.id)}</code></td>
                  <td data-label="Status">
                    <span class="status-dot status-${escapeHtml(row.status)}"></span>
                    ${escapeHtml(formatStatusLabel(row.status))}
                  </td>
                  <td data-label="Title">
                    <strong>${escapeHtml(row.title || "")}</strong>
                    <div class="muted">${escapeHtml(row.summary || "")}</div>
                  </td>
                  <td class="timestamp" data-label="Updated">
                    ${escapeHtml(row.updated_at || row.created_at || "")}
                  </td>
                  <td data-label="Control">
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
                  <td data-label="ID"><code>${escapeHtml(row.id)}</code></td>
                  <td data-label="Status">
                    <span class="status-dot status-${escapeHtml(row.status)}"></span>
                    ${escapeHtml(row.status)}
                    <div class="timestamp">${escapeHtml(row.expires_at || "")}</div>
                  </td>
                  <td data-label="Request">
                    <strong>${escapeHtml(row.title || "")}</strong>
                    <div class="muted">${escapeHtml(row.reason || row.summary || "")}</div>
                    <div class="timestamp">${escapeHtml(row.metadata?.task_id || "")}</div>
                  </td>
                  <td data-label="Command">
                    <div>${escapeHtml(row.tool || "")}</div>
                    <code>${escapeHtml(row.command || "")}</code>
                  </td>
                  <td data-label="Decision">
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
                  <td class="timestamp" data-label="Time">${escapeHtml(row.timestamp)}</td>
                  <td data-label="Tool"><code>${escapeHtml(row.tool_name)}</code></td>
                  <td data-label="Result">
                    <span class="status-dot status-${row.ok === false ? "failed" : "completed"}">
                    </span>
                    ${escapeHtml(row.ok === false ? "failed" : "ok")}
                    <div class="muted">${escapeHtml(row.message || row.code || "")}</div>
                  </td>
                  <td data-label="Policy">
                    ${escapeHtml(row.decision_action || "n/a")}
                    <div class="muted">${escapeHtml(row.decision_risk_level || "")}</div>
                  </td>
                  <td data-label="Duration">${escapeHtml(row.duration_ms || 0)} ms</td>
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

function renderMessages(messages, filterText = "") {
  const filtered = filterText
    ? messages.filter((m) => m.message?.toLowerCase().includes(filterText.toLowerCase()))
    : messages;
  if (!filtered.length) {
    return '<div class="empty">No messages' + (filterText ? " matching filter" : "") + '.</div>';
  }
  return filtered
    .map(
      (row) => {
        const returncode = row.metadata?.returncode;
        const stdout = row.metadata?.stdout || "";
        const stderr = row.metadata?.stderr || "";
        const isSuccess = returncode === 0;
        const hasStderr = stderr.trim().length > 0;
        const response = row.response || "";
        const lines = response.split("\n").length;
        const isLong = lines > 20;
        const shortResponse = isLong ? response.split("\n").slice(0, 10).join("\n") : response;
        const id = `msg-${row.id}`;
        const isRunning = row.status === "acknowledged" || row.status === "queued";
        const exitBadge = isRunning
          ? '<span class="exit-badge exit-running">…</span>'
          : `<span class="exit-badge exit-${isSuccess ? "ok" : "fail"}">${returncode ?? "—"}</span>`;
        return `
        <article class="message" id="${escapeHtml(id)}">
          <div class="message-header">
            ${exitBadge}
            <code class="message-command">${escapeHtml(row.message || "")}</code>
            ${isRunning ? '<span class="running-indicator">running</span>' : ""}
            <span class="timestamp">${escapeHtml(row.updated_at || row.created_at || "")}</span>
            <div class="message-actions">
              ${!isRunning ? `<button class="icon-btn" title="Copy output" data-copy="${escapeHtml(id)}">📋</button>` : ""}
              ${!isRunning ? `<button class="icon-btn" title="Re-run" data-rerun="${escapeHtml(row.message || "")}">↻</button>` : ""}
            </div>
          </div>
          ${stdout.trim() ? `<pre class="cli-stdout">${escapeHtml(stdout.trim())}</pre>` : ""}
          ${hasStderr ? `<pre class="cli-stderr">${escapeHtml(stderr.trim())}</pre>` : ""}
          ${response.trim() ? `
            <div class="message-response">
              <pre class="${isLong ? "collapsible" : ""}">${escapeHtml(isLong ? shortResponse : response)}</pre>
              ${isLong ? `<button class="expand-btn" data-expand="${escapeHtml(id)}">▼ show ${lines - 10} more lines</button>` : ""}
            </div>
          ` : ""}
        </article>
      `;
      }
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
      <section>
        <h2>CLI</h2>
        <input id="cliFilter" type="text" placeholder="Filter commands..." value="${escapeHtml(cliFilter)}" style="margin-bottom:8px;width:100%;padding:6px;" />
        <textarea
          id="messageText"
          placeholder="nulm doctor --json"
        ></textarea>
        <div class="actions">
          <button class="primary" id="sendMessage">Run</button>
          <button id="rerunLast">Re-run last</button>
        </div>
        <div class="agent-section">
          <h3>Agent Task</h3>
          <textarea id="agentTaskText" placeholder="Describe what you want the agent to do..." style="min-height:60px;"></textarea>
          <div class="actions">
            <button class="primary" id="dispatchAgent">Dispatch Agent</button>
          </div>
        </div>
        <div class="messages-list">
          ${renderMessages(data.messages || [], cliFilter)}
        </div>
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
    renderApp(dashboardData);
  }
}

function bindActions() {
  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      activeTab = button.dataset.tab;
      renderApp(dashboardData);
    });
  });
  document.querySelectorAll("[data-tab-jump]").forEach((button) => {
    button.addEventListener("click", () => {
      activeTab = button.dataset.tabJump;
      renderApp(dashboardData);
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
  document.getElementById("refresh")?.addEventListener("click", () => {
    refreshDashboard({ showLoading: false });
  });
  document.getElementById("sendMessage")?.addEventListener("click", sendMessage);
  document.getElementById("cliFilter")?.addEventListener("input", (e) => {
    cliFilter = e.target.value;
    renderApp(dashboardData);
  });
  document.querySelectorAll("[data-copy]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.copy;
      const el = document.getElementById(id);
      if (!el) return;
      const pre = el.querySelector(".message-response pre");
      const text = pre ? pre.textContent : el.querySelector(".message-response")?.textContent || "";
      navigator.clipboard.writeText(text).catch(() => {});
    });
  });
  document.querySelectorAll("[data-expand]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.expand;
      const el = document.getElementById(id);
      if (!el) return;
      const pre = el.querySelector(".message-response pre.collapsible");
      if (pre) pre.classList.remove("collapsible");
      btn.remove();
    });
  });
  document.querySelectorAll("[data-rerun]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const cmd = btn.dataset.rerun;
      const box = document.getElementById("messageText");
      if (box) box.value = cmd;
      activeTab = "messages";
      renderApp(dashboardData);
    });
  });
  const rerunLastBtn = document.getElementById("rerunLast");
  if (rerunLastBtn) {
    rerunLastBtn.addEventListener("click", () => {
      const last = (dashboardData && dashboardData.messages) ? dashboardData.messages[0] : null;
      if (last && last.message) {
        const box = document.getElementById("messageText");
        if (box) box.value = last.message;
      }
    });
  }
  document.getElementById("dispatchAgent")?.addEventListener("click", async () => {
    const box = document.getElementById("agentTaskText");
    const task = box?.value?.trim();
    if (!task) return;
    try {
      const result = await dispatchAgentTask(task);
      if (result.task_id) pollAgentTask(result.task_id);
    } catch (err) {
      lastError = err.message;
      renderApp(dashboardData);
    }
  });
}

function renderShell(subtitle, mainContent) {
  app.innerHTML = `
    <header>
      <div>
        <h1>nulm control plane</h1>
        <div class="muted">${escapeHtml(subtitle)}</div>
      </div>
      <button id="refresh" ${isRefreshing ? "disabled" : ""}>
        ${isRefreshing ? "Refreshing" : "Refresh"}
      </button>
    </header>
    <main>
      ${mainContent}
    </main>
  `;
  bindActions();
}

function renderApp(data) {
  if (!data) {
    renderShell("Loading dashboard state...", '<div class="empty">Loading...</div>');
    return;
  }
  renderShell(
    data.state_dir || "",
    `
      ${lastError ? `<div class="notice danger">${escapeHtml(lastError)}</div>` : ""}
      ${renderApprovalStrip(data)}
      <div class="metrics">${renderMetrics(data)}</div>
      ${renderTabs()}
      ${renderTabContent(data)}
    `
  );
}

async function refreshDashboard({ showLoading = true } = {}) {
  if (showLoading && !dashboardData) {
    renderApp(null);
  } else if (dashboardData) {
    isRefreshing = true;
    renderApp(dashboardData);
  }

  try {
    dashboardData = await loadDashboard();
    lastError = "";
  } catch (error) {
    lastError = error.message;
    if (!dashboardData) {
      renderShell("Dashboard API unavailable", `<div class="empty">${escapeHtml(error.message)}</div>`);
      return;
    }
  } finally {
    isRefreshing = false;
  }
  renderApp(dashboardData);
}

refreshDashboard();
