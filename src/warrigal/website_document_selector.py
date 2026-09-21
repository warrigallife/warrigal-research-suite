"""Review and select inventoried website documents without acquiring them."""

from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import unquote, urlparse

import tkinter as tk
from tkinter import messagebox, ttk

from warrigal.acquisition.manifest import CollectionManifest, ManifestResource

SMALL_FILE_LIMIT_BYTES = 25 * 1024 * 1024


def resource_order_key(resource: ManifestResource) -> tuple[bool, int, str]:
    """Order known-size resources smallest-first and unknown sizes last."""

    return (
        resource.expected_size_bytes is None,
        resource.expected_size_bytes or 0,
        resource.url,
    )


def selected_manifest(
    manifest: CollectionManifest,
    selected_urls: set[str],
) -> CollectionManifest:
    """Create a provenance-preserving manifest containing selected resources."""

    available = {resource.url for resource in manifest.resources}
    unknown = selected_urls - available
    if unknown:
        raise ValueError(f"Selection contains {len(unknown)} unknown resource(s).")

    resources = sorted(
        (
            resource
            for resource in manifest.resources
            if resource.url in selected_urls
        ),
        key=resource_order_key,
    )
    metadata = dict(manifest.metadata)
    metadata.update(
        {
            "selection_source_manifest_id": manifest.manifest_id,
            "selection_resource_count": len(resources),
            "selection_mode": "manual",
        }
    )
    result = CollectionManifest(
        manifest_id=manifest.manifest_id,
        name=f"{manifest.name} — selected documents",
        description=manifest.description,
        discovery_provenance=dict(manifest.discovery_provenance),
        resources=resources,
        leads=list(manifest.leads),
        metadata=metadata,
    )
    result.validate()
    return result


def human_size(size: int | None) -> str:
    if size is None:
        return "Unknown"
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def resource_name(resource: ManifestResource) -> str:
    name = Path(unquote(urlparse(resource.url).path)).name
    return name or resource.url


def size_category(resource: ManifestResource) -> str:
    size = resource.expected_size_bytes
    if size is None:
        return "Unknown size"
    if size <= SMALL_FILE_LIMIT_BYTES:
        return "Smaller (≤25 MB)"
    return "Large (>25 MB)"


def load_existing_selection(
    output: Path,
    manifest_id: str,
) -> set[str]:
    if not output.exists():
        return set()
    existing = CollectionManifest.from_json(output.read_text(encoding="utf-8"))
    if existing.manifest_id != manifest_id:
        return set()
    return {resource.url for resource in existing.resources}


class WebsiteDocumentSelector(tk.Tk):
    def __init__(
        self,
        manifest: CollectionManifest,
        output: Path,
    ) -> None:
        super().__init__()
        self.manifest = manifest
        self.output = output
        self.resources = sorted(manifest.resources, key=resource_order_key)
        self.by_id: dict[str, ManifestResource] = {}
        self.selected_urls = load_existing_selection(output, manifest.manifest_id)

        self.title("Select website documents")
        self.geometry("1050x680")
        self.minsize(760, 480)
        self.status = tk.StringVar()
        self._build()
        self._refresh_status()

    def _build(self) -> None:
        outer = ttk.Frame(self, padding=16)
        outer.pack(fill="both", expand=True)
        ttk.Label(
            outer,
            text="Select website documents",
            font=("Helvetica", 20, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            outer,
            text=(
                "Click a row to include or exclude it. Display and acquisition "
                "order are smallest to largest; unknown sizes appear last."
            ),
        ).pack(anchor="w", pady=(2, 12))

        columns = ("selected", "size", "category", "name", "url")
        self.tree = ttk.Treeview(outer, columns=columns, show="headings")
        self.tree.heading("selected", text="Include")
        self.tree.heading("size", text="Size")
        self.tree.heading("category", text="Current automatic run")
        self.tree.heading("name", text="Document")
        self.tree.heading("url", text="URL")
        self.tree.column("selected", width=70, anchor="center", stretch=False)
        self.tree.column("size", width=95, anchor="e", stretch=False)
        self.tree.column("category", width=155, stretch=False)
        self.tree.column("name", width=250)
        self.tree.column("url", width=450)

        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="left", fill="y")

        for index, resource in enumerate(self.resources):
            item_id = f"resource-{index}"
            self.by_id[item_id] = resource
            self.tree.insert(
                "",
                "end",
                iid=item_id,
                values=(
                    "✓" if resource.url in self.selected_urls else "",
                    human_size(resource.expected_size_bytes),
                    size_category(resource),
                    resource_name(resource),
                    resource.url,
                ),
            )
        self.tree.bind("<ButtonRelease-1>", self._toggle_event)
        self.tree.bind("<space>", self._toggle_focused)

        controls = ttk.Frame(self)
        controls.pack(fill="x", padx=16, pady=(0, 16))
        ttk.Label(controls, textvariable=self.status).pack(side="left")
        ttk.Button(
            controls,
            text="Select smaller files (≤25 MB)",
            command=self._select_smaller,
        ).pack(side="right", padx=(6, 0))
        ttk.Button(controls, text="Select all", command=self._select_all).pack(
            side="right", padx=(6, 0)
        )
        ttk.Button(controls, text="Clear", command=self._clear).pack(
            side="right", padx=(6, 0)
        )
        ttk.Button(controls, text="Save selection", command=self._save).pack(
            side="right", padx=(6, 0)
        )

    def _toggle_event(self, event: tk.Event) -> None:
        item_id = self.tree.identify_row(event.y)
        if item_id:
            self._toggle(item_id)

    def _toggle_focused(self, _event: tk.Event) -> str:
        item_id = self.tree.focus()
        if item_id:
            self._toggle(item_id)
        return "break"

    def _toggle(self, item_id: str) -> None:
        resource = self.by_id[item_id]
        if resource.url in self.selected_urls:
            self.selected_urls.remove(resource.url)
        else:
            self.selected_urls.add(resource.url)
        values = list(self.tree.item(item_id, "values"))
        values[0] = "✓" if resource.url in self.selected_urls else ""
        self.tree.item(item_id, values=values)
        self._refresh_status()

    def _select_all(self) -> None:
        self.selected_urls = {resource.url for resource in self.resources}
        self._redraw_marks()

    def _select_smaller(self) -> None:
        self.selected_urls = {
            resource.url
            for resource in self.resources
            if resource.expected_size_bytes is not None
            and resource.expected_size_bytes <= SMALL_FILE_LIMIT_BYTES
        }
        self._redraw_marks()

    def _clear(self) -> None:
        self.selected_urls.clear()
        self._redraw_marks()

    def _redraw_marks(self) -> None:
        for item_id, resource in self.by_id.items():
            values = list(self.tree.item(item_id, "values"))
            values[0] = "✓" if resource.url in self.selected_urls else ""
            self.tree.item(item_id, values=values)
        self._refresh_status()

    def _refresh_status(self) -> None:
        known = sum(
            resource.expected_size_bytes or 0
            for resource in self.resources
            if resource.url in self.selected_urls
        )
        unknown = sum(
            resource.expected_size_bytes is None
            for resource in self.resources
            if resource.url in self.selected_urls
        )
        suffix = f"; {unknown} unknown-size" if unknown else ""
        self.status.set(
            f"Selected {len(self.selected_urls)} of {len(self.resources)} "
            f"({human_size(known)} known total{suffix})"
        )

    def _save(self) -> None:
        if not self.selected_urls:
            messagebox.showwarning(
                "Nothing selected",
                "Select at least one document, or close this window without saving.",
            )
            return
        result = selected_manifest(self.manifest, self.selected_urls)
        self.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.output.with_name(self.output.name + ".tmp")
        temporary.write_text(result.to_json(), encoding="utf-8")
        temporary.replace(self.output)
        messagebox.showinfo(
            "Selection saved",
            f"Saved {len(result.resources)} documents.\n\n{self.output}",
        )
        self.destroy()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest")
    parser.add_argument("--output", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    manifest_path = Path(args.manifest).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    manifest = CollectionManifest.from_json(manifest_path.read_text(encoding="utf-8"))
    WebsiteDocumentSelector(manifest, output).mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
