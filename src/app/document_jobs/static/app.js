"use strict";
const byId = id => document.getElementById(id);
let token = null;
let config;
let polling = false;
let uploading = false;
let reviewController = null;
let reviewDirty = false;
const notice = message => { byId("notice").textContent = message; };
async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, ...(options.headers || {}) }, cache: "no-store" });
  const body = await response.json();
  if (!response.ok) {
    if (response.status === 401) logout();
    throw new Error(body.code || "Request failed");
  }
  return body;
}
function logout() {
  if (reviewDirty && !confirm("Sign out and discard unsaved review edits?")) return;
  closeReview();
  token = null;
  byId("workspace").hidden = true;
  byId("login").hidden = false;
  byId("logout").hidden = true;
  byId("jobs").replaceChildren();
}
function closeReview() {
  if (reviewController && typeof reviewController.unmount === "function") reviewController.unmount();
  reviewController = null;
  reviewDirty = false;
  byId("review-root").replaceChildren();
  byId("review-workspace").hidden = true;
  if (token) byId("workspace").hidden = false;
  if (location.hash.startsWith("#review=")) history.replaceState(null, "", location.pathname);
}
async function openReview(job) {
  if (!token) return;
  byId("workspace").hidden = true;
  byId("review-workspace").hidden = false;
  location.hash = `review=${encodeURIComponent(job.id)}`;
  try {
    const review = await import("/documents/review-assets/review.js");
    reviewController = review.mountReviewWorkspace(byId("review-root"), {
      jobId: job.id,
      filename: job.filename,
      getAccessToken: () => token,
      onAuthenticationRequired: () => {
        byId("login").hidden = false;
        notice("Your session expired. Sign in again; unsaved review edits remain in this tab.");
      },
      onDirtyChange: dirty => { reviewDirty = dirty; },
      onBack: () => {
        if (!reviewDirty || confirm("Discard unsaved review edits?")) {
          closeReview();
          refresh();
        }
      },
    });
  } catch (_) {
    byId("review-root").textContent = "The review workspace has not been built. Run npm --prefix frontend run build; original unreviewed downloads remain available.";
  }
}
byId("logout").onclick = logout;
byId("login").onsubmit = async event => {
  event.preventDefault();
  try {
    const response = await fetch(`https://cognito-idp.${config.region}.amazonaws.com/`, {
      method: "POST", headers: { "Content-Type": "application/x-amz-json-1.1", "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth" },
      body: JSON.stringify({ AuthFlow: "USER_PASSWORD_AUTH", ClientId: config.client_id, AuthParameters: { USERNAME: byId("username").value, PASSWORD: byId("password").value } })
    });
    const body = await response.json();
    if (!response.ok || !body.AuthenticationResult) throw new Error("Sign-in failed. Ask the operator to confirm your approved account and permanent password.");
    token = body.AuthenticationResult.AccessToken;
    byId("login").hidden = true;
    byId("logout").hidden = false;
    byId("workspace").hidden = Boolean(reviewController);
    notice("Signed in. Your access token stays in this tab's memory.");
    if (reviewController) return;
    await refresh();
    const reviewId = location.hash.startsWith("#review=") ? decodeURIComponent(location.hash.slice(8)) : null;
    if (reviewId) {
      const jobs = await api("/api/v1/documents/jobs");
      const job = jobs.find(item => item.id === reviewId);
      if (job) await openReview(job);
    }
  } catch (error) { notice(error.message); }
  finally { byId("password").value = ""; }
};
async function refresh() {
  if (!token || polling || reviewController) return;
  polling = true;
  try {
    const activeToken = token;
    const jobs = await api("/api/v1/documents/jobs");
    if (activeToken !== token) return;
    const fragment = document.createDocumentFragment();
    for (const job of jobs) {
      const row = document.createElement("article");
      const title = document.createElement("h2"); title.textContent = job.filename;
      const id = document.createElement("p"); id.className = "job-id"; id.textContent = job.id;
      const partial = job.phase === "PARTIAL_SUCCESS";
      const phase = document.createElement("p"); phase.textContent = `${partial ? "Partial result (PARTIAL_SUCCESS)" : job.phase}${job.pages_available === null ? "" : ` · ${job.pages_available} pages reported`}${job.error_code ? ` · ${job.error_code}` : ""}`;
      if (partial) phase.className = "partial-result";
      row.append(title, id, phase);
      if ((partial || job.phase === "SUCCEEDED") && job.warning_count > 0) {
        const warnings = document.createElement("p"); warnings.className = "conversion-warnings";
        warnings.textContent = `${job.warning_count} conversion warning${job.warning_count === 1 ? "" : "s"}. Details are available in the downloaded HTML; choose document.html for the full summary.`;
        row.append(warnings);
      }
      if (job.phase === "UPLOADING") {
        const start = document.createElement("button"); start.textContent = "Start uploaded PDF";
        start.onclick = async () => { try { await api(`/api/v1/documents/jobs/${job.id}/start`, {method:"POST"}); await refresh(); } catch(error) { notice(error.message); } };
        row.append(start);
      }
      if (job.phase === "FAILED") {
        const retry = document.createElement("button"); retry.textContent = "Resume if recoverable";
        retry.onclick = async () => { try { await api(`/api/v1/documents/jobs/${job.id}/retry`, {method:"POST"}); await refresh(); } catch(error) { notice(error.message); } };
        row.append(retry);
      }
      if (job.artifacts.length) {
        const select = document.createElement("select"); select.setAttribute("aria-label", "Artifact");
        for (const name of job.artifacts) { const option = document.createElement("option"); option.value = name; option.textContent = `Original · unreviewed · ${name}`; select.append(option); }
        const download = document.createElement("button"); download.textContent = "Download original · unreviewed";
        download.onclick = async () => {
          try {
            const result = await api(`/api/v1/documents/jobs/${job.id}/artifacts/${encodeURIComponent(select.value)}`);
            const link = document.createElement("a"); link.href = result.url; link.rel = "noreferrer"; link.click();
          } catch(error) { notice(error.message); }
        };
        row.append(select, download);
      }
      if ((job.phase === "SUCCEEDED" || job.phase === "PARTIAL_SUCCESS") && job.artifacts.includes("document.json")) {
        const review = document.createElement("button"); review.textContent = "Review";
        review.onclick = () => openReview(job);
        row.append(review);
      }
      fragment.append(row);
    }
    byId("jobs").replaceChildren(fragment);
  } catch(error) { notice(error.message); }
  finally { polling = false; }
}
async function upload(files) {
  if (!token || uploading) { notice("Wait for the current upload batch to finish."); return; }
  uploading = true;
  try {
    // Sequential direct-to-S3 uploads bound browser/network usage; accepted OCR jobs run concurrently.
    for (const file of files) {
      if (!file.name.toLowerCase().endsWith(".pdf") || file.size > config.max_pdf_bytes) {
        notice(`Skipped ${file.name}: PDF required, within the displayed size limit.`); continue;
      }
      notice(`Uploading ${file.name}…`);
      const grant = await api("/api/v1/documents/uploads", { method: "POST", body: JSON.stringify({filename:file.name, size_bytes:file.size}) });
      const form = new FormData();
      Object.entries(grant.fields).forEach(([key,value]) => form.append(key,value));
      form.append("file",file);
      const sent = await fetch(grant.url, {method:"POST",body:form});
      if (!sent.ok) throw new Error("S3 upload failed. Choose the file again to allocate a new upload.");
      await api(`/api/v1/documents/jobs/${grant.job_id}/start`, {method:"POST"});
      notice(`Accepted ${file.name}. Job ${grant.job_id}`);
      await refresh();
    }
  } catch(error) { notice(error.message); }
  finally { uploading = false; byId("files").value = ""; }
}
byId("files").onchange = event => upload(Array.from(event.target.files));
byId("drop").ondragover = event => event.preventDefault();
byId("drop").ondrop = event => { event.preventDefault(); upload(Array.from(event.dataTransfer.files)); };
byId("refresh").onclick = refresh;
fetch("/documents/config", {cache:"no-store"}).then(r => r.json()).then(value => {
  config = value;
  byId("limit").textContent = `Maximum PDF size: ${Math.floor(config.max_pdf_bytes / 1048576)} MiB. Multiple document jobs can run concurrently. HTML is provided as a download.`;
}).catch(() => notice("Could not load configuration."));
setInterval(refresh, 5000);
