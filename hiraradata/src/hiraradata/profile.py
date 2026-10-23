"""data_profile: describe a table an agent cannot read in full.

A million-row CSV does not fit in a context window, and the first fifty rows
lie about the rest. This streams the whole file once and returns, per
column: the inferred type, nulls, distinct values, the most common values,
numeric statistics (quantiles, histogram, outliers), string lengths and date
ranges, plus table-level problems (duplicate rows, constant or empty
columns, mixed types, likely IDs) as plain-language warnings.

Standard library + NumPy only: no pandas, so memory stays flat.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import random
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import numpy as np

from .errors import DataError

NULLS = frozenset({"", "na", "n/a", "null", "none", "nan", "-", "#n/a", "nil", "undefined"})
INT_RX = re.compile(r"^[+-]?\d+$")
FLOAT_RX = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")
DATE_RX = re.compile(
    r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$")
BOOLS = {"true": True, "false": False}
RESERVOIR = 20_000
TOP_KEYS = 10_000
DISTINCT_CAP = 100_000
DUP_CAP = 5_000_000


class Column:
    def __init__(self, name: str) -> None:
        self.name = name
        self.count = 0
        self.nulls = 0
        self.kinds: Counter = Counter()
        self.n = 0
        self.mean = 0.0
        self.m2 = 0.0
        self.min: float | None = None
        self.max: float | None = None
        self.zeros = 0
        self.negatives = 0
        self.sample: list[float] = []
        self.rng = random.Random(len(name))
        self.top: Counter = Counter()
        self.top_capped = False
        self.distinct: set = set()
        self.distinct_capped = False
        self.len_min: int | None = None
        self.len_max = 0
        self.len_sum = 0
        self.date_min: str | None = None
        self.date_max: str | None = None
        self.examples: list[str] = []

    # --- feeding -----------------------------------------------------------------

    def add(self, value) -> None:
        self.count += 1
        kind, number, text = classify(value)
        if kind == "null":
            self.nulls += 1
            return
        self.kinds[kind] += 1
        if len(self.examples) < 3 and text not in self.examples:
            self.examples.append(text[:80])
        if number is not None:
            self._number(number)
        if kind == "date":
            if self.date_min is None or text < self.date_min:
                self.date_min = text
            if self.date_max is None or text > self.date_max:
                self.date_max = text
        length = len(text)
        self.len_min = length if self.len_min is None else min(self.len_min, length)
        self.len_max = max(self.len_max, length)
        self.len_sum += length
        if text in self.top or len(self.top) < TOP_KEYS:
            self.top[text] += 1
        else:
            self.top_capped = True
        if not self.distinct_capped:
            self.distinct.add(text)
            if len(self.distinct) >= DISTINCT_CAP:
                self.distinct_capped = True

    def _number(self, x: float) -> None:
        if not math.isfinite(x):
            return
        self.n += 1
        delta = x - self.mean
        self.mean += delta / self.n
        self.m2 += delta * (x - self.mean)
        self.min = x if self.min is None else min(self.min, x)
        self.max = x if self.max is None else max(self.max, x)
        if x == 0:
            self.zeros += 1
        elif x < 0:
            self.negatives += 1
        if len(self.sample) < RESERVOIR:
            self.sample.append(x)
        else:
            j = self.rng.randrange(self.n)
            if j < RESERVOIR:
                self.sample[j] = x

    # --- reporting ---------------------------------------------------------------

    def inferred(self) -> str:
        filled = self.count - self.nulls
        if filled == 0:
            return "empty"
        k = Counter(self.kinds)
        if k["code"]:
            # Digit codes (zip, account numbers): once one has a leading zero
            # the whole column is an identifier, including the plain integers.
            if k["code"] + k["integer"] == filled:
                return "string"
            k["string"] += k.pop("code")
        numeric = k["integer"] + k["float"]
        if k["integer"] == filled:
            return "integer"
        if numeric == filled:
            return "float"
        for kind in ("boolean", "date", "string"):
            if k[kind] == filled:
                return kind
        top_kind, top_n = k.most_common(1)[0]
        if numeric / filled >= 0.95:
            return "float (mixed)"
        if top_n / filled >= 0.95:
            return f"{top_kind} (mixed)"
        return "mixed"

    def report(self) -> dict:
        filled = self.count - self.nulls
        kind = self.inferred()
        distinct = len(self.distinct)
        out: dict = {
            "name": self.name,
            "type": kind,
            "count": self.count,
            "nulls": self.nulls,
            "null_pct": round(100 * self.nulls / self.count, 2) if self.count else 0.0,
            "distinct": distinct,
            "distinct_is_lower_bound": self.distinct_capped,
            "top_values": [
                {"value": v, "count": c, "pct": round(100 * c / filled, 2)}
                for v, c in self.top.most_common(5)
            ] if filled else [],
            "examples": self.examples,
        }
        if kind.startswith("mixed") or "(mixed)" in kind:
            out["type_counts"] = dict(self.kinds)
        if self.n and not kind.startswith("string"):
            sample = np.asarray(self.sample)
            q = np.percentile(sample, [5, 25, 50, 75, 95])
            iqr = q[3] - q[1]
            lo, hi = q[1] - 1.5 * iqr, q[3] + 1.5 * iqr
            outlier_frac = float(np.mean((sample < lo) | (sample > hi))) if iqr > 0 else 0.0
            counts, edges = np.histogram(sample, bins=min(10, max(1, len(set(self.sample)))))
            scale = self.n / len(sample)
            out["numeric"] = {
                "min": _num(self.min), "max": _num(self.max), "mean": _num(self.mean),
                "std": _num(math.sqrt(self.m2 / (self.n - 1)) if self.n > 1 else 0.0),
                "p05": _num(q[0]), "p25": _num(q[1]), "median": _num(q[2]),
                "p75": _num(q[3]), "p95": _num(q[4]),
                "zeros": self.zeros, "negatives": self.negatives,
                "outliers": int(round(outlier_frac * self.n)),
                "outlier_fences": [_num(lo), _num(hi)],
                "histogram": [{"from": _num(edges[i]), "to": _num(edges[i + 1]),
                               "count": int(round(counts[i] * scale))} for i in range(len(counts))],
                "estimated": self.n > len(sample),
            }
        if kind in ("string", "mixed") or kind.startswith("string"):
            if self.kinds.get("code"):
                out["note"] = "digit codes with leading zeros; treat as text, not numbers"
            out["length"] = {"min": self.len_min, "max": self.len_max,
                             "mean": round(self.len_sum / filled, 1) if filled else None}
        if self.date_min is not None:
            out["date_range"] = [self.date_min, self.date_max]
        return out


def _num(x) -> float | None:
    if x is None:
        return None
    x = float(x)
    if not math.isfinite(x):
        return None
    return round(x, 6) if abs(x) < 1e15 else x


def classify(value) -> tuple[str, float | None, str]:
    """(kind, numeric value, text form) for one cell."""
    if value is None:
        return "null", None, ""
    if isinstance(value, bool):
        return "boolean", None, str(value).lower()
    if isinstance(value, int):
        return "integer", float(value), str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return "null", None, ""
        return "float", value, repr(value)
    if isinstance(value, (datetime, date)):
        return "date", None, value.isoformat()
    if not isinstance(value, str):
        text = json.dumps(value, default=str, ensure_ascii=False)
        return "string", None, text
    text = value.strip()
    low = text.lower()
    if low in NULLS:
        return "null", None, ""
    if low in BOOLS:
        return "boolean", None, low
    if INT_RX.match(text):
        digits = text.lstrip("+-")
        # Leading zeros (zip codes, account numbers) and very long digit runs
        # are identifiers, not quantities.
        if (len(digits) > 1 and digits[0] == "0") or len(digits) > 15:
            return "code", None, text
        return "integer", float(text), text
    if FLOAT_RX.match(text):
        return "float", float(text), text
    if DATE_RX.match(text):
        return "date", None, text
    return "string", None, text


# --- loaders -----------------------------------------------------------------------

def _flatten(obj: dict, prefix: str = "", depth: int = 0) -> dict:
    out = {}
    for key, value in obj.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict) and depth < 3:
            out.update(_flatten(value, f"{name}.", depth + 1))
        else:
            out[name] = value
    return out


def _records_to_rows(records, max_columns: int):
    header: list[str] = []
    index: dict[str, int] = {}
    rows = []
    for rec in records:
        if not isinstance(rec, dict):
            rec = {"value": rec}
        flat = _flatten(rec)
        for key in flat:
            if key not in index and len(header) < max_columns:
                index[key] = len(header)
                header.append(key)
        rows.append(flat)
    return header, [[r.get(h) for h in header] for r in rows]


def detect_format(path: Path, hint: str | None, head: bytes) -> str:
    fmt = (hint or "").lower().lstrip(".")
    if fmt and fmt != "auto":
        return fmt
    name = path.name.lower()
    for ext, kind in ((".xlsx", "xlsx"), (".xlsm", "xlsx"), (".parquet", "parquet"),
                      (".jsonl", "jsonl"), (".ndjson", "jsonl"), (".json", "json"),
                      (".tsv", "tsv"), (".csv", "csv")):
        if name.endswith(ext):
            return kind
    if head.startswith(b"PK\x03\x04"):
        return "xlsx"
    if head.startswith(b"PAR1"):
        return "parquet"
    stripped = head.lstrip()
    if stripped[:1] == b"[":
        return "json"
    if stripped[:1] == b"{":
        first = stripped.split(b"\n", 1)[0].strip()
        return "jsonl" if first.endswith(b"}") and b"\n" in stripped else "json"
    return "csv"


def _open_text(path: Path):
    raw = path.open("rb")
    head = raw.read(65536)
    raw.seek(0)
    try:
        head.decode("utf-8")
        encoding = "utf-8-sig"
    except UnicodeDecodeError:
        encoding = "latin-1"
    return io.TextIOWrapper(raw, encoding=encoding, newline=""), encoding, head


def iter_table(path: Path, *, fmt: str, sheet: str | None, delimiter: str | None,
               has_header: bool | None, max_columns: int):
    """Yields (header, rows iterator, details)."""
    if fmt in ("csv", "tsv"):
        handle, encoding, head = _open_text(path)
        sample = head.decode(encoding.replace("-sig", ""), "replace")
        if delimiter:
            dialect = csv.excel
            delim = delimiter
        elif fmt == "tsv":
            dialect, delim = csv.excel_tab, "\t"
        else:
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
                delim = dialect.delimiter
            except csv.Error:
                dialect, delim = csv.excel, ","
        reader = csv.reader(handle, dialect, delimiter=delim)
        try:
            first = next(reader)
        except StopIteration:
            handle.close()
            raise DataError("the file is empty") from None
        header_flag = has_header
        if header_flag is None:
            try:
                header_flag = csv.Sniffer().has_header(sample)
            except csv.Error:
                header_flag = True
            # Sniffer misses all-text tables; text-only first rows are headers.
            if not header_flag and all(classify(c)[0] in ("string", "null") for c in first):
                header_flag = True
        if header_flag:
            header = [c.strip() or f"column_{i + 1}" for i, c in enumerate(first)]
            rows = reader
        else:
            header = [f"column_{i + 1}" for i in range(len(first))]
            rows = _chain([first], reader)
        return header[:max_columns], rows, {"encoding": encoding, "delimiter": delim,
                                            "header_row": bool(header_flag)}, handle
    if fmt == "json":
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DataError(f"not valid JSON: {exc}") from exc
        if isinstance(data, dict):
            lists = [v for v in data.values() if isinstance(v, list)]
            if len(lists) != 1:
                raise DataError("JSON must be an array of records, or an object holding one")
            data = lists[0]
        if not isinstance(data, list):
            raise DataError("JSON must be an array of records")
        header, rows = _records_to_rows(data, max_columns)
        return header, iter(rows), {}, None
    if fmt == "jsonl":
        records = []
        with path.open(encoding="utf-8-sig") as handle:
            for i, line in enumerate(handle, 1):
                if line.strip():
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError as exc:
                        raise DataError(f"line {i} is not valid JSON: {exc.msg}") from exc
        header, rows = _records_to_rows(records, max_columns)
        return header, iter(rows), {}, None
    if fmt == "xlsx":
        import openpyxl

        try:
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        except Exception as exc:  # noqa: BLE001
            raise DataError(f"cannot open workbook: {exc}") from exc
        names = wb.sheetnames
        if sheet and sheet not in names:
            raise DataError(f"no sheet {sheet!r}; sheets: {', '.join(names)}")
        ws = wb[sheet or names[0]]
        it = ws.iter_rows(values_only=True)
        try:
            first = next(it)
        except StopIteration:
            raise DataError("the sheet is empty") from None
        header = [str(c).strip() if c is not None else f"column_{i + 1}"
                  for i, c in enumerate(first)]
        return header[:max_columns], it, {"sheet": ws.title, "sheets": names}, wb
    if fmt == "parquet":
        try:
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise DataError("Parquet needs pyarrow: pip install 'hiraradata[parquet]'") from exc
        pf = pq.ParquetFile(path)
        header = pf.schema_arrow.names[:max_columns]

        def rows():
            for batch in pf.iter_batches(batch_size=50_000, columns=header):
                cols = [batch.column(i).to_pylist() for i in range(batch.num_columns)]
                yield from zip(*cols)

        return header, rows(), {"row_groups": pf.num_row_groups}, None
    raise DataError(f"unsupported format {fmt!r}; use csv, tsv, json, jsonl, xlsx or parquet")


def _chain(*iterables):
    for it in iterables:
        yield from it


def profile_path(path: Path, *, fmt: str | None = None, sheet: str | None = None,
                 delimiter: str | None = None, has_header: bool | None = None,
                 max_rows: int = 2_000_000, max_columns: int = 500, sample_rows: int = 5) -> dict:
    with path.open("rb") as handle:
        head = handle.read(4096)
    kind = detect_format(path, fmt, head)
    header, rows, details, closer = iter_table(path, fmt=kind, sheet=sheet, delimiter=delimiter,
                                               has_header=has_header, max_columns=max_columns)
    try:
        return _profile(header, rows, kind, details, max_rows=max_rows, sample_rows=sample_rows)
    finally:
        if closer is not None:
            closer.close()


def profile_records(data, *, max_rows: int, max_columns: int, sample_rows: int = 5) -> dict:
    header, rows = _records_to_rows(data, max_columns)
    return _profile(header, iter(rows), "records", {}, max_rows=max_rows, sample_rows=sample_rows)


def _profile(header, rows, kind, details, *, max_rows: int, sample_rows: int) -> dict:
    if not header:
        raise DataError("no columns found")
    cols = [Column(h) for h in header]
    width = len(cols)
    hashes: set[int] = set()
    dup_rows = 0
    dup_capped = False
    ragged = 0
    total = 0
    sample: list[dict] = []
    for row in rows:
        total += 1
        if total > max_rows:
            continue
        row = list(row)
        if len(row) != width:
            ragged += 1
            row = (row + [None] * width)[:width]
        for col, value in zip(cols, row):
            col.add(value)
        if len(sample) < sample_rows:
            sample.append({h: (v if isinstance(v, (str, int, float, bool)) or v is None else str(v))
                           for h, v in zip(header, row)})
        if not dup_capped:
            digest = int.from_bytes(hashlib.blake2b(
                json.dumps(row, default=str).encode(), digest_size=8).digest(), "big")
            if digest in hashes:
                dup_rows += 1
            else:
                hashes.add(digest)
                if len(hashes) >= DUP_CAP:
                    dup_capped = True
    profiled = min(total, max_rows)
    reports = [c.report() for c in cols]
    warnings = []
    for r in reports:
        name = r["name"]
        if r["type"] == "empty":
            warnings.append(f"{name}: every value is empty")
            continue
        if r["null_pct"] >= 30:
            warnings.append(f"{name}: {r['null_pct']}% missing")
        if r["distinct"] == 1 and not r["distinct_is_lower_bound"]:
            warnings.append(f"{name}: constant ({r['top_values'][0]['value']!r})")
        if "mixed" in r["type"]:
            warnings.append(f"{name}: mixed types {r.get('type_counts')}")
        filled = r["count"] - r["nulls"]
        if filled > 20 and r["distinct"] == filled and r["type"] in ("integer", "string"):
            warnings.append(f"{name}: unique per row (likely an identifier)")
        num = r.get("numeric")
        if num and num["outliers"] and num["outliers"] / max(1, filled) >= 0.01:
            warnings.append(f"{name}: ~{num['outliers']} outliers outside "
                            f"{num['outlier_fences'][0]:g}..{num['outlier_fences'][1]:g}")
    if dup_rows:
        warnings.append(f"{dup_rows} duplicate row(s)")
    if ragged:
        warnings.append(f"{ragged} row(s) with the wrong number of fields")
    lines = [f"{profiled} rows x {width} columns ({kind})"
             + (f", {total - profiled} more rows not profiled" if total > profiled else "")]
    for r in reports[:60]:
        bits = [r["type"], f"{r['null_pct']}% null", f"{r['distinct']}{'+' if r['distinct_is_lower_bound'] else ''} distinct"]
        if r.get("numeric"):
            n = r["numeric"]
            bits.append(f"{n['min']:g}..{n['max']:g}, median {n['median']:g}")
        elif r["top_values"]:
            bits.append("top " + ", ".join(repr(t["value"]) for t in r["top_values"][:3]))
        if r.get("date_range"):
            bits.append(f"{r['date_range'][0]}..{r['date_range'][1]}")
        lines.append(f"- {r['name']}: " + "; ".join(bits))
    lines += [f"! {w}" for w in warnings[:30]]
    return {
        "format": kind,
        **{k: v for k, v in details.items()},
        "rows": profiled,
        "rows_total": total,
        "columns": width,
        "duplicate_rows": dup_rows,
        "duplicates_is_lower_bound": dup_capped,
        "ragged_rows": ragged,
        "column_profiles": reports,
        "sample_rows": sample,
        "warnings": warnings,
        "text": "\n".join(lines),
        "truncated": total > profiled,
    }


__all__ = ["classify", "detect_format", "profile_path", "profile_records"]
