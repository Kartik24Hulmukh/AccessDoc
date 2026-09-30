'use strict';
const $ = selector => document.querySelector(selector);
const form = $('#report-form'), errors = $('#errors'), progress = $('#progress');
const button = $('#generate'), result = $('#result'), download = $('#download');
const remediationButton = $('#remediate'), cancelButton = $('#cancel');
let revision = 0, active = null, bundleUrl = null, successful = null;
$('#date').value = new Date().toISOString().slice(0, 10);

function abortError() { return new DOMException('Cancelled', 'AbortError'); }
function guard(operation) {
  if (active !== operation || operation.revision !== revision || operation.controller.signal.aborted) throw abortError();
}
// File.text() cannot itself be stopped. Stop waiting and guard its completion instead.
function abortable(promise, signal) {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(abortError());
    const abort = () => reject(abortError());
    signal.addEventListener('abort', abort, {once: true});
    promise.then(value => { signal.removeEventListener('abort', abort); signal.aborted ? reject(abortError()) : resolve(value); },
      error => { signal.removeEventListener('abort', abort); reject(error); });
  });
}
function delay(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(abortError());
    const abort = () => { clearTimeout(timer); reject(abortError()); };
    const timer = setTimeout(() => { signal.removeEventListener('abort', abort); resolve(); }, ms);
    signal.addEventListener('abort', abort, {once: true});
  });
}
function invalidateGuidance() {
  $('#remediation-out').hidden = true;
  $('#remediation-text').textContent = '';
  $('#remediation-meta').textContent = '';
}
function refreshControls() {
  button.disabled = !!active;
  button.textContent = active?.kind === 'bundle' ? 'Generating report bundle…' : 'Generate report bundle';
  cancelButton.disabled = !active;
  remediationButton.disabled = !!active || !successful || successful.revision !== revision;
  if (successful) {
    $('#result-context').textContent = `Last successful bundle: ${successful.client} · ${successful.source} · revision ${successful.revision}.` +
      (successful.revision !== revision ? ' Inputs have changed; this download is for the previous report. Generate again for current inputs and guidance.' : ' Matches current inputs.');
  }
}
function stopOperation(message = '') {
  if (active) active.controller.abort();
  active = null;
  progress.hidden = true;
  $('#remediation-status').hidden = true;
  $('#operation-status').textContent = message;
  refreshControls();
}
function revisionChanged() {
  revision += 1;
  invalidateGuidance();
  const pending = !!active;
  stopOperation(pending ? 'Inputs changed. Browser waiting and retries stopped; already accepted server work may still finish.' : '');
}
function beginOperation(kind) {
  stopOperation();
  errors.hidden = true;
  const operation = {kind, revision, controller: new AbortController()};
  active = operation;
  refreshControls();
  return operation;
}
function finishOperation(operation) {
  if (active === operation) stopOperation();
}
function showError(message, heading = 'Report not generated') {
  errors.replaceChildren();
  const strong = document.createElement('strong');
  strong.textContent = heading;
  const p = document.createElement('p');
  p.textContent = String(message);
  errors.append(strong, p);
  errors.hidden = false;
  errors.focus();
}
function clearBundle() {
  if (bundleUrl) URL.revokeObjectURL(bundleUrl);
  bundleUrl = null;
  download.removeAttribute('href');
}
function startDownload(blob) {
  // Replacement succeeds before the last good URL is discarded.
  const next = URL.createObjectURL(blob);
  clearBundle();
  bundleUrl = next;
  download.href = bundleUrl;
  download.download = 'accessdoc-report-bundle.zip';
  const a = document.createElement('a');
  a.href = bundleUrl;
  a.download = download.download;
  document.body.appendChild(a);
  a.click();
  a.remove();
}
function captureInputs() {
  return Object.freeze({
    revision, client: $('#client').value, date: $('#date').value, agency: $('#agency').value,
    color: $('#color').value, format: $('#format').value, pasted: $('#scanner').value.trim(),
    file: $('#evidence-file').files[0], logo: $('#logo').files[0], manual: $('#manual').value,
    key: $('#api-key').value
  });
}
async function effectiveEvidence(inputs, operation) {
  guard(operation);
  const file = inputs.file;
  if (file && file.size > 2000000) throw new Error('File exceeds 2000 KB');
  const scanner = file ? await abortable(file.text(), operation.controller.signal) : inputs.pasted;
  guard(operation);
  if (!scanner.trim()) throw new Error('Paste or upload scanner evidence.');
  return Object.freeze({scanner, source: file ? file.name : 'pasted-evidence'});
}
function logoData(file, operation) {
  if (!file) return Promise.resolve('');
  if (file.size > 500000) return Promise.reject(new Error('Logo exceeds 500 KB'));
  if (file.type !== 'image/png') return Promise.reject(new Error('Logo must be a PNG'));
  return new Promise((resolve, reject) => {
    const signal = operation.controller.signal, reader = new FileReader();
    if (signal.aborted) return reject(abortError());
    const abort = () => { reader.abort(); reject(abortError()); };
    const cleanup = () => signal.removeEventListener('abort', abort);
    signal.addEventListener('abort', abort, {once: true});
    reader.onload = () => { cleanup(); signal.aborted ? reject(abortError()) : resolve(reader.result); };
    reader.onerror = () => { cleanup(); reject(new Error('Logo could not be read')); };
    reader.onabort = () => { cleanup(); reject(abortError()); };
    reader.readAsDataURL(file);
  });
}
function headers(key, accept) {
  return {'Content-Type': 'application/json', ...(accept ? {'Accept': accept} : {}), ...(key ? {'Authorization': 'Bearer ' + key} : {})};
}
function syncFiles() {
  $('#file-name').textContent = $('#evidence-file').files[0]?.name || 'No file selected';
  $('#scanner').required = !$('#evidence-file').files.length;
  $('#logo-name').textContent = $('#logo').files[0]?.name || 'No logo selected';
}
// Every action binds to a snapshot taken before any asynchronous read or request.
form.addEventListener('input', revisionChanged);
form.addEventListener('change', () => { syncFiles(); revisionChanged(); });
$('#color').addEventListener('input', event => { $('#color-value').textContent = event.target.value.toUpperCase(); });
cancelButton.addEventListener('click', () => stopOperation('Cancelled browser waiting and retries. Already accepted server work may still finish.'));
$('#new-report').addEventListener('click', () => {
  stopOperation();
  revision += 1;
  form.reset();
  // Explicitly clear private fields, including values a browser might have autofilled.
  for (const id of ['api-key', 'client', 'agency', 'scanner', 'manual', 'evidence-file', 'logo']) $('#' + id).value = '';
  $('#date').value = new Date().toISOString().slice(0, 10);
  $('#color-value').textContent = $('#color').value.toUpperCase();
  syncFiles();
  invalidateGuidance();
  clearBundle();
  successful = null;
  result.hidden = true;
  $('#summary').replaceChildren();
  $('#result-context').textContent = '';
  $('#remediation-status').textContent = '';
  errors.replaceChildren();
  errors.hidden = true;
  $('#operation-status').textContent = 'New report. Private form fields and page outputs cleared; browser waiting and retries stopped. Already accepted server work may still finish.';
  refreshControls();
  $('#client').focus();
});
$('#sample').addEventListener('click', async () => {
  const operation = beginOperation('sample');
  try {
    const response = await fetch('/sample/axe-sample.json', {signal: operation.controller.signal});
    if (!response.ok) throw new Error('Sample could not be loaded');
    const text = await response.text();
    guard(operation);
    finishOperation(operation);
    $('#evidence-file').value = '';
    $('#scanner').value = text;
    $('#format').value = 'axe';
    $('#client').value = 'Northstar Community Bank';
    $('#agency').value = 'Inclusive Studio';
    syncFiles();
    revisionChanged();
    $('#scanner').focus();
  } catch (error) {
    if (active === operation && error.name !== 'AbortError') showError(error.message, 'Sample not loaded');
  } finally { finishOperation(operation); }
});
form.addEventListener('submit', async event => {
  event.preventDefault();
  if (active) return;
  errors.hidden = true;
  if (!form.reportValidity()) { showError('Complete the required fields before generating the report.'); return; }
  const inputs = captureInputs(), operation = beginOperation('bundle');
  invalidateGuidance();
  progress.hidden = false;
  progress.textContent = 'Generating and validating the report bundle…';
  try {
    const evidence = await effectiveEvidence(inputs, operation);
    const logo = await logoData(inputs.logo, operation);
    guard(operation);
    const payload = {client_name: inputs.client, audit_date: inputs.date, agency_name: inputs.agency,
      primary_color: inputs.color, format_hint: inputs.format, scanner_input: evidence.scanner,
      source_filename: evidence.source, manual_findings: inputs.manual, logo_data_url: logo};
    const options = {method: 'POST', headers: headers(inputs.key, 'application/zip'), body: JSON.stringify(payload), signal: operation.controller.signal};
    let response = await fetch('/api/bundle', options);
    guard(operation);
    if (response.status === 429) {
      const raw = parseInt(response.headers.get('Retry-After') || '5', 10);
      const wait = Math.max(0, Math.min(Number.isFinite(raw) ? raw : 5, 15));
      progress.textContent = `Rate limit reached — retrying in ${wait}s…`;
      await delay(wait * 1000, operation.controller.signal);
      guard(operation);
      response = await fetch('/api/bundle', options);
      guard(operation);
    }
    const type = (response.headers.get('Content-Type') || '').toLowerCase();
    if (!response.ok) {
      let message = 'Generation failed';
      if (type.includes('json')) {
        const data = await response.json();
        message = data.title || (typeof data.error === 'string' ? data.error : data.error?.message) || message;
      }
      throw new Error(message);
    }
    if (!type.includes('application/zip')) throw new Error('The server returned an unexpected response.');
    const blob = await response.blob();
    guard(operation);
    if (!blob.size) throw new Error('The generated bundle was empty.');
    // Retain evidence identity, not credentials or private branding fields, for matching guidance.
    successful = Object.freeze({revision: inputs.revision, client: inputs.client, source: evidence.source, scanner: evidence.scanner});
    startDownload(blob);
    $('#summary').replaceChildren();
    const stats = [
      [response.headers.get('X-AccessDoc-Finding-Count') || '0', 'finding groups'],
      [response.headers.get('X-AccessDoc-Instance-Count') || '0', 'instances'],
      [response.headers.get('X-AccessDoc-Unmapped-Count') || '0', 'unmapped'],
      [Math.max(1, Math.round(blob.size / 1024)) + ' KB', 'bundle']
    ];
    for (const [value, label] of stats) {
      const cell = document.createElement('div'), strong = document.createElement('strong');
      strong.textContent = value;
      cell.append(strong, document.createTextNode(' ' + label));
      $('#summary').append(cell);
    }
    result.hidden = false;
    refreshControls();
    $('#result-title').focus();
  } catch (error) {
    if (active === operation && error.name !== 'AbortError') showError(error.message);
  } finally { finishOperation(operation); }
});
remediationButton.addEventListener('click', async () => {
  if (active || !successful || successful.revision !== revision) return;
  const evidence = successful, inputs = captureInputs(), operation = beginOperation('remediation');
  invalidateGuidance();
  const status = $('#remediation-status');
  status.hidden = false;
  status.textContent = 'Requesting remediation plan…';
  try {
    let parsed;
    try { parsed = JSON.parse(evidence.scanner); } catch (_) { throw new Error('Remediation needs valid axe-core JSON.'); }
    const response = await fetch('/api/remediate', {method: 'POST', headers: headers(inputs.key),
      body: JSON.stringify({scanner_input: parsed, client_name: evidence.client}), signal: operation.controller.signal});
    const data = await response.json().catch(() => ({}));
    guard(operation);
    if (!response.ok) throw new Error((data.error && (data.error.message || data.error)) || `Remediation unavailable (${response.status})`);
    $('#remediation-text').textContent = data.guidance || '';
    $('#remediation-meta').textContent = `${evidence.client} · ${evidence.source} · revision ${evidence.revision}. ` +
      (data.fallback ? '⚠ Locally generated fallback guidance; upstream calls may have failed or been skipped. ' : 'Model: ' + (data.model || 'unknown') + ' · ') +
      (data.latency_ms ? Math.round(data.latency_ms) + ' ms · ' : '') + (data.violations_considered || 0) +
      ' violations considered' + (data.violations_received !== undefined ? ' of ' + data.violations_received + ' bounded findings received' : '') + '. Advisory only — verify with a qualified accessibility professional.';
    $('#remediation-out').hidden = false;
  } catch (error) {
    if (active === operation && error.name !== 'AbortError') showError(error.message, 'Remediation plan not generated');
  } finally { finishOperation(operation); }
});
window.addEventListener('beforeunload', () => { stopOperation(); clearBundle(); });
refreshControls();
