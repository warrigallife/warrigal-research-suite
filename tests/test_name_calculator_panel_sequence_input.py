import unittest
from unittest import mock

from warrigal.name_calculator_panel import NameCalculatorPanel


class ResolveSequenceInputTests(unittest.TestCase):
    """Covers the connection between the Name Calculator's mapped sequence
    and the shared numeric input the Sequence & Multiplication / Repeated
    Multiplication sections consume.

    A real `NameCalculatorPanel` is built for each test (this repo already
    establishes, in earlier sessions, that building/driving the actual
    Tkinter window headlessly-but-for-real is how this panel's behaviour is
    verified -- there is no mocked/simulated UI layer here)."""

    def setUp(self):
        # Error/info dialogs are real, modal `tkinter.messagebox` windows --
        # patched out so a genuinely-empty-input test cannot block this
        # test run waiting for someone to click "OK".
        self._messagebox_patchers = [
            mock.patch("warrigal.name_calculator_panel.messagebox.showerror"),
            mock.patch("warrigal.name_calculator_panel.messagebox.showinfo"),
        ]
        for patcher in self._messagebox_patchers:
            patcher.start()

        self.panel = NameCalculatorPanel()
        self.panel.update()

    def tearDown(self):
        self.panel.destroy()
        for patcher in self._messagebox_patchers:
            patcher.stop()

    def _calculate(self, text: str) -> None:
        self.panel.input_text.delete("1.0", "end")
        self.panel.input_text.insert("1.0", text)
        self.panel.calculate()

    def test_fill_then_generate_reproduces_the_reported_scenario(self):
        self._calculate("LIAM")
        self.panel.fill_sequence_from_calculator()

        self.panel.multiplication_multiplier.set("6")
        self.panel.multiplication_repetitions.set("3")
        self.panel.compute_multiplication()

        self.assertIsNotNone(self.panel.multiplication_result)
        self.assertEqual(self.panel.multiplication_result.values, [30, 9, 1, 40])
        self.assertEqual(
            self.panel.multiplication_result.stages[-1], [6480, 1944, 216, 8640]
        )
        self.assertEqual(self.panel.multiplication_result.source, "calculator_output")

    def test_generator_recovers_when_the_shared_box_reads_empty_after_a_fill(self):
        """Directly reproduces the reported symptom: the box was filled from
        the calculator, but is empty at the moment "Generate stages" reads
        it. The connection must still resolve to the calculator's sequence
        instead of raising "Enter one or more numbers"."""
        self._calculate("LIAM")
        self.panel.fill_sequence_from_calculator()

        self.panel.sequence_input.delete("1.0", "end")
        self.assertEqual(self.panel.sequence_input.get("1.0", "end").strip(), "")

        self.panel.multiplication_multiplier.set("6")
        self.panel.multiplication_repetitions.set("3")
        self.panel.compute_multiplication()

        self.assertIsNotNone(self.panel.multiplication_result)
        self.assertEqual(self.panel.multiplication_result.values, [30, 9, 1, 40])
        self.assertEqual(self.panel.multiplication_result.source, "calculator_output")

    def test_the_six_operations_section_shares_the_same_recovery(self):
        self._calculate("LIAM")
        self.panel.fill_sequence_from_calculator()
        self.panel.sequence_input.delete("1.0", "end")

        self.panel.sequence_operation.set("Sum")
        self.panel.compute_sequence()

        self.assertIsNotNone(self.panel.sequence_result)
        self.assertEqual(self.panel.sequence_result.output, [80])
        self.assertEqual(self.panel.sequence_result.source, "calculator_output")

    def test_manual_input_with_no_prior_fill_is_unaffected(self):
        self.panel.sequence_input.delete("1.0", "end")
        self.panel.sequence_input.insert("1.0", "4")
        self.panel.multiplication_multiplier.set("10")
        self.panel.multiplication_repetitions.set("4")
        self.panel.compute_multiplication()

        self.assertIsNotNone(self.panel.multiplication_result)
        self.assertEqual(self.panel.multiplication_result.source, "manual")
        self.assertEqual(
            self.panel.multiplication_result.stages,
            [[4], [40], [400], [4000], [40000]],
        )

    def test_genuinely_empty_input_with_no_fill_still_reports_no_result(self):
        self.panel.sequence_input.delete("1.0", "end")
        self.panel.compute_multiplication()

        self.assertIsNone(self.panel.multiplication_result)
        self.assertEqual(self.panel.multiplication_output.get("1.0", "end").strip(), "")


if __name__ == "__main__":
    unittest.main()
