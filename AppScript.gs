/**
 * Job Tracker — two-way sync: editing Company (B), Role (C), or Status (D) on the
 * "Applications" sheet (row 11+) calls the API to update the database status.
 *
 * Install: Extensions → Apps Script → paste this file → Save → Run authorize once if prompted.
 *
 * Required Script property (Project Settings → Script properties):
 *   SHEET_SYNC_TOKEN  — exact copy of SHEET_SYNC_TOKEN from your Render backend env.
 *
 * Optional Script property:
 *   SHEET_API_URL     — default: https://job-tracker-9uq8.onrender.com/api/applications/sheet-update
 */

function onEdit(e) {
  if (!e || !e.range) return;

  var sh = e.range.getSheet();
  if (sh.getName() !== 'Applications') return;

  var row = e.range.getRow();
  var col = e.range.getColumn();

  if (row < 11) return;
  /** Company=B(2), Role=C(3), Status=D(4). Ignore A(Date), Notes, etc. */
  if (col !== 2 && col !== 3 && col !== 4) return;

  var company = String(sh.getRange(row, 2).getDisplayValue() || '').trim();
  var role = String(sh.getRange(row, 3).getDisplayValue() || '').trim();
  var status = String(sh.getRange(row, 4).getDisplayValue() || '').trim();

  if (!status) return;

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

  var payload = {
    row_number: row,
    company: company,
    role: role,
    status: status,
    spreadsheet_id: spreadsheetId,
  };

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
