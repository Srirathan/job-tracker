/**
 * Job Tracker — Sheet ↔ API
 *
 * Script properties (Project Settings → Script properties):
 *   SHEET_SYNC_TOKEN — same as Render SHEET_SYNC_TOKEN
 * Optional:
 *   SHEET_API_URL — default …/api/applications/sheet-update
 *   SHEET_RECONCILE_URL — default …/api/applications/sheet-reconcile
 *
 * One-time: run installSheetChangeTrigger() once (▶ Run), then check
 * Triggers — you should see "On change" → onSheetChange.
 * Simple onEdit still works without that; row DELETE needs the installable trigger.
 */

function sheetDateToIso(rawValue, displayValue) {
  if (rawValue instanceof Date && !isNaN(rawValue.getTime())) {
    return Utilities.formatDate(rawValue, Session.getScriptTimeZone(), 'yyyy-MM-dd');
  }
  var s = String(displayValue || '').trim();
  return s.slice(0, 10);
}

function getApplicationsSheet_() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName('Applications');
  if (sh) return sh;
  var sheets = ss.getSheets();
  for (var i = 0; i < sheets.length; i++) {
    if (String(sheets[i].getName()).toLowerCase() === 'applications') return sheets[i];
  }
  return null;
}

function getReconcileUrl_(props) {
  var u = String(props.getProperty('SHEET_RECONCILE_URL') || '').trim();
  if (u) return u;
  var base = String(props.getProperty('SHEET_API_URL') || '').trim();
  if (base && base.indexOf('sheet-update') >= 0) return base.replace('sheet-update', 'sheet-reconcile');
  return 'https://job-tracker-9uq8.onrender.com/api/applications/sheet-reconcile';
}

/**
 * Collect {company, role} for each data row (11..lastRow) where both B and C are non-empty.
 */
function collectSheetPairs_(sh) {
  var lastRow = sh.getLastRow();
  if (lastRow < 11) {
    return { rows: [], confirm_empty: true };
  }
  var pairs = [];
  var values = sh.getRange(11, 2, lastRow, 3).getDisplayValues();
  for (var i = 0; i < values.length; i++) {
    var company = String(values[i][0] || '').trim();
    var role = String(values[i][1] || '').trim();
    if (company && role) pairs.push({ company: company, role: role });
  }
  return { rows: pairs, confirm_empty: false };
}

function pushSheetReconcileToApi_() {
  var sh = getApplicationsSheet_();
  if (!sh) {
    Logger.log('sheet-reconcile: no Applications sheet');
    return;
  }

  var props = PropertiesService.getScriptProperties();
  var token = String(props.getProperty('SHEET_SYNC_TOKEN') || '').trim();
  if (!token) {
    Logger.log('sheet-reconcile: missing SHEET_SYNC_TOKEN');
    return;
  }

  var collected = collectSheetPairs_(sh);
  var spreadsheetId = sh.getParent().getId();
  var payload = {
    spreadsheet_id: spreadsheetId,
    rows: collected.rows,
    confirm_empty: collected.confirm_empty,
  };

  var apiUrl = getReconcileUrl_(props);
  var response = UrlFetchApp.fetch(apiUrl, {
    method: 'post',
    contentType: 'application/json',
    headers: { 'X-Sheet-Token': token },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true,
  });

  var code = response.getResponseCode();
  var body = response.getContentText();
  if (code !== 200) {
    Logger.log('sheet-reconcile HTTP ' + code + ' ' + body);
    return;
  }
  Logger.log('sheet-reconcile OK ' + body);
}

/**
 * Installable trigger only (run installSheetChangeTrigger once).
 */
function onSheetChange(e) {
  if (!e) return;
  if (String(e.changeType) !== 'REMOVE_ROW') return;

  var sh = getApplicationsSheet_();
  if (!sh) return;
  /** Event source may omit sheet; still reconcile whole Applications tab. */
  pushSheetReconcileToApi_();
}

/** Run once from the editor to register On change → onSheetChange. */
function installSheetChangeTrigger() {
  var ss = SpreadsheetApp.getActive();
  var existing = ScriptApp.getProjectTriggers();
  for (var i = 0; i < existing.length; i++) {
    if (existing[i].getHandlerFunction() === 'onSheetChange') return;
  }
  ScriptApp.newTrigger('onSheetChange').forSpreadsheet(ss).onChange().create();
}

function pushApplicationsRowToApi(row, sh) {
  sh = sh || getApplicationsSheet_();
  if (!sh) return 'no Applications sheet';

  if (row < 11) return 'row < 11';

  var company = String(sh.getRange(row, 2).getDisplayValue() || '').trim();
  var role = String(sh.getRange(row, 3).getDisplayValue() || '').trim();
  var status = String(sh.getRange(row, 4).getDisplayValue() || '').trim();

  if (!company || !role || !status) return 'skip incomplete row';

  var props = PropertiesService.getScriptProperties();
  var token = String(props.getProperty('SHEET_SYNC_TOKEN') || '').trim();
  if (!token) return 'missing SHEET_SYNC_TOKEN';

  var apiUrl =
    String(props.getProperty('SHEET_API_URL') || '').trim() ||
    'https://job-tracker-9uq8.onrender.com/api/applications/sheet-update';

  var spreadsheetId = sh.getParent().getId();
  var dateRaw = sh.getRange(row, 1).getValue();
  var dateDisp = sh.getRange(row, 1).getDisplayValue();
  var dateIso = sheetDateToIso(dateRaw, dateDisp);

  var payload = {
    row_number: row,
    company: company,
    role: role,
    status: status,
    spreadsheet_id: spreadsheetId,
  };
  if (dateIso && dateIso.length >= 8) payload.date = dateIso;

  var response = UrlFetchApp.fetch(apiUrl, {
    method: 'put',
    contentType: 'application/json',
    headers: { 'X-Sheet-Token': token },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true,
  });

  var code = response.getResponseCode();
  var body = response.getContentText();
  if (code !== 200) {
    Logger.log('sheet-update HTTP ' + code + ' ' + body);
    return 'HTTP ' + code;
  }
  Logger.log('sheet-update OK row ' + row + ' ' + body);
  return 'OK';
}

function onEdit(e) {
  if (!e || !e.range) return;

  var sh = e.range.getSheet();
  if (String(sh.getName()).toLowerCase() !== 'applications') return;

  var row = e.range.getRow();
  var col = e.range.getColumn();

  if (row < 11) return;
  if (col < 1 || col > 4) return;

  pushApplicationsRowToApi(row, sh);
}

function debugPushRow22() {
  var msg = pushApplicationsRowToApi(22);
  Logger.log('debugPushRow22: ' + msg);
}
