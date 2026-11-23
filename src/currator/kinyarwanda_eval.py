"""Measure Currator's recognition against human transcripts in a TSV manifest."""

import argparse
import csv
import getpass
import mimetypes
import re
import time
import unicodedata
from pathlib import Path

import httpx


def words(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFC", text).casefold().replace("’", "'")
    return re.findall(r"[^\W_]+(?:'[^\W_]+)*", normalized)


def edit_distance(reference: list[str], candidate: list[str]) -> int:
    row = list(range(len(candidate) + 1))
    for i, expected in enumerate(reference, 1):
        updated = [i]
        for j, observed in enumerate(candidate, 1):
            updated.append(min(row[j] + 1, updated[-1] + 1, row[j - 1] + (expected != observed)))
        row = updated
    return row[-1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="UTF-8 TSV with audio and reference columns")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--username", help="Prompt for the HTTP demo password")
    parser.add_argument("--language", choices=["auto", "rw"], default="auto")
    args = parser.parse_args()
    auth = (args.username, getpass.getpass("Demo password: ")) if args.username else None
    errors = reference_words = reviews = failures = completed = 0
    with args.manifest.open(encoding="utf-8-sig", newline="") as manifest, httpx.Client(
        base_url=args.url, auth=auth, timeout=50,
    ) as client:
        rows = csv.DictReader(manifest, delimiter="\t")
        if not {"audio", "reference"} <= set(rows.fieldnames or []):
            parser.error("Manifest requires audio and reference columns")
        for row in rows:
            path = args.manifest.parent / row["audio"]
            reference = words(row["reference"])
            if not reference:
                continue
            start = time.monotonic()
            try:
                with path.open("rb") as clip:
                    response = client.post(
                        "/api/speech/transcribe", params={"language": args.language},
                        files={"audio": (path.name, clip, mimetypes.guess_type(path.name)[0] or "")},
                    )
                response.raise_for_status()
                result = response.json()
            except (OSError, ValueError, httpx.HTTPError) as error:
                print(f"{path.name}\tERROR\t{error}")
                failures += 1
                continue
            count = edit_distance(reference, words(result["text"]))
            errors += count
            reference_words += len(reference)
            completed += 1
            reviews += bool(result.get("needs_confirmation"))
            print(f"{path.name}\t{count}/{len(reference)}\t{time.monotonic() - start:.2f}s"
                  f"\t{result['text']}")
    if reference_words:
        print(f"Word error rate {errors / reference_words:.1%} across {completed} clips. "
              f"Review requested on {reviews}. Failed clips: {failures}.")
    return int(failures > 0 or reference_words == 0)


if __name__ == "__main__":
    raise SystemExit(main())
