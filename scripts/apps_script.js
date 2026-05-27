/**
 * Google Apps Script - Blog Writer Agent Webhook Trigger
 *
 * PURPOSE:
 *   Monitors the Google Sheet for status column (D) changes to "generate".
 *   When detected, sends a POST request to the FastAPI webhook server with
 *   row data (keyword, sub_keyword, outline) and API key authentication.
 *
 * SETUP INSTRUCTIONS:
 * ------------------------------------------------------------------
 * 1. INSTALLABLE TRIGGER (required — simple triggers CANNOT make HTTP calls):
 *    - Open your Google Sheet
 *    - Click Extensions > Apps Script
 *    - Paste this entire file into the editor
 *    - Click the clock icon (Triggers) in the left sidebar
 *    - Click "+ Add Trigger"
 *    - Function: onEditInstallable
 *    - Event source: From spreadsheet
 *    - Event type: On edit
 *    - Click Save (authorize when prompted)
 *
 * 2. SCRIPT PROPERTIES (secrets — never hardcode these):
 *    - In the Apps Script editor, click the gear icon (Project Settings)
 *    - Scroll down to "Script Properties"
 *    - Click "Add script property" for each:
 *        Property: WEBHOOK_URL  Value: https://your-server.com/api/generate
 *        Property: API_KEY      Value: your-secret-api-key
 *
 * NOTE: You MUST use an installable trigger, NOT a simple trigger.
 *       Simple onEdit() triggers run with restricted authorization and
 *       CANNOT call UrlFetchApp.fetch() to make external HTTP requests.
 *       Only installable triggers have the required authorization scope.
 * ------------------------------------------------------------------
 */

// Column index constants (1-based)
const STATUS_COL = 4;      // Column D: status ("generate", "done", etc.)
const KEYWORD_COL = 1;     // Column A: main keyword
const SUB_KEYWORD_COL = 2; // Column B: sub keyword(s)
const OUTLINE_COL = 3;     // Column C: article outline
const ERROR_COL = 14;      // Column N: error messages written by this script

const TRIGGER_VALUE = "generate"; // Value in status column that fires the webhook

/**
 * Installable onEdit trigger handler.
 *
 * Fires when any cell in the spreadsheet is edited. Only proceeds when:
 * - The edited cell is in the status column (D)
 * - The new value is exactly "generate"
 * - The row is not the header row (row 1)
 *
 * @param {GoogleAppsScript.Events.SheetsOnEdit} e - The edit event object.
 */
function onEditInstallable(e) {
  // Only act on edits to the status column (D)
  if (e.range.getColumn() !== STATUS_COL) return;

  // Only act when value is changed to "generate"
  if (e.value !== TRIGGER_VALUE) return;

  const row = e.range.getRow();

  // Skip header row
  if (row <= 1) return;

  const sheet = e.range.getSheet();

  // Collect row data
  const keyword = sheet.getRange(row, KEYWORD_COL).getValue();
  const sub_keyword = sheet.getRange(row, SUB_KEYWORD_COL).getValue() || "";
  const outline = sheet.getRange(row, OUTLINE_COL).getValue() || "";

  // Build payload
  const payload = {
    rows: [
      {
        row_number: row,
        keyword: keyword,
        sub_keyword: sub_keyword,
        outline: outline
      }
    ]
  };

  _sendWebhook(sheet, row, payload);
}

/**
 * Batch trigger function for manual use.
 *
 * Scans all data rows for status "generate" and sends them as a single
 * webhook payload. Run this manually from the Apps Script editor or a
 * custom menu to process multiple rows at once.
 *
 * Usage: Extensions > Apps Script > Select triggerBatch > Run
 */
function triggerBatch() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow <= 1) {
    Logger.log("No data rows found.");
    return;
  }

  const rows = [];

  for (let row = 2; row <= lastRow; row++) {
    const statusValue = sheet.getRange(row, STATUS_COL).getValue();
    if (statusValue === TRIGGER_VALUE) {
      const keyword = sheet.getRange(row, KEYWORD_COL).getValue();
      const sub_keyword = sheet.getRange(row, SUB_KEYWORD_COL).getValue() || "";
      const outline = sheet.getRange(row, OUTLINE_COL).getValue() || "";

      rows.push({
        row_number: row,
        keyword: keyword,
        sub_keyword: sub_keyword,
        outline: outline
      });
    }
  }

  if (rows.length === 0) {
    Logger.log("No rows with status 'generate' found.");
    return;
  }

  Logger.log("Found " + rows.length + " row(s) with status 'generate'. Sending batch webhook...");

  const payload = { rows: rows };

  // For batch mode, use the first matching row as the error target row
  // (errors from individual rows are not easily attributable in a batch call)
  const firstRow = rows[0].row_number;
  _sendWebhook(sheet, firstRow, payload);
}

/**
 * Internal helper: sends a POST webhook request with the given payload.
 * Reads WEBHOOK_URL and API_KEY from Script Properties.
 * Writes error details to column N of the specified row on failure.
 * Clears column N on success.
 *
 * @param {GoogleAppsScript.Spreadsheet.Sheet} sheet - The active sheet.
 * @param {number} errorRow - Row number to write errors to (column N).
 * @param {Object} payload - The JSON payload to send.
 */
function _sendWebhook(sheet, errorRow, payload) {
  // Load config from Script Properties (never hardcode secrets)
  const props = PropertiesService.getScriptProperties();
  const webhookUrl = props.getProperty("WEBHOOK_URL");
  const apiKey = props.getProperty("API_KEY");

  // Validate config exists
  if (!webhookUrl || !apiKey) {
    const configError = "Apps Script config missing: set WEBHOOK_URL and API_KEY in Script Properties";
    Logger.log(configError);
    sheet.getRange(errorRow, ERROR_COL).setValue(configError);
    return;
  }

  const options = {
    method: "post",
    contentType: "application/json",
    headers: { "X-API-Key": apiKey },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true // Prevent throw on non-200; handle manually below
  };

  try {
    const response = UrlFetchApp.fetch(webhookUrl, options);
    const responseCode = response.getResponseCode();

    if (responseCode !== 200) {
      // Write error details to column N
      const errorMessage = "Webhook error: HTTP " + responseCode + " - " + response.getContentText();
      Logger.log(errorMessage);
      sheet.getRange(errorRow, ERROR_COL).setValue(errorMessage);
    } else {
      // Success: clear any previous error in column N
      sheet.getRange(errorRow, ERROR_COL).clearContent();
      Logger.log("Webhook sent successfully. Row: " + errorRow + ", Response: " + response.getContentText());
    }
  } catch (err) {
    // Network or fetch error
    const errorMessage = "Webhook error: " + err.toString();
    Logger.log(errorMessage);
    sheet.getRange(errorRow, ERROR_COL).setValue(errorMessage);
  }
}
