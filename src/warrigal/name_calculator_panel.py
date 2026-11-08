"""Native graphical panel for the Warrigal Name Calculator."""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from warrigal.name_calculator import (
    MAPPING_PROFILES,
    Fingerprint,
    calculate_fingerprint,
    default_records_root,
    save_fingerprint,
)
from warrigal.scripture_import import load_text_units, parse_labelled_text, preserve_source_file, save_text_batch
from warrigal.sequence_multiplication import (
    DOUBLING_MULTIPLIER,
    MAX_MULTIPLIER,
    MAX_REPETITIONS,
    MIN_MULTIPLIER,
    MIN_REPETITIONS,
    OPERATIONS,
    compute_multiplication_stages,
    compute_sequence_operation,
    default_sequence_records_root,
    save_multiplication_stages,
    save_sequence_result,
)


class NameCalculatorPanel(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Warrigal Name Calculator")
        self.geometry("1080x820")
        self.minsize(900, 680)
        self.result: Fingerprint | None = None

        self.profile = tk.StringVar(value=next(iter(MAPPING_PROFILES)))
        self.source_title = tk.StringVar()
        self.source_reference = tk.StringVar()
        self.status = tk.StringVar(value="Ready — enter text, then calculate.")
        self.attachment_path = ""
        self.attachment_sha256 = ""
        self.sequence_operation = tk.StringVar(value=OPERATIONS[0])
        self.sequence_status = tk.StringVar(value="Ready — independent of the calculator above.")
        self.sequence_result = None
        self.multiplication_multiplier = tk.StringVar(value="10")
        self.multiplication_repetitions = tk.StringVar(value="4")
        self.multiplication_status = tk.StringVar(value="Ready — independent of the calculator above.")
        self.multiplication_result = None
        self._calculator_fill_text: str | None = None
        self._calculator_fill_fingerprint: str | None = None
        self._build()

    def _build(self) -> None:
        # The window's content (calculator + the Sequence & Multiplication /
        # Repeated Multiplication sections) can be taller than a MacBook
        # display. Wrap the existing layout in a scrollable canvas instead
        # of redesigning it: `outer` still holds every widget below exactly
        # as before, at exactly the same grid positions -- only its
        # immediate parent changed, from the window itself to a frame
        # inside a scrolling `Canvas`.
        container = ttk.Frame(self)
        container.pack(fill="both", expand=True)

        canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        outer = ttk.Frame(canvas, padding=18)
        outer_window = canvas.create_window((0, 0), window=outer, anchor="nw")

        def _sync_scrollregion(_event=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _sync_outer_width(event) -> None:
            # Keep the content exactly as wide as the visible canvas, so
            # existing sticky="ew"/columnconfigure(weight=1) widgets inside
            # `outer` resize horizontally exactly as they did before.
            canvas.itemconfigure(outer_window, width=event.width)

        outer.bind("<Configure>", _sync_scrollregion)
        canvas.bind("<Configure>", _sync_outer_width)

        def _on_mousewheel(event) -> None:
            if event.delta > 0:
                canvas.yview_scroll(-1, "units")
            elif event.delta < 0:
                canvas.yview_scroll(1, "units")

        # macOS trackpad/mouse wheel scrolling, while this window has focus.
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(6, weight=1)

        ttk.Label(outer, text="Warrigal Name Calculator", font=("Arial", 25, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 4)
        )
        ttk.Label(
            outer,
            text="Text → declared language mapping → Double-9 fingerprint → saved JUFE research record",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 14))

        ttk.Label(outer, text="Mapping").grid(row=2, column=0, sticky="nw", padx=(0, 12), pady=4)
        ttk.Combobox(
            outer, textvariable=self.profile, values=list(MAPPING_PROFILES), state="readonly"
        ).grid(row=2, column=1, sticky="ew", pady=4)

        source = ttk.Frame(outer)
        source.grid(row=3, column=0, columnspan=2, sticky="ew", pady=4)
        source.columnconfigure(1, weight=1)
        source.columnconfigure(3, weight=1)
        ttk.Label(source, text="Source title").grid(row=0, column=0, padx=(0, 8))
        ttk.Entry(source, textvariable=self.source_title).grid(row=0, column=1, sticky="ew", padx=(0, 14))
        ttk.Label(source, text="Reference / URL").grid(row=0, column=2, padx=(0, 8))
        ttk.Entry(source, textvariable=self.source_reference).grid(row=0, column=3, sticky="ew")

        texts = ttk.Frame(outer)
        texts.grid(row=4, column=0, columnspan=2, sticky="nsew", pady=(8, 4))
        texts.columnconfigure(0, weight=1)
        texts.columnconfigure(1, weight=1)
        ttk.Label(texts, text="Original-language text (preserved; not remapped as English)").grid(row=0, column=0, sticky="w")
        ttk.Label(texts, text="Text to calculate (for now: English translation/name)").grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.original = tk.Text(texts, height=7, wrap="word")
        self.original.grid(row=1, column=0, sticky="nsew", pady=4)
        self.input_text = tk.Text(texts, height=7, wrap="word")
        self.input_text.grid(row=1, column=1, sticky="nsew", padx=(12, 0), pady=4)

        buttons = ttk.Frame(outer)
        buttons.grid(row=5, column=0, columnspan=2, sticky="ew", pady=8)
        ttk.Button(buttons, text="Calculate", command=self.calculate).pack(side="left")
        ttk.Button(
            buttons,
            text="Show JUFE number script",
            command=self.export_number_script,
        ).pack(side="left", padx=8)
        ttk.Button(buttons, text="Calculate and save record", command=self.calculate_and_save).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Process labelled chapter", command=self.process_labelled_chapter).pack(side="left")
        ttk.Button(buttons, text="Import text corpus", command=self.import_corpus).pack(side="left", padx=8)
        ttk.Button(buttons, text="Attach photo / source", command=self.attach_source).pack(side="left")
        ttk.Button(buttons, text="Open saved records", command=self.open_records).pack(side="left")
        ttk.Button(buttons, text="Clear", command=self.clear).pack(side="right")

        self.output = tk.Text(outer, height=22, wrap="none")
        self.output.grid(row=6, column=0, columnspan=2, sticky="nsew", pady=(4, 8))
        ttk.Label(outer, textvariable=self.status).grid(row=7, column=0, columnspan=2, sticky="w")

        self._build_sequence_section(outer)

    def _build_sequence_section(self, outer: ttk.Frame) -> None:
        """Optional Sequence & Multiplication section.

        Independent of the Name Calculator above: it has its own input,
        operation choice, output and status, and does not read or change
        anything the calculator has already produced unless the owner
        explicitly asks for it via "Use calculator's mapped sequence".
        """
        section = ttk.LabelFrame(outer, text="Sequence & Multiplication (optional)", padding=12)
        section.grid(row=8, column=0, columnspan=2, sticky="nsew", pady=(10, 0))
        section.columnconfigure(0, weight=1)

        ttk.Label(
            section,
            text=(
                "Process a numerical set independently of the calculator above -- "
                "type numbers directly, or pull the calculator's own mapped sequence."
            ),
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))

        ttk.Label(section, text="Numbers (comma or space separated)").grid(
            row=1, column=0, columnspan=3, sticky="w"
        )
        self.sequence_input = tk.Text(section, height=3, wrap="word")
        self.sequence_input.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(2, 8))

        controls = ttk.Frame(section)
        controls.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        ttk.Button(
            controls,
            text="Use calculator's mapped sequence",
            command=self.fill_sequence_from_calculator,
        ).pack(side="left")
        ttk.Label(controls, text="Operation").pack(side="left", padx=(16, 6))
        ttk.Combobox(
            controls, textvariable=self.sequence_operation, values=list(OPERATIONS), state="readonly"
        ).pack(side="left")
        ttk.Button(controls, text="Compute", command=self.compute_sequence).pack(side="left", padx=(16, 0))
        ttk.Button(
            controls, text="Save sequence record", command=self.save_sequence_record
        ).pack(side="left", padx=8)
        ttk.Button(
            controls, text="Open saved sequences", command=self.open_sequence_records
        ).pack(side="left")

        self.sequence_output = tk.Text(section, height=6, wrap="none")
        self.sequence_output.grid(row=4, column=0, columnspan=3, sticky="nsew")
        ttk.Label(section, textvariable=self.sequence_status).grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(6, 0)
        )

        ttk.Separator(section, orient="horizontal").grid(
            row=6, column=0, columnspan=3, sticky="ew", pady=(12, 8)
        )
        ttk.Label(
            section,
            text=(
                "Repeated Multiplication Generator -- uses the same numbers "
                "entered or pulled above. Stage 0 is the original input; "
                "each later stage multiplies the previous stage by the "
                "chosen multiplier."
            ),
        ).grid(row=7, column=0, columnspan=3, sticky="w", pady=(0, 6))

        multiplication_controls = ttk.Frame(section)
        multiplication_controls.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        ttk.Label(multiplication_controls, text="Multiplier (0-99)").pack(side="left")
        ttk.Spinbox(
            multiplication_controls,
            from_=MIN_MULTIPLIER,
            to=MAX_MULTIPLIER,
            width=5,
            textvariable=self.multiplication_multiplier,
        ).pack(side="left", padx=(6, 16))
        ttk.Label(multiplication_controls, text="Repetitions (0-99)").pack(side="left")
        ttk.Spinbox(
            multiplication_controls,
            from_=MIN_REPETITIONS,
            to=MAX_REPETITIONS,
            width=5,
            textvariable=self.multiplication_repetitions,
        ).pack(side="left", padx=(6, 16))
        ttk.Button(
            multiplication_controls,
            text="Doubling preset (×2)",
            command=self.apply_doubling_preset,
        ).pack(side="left")

        multiplication_buttons = ttk.Frame(section)
        multiplication_buttons.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        ttk.Button(
            multiplication_buttons, text="Generate stages", command=self.compute_multiplication
        ).pack(side="left")
        ttk.Button(
            multiplication_buttons,
            text="Save stages record",
            command=self.save_multiplication_record,
        ).pack(side="left", padx=8)
        ttk.Button(
            multiplication_buttons,
            text="Open saved sequences",
            command=self.open_sequence_records,
        ).pack(side="left")

        self.multiplication_output = tk.Text(section, height=10, wrap="none")
        self.multiplication_output.grid(row=10, column=0, columnspan=3, sticky="nsew")
        ttk.Label(section, textvariable=self.multiplication_status).grid(
            row=11, column=0, columnspan=3, sticky="w", pady=(6, 0)
        )

    def fill_sequence_from_calculator(self) -> None:
        if self.result is None:
            messagebox.showinfo(
                "No calculator output yet",
                "Calculate a result above first, or type numbers directly "
                "into the Sequence & Multiplication section.",
            )
            return
        filled_text = ", ".join(map(str, self.result.mapped_sequence))
        self.sequence_input.delete("1.0", "end")
        self.sequence_input.insert("1.0", filled_text)
        self._calculator_fill_text = filled_text
        self._calculator_fill_fingerprint = self.result.fingerprint_id
        self.sequence_status.set(
            f"Filled from calculator fingerprint {self.result.fingerprint_id}."
        )

    def _resolve_sequence_input(self) -> tuple[str, str, str]:
        """Return (raw_input, source, source_description) for whichever
        numbers should actually be processed.

        Reads the shared numeric input box, exactly as before. If that box
        is blank but "Use calculator's mapped sequence" has already filled
        it once this session, falls back to that same sequence instead of
        failing -- so a momentarily empty read of the box (the box was
        cleared, or its content was not yet visible to this read) can
        never silently disconnect the generator (or the six operations
        above it, which share this same box) from the calculator's output
        the owner explicitly asked to use. "calculator_output" is reported
        only when the resolved input actually is that filled sequence, not
        merely because a calculation happened to run at some point.
        """
        raw_input = self.sequence_input.get("1.0", "end").strip()
        if raw_input:
            if self._calculator_fill_text is not None and raw_input == self._calculator_fill_text:
                return raw_input, "calculator_output", f"Fingerprint {self._calculator_fill_fingerprint}"
            return raw_input, "manual", ""
        if self._calculator_fill_text:
            return (
                self._calculator_fill_text,
                "calculator_output",
                f"Fingerprint {self._calculator_fill_fingerprint}",
            )
        return raw_input, "manual", ""

    def compute_sequence(self) -> None:
        raw_input, source, source_description = self._resolve_sequence_input()
        try:
            result = compute_sequence_operation(
                raw_input,
                self.sequence_operation.get(),
                source=source,
                source_description=source_description,
            )
        except Exception as exc:
            messagebox.showerror("Cannot compute sequence", str(exc))
            return

        self.sequence_result = result
        lines = [
            f"Result ID: {result.result_id}",
            f"Operation: {result.operation}",
            f"Input values: {', '.join(map(str, result.values))}",
            f"Output: {', '.join(map(str, result.output))}",
            f"Source: {result.source}",
        ]
        if result.source_description:
            lines.append(f"Source detail: {result.source_description}")
        self.sequence_output.delete("1.0", "end")
        self.sequence_output.insert("1.0", "\n".join(lines))
        self.sequence_status.set(
            "Computed. Nothing is saved until you use 'Save sequence record'."
        )

    def save_sequence_record(self) -> None:
        if self.sequence_result is None:
            self.compute_sequence()
        if self.sequence_result is None:
            return
        path = save_sequence_result(self.sequence_result)
        self.sequence_status.set(f"Saved without duplicate filenames: {path}")
        messagebox.showinfo("Sequence record saved", f"Saved:\n{path}")

    def open_sequence_records(self) -> None:
        import subprocess
        root = default_sequence_records_root()
        root.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(root)], check=False)

    def apply_doubling_preset(self) -> None:
        self.multiplication_multiplier.set(str(DOUBLING_MULTIPLIER))
        self.multiplication_status.set(
            f"Doubling preset applied: multiplier set to {DOUBLING_MULTIPLIER}."
        )

    def compute_multiplication(self) -> None:
        raw_input, source, source_description = self._resolve_sequence_input()
        try:
            result = compute_multiplication_stages(
                raw_input,
                self.multiplication_multiplier.get(),
                self.multiplication_repetitions.get(),
                source=source,
                source_description=source_description,
            )
        except Exception as exc:
            messagebox.showerror("Cannot generate stages", str(exc))
            return

        self.multiplication_result = result
        lines = [
            f"Result ID: {result.result_id}",
            f"Multiplier: {result.multiplier}",
            f"Repetitions: {result.repetitions}",
            f"Source: {result.source}",
        ]
        if result.source_description:
            lines.append(f"Source detail: {result.source_description}")
        lines.append("")
        for stage_index, stage_values in enumerate(result.stages):
            lines.append(f"Stage {stage_index}: {', '.join(map(str, stage_values))}")
        self.multiplication_output.delete("1.0", "end")
        self.multiplication_output.insert("1.0", "\n".join(lines))
        self.multiplication_status.set(
            "Generated. Nothing is saved until you use 'Save stages record'."
        )

    def save_multiplication_record(self) -> None:
        if self.multiplication_result is None:
            self.compute_multiplication()
        if self.multiplication_result is None:
            return
        path = save_multiplication_stages(self.multiplication_result)
        self.multiplication_status.set(f"Saved without duplicate filenames: {path}")
        messagebox.showinfo("Stages record saved", f"Saved:\n{path}")

    def _calculate(self) -> Fingerprint:
        calculated = calculate_fingerprint(
            self.input_text.get("1.0", "end").strip(),
            mapping_profile=self.profile.get(),
            original_text=self.original.get("1.0", "end").strip(),
            translation_text=self.input_text.get("1.0", "end").strip(),
            source_title=self.source_title.get(),
            source_reference=self.source_reference.get(),
            source_attachment_path=self.attachment_path,
            source_attachment_sha256=self.attachment_sha256,
        )
        self.result = calculated
        return calculated

    def calculate(self) -> None:
        try:
            result = self._calculate()
        except Exception as exc:
            messagebox.showerror("Cannot calculate", str(exc))
            return
        lines = [
            f"Fingerprint: {result.fingerprint_id}",
            f"Mapping: {result.mapping_profile} [{result.mapping_status}]",
            f"Normalised: {result.normalized_text}",
            "",
            "WORD RESULTS",
        ]
        for word in result.words:
            lines.extend([
                f"{word.word}",
                f"  Symbols: {' '.join(word.symbols)}",
                f"  Ordinal: {' '.join(map(str, word.ordinal_values))}",
                f"  Custom:  {' '.join(map(str, word.mapped_values))}",
                f"  Total {word.total} → node {word.node18_root} ({word.layer}); 1–9 comparison {word.digital_root_9}",
            ])
        lines.extend([
            "",
            f"Full mapped sequence: {', '.join(map(str, result.mapped_sequence))}",
            f"Word roots: {', '.join(map(str, result.word_roots_18))}",
            f"Combined total: {result.total}",
            f"Double-9 root: {result.total_root_18} ({result.double9_layer})",
            f"Optional 1–9 comparison: {result.total_root_9}",
            "",
            f"Direct frequency candidates (Hz): {', '.join(map(str, result.frequency_candidates_hz))}",
            result.frequency_mapping_status,
            result.jufe_runtime_status,
        ])
        self.output.delete("1.0", "end")
        self.output.insert("1.0", "\n".join(lines))
        self.status.set("Calculated. Nothing is saved until you use ‘Calculate and save record’. ")

    def export_number_script(self) -> None:
        try:
            result = self._calculate()
        except Exception as exc:
            messagebox.showerror("Cannot create JUFE number script", str(exc))
            return

        number_script = ",".join(
            map(str, result.mapped_sequence)
        )

        self.output.delete("1.0", "end")
        self.output.insert("1.0", number_script)

        # Select the complete script so it can be copied immediately.
        self.output.tag_add("sel", "1.0", "end-1c")
        self.output.mark_set("insert", "1.0")
        self.output.focus_set()

        # Also place the same script on the clipboard.
        self.clipboard_clear()
        self.clipboard_append(number_script)

        self.status.set(
            "JUFE number script displayed and copied to clipboard. "
            "No file was created."
        )

    def calculate_and_save(self) -> None:
        self.calculate()
        if self.result is None:
            return
        path = save_fingerprint(self.result)
        self.status.set(f"Saved without duplicate filenames: {path}")
        messagebox.showinfo("Record saved", f"Saved:\n{path}")

    def open_records(self) -> None:
        import subprocess
        root = default_records_root()
        root.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(root)], check=False)

    def process_labelled_chapter(self) -> None:
        book = simpledialog.askstring("Book", "Book/document name (for example John):", parent=self) or ""
        chapter = simpledialog.askstring("Chapter", "Default chapter number:", parent=self) or ""
        try:
            units = parse_labelled_text(
                self.input_text.get("1.0", "end").strip(),
                default_book=book,
                default_chapter=chapter,
                source_title=self.source_title.get(),
                source_reference=self.source_reference.get(),
            )
            manifest = save_text_batch(units, mapping_profile=self.profile.get())
        except Exception as exc:
            messagebox.showerror("Cannot process chapter", str(exc))
            return
        self.status.set(f"Saved {len(units)} labelled verse records and batch manifest: {manifest}")
        messagebox.showinfo("Chapter processed", f"Processed {len(units)} verses.\n\nBatch record:\n{manifest}")

    def import_corpus(self) -> None:
        selected = filedialog.askopenfilename(
            title="Choose a structured text corpus",
            filetypes=[
                ("Supported text corpora", "*.txt *.md *.csv *.json *.pdf"),
                ("All files", "*.*"),
            ],
        )
        if not selected:
            return
        try:
            units = load_text_units(
                Path(selected),
                source_title=self.source_title.get(),
                source_reference=self.source_reference.get(),
            )
            manifest = save_text_batch(units, mapping_profile=self.profile.get())
        except Exception as exc:
            messagebox.showerror("Cannot import corpus", str(exc))
            return
        self.status.set(f"Imported {len(units)} units: {manifest}")
        messagebox.showinfo("Corpus imported", f"Imported and processed {len(units)} units.\n\nBatch record:\n{manifest}")

    def attach_source(self) -> None:
        selected = filedialog.askopenfilename(
            title="Choose a photograph, scan, PDF or source file",
            filetypes=[
                ("Source evidence", "*.jpg *.jpeg *.png *.heic *.tif *.tiff *.pdf *.txt *.md"),
                ("All files", "*.*"),
            ],
        )
        if not selected:
            return
        try:
            preserved, digest = preserve_source_file(Path(selected))
        except Exception as exc:
            messagebox.showerror("Cannot preserve source", str(exc))
            return
        self.attachment_path = str(preserved)
        self.attachment_sha256 = digest
        if not self.source_title.get():
            self.source_title.set(Path(selected).stem)
        if not self.source_reference.get():
            self.source_reference.set(Path(selected).name)
        self.status.set("Source preserved. Type or paste its transcription, then calculate and save.")
        messagebox.showinfo(
            "Source preserved",
            "The original file has been preserved once by content hash.\n\n"
            "Now type or paste the exact text you want calculated.",
        )

    def clear(self) -> None:
        self.original.delete("1.0", "end")
        self.input_text.delete("1.0", "end")
        self.output.delete("1.0", "end")
        self.source_title.set("")
        self.source_reference.set("")
        self.result = None
        self.attachment_path = ""
        self.attachment_sha256 = ""
        self.status.set("Ready — enter text, then calculate.")


def main() -> None:
    NameCalculatorPanel().mainloop()


if __name__ == "__main__":
    main()
