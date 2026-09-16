from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


SUCCESS_STATUSES = {"acquired", "archived", "verified", "alternate_recovered"}

DAMAGE_MARKERS = (
    "startxref",
    "object streams",
    "not defined",
    "eof marker",
    "pdfstream",
    "pdfread",
    "malformed",
    "broken xref",
    "xref",
)

MISSING_MARKERS = (
    "404",
    "not found",
)

ACCESS_MARKERS = (
    "401",
    "403",
    "unauthorized",
    "forbidden",
)

NETWORK_MARKERS = (
    "timeout",
    "timed out",
    "connection",
    "temporary failure",
    "name resolution",
    "ssl",
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def classify_failure(record: dict[str, Any]) -> tuple[str, str]:
    error = record.get("error")
    errors = record.get("errors") or []

    pieces: list[str] = []

    if isinstance(error, str):
        pieces.append(error)
    elif isinstance(error, dict):
        pieces.extend(
            str(error.get(key, ""))
            for key in ("error_type", "type", "message")
        )

    for item in errors:
        if isinstance(item, str):
            pieces.append(item)
        elif isinstance(item, dict):
            pieces.extend(
                str(item.get(key, ""))
                for key in ("error_type", "type", "message")
            )

    message = " | ".join(
        piece.strip()
        for piece in pieces
        if piece and piece.strip()
    )
    lowered = message.lower()

    if any(marker in lowered for marker in MISSING_MARKERS):
        return "missing_search_required", message

    if any(marker in lowered for marker in ACCESS_MARKERS):
        return "access_blocked", message

    if any(marker in lowered for marker in DAMAGE_MARKERS):
        return "damaged_recoverable", message

    if any(marker in lowered for marker in NETWORK_MARKERS):
        return "temporary_network_failure", message

    return "unclassified_failure", message


def manifest_lookup(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        resource["url"]: resource
        for resource in manifest.get("resources", [])
    }


def create_queue(
    manifest: dict[str, Any],
    checkpoint: dict[str, Any],
) -> dict[str, Any]:
    resources = manifest_lookup(manifest)
    queue: list[dict[str, Any]] = []

    for url, record in checkpoint.get("resources", {}).items():
        status = record.get("status", "unknown")

        if status in SUCCESS_STATUSES:
            continue

        classification, message = classify_failure(record)
        resource = resources.get(url, {})

        queue.append(
            {
                "url": url,
                "status": status,
                "classification": classification,
                "media_type": (
                    resource.get("media_type")
                    or record.get("media_type")
                ),
                "expected_size_bytes": resource.get(
                    "expected_size_bytes"
                ),
                "branch": (
                    resource.get("metadata", {}).get("branch")
                ),
                "error": message,
                "recommended_action": {
                    "damaged_recoverable": (
                        "Preserve original bytes, attempt non-destructive "
                        "PDF repair, then retain original and repaired derivative."
                    ),
                    "missing_search_required": (
                        "Search exact filename, title, source indexes and "
                        "web archives for an alternate copy."
                    ),
                    "temporary_network_failure": (
                        "Retry later using the same checkpoint."
                    ),
                    "access_blocked": (
                        "Review source access without bypassing restrictions."
                    ),
                    "unclassified_failure": (
                        "Inspect the recorded exception before choosing action."
                    ),
                }[classification],
            }
        )

    queue.sort(
        key=lambda item: (
            item["classification"],
            item["branch"] or "",
            item["url"],
        )
    )

    counts = Counter(
        item["classification"]
        for item in queue
    )

    return {
        "version": 1,
        "created_at": datetime.now().astimezone().isoformat(),
        "manifest_id": manifest.get("manifest_id"),
        "checkpoint_manifest_id": checkpoint.get("manifest_id"),
        "total_recovery_items": len(queue),
        "classifications": dict(sorted(counts.items())),
        "items": queue,
    }


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Bunker of Doom Document Recovery Queue",
        "",
        f"- Manifest: `{report.get('manifest_id')}`",
        f"- Created: `{report.get('created_at')}`",
        f"- Recovery items: **{report['total_recovery_items']}**",
        "",
        "## Classification summary",
        "",
    ]

    if report["classifications"]:
        for name, count in report["classifications"].items():
            lines.append(f"- `{name}`: {count}")
    else:
        lines.append("- No unresolved resources.")

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in report["items"]:
        grouped.setdefault(item["classification"], []).append(item)

    for classification, items in grouped.items():
        lines.extend(
            [
                "",
                f"## {classification}",
                "",
            ]
        )

        for item in items:
            lines.extend(
                [
                    f"### {item['url']}",
                    "",
                    f"- Status: `{item['status']}`",
                    f"- Branch: `{item['branch'] or 'unknown'}`",
                    f"- Media type: `{item['media_type'] or 'unknown'}`",
                    (
                        "- Expected bytes: "
                        f"`{item['expected_size_bytes']}`"
                    ),
                    f"- Error: `{item['error'] or 'not recorded'}`",
                    f"- Action: {item['recommended_action']}",
                    "",
                ]
            )

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a non-destructive document recovery queue "
            "from a Warrigal manifest checkpoint."
        )
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--json-output", required=True, type=Path)
    parser.add_argument("--markdown-output", required=True, type=Path)
    args = parser.parse_args()

    manifest = load_json(args.manifest)
    checkpoint = load_json(args.checkpoint)

    manifest_id = manifest.get("manifest_id")
    checkpoint_id = checkpoint.get("manifest_id")

    if manifest_id != checkpoint_id:
        raise SystemExit(
            "STOPPED: manifest/checkpoint identity mismatch: "
            f"{manifest_id!r} != {checkpoint_id!r}"
        )

    report = create_queue(manifest, checkpoint)

    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)

    json_temporary = args.json_output.with_suffix(
        args.json_output.suffix + ".tmp"
    )
    markdown_temporary = args.markdown_output.with_suffix(
        args.markdown_output.suffix + ".tmp"
    )

    json_temporary.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    markdown_temporary.write_text(
        markdown_report(report),
        encoding="utf-8",
    )

    json_temporary.replace(args.json_output)
    markdown_temporary.replace(args.markdown_output)

    print("=== DOCUMENT RECOVERY QUEUE CREATED ===")
    print("MANIFEST:", report["manifest_id"])
    print("RECOVERY ITEMS:", report["total_recovery_items"])

    for classification, count in report["classifications"].items():
        print(f"{classification.upper()}: {count}")

    print("JSON:", args.json_output.resolve())
    print("MARKDOWN:", args.markdown_output.resolve())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
