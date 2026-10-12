import os
import unittest
from unittest.mock import Mock

import gspread

os.environ.setdefault("GROQ_API_KEY", "gsk_test")

import create_charts_user2 as charts


def make_spreadsheet(has_chart=False, charts_exist=True, productos_exist=True, locale="en_US"):
    productos = Mock(title="Productos_2")
    productos.col_values.return_value = ["Fecha", 46000, 46001]
    charts_sheet = Mock(id=7)
    charts_sheet.acell.return_value = Mock(value="2026-10")

    spreadsheet = Mock(locale=locale)

    def worksheet(name):
        if name == "Productos_2" and productos_exist:
            return productos
        if name == charts.CHARTS_TAB and charts_exist:
            return charts_sheet
        raise gspread.exceptions.WorksheetNotFound

    spreadsheet.worksheet.side_effect = worksheet
    spreadsheet.add_worksheet.return_value = charts_sheet
    spreadsheet.fetch_sheet_metadata.return_value = {
        "sheets": [
            {"properties": {"sheetId": 7}, **({"charts": [{"chartId": 1}]} if has_chart else {})}
        ]
    }
    return spreadsheet, charts_sheet, productos


def request_names(spreadsheet):
    requests = spreadsheet.batch_update.call_args.args[0]["requests"]
    return [next(iter(r)) for r in requests]


def sent_formulas(spreadsheet):
    requests = spreadsheet.batch_update.call_args.args[0]["requests"]
    return [
        r["updateCells"]["rows"][0]["values"][0]["userEnteredValue"]["formulaValue"]
        for r in requests
        if "updateCells" in r
    ]


class FormulaTests(unittest.TestCase):
    def test_table_formula_reads_products_tab_and_selected_month(self):
        formula = charts.table_formula("Productos_2")

        self.assertTrue(formula.startswith("=QUERY(ARRAYFORMULA({'Productos_2'!E2:E,"))
        self.assertIn("sum(Col2)", formula)
        self.assertIn("$B$1", formula)
        self.assertIn("limit 40", formula)

    def test_months_formula_reads_fecha_column(self):
        self.assertIn("'Productos_2'!B2:B", charts.months_formula("Productos_2"))


class LocalizeFormulaTests(unittest.TestCase):
    def test_us_locale_is_unchanged(self):
        formula = '=IF(A1,TEXT(B1,"yyyy-mm"),{1,2})'
        self.assertEqual(charts.localize_formula(formula, "en_US"), formula)

    def test_es_ar_uses_semicolons_and_backslash_for_array_columns(self):
        formula = '=QUERY({A1:A,TEXT(B1:B,"yyyy-mm")},"select Col1, sum(Col2)",0)'

        result = charts.localize_formula(formula, "es_AR")

        self.assertEqual(
            result, '=QUERY({A1:A\\TEXT(B1:B;"yyyy-mm")};"select Col1, sum(Col2)";0)'
        )


class CreateChartsTests(unittest.TestCase):
    def test_creates_tab_chart_dropdown_and_formulas(self):
        spreadsheet, _, _ = make_spreadsheet(charts_exist=False)

        charts.create_charts(spreadsheet, "Productos_2")

        spreadsheet.add_worksheet.assert_called_once()
        self.assertEqual(
            request_names(spreadsheet),
            ["setDataValidation", "updateCells", "updateCells", "addChart"],
        )
        requests = spreadsheet.batch_update.call_args.args[0]["requests"]
        self.assertEqual(requests[3]["addChart"]["chart"]["spec"]["basicChart"]["chartType"], "BAR")

    def test_second_run_does_not_add_another_chart(self):
        spreadsheet, _, _ = make_spreadsheet(has_chart=True)

        charts.create_charts(spreadsheet, "Productos_2")

        self.assertEqual(
            request_names(spreadsheet), ["setDataValidation", "updateCells", "updateCells"]
        )

    def test_keeps_selected_month_when_already_set(self):
        spreadsheet, charts_sheet, _ = make_spreadsheet()

        charts.create_charts(spreadsheet, "Productos_2")

        updated_ranges = [c.args[1] for c in charts_sheet.update.call_args_list]
        self.assertNotIn("B1", updated_ranges)

    def test_formulas_are_sent_in_the_sheet_locale(self):
        spreadsheet, _, _ = make_spreadsheet(locale="es_AR")

        charts.create_charts(spreadsheet, "Productos_2")

        months, table = sent_formulas(spreadsheet)
        self.assertIn('"yyyy-mm");', table)
        self.assertIn("\\", table)
        self.assertNotIn(",1,FALSE", months)

    def test_us_locale_formulas_keep_commas(self):
        spreadsheet, _, _ = make_spreadsheet(locale="en_US")

        charts.create_charts(spreadsheet, "Productos_2")

        months, table = sent_formulas(spreadsheet)
        self.assertEqual(months, charts.months_formula("Productos_2"))
        self.assertEqual(table, charts.table_formula("Productos_2"))

    def test_missing_products_tab_stops_without_changes(self):
        spreadsheet, _, _ = make_spreadsheet(productos_exist=False)

        with self.assertRaises(SystemExit):
            charts.create_charts(spreadsheet, "Productos_2")

        spreadsheet.batch_update.assert_not_called()
        spreadsheet.add_worksheet.assert_not_called()

    def test_warns_when_dates_are_text(self):
        spreadsheet, _, productos = make_spreadsheet()
        productos.col_values.return_value = ["Fecha", "03/10/2026", 46001]

        with self.assertLogs(charts.logger, level="WARNING") as logs:
            charts.create_charts(spreadsheet, "Productos_2")

        self.assertIn("text", logs.output[0])


if __name__ == "__main__":
    unittest.main()
