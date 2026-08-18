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


if __name__ == "__main__":
    unittest.main()
