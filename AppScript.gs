/**
 * Job Tracker — Sheet ↔ API sync (row ≥ 11 on tab "Applications").
 * Edits in columns A–D update or create an application row in the backend.
 *
 * Install: Extensions → Apps Script → paste → Save.
 *
 * Script properties (Project Settings → Script properties):
 *   SHEET_SYNC_TOKEN  — same value as SHEET_SYNC_TOKEN on Render.
 * Optional:
 *   SHEET_API_URL     — default https://job-tracker-9uq8.onrender.com/api/applications/sheet-update
 */

/**
 * Prefer a real Date from the cell; fallback to displayed text (expects YYYY-MM-DD start).
 */
function sheetDateToIso(rawValue, displayValue) {
  if (rawValue instanceof Date && !isNaN(rawValue.getTime())) {
    return Utilities.formatDate(rawValue, Session.getScriptTimeZone(), 'yyyy-MM-dd');
  }
  var s = String(displayValue || '').trim();
  return s.slice(0, 10);
}

function onEdit(e) {
  if (!e || !e.range) return;

  var sh = e.range.getSheet();
  if (sh.getName() !== 'Applications') return;

  var row = e.range.getRow();
  var col = e.range.getColumn();

  if (row < 11) return;
  /** Columns A–D (date, company, role, status). Notes / other cols ignored. */
  if (col < 1 || col > 4) return;

  var company = String(sh.getRange(row, 2).getDisplayValue() || '').trim();
  var role = String(sh.getRange(row, 3).getDisplayValue() || '').trim();
  var status = String(sh.getRange(row, 4).getDisplayValue() || '').trim();

  /** Need full row before creating/updating DB; empty status exits (mid-edit clear). */
  if (!company || !role || !status) return;

  var props = PropertiesService.getScriptProperties();
  var token = props.getProperty('SHEET_SYNC_TOKEN');
  if (!token) {
    Logger.log('Apps Script: set Script property SHEET_SYNC_TOKEN');
    return;
  }

  var apiUrl =
    props.getProperty('SHEET_API_URL') ||
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
  if (dateIso && dateIso.length >= 8) {
    payload.date = dateIso;
  }

  var response = UrlFetchApp.fetch(apiUrl, {
    method: 'put',
    contentType: 'application/json',
    headers: { 'X-Sheet-Token': token },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true,
  });

  var code = response.getResponseCode();
  if (code !== 200) {
    Logger.log(
      'sheet-update failed HTTP ' + code + ' body=' + response.getContentText()
    );
  }
}
