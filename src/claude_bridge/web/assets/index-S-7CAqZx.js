(function(){const e=document.createElement("link").relList;if(e&&e.supports&&e.supports("modulepreload"))return;for(const o of document.querySelectorAll('link[rel="modulepreload"]'))i(o);new MutationObserver(o=>{for(const n of o)if(n.type==="childList")for(const l of n.addedNodes)l.tagName==="LINK"&&l.rel==="modulepreload"&&i(l)}).observe(document,{childList:!0,subtree:!0});function a(o){const n={};return o.integrity&&(n.integrity=o.integrity),o.referrerPolicy&&(n.referrerPolicy=o.referrerPolicy),o.crossOrigin==="use-credentials"?n.credentials="include":o.crossOrigin==="anonymous"?n.credentials="omit":n.credentials="same-origin",n}function i(o){if(o.ep)return;o.ep=!0;const n=a(o);fetch(o.href,n)}})();const D=window.__NULM_DASHBOARD__||{},w=new URLSearchParams(window.location.search),N=w.get("token")||D.token||"",F=D.apiBaseUrl||"",M=document.getElementById("app"),L=[{key:"pending",label:"Pending"},{key:"queued",label:"Queued"},{key:"planning",label:"Planning"},{key:"running",label:"Running"},{key:"in_progress",label:"In Progress"},{key:"blocked",label:"Blocked"},{key:"approval_pending",label:"Approval Pending"},{key:"testing",label:"Testing"},{key:"failed",label:"Failed"},{key:"completed",label:"Completed"},{key:"cancelled",label:"Cancelled"}],H=[{key:"overview",label:"Overview"},{key:"activity",label:"Activity"},{key:"approvals",label:"Approvals"},{key:"messages",label:"CLI"}];let m="overview",g="",c=null,A=!1,S="";function y(t){const e=t.includes("?")?"&":"?";return`${F}${t}${e}token=${encodeURIComponent(N)}`}async function J(){const t=await fetch(y("/api/status"));if(!t.ok)throw new Error(`Dashboard API returned ${t.status}`);return t.json()}async function R(t,e={reason:"dashboard"}){const a=await fetch(y(t),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(e)});if(!a.ok){let i=`Dashboard API returned ${a.status}`;try{i=(await a.json()).error||i}catch{}throw new Error(i)}g="",await $({showLoading:!1})}let f=null;async function W(){const t=document.getElementById("messageText"),e=t.value.trim();if(!e)return;const a=await q("/api/cli",{command:e});a.session_id&&K(a.session_id),t.value=""}async function q(t,e={}){const a=await fetch(y(t),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(e)});if(!a.ok){let i=`Dashboard API returned ${a.status}`;try{i=(await a.json()).error||i}catch{}throw new Error(i)}return a.json()}function K(t){f&&clearInterval(f),f=setInterval(async()=>{try{const e=await fetch(y(`/api/cli/${t}/stream`));if(!e.ok)return;const a=await e.json();(a.status==="completed"||a.status==="failed"||a.error)&&(clearInterval(f),f=null,await $({showLoading:!1}))}catch{}},500)}let h=null;function Q(t,e="agent_loop"){return q("/api/agent",{task:t,mode:e})}function z(t){h&&clearInterval(h),h=setInterval(async()=>{try{const e=await fetch(y(`/api/agent/task/${t}`));if(!e.ok)return;const a=await e.json();(a.status==="completed"||a.status==="failed"||a.error)&&(clearInterval(h),h=null,await $({showLoading:!1}))}catch{}},500)}function s(t){return String(t??"").replace(/[&<>"']/g,e=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[e])}function G(t){const e=L.find(a=>a.key===t);return e?e.label:String(t||"unknown")}function b(t,e,a=""){const i=a?`<span class="status-dot status-${s(a)}"></span>`:"";return`
    <div class="metric">
      <div class="metric-value">${s(t)}</div>
      <div class="metric-label">${i}${s(e)}</div>
    </div>
  `}function B(t,e){return!t||t.available!==!1?"":`<div class="notice">${s(e)} unavailable: ${s(t.error)}</div>`}function V(t){var r,d;const e=t.summary||{},a=e.by_status||{},i=(t.approvals||[]).filter(u=>u.status==="pending").length,o=((r=t.activity)==null?void 0:r.failure_count)||0,n=t.workspace||{};let l=b(e.total||0,"Total Tasks");l+=b(i,"Pending Approvals","approval_pending"),l+=b(o,"Recent Failures",o?"failed":""),l+=b(((d=n.profile)==null?void 0:d.tool_profile)||"unknown","Tool Profile");for(const u of L){const v=a[u.key]||0;v>0&&(l+=b(v,u.label,u.key))}return l}function X(t){return(t.approvals||[]).filter(e=>e.status==="pending")}function Y(t){const e=X(t);if(!e.length)return"";const a=e[0];return`
    <section class="approval-strip" aria-label="Pending approval action center">
      <div>
        <div class="label">Action Center</div>
        <strong>${s(e.length)} pending approval${e.length===1?"":"s"}</strong>
        <div class="muted">
          ${s(a.title||a.tool||"Approval required")}
          ${a.command?` · ${s(a.command)}`:""}
        </div>
      </div>
      <div class="actions">
        <button class="primary" data-tab-jump="approvals">Review</button>
      </div>
    </section>
  `}function Z(){return`
    <nav class="tabs" aria-label="Dashboard sections">
      ${H.map(t=>`
            <button
              class="tab ${t.key===m?"active":""}"
              data-tab="${s(t.key)}"
            >
              ${s(t.label)}
            </button>
          `).join("")}
    </nav>
  `}function tt(t){var e,a,i;return!t||t.available===!1?'<div class="empty">Workspace metadata unavailable.</div>':`
    <div class="detail-grid">
      <div>
        <div class="label">Active Project</div>
        <code>${s(t.active_project_dir)}</code>
      </div>
      <div>
        <div class="label">Approval</div>
        <span>${(e=t.approval)!=null&&e.auto_approve?"auto":"manual"}</span>
        <span class="muted">
          ${(a=t.approval)!=null&&a.client_managed_approval?"client-managed":"server-managed"}
        </span>
      </div>
      <div>
        <div class="label">Risk Auto-Approve</div>
        <span>${s(((i=t.approval)==null?void 0:i.auto_approve_risk_level)||"none")}</span>
      </div>
      <div>
        <div class="label">Allowed Roots</div>
        <code>${s((t.allowed_roots||[]).join(", "))}</code>
      </div>
    </div>
  `}function et(t){return t.length?`
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>ID</th><th>Status</th><th>Title</th><th>Updated</th><th>Control</th>
          </tr>
        </thead>
        <tbody>
          ${t.map(e=>`
                <tr>
                  <td data-label="ID"><code>${s(e.id)}</code></td>
                  <td data-label="Status">
                    <span class="status-dot status-${s(e.status)}"></span>
                    ${s(G(e.status))}
                  </td>
                  <td data-label="Title">
                    <strong>${s(e.title||"")}</strong>
                    <div class="muted">${s(e.summary||"")}</div>
                  </td>
                  <td class="timestamp" data-label="Updated">
                    ${s(e.updated_at||e.created_at||"")}
                  </td>
                  <td data-label="Control">
                    <div class="control-stack">
                      <select data-status-for="${s(e.id)}">
                        ${L.map(a=>`
                              <option
                                value="${s(a.key)}"
                                ${a.key===e.status?"selected":""}
                              >
                                ${s(a.label)}
                              </option>
                            `).join("")}
                      </select>
                      <input
                        type="text"
                        placeholder="Reason"
                        data-reason-for="${s(e.id)}"
                      >
                      <div class="actions">
                        <button class="primary" data-status-action="${s(e.id)}">
                          Update
                        </button>
                        <button
                          class="danger"
                          data-action="/api/tasks/${s(e.id)}/cancel"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  </td>
                </tr>
              `).join("")}
        </tbody>
      </table>
    </div>
  `:'<div class="empty">No tasks recorded.</div>'}function at(t){return t.length?`
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>ID</th><th>Status</th><th>Request</th><th>Command</th><th>Decision</th>
          </tr>
        </thead>
        <tbody>
          ${t.map(e=>{var a;return`
                <tr>
                  <td data-label="ID"><code>${s(e.id)}</code></td>
                  <td data-label="Status">
                    <span class="status-dot status-${s(e.status)}"></span>
                    ${s(e.status)}
                    <div class="timestamp">${s(e.expires_at||"")}</div>
                  </td>
                  <td data-label="Request">
                    <strong>${s(e.title||"")}</strong>
                    <div class="muted">${s(e.reason||e.summary||"")}</div>
                    <div class="timestamp">${s(((a=e.metadata)==null?void 0:a.task_id)||"")}</div>
                  </td>
                  <td data-label="Command">
                    <div>${s(e.tool||"")}</div>
                    <code>${s(e.command||"")}</code>
                  </td>
                  <td data-label="Decision">
                    <div class="control-stack">
                      <input
                        type="text"
                        placeholder="Decision reason"
                        data-reason-for="${s(e.id)}"
                      >
                      <div class="actions">
                        <button
                          class="primary"
                          data-action="/api/approvals/${s(e.id)}/approve"
                        >
                          Approve
                        </button>
                        <button data-action="/api/approvals/${s(e.id)}/allow_always">
                          Allow Always
                        </button>
                        <button
                          class="danger"
                          data-action="/api/approvals/${s(e.id)}/reject"
                        >
                          Reject
                        </button>
                      </div>
                    </div>
                  </td>
                </tr>
              `}).join("")}
        </tbody>
      </table>
    </div>
  `:'<div class="empty">No approvals recorded.</div>'}function st(t){if(!t||t.available===!1)return B(t,"Recent tool calls");const e=t.records||[];return e.length?`
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>Time</th><th>Tool</th><th>Result</th><th>Policy</th><th>Duration</th></tr>
        </thead>
        <tbody>
          ${e.map(a=>`
                <tr>
                  <td class="timestamp" data-label="Time">${s(a.timestamp)}</td>
                  <td data-label="Tool"><code>${s(a.tool_name)}</code></td>
                  <td data-label="Result">
                    <span class="status-dot status-${a.ok===!1?"failed":"completed"}">
                    </span>
                    ${s(a.ok===!1?"failed":"ok")}
                    <div class="muted">${s(a.message||a.code||"")}</div>
                  </td>
                  <td data-label="Policy">
                    ${s(a.decision_action||"n/a")}
                    <div class="muted">${s(a.decision_risk_level||"")}</div>
                  </td>
                  <td data-label="Duration">${s(a.duration_ms||0)} ms</td>
                </tr>
              `).join("")}
        </tbody>
      </table>
    </div>
  `:'<div class="empty">No recent tool calls.</div>'}function nt(t){if(!t||t.available===!1)return B(t,"Usage");const e=t.telemetry||{},a=t.top_cost_tools||[];return`
    <div class="detail-grid">
      <div>
        <div class="label">Estimated Tokens</div>
        <strong>${s(e.total_estimated_tokens||0)}</strong>
      </div>
      <div>
        <div class="label">Average Duration</div>
        <strong>${s(e.avg_duration_ms||0)} ms</strong>
      </div>
      <div>
        <div class="label">Truncated Results</div>
        <strong>${s(e.truncated_results||0)}</strong>
      </div>
      <div>
        <div class="label">Top Cost Tools</div>
        ${a.map(i=>`<code>${s(i.tool_name)}</code>`).join(" ")}
      </div>
    </div>
  `}function it(t,e=""){const a=e?t.filter(i=>{var o;return(o=i.message)==null?void 0:o.toLowerCase().includes(e.toLowerCase())}):t;return a.length?a.map(i=>{var I,x,C;const o=(I=i.metadata)==null?void 0:I.returncode,n=((x=i.metadata)==null?void 0:x.stdout)||"",l=((C=i.metadata)==null?void 0:C.stderr)||"",r=o===0,d=l.trim().length>0,u=i.response||"",v=u.split(`
`).length,k=v>20,U=k?u.split(`
`).slice(0,10).join(`
`):u,E=`msg-${i.id}`,_=i.status==="acknowledged"||i.status==="queued",O=_?'<span class="exit-badge exit-running">…</span>':`<span class="exit-badge exit-${r?"ok":"fail"}">${o??"—"}</span>`;return`
        <article class="message" id="${s(E)}">
          <div class="message-header">
            ${O}
            <code class="message-command">${s(i.message||"")}</code>
            ${_?'<span class="running-indicator">running</span>':""}
            <span class="timestamp">${s(i.updated_at||i.created_at||"")}</span>
            <div class="message-actions">
              ${_?"":`<button class="icon-btn" title="Copy output" data-copy="${s(E)}">📋</button>`}
              ${_?"":`<button class="icon-btn" title="Re-run" data-rerun="${s(i.message||"")}">↻</button>`}
            </div>
          </div>
          ${n.trim()?`<pre class="cli-stdout">${s(n.trim())}</pre>`:""}
          ${d?`<pre class="cli-stderr">${s(l.trim())}</pre>`:""}
          ${u.trim()?`
            <div class="message-response">
              <pre class="${k?"collapsible":""}">${s(k?U:u)}</pre>
              ${k?`<button class="expand-btn" data-expand="${s(E)}">▼ show ${v-10} more lines</button>`:""}
            </div>
          `:""}
        </article>
      `}).join(""):'<div class="empty">No messages'+(e?" matching filter":"")+".</div>"}function ot(t){return m==="activity"?`
      <div class="grid">
        <section>
          <h2>Recent Tool Calls</h2>
          ${st(t.recent_tool_calls)}
        </section>
        <section>
          <h2>Usage</h2>
          ${nt(t.usage)}
        </section>
      </div>
    `:m==="approvals"?`
      <section>
        <h2>Approvals</h2>
        ${at(t.approvals||[])}
      </section>
    `:m==="messages"?`
      <section>
        <h2>CLI</h2>
        <input id="cliFilter" type="text" placeholder="Filter commands..." value="${s(S)}" style="margin-bottom:8px;width:100%;padding:6px;" />
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
          ${it(t.messages||[],S)}
        </div>
      </section>
    `:`
    <div class="grid">
      <section>
        <h2>Tasks</h2>
        ${et(t.tasks||[])}
      </section>
      <section>
        <h2>Workspace</h2>
        ${tt(t.workspace)}
      </section>
    </div>
  `}function j(t){var e;return((e=document.querySelector(`[data-reason-for="${CSS.escape(t)}"]`))==null?void 0:e.value)||""}async function P(t){try{await t()}catch(e){g=e.message,p(c)}}function lt(){var e,a,i,o;document.querySelectorAll("[data-tab]").forEach(n=>{n.addEventListener("click",()=>{m=n.dataset.tab,p(c)})}),document.querySelectorAll("[data-tab-jump]").forEach(n=>{n.addEventListener("click",()=>{m=n.dataset.tabJump,p(c)})}),document.querySelectorAll("[data-action]").forEach(n=>{n.addEventListener("click",()=>{const r=n.dataset.action.split("/")[3]||"";P(()=>R(n.dataset.action,{reason:j(r)}))})}),document.querySelectorAll("[data-status-action]").forEach(n=>{n.addEventListener("click",()=>{var d;const l=n.dataset.statusAction,r=(d=document.querySelector(`[data-status-for="${CSS.escape(l)}"]`))==null?void 0:d.value;P(()=>R(`/api/tasks/${l}/status`,{status:r,reason:j(l)}))})}),(e=document.getElementById("refresh"))==null||e.addEventListener("click",()=>{$({showLoading:!1})}),(a=document.getElementById("sendMessage"))==null||a.addEventListener("click",W),(i=document.getElementById("cliFilter"))==null||i.addEventListener("input",n=>{S=n.target.value,p(c)}),document.querySelectorAll("[data-copy]").forEach(n=>{n.addEventListener("click",()=>{var v;const l=n.dataset.copy,r=document.getElementById(l);if(!r)return;const d=r.querySelector(".message-response pre"),u=d?d.textContent:((v=r.querySelector(".message-response"))==null?void 0:v.textContent)||"";navigator.clipboard.writeText(u).catch(()=>{})})}),document.querySelectorAll("[data-expand]").forEach(n=>{n.addEventListener("click",()=>{const l=n.dataset.expand,r=document.getElementById(l);if(!r)return;const d=r.querySelector(".message-response pre.collapsible");d&&d.classList.remove("collapsible"),n.remove()})}),document.querySelectorAll("[data-rerun]").forEach(n=>{n.addEventListener("click",()=>{const l=n.dataset.rerun,r=document.getElementById("messageText");r&&(r.value=l),m="messages",p(c)})});const t=document.getElementById("rerunLast");t&&t.addEventListener("click",()=>{const n=c&&c.messages?c.messages[0]:null;if(n&&n.message){const l=document.getElementById("messageText");l&&(l.value=n.message)}}),(o=document.getElementById("dispatchAgent"))==null||o.addEventListener("click",async()=>{var r;const n=document.getElementById("agentTaskText"),l=(r=n==null?void 0:n.value)==null?void 0:r.trim();if(l)try{const d=await Q(l);d.task_id&&z(d.task_id)}catch(d){g=d.message,p(c)}})}function T(t,e){M.innerHTML=`
    <header>
      <div>
        <h1>nulm control plane</h1>
        <div class="muted">${s(t)}</div>
      </div>
      <button id="refresh" ${A?"disabled":""}>
        ${A?"Refreshing":"Refresh"}
      </button>
    </header>
    <main>
      ${e}
    </main>
  `,lt()}function p(t){if(!t){T("Loading dashboard state...",'<div class="empty">Loading...</div>');return}T(t.state_dir||"",`
      ${g?`<div class="notice danger">${s(g)}</div>`:""}
      ${Y(t)}
      <div class="metrics">${V(t)}</div>
      ${Z()}
      ${ot(t)}
    `)}async function $({showLoading:t=!0}={}){t&&!c?p(null):c&&(A=!0,p(c));try{c=await J(),g=""}catch(e){if(g=e.message,!c){T("Dashboard API unavailable",`<div class="empty">${s(e.message)}</div>`);return}}finally{A=!1}p(c)}$();
