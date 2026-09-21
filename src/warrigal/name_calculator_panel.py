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
        self._build()

    def _build(self) -> None:
        outer = ttk.Frame(self, padding=18)
        outer.pack(fill="both", expand=True)
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
