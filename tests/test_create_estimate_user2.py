import os
import unittest
from unittest.mock import Mock

import gspread

os.environ.setdefault("GROQ_API_KEY", "gsk_test")

import create_estimate_user2 as estimate


def make_spreadsheet(estimate_exists=True, summary_exists=True, locale="en_US"):
    sheet = Mock(id=9)
    spreadsheet = Mock(locale=locale)

    def worksheet(name):
        if name == "Summary_2" and summary_exists:
            return Mock()
        if name == estimate.ESTIMATE_TAB and estimate_exists:
            return sheet
        raise gspread.exceptions.WorksheetNotFound

    spreadsheet.worksheet.side_effect = worksheet
    spreadsheet.add_worksheet.return_value = sheet
    return spreadsheet, sheet


def sent_formulas(spreadsheet):
    requests = spreadsheet.batch_update.call_args.args[0]["requests"]
    return {
        (r["updateCells"]["start"]["rowIndex"], r["updateCells"]["start"]["columnIndex"]):
            r["updateCells"]["rows"][0]["values"][0]["userEnteredValue"]["formulaValue"]
        for r in requests
        if "updateCells" in r
    }


class FormulaTests(unittest.TestCase):
    def test_window_is_the_three_previous_months(self):
        self.assertIn("EDATE(TODAY(),-1)", estimate.month_name_formula(1))
        self.assertIn("EDATE(TODAY(),-3)", estimate.year_formula(3))
        self.assertIn('"Enero"', estimate.month_name_formula(1))
        self.assertIn('"Diciembre"', estimate.month_name_formula(1))

    def test_total_is_read_by_header_not_by_position(self):
        formula = estimate.total_column_formula("Summary_2")

        self.assertEqual(formula, "=MATCH(\"Total ($)\",'Summary_2'!$1:$1,0)")

    def test_estimate_averages_only_months_with_data(self):
        formula = estimate.estimate_formula()

        self.assertIn("SUMPRODUCT(C5:C7,D5:D7)/SUM(D5:D7)", formula)
        self.assertIn('"Sin datos"', formula)

    def test_category_estimate_does_not_use_the_chart_month(self):
        formula = estimate.category_estimate_formula(12, "Summary_2")

        self.assertNotIn("Charts_2", formula)
        self.assertEqual(formula.count("SUMIFS("), 3)


class CreateEstimateTests(unittest.TestCase):
    def test_creates_tab_and_writes_all_formulas(self):
        spreadsheet, _ = make_spreadsheet(estimate_exists=False)

        estimate.create_estimate(spreadsheet, "Summary_2")

        spreadsheet.add_worksheet.assert_called_once()
        formulas = sent_formulas(spreadsheet)
        self.assertIn((1, 7), formulas)                      # H2
        self.assertIn((estimate.ESTIMATE_ROW - 1, 2), formulas)
        self.assertEqual(len(formulas), 1 + 2 + 3 * 4 + 1 + 2 * estimate.MAX_CATEGORIES)

    def test_labels_show_the_next_month_name(self):
        spreadsheet, _ = make_spreadsheet()

        estimate.create_estimate(spreadsheet, "Summary_2")

        formulas = sent_formulas(spreadsheet)
        label = formulas[(estimate.ESTIMATE_ROW - 1, 0)]
        self.assertTrue(label.startswith('="Gasto estimado "&CHOOSE(MONTH(EDATE(TODAY(),1)),'))
        self.assertIn("EDATE(TODAY(),1)", formulas[(0, 0)])

    def test_existing_tab_is_reused(self):
        spreadsheet, _ = make_spreadsheet()

        estimate.create_estimate(spreadsheet, "Summary_2")

        spreadsheet.add_worksheet.assert_not_called()

    def test_formulas_follow_the_sheet_locale(self):
        spreadsheet, _ = make_spreadsheet(locale="es_AR")

        estimate.create_estimate(spreadsheet, "Summary_2")

        total = sent_formulas(spreadsheet)[(1, 7)]
        self.assertEqual(total, "=MATCH(\"Total ($)\";'Summary_2'!$1:$1;0)")

    def test_missing_summary_tab_stops_without_changes(self):
        spreadsheet, _ = make_spreadsheet(summary_exists=False)

        with self.assertRaises(SystemExit):
            estimate.create_estimate(spreadsheet, "Summary_2")

        spreadsheet.batch_update.assert_not_called()
        spreadsheet.add_worksheet.assert_not_called()


if __name__ == "__main__":
    unittest.main()
