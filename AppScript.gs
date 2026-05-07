/**
 * Job Tracker — Sheet → API (tab "Applications", data rows ≥ 11, columns A–D).
 *
 * Script properties (gear icon → Project Settings → Script properties):
 *   SHEET_SYNC_TOKEN — same as Render env SHEET_SYNC_TOKEN (no extra spaces).
 * Optional:
 *   SHEET_API_URL — default https://job-tracker-9uq8.onrender.com/api/applications/sheet-update
 */

function sheetDateToIso(rawValue, displayValue) {
  if (rawValue instanceof Date && !isNaN(rawValue.getTime())) {
    return Utilities.formatDate(rawValue, Session.getScriptTimeZone(), 'yyyy-MM-dd');
  }
  var s = String(displayValue || '').trim();
  return s.slice(0, 10);
}

/**
 * Push one data row to the backend if Date, Company, Role, and Status are all set.
 * @param {number} row 1-based row index (must be ≥ 11)
 * @param {GoogleAppsScript.Spreadsheet.Sheet} sh optional sheet (default: active Applications sheet)
 * @return {string} short result for logging
 */
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

/**
 * Run once from the editor (▶) after selecting the script: pushes row 22 to the API.
 * Change the row number if you tested on another line.
 */
function debugPushRow22() {
  var msg = pushApplicationsRowToApi(22);
  Logger.log('debugPushRow22: ' + msg);
}
