import json
import unittest
from unittest.mock import Mock, call, patch

import gspread

from services import sheets_service


def api_error(status_code):
    response = Mock(status_code=status_code)
    response.json.return_value = {
        "error": {"code": status_code, "message": "test error", "status": "TEST"}
    }
    return gspread.exceptions.APIError(response)


class OpenSpreadsheetRetryTests(unittest.TestCase):
    @patch.object(sheets_service.time, "sleep")
    def test_retries_transient_error_then_returns_spreadsheet(self, sleep):
        spreadsheet = Mock()
        client = Mock()
        client.open_by_key.side_effect = [api_error(503), api_error(429), spreadsheet]

        result = sheets_service._open_spreadsheet_with_retry(client)

        self.assertIs(result, spreadsheet)
        self.assertEqual(client.open_by_key.call_count, 3)
        sleep.assert_has_calls([call(0.5), call(1.0)])

    @patch.object(sheets_service.time, "sleep")
    def test_raises_after_bounded_transient_attempts(self, sleep):
        client = Mock()
        client.open_by_key.side_effect = api_error(503)

        with self.assertRaises(gspread.exceptions.APIError):
            sheets_service._open_spreadsheet_with_retry(client)

        self.assertEqual(client.open_by_key.call_count, 3)
        sleep.assert_has_calls([call(0.5), call(1.0)])

    @patch.object(sheets_service.time, "sleep")
    def test_does_not_retry_non_transient_api_error(self, sleep):
        client = Mock()
        client.open_by_key.side_effect = api_error(403)

        with self.assertRaises(gspread.exceptions.APIError):
            sheets_service._open_spreadsheet_with_retry(client)

        client.open_by_key.assert_called_once_with(sheets_service.GOOGLE_SHEET_ID)
        sleep.assert_not_called()


class SpreadsheetCredentialTests(unittest.TestCase):
    @patch.object(sheets_service.gspread, "authorize")
    @patch.object(sheets_service.Credentials, "from_service_account_info")
    def test_malformed_inline_credentials_keep_existing_failure(self, from_info, authorize):
        with patch.object(sheets_service, "GOOGLE_SERVICE_ACCOUNT_JSON", "{not-json"):
            with self.assertRaises((OSError, json.JSONDecodeError)):
                sheets_service._get_spreadsheet()

        from_info.assert_not_called()
        authorize.assert_not_called()


class ProductosSheetTests(unittest.TestCase):
    def test_producto_row_includes_quantity_and_unit_price(self):
        item = {"name": "24 HUEVOS FRESCOS", "quantity": 2, "unit_price": 5.25, "price": 10.5}

        row = sheets_service._producto_row("L", "03/10/2026", "MERCADONA", "Supermercado", item)

        self.assertEqual(
            row,
            ["L", "03/10/2026", "MERCADONA", "Supermercado", "24 HUEVOS FRESCOS", 10.5, 2, 5.25],
        )

    def test_producto_row_defaults_quantity_to_one(self):
        row = sheets_service._producto_row("L", None, None, None, {"name": "Pan", "price": None})

        self.assertEqual(row, ["L", "", "", "", "Pan", "", 1, ""])

    def test_new_productos_tab_gets_full_header(self):
        spreadsheet = Mock()
        spreadsheet.worksheet.side_effect = gspread.exceptions.WorksheetNotFound
        sheet = spreadsheet.add_worksheet.return_value

        sheets_service._get_or_create_productos_sheet(spreadsheet, name="Productos_2")

        spreadsheet.add_worksheet.assert_called_once_with(title="Productos_2", rows=1000, cols=8)
        sheet.append_row.assert_called_once_with(sheets_service.PRODUCTOS_HEADER)

    def test_old_productos_tab_gets_missing_header_columns(self):
        sheet = Mock(col_count=6)
        sheet.row_values.return_value = sheets_service.PRODUCTOS_HEADER[:6]
        spreadsheet = Mock()
        spreadsheet.worksheet.return_value = sheet

        sheets_service._get_or_create_productos_sheet(spreadsheet)

        sheet.add_cols.assert_called_once_with(2)
        sheet.update.assert_called_once_with([["Cantidad", "Precio unitario"]], "G1")

    def test_complete_productos_header_is_left_alone(self):
        sheet = Mock(col_count=8)
        sheet.row_values.return_value = sheets_service.PRODUCTOS_HEADER
        spreadsheet = Mock()
        spreadsheet.worksheet.return_value = sheet

        sheets_service._get_or_create_productos_sheet(spreadsheet)

        sheet.update.assert_not_called()
        sheet.add_cols.assert_not_called()


if __name__ == "__main__":
    unittest.main()
