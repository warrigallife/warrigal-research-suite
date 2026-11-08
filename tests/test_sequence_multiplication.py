import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from warrigal.sequence_multiplication import (
    DIGITAL_ROOT_9_EACH,
    DOUBLING_MULTIPLIER,
    MAX_MULTIPLIER,
    MAX_REPETITIONS,
    NODE18_ROOT_EACH,
    OPERATIONS,
    PRODUCT,
    RUNNING_PRODUCT,
    RUNNING_SUM,
    SUM,
    compute_multiplication_stages,
    compute_sequence_operation,
    generate_multiplication_stages,
    parse_number_sequence,
    save_multiplication_stages,
    save_sequence_result,
)


class ParseNumberSequenceTests(unittest.TestCase):
    def test_comma_separated_values(self):
        self.assertEqual(parse_number_sequence("1,2,3"), [1.0, 2.0, 3.0])

    def test_whitespace_separated_values(self):
        self.assertEqual(parse_number_sequence("1 2 3"), [1.0, 2.0, 3.0])

    def test_mixed_comma_and_whitespace(self):
        self.assertEqual(parse_number_sequence("1, 2, 3  4"), [1.0, 2.0, 3.0, 4.0])

    def test_empty_input_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Enter one or more numbers"):
            parse_number_sequence("   ")

    def test_non_numeric_token_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "not a number"):
            parse_number_sequence("1, two, 3")


class ComputeSequenceOperationTests(unittest.TestCase):
    def test_sum(self):
        result = compute_sequence_operation("1,2,3,4", SUM)
        self.assertEqual(result.output, [10])

    def test_product(self):
        result = compute_sequence_operation("1,2,3,4", PRODUCT)
        self.assertEqual(result.output, [24])

    def test_running_sum(self):
        result = compute_sequence_operation("1,2,3", RUNNING_SUM)
        self.assertEqual(result.output, [1, 3, 6])

    def test_running_product(self):
        result = compute_sequence_operation("1,2,3,4", RUNNING_PRODUCT)
        self.assertEqual(result.output, [1, 2, 6, 24])

    def test_digital_root_9_each_reuses_existing_function(self):
        result = compute_sequence_operation("9,10,18", DIGITAL_ROOT_9_EACH)
        self.assertEqual(result.output, [9, 1, 9])

    def test_node18_root_each_reuses_existing_function(self):
        result = compute_sequence_operation("18,19,36", NODE18_ROOT_EACH)
        self.assertEqual(result.output, [18, 1, 18])

    def test_unknown_operation_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "not an established sequence operation"):
            compute_sequence_operation("1,2,3", "Square each value")

    def test_result_is_deterministic_for_identical_input(self):
        first = compute_sequence_operation("5,5,5", SUM, created_at="2026-01-01T00:00:00+00:00")
        second = compute_sequence_operation("5,5,5", SUM, created_at="2026-06-01T00:00:00+00:00")
        self.assertEqual(first.result_id, second.result_id)
        self.assertNotEqual(first.created_at, second.created_at)

    def test_different_operation_on_same_input_has_different_id(self):
        sum_result = compute_sequence_operation("1,2,3", SUM)
        product_result = compute_sequence_operation("1,2,3", PRODUCT)
        self.assertNotEqual(sum_result.result_id, product_result.result_id)

    def test_retains_source_and_raw_input_for_provenance(self):
        result = compute_sequence_operation(
            "7,8,9",
            SUM,
            source="calculator_output",
            source_description="Fingerprint WRG-NAME-ABCDEF1234567890",
        )
        self.assertEqual(result.raw_input, "7,8,9")
        self.assertEqual(result.values, [7, 8, 9])
        self.assertEqual(result.source, "calculator_output")
        self.assertIn("WRG-NAME-", result.source_description)

    def test_all_declared_operations_are_computable(self):
        for operation in OPERATIONS:
            result = compute_sequence_operation("3,6,9", operation)
            self.assertTrue(result.output)


class SaveSequenceResultTests(unittest.TestCase):
    def test_save_is_atomic_and_reproducible(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = compute_sequence_operation("1,2,3", SUM)

            first_path = save_sequence_result(result, root=root)
            self.assertTrue(first_path.exists())
            self.assertFalse(first_path.with_suffix(".json.tmp").exists())

            second_path = save_sequence_result(result, root=root)
            self.assertEqual(first_path, second_path)

            saved_files = list(root.glob("*.json"))
            self.assertEqual(len(saved_files), 1)


class GenerateMultiplicationStagesTests(unittest.TestCase):
    """Covers the repeated-multiplication generator directly: stage 0 is the
    untouched input, each stage multiplies the previous one, and arbitrarily
    large integers are computed exactly."""

    def test_documented_example(self):
        stages = generate_multiplication_stages([4], 10, 4)
        self.assertEqual(stages, [[4], [40], [400], [4000], [40000]])

    def test_zero_repetitions_returns_only_stage_zero(self):
        stages = generate_multiplication_stages([4, 7], 10, 0)
        self.assertEqual(stages, [[4, 7]])

    def test_multiplier_zero(self):
        stages = generate_multiplication_stages([5, 9], 0, 3)
        self.assertEqual(stages, [[5, 9], [0, 0], [0, 0], [0, 0]])

    def test_multiplier_one_is_unchanged_at_every_stage(self):
        stages = generate_multiplication_stages([3, 6], 1, 5)
        self.assertTrue(all(stage == [3, 6] for stage in stages))

    def test_multiplier_two_doubling(self):
        stages = generate_multiplication_stages([1], DOUBLING_MULTIPLIER, 5)
        self.assertEqual(stages, [[1], [2], [4], [8], [16], [32]])

    def test_multiplier_ninety_nine_at_max_repetitions_is_exact(self):
        stages = generate_multiplication_stages([1], MAX_MULTIPLIER, MAX_REPETITIONS)
        self.assertEqual(len(stages), MAX_REPETITIONS + 1)
        expected_final = MAX_MULTIPLIER ** MAX_REPETITIONS
        self.assertEqual(stages[-1], [expected_final])
        # Confirms this is an exact Python int, not a float that has lost
        # precision or silently overflowed to inf.
        self.assertIsInstance(stages[-1][0], int)
        self.assertGreater(stages[-1][0], 10**190)

    def test_multiple_input_values_are_calculated_independently_and_in_order(self):
        stages = generate_multiplication_stages([1, 2, 3], 10, 2)
        self.assertEqual(stages, [[1, 2, 3], [10, 20, 30], [100, 200, 300]])

    def test_multiplier_out_of_range_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Multiplier must be between"):
            generate_multiplication_stages([1], 100, 1)
        with self.assertRaisesRegex(ValueError, "Multiplier must be between"):
            generate_multiplication_stages([1], -1, 1)

    def test_repetitions_out_of_range_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Repetitions must be between"):
            generate_multiplication_stages([1], 2, 100)
        with self.assertRaisesRegex(ValueError, "Repetitions must be between"):
            generate_multiplication_stages([1], 2, -1)

    def test_non_integer_multiplier_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Multiplier must be a whole number"):
            generate_multiplication_stages([1], 2.5, 1)

    def test_non_integer_repetitions_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Repetitions must be a whole number"):
            generate_multiplication_stages([1], 2, 1.5)


class ComputeMultiplicationStagesTests(unittest.TestCase):
    def test_reproducible_record_matches_documented_example(self):
        result = compute_multiplication_stages("4", 10, 4)
        self.assertEqual(result.values, [4])
        self.assertEqual(result.multiplier, 10)
        self.assertEqual(result.repetitions, 4)
        self.assertEqual(
            result.stages, [[4], [40], [400], [4000], [40000]]
        )

    def test_result_is_deterministic_for_identical_input(self):
        first = compute_multiplication_stages(
            "4", 10, 4, created_at="2026-01-01T00:00:00+00:00"
        )
        second = compute_multiplication_stages(
            "4", 10, 4, created_at="2026-06-01T00:00:00+00:00"
        )
        self.assertEqual(first.result_id, second.result_id)
        self.assertNotEqual(first.created_at, second.created_at)

    def test_different_multiplier_has_different_id(self):
        base = compute_multiplication_stages("4", 10, 4)
        doubled = compute_multiplication_stages("4", DOUBLING_MULTIPLIER, 4)
        self.assertNotEqual(base.result_id, doubled.result_id)

    def test_retains_source_and_raw_input_for_provenance(self):
        result = compute_multiplication_stages(
            "30, 9, 1, 40",
            10,
            2,
            source="calculator_output",
            source_description="Fingerprint WRG-NAME-ABCDEF1234567890",
        )
        self.assertEqual(result.raw_input, "30, 9, 1, 40")
        self.assertEqual(result.values, [30, 9, 1, 40])
        self.assertEqual(result.source, "calculator_output")
        self.assertIn("WRG-NAME-", result.source_description)


class SaveMultiplicationStagesTests(unittest.TestCase):
    def test_save_is_atomic_and_reproducible(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = compute_multiplication_stages("4", 10, 4)

            first_path = save_multiplication_stages(result, root=root)
            self.assertTrue(first_path.exists())
            self.assertFalse(first_path.with_suffix(".json.tmp").exists())

            second_path = save_multiplication_stages(result, root=root)
            self.assertEqual(first_path, second_path)

            saved_files = list(root.glob("*.json"))
            self.assertEqual(len(saved_files), 1)


if __name__ == "__main__":
    unittest.main()
