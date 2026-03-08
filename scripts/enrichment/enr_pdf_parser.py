#!/usr/bin/env python3
"""
Parse ENR Top 400 Contractors data from the official PDF.

Extracts all 400 company entries with 15 fields each:
rank, previous rank, firm name, city, state, subsidiaries flag,
revenue, international revenue, new contracts, 8 sector percentages,
and CM-at-Risk percentage.

Usage:
    python -m scripts.enrichment.enr_pdf_parser /path/to/ENR-2024-Top-400.pdf
    python -m scripts.enrichment.enr_pdf_parser --output enr_data.json /path/to/pdf
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import fitz  # PyMuPDF

# AP-style state abbreviations → 2-letter postal codes
AP_STATE_MAP: dict[str, str] = {
    "Ala.": "AL",
    "Alaska": "AK",
    "Ariz.": "AZ",
    "Ark.": "AR",
    "Calif.": "CA",
    "Colo.": "CO",
    "Conn.": "CT",
    "Del.": "DE",
    "D.C.": "DC",
    "Fla.": "FL",
    "Ga.": "GA",
    "Hawaii": "HI",
    "Idaho": "ID",
    "Ill.": "IL",
    "Ind.": "IN",
    "Iowa": "IA",
    "Kan.": "KS",
    "Ky.": "KY",
    "La.": "LA",
    "Maine": "ME",
    "Md.": "MD",
    "Mass.": "MA",
    "Mich.": "MI",
    "Minn.": "MN",
    "Miss.": "MS",
    "Mo.": "MO",
    "Mont.": "MT",
    "Neb.": "NE",
    "Nev.": "NV",
    "N.H.": "NH",
    "N.J.": "NJ",
    "N.M.": "NM",
    "N.Y.": "NY",
    "N.C.": "NC",
    "N.D.": "ND",
    "Ohio": "OH",
    "Okla.": "OK",
    "Ore.": "OR",
    "Pa.": "PA",
    "R.I.": "RI",
    "S.C.": "SC",
    "S.D.": "SD",
    "Tenn.": "TN",
    "Texas": "TX",
    "Utah": "UT",
    "Vt.": "VT",
    "Va.": "VA",
    "Wash.": "WA",
    "W.Va.": "WV",
    "Wis.": "WI",
    "Wyo.": "WY",
}

# Sector column names in display order (matches PDF column order)
SECTOR_NAMES = [
    "General Building",
    "Manufacturing",
    "Power",
    "Water/Sewer/Waste",
    "Industrial/Petroleum",
    "Transportation",
    "Hazardous Waste",
    "Telecom",
]


def _convert_state(ap_state: str) -> str:
    """Convert AP-style state abbreviation to 2-letter postal code."""
    ap_state = ap_state.strip().rstrip("†")
    if ap_state in AP_STATE_MAP:
        return AP_STATE_MAP[ap_state]
    # Already a 2-letter code
    if len(ap_state) == 2 and ap_state.isalpha():
        return ap_state.upper()
    raise ValueError(f"Unknown state abbreviation: {repr(ap_state)}")


def _parse_firm_field(field: str) -> tuple[str, str, str, bool]:
    """Parse firm field: 'FIRM NAME, City, State†' → (name, city, state, has_subsidiaries).

    Returns (firm_name, hq_city, hq_state_2letter, has_subsidiaries).
    """
    text = field.strip()
    has_subsidiaries = text.endswith("†")
    if has_subsidiaries:
        text = text[:-1].strip()

    # Split on last two commas to get: FIRM NAME, City, State
    # Some firm names contain commas (rare), so split from the right
    parts = text.rsplit(",", 2)
    if len(parts) == 3:
        firm_name = parts[0].strip()
        city = parts[1].strip()
        state_ap = parts[2].strip()
    elif len(parts) == 2:
        # Edge case: city might contain no comma separation from state
        firm_name = parts[0].strip()
        # Try to split the last part into city + state
        last = parts[1].strip()
        # State is the last word
        words = last.rsplit(" ", 1)
        if len(words) == 2:
            city = words[0].strip()
            state_ap = words[1].strip()
        else:
            city = last
            state_ap = ""
    else:
        raise ValueError(f"Cannot parse firm field: {repr(field)}")

    state_2letter = _convert_state(state_ap)
    return firm_name, city, state_2letter, has_subsidiaries


def _parse_float(s: str) -> float | None:
    """Parse a float from comma-formatted string, or None for 'NA'."""
    s = s.strip()
    if s.upper() == "NA":
        return None
    return float(s.replace(",", ""))


def _parse_int(s: str) -> int | None:
    """Parse an integer, or None for '**' (new entrant)."""
    s = s.strip()
    if s == "**":
        return None
    return int(s)


def parse_enr_pdf(pdf_path: str) -> list[dict]:
    """Parse all 400 company entries from the ENR Top 400 PDF.

    Returns a list of dicts, one per company, sorted by rank.
    """
    doc = fitz.open(pdf_path)
    entries: list[dict] = []

    # Data table spans pages 18-25 (0-indexed: 17-24)
    for page_num in range(17, 25):
        page = doc[page_num]
        blocks = page.get_text("blocks")

        for block in blocks:
            text = block[4]
            # Skip header blocks and non-data blocks
            if not text.strip() or block[6] != 0:  # type 0 = text
                continue

            # Data rows contain tab characters — headers don't have the right pattern
            if "\t" not in text:
                continue

            # Split on \t and \n, filter empties
            tokens = [t.strip() for t in re.split(r"[\t\n]+", text) if t.strip()]

            # A valid data row has exactly 15 tokens:
            # rank, prev_rank, firm_field, revenue, intl_rev, new_contracts,
            # 8 sector pcts, cm_at_risk
            if len(tokens) != 15:
                continue

            # First token must be a rank number (1-400)
            try:
                rank = int(tokens[0])
            except ValueError:
                continue
            if rank < 1 or rank > 400:
                continue

            try:
                prev_rank = _parse_int(tokens[1])
                firm_name, hq_city, hq_state, has_subs = _parse_firm_field(tokens[2])
                revenue = _parse_float(tokens[3])
                intl_revenue = _parse_float(tokens[4])
                new_contracts = _parse_float(tokens[5])

                # 8 sector percentages (indices 6-13)
                sector_pcts = [int(tokens[i]) for i in range(6, 14)]

                # CM-at-Risk percentage (index 14)
                cm_at_risk = int(tokens[14])

                # Build sectors dict
                sectors = {}
                for name, pct in zip(SECTOR_NAMES, sector_pcts, strict=False):
                    sectors[name] = pct

                entry = {
                    "rank_2024": rank,
                    "rank_2023": prev_rank,
                    "firm_name": firm_name,
                    "hq_city": hq_city,
                    "hq_state": hq_state,
                    "has_subsidiaries": has_subs,
                    "revenue_2023_mil": revenue,
                    "intl_revenue_mil": intl_revenue,
                    "new_contracts_2023_mil": new_contracts,
                    "sectors": sectors,
                    "cm_at_risk_pct": cm_at_risk,
                }
                entries.append(entry)

            except Exception as e:
                print(f"ERROR parsing rank {rank}: {e}", file=sys.stderr)
                print(f"  tokens: {tokens}", file=sys.stderr)
                continue

    doc.close()
    entries.sort(key=lambda x: x["rank_2024"])
    return entries


def validate_entries(entries: list[dict]) -> list[str]:
    """Validate parsed entries. Returns list of warning messages."""
    warnings = []

    # Check we got all 400
    if len(entries) != 400:
        warnings.append(f"Expected 400 entries, got {len(entries)}")

    # Check rank continuity
    ranks = {e["rank_2024"] for e in entries}
    expected_ranks = set(range(1, 401))
    missing = expected_ranks - ranks
    extra = ranks - expected_ranks
    if missing:
        warnings.append(f"Missing ranks: {sorted(missing)}")
    if extra:
        warnings.append(f"Extra ranks: {sorted(extra)}")

    # Check for duplicate ranks
    rank_counts: dict[int, int] = {}
    for e in entries:
        r = e["rank_2024"]
        rank_counts[r] = rank_counts.get(r, 0) + 1
    dupes = {r: c for r, c in rank_counts.items() if c > 1}
    if dupes:
        warnings.append(f"Duplicate ranks: {dupes}")

    # Validate sector sums
    bad_sums = []
    for e in entries:
        sector_sum = sum(e["sectors"].values())
        if sector_sum < 95 or sector_sum > 105:
            bad_sums.append((e["rank_2024"], e["firm_name"], sector_sum))
    if bad_sums:
        for rank, name, s in bad_sums:
            warnings.append(f"Sector sum out of range for #{rank} {name}: {s}%")

    # Check revenue values are positive
    for e in entries:
        if e["revenue_2023_mil"] is not None and e["revenue_2023_mil"] < 0:
            warnings.append(f"Negative revenue for #{e['rank_2024']} {e['firm_name']}")

    return warnings


def main():
    parser = argparse.ArgumentParser(description="Parse ENR Top 400 PDF")
    parser.add_argument("pdf_path", help="Path to ENR Top 400 PDF")
    parser.add_argument("--output", "-o", default=None, help="Output JSON file path")
    args = parser.parse_args()

    if not Path(args.pdf_path).exists():
        print(f"File not found: {args.pdf_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Parsing {args.pdf_path}...")
    entries = parse_enr_pdf(args.pdf_path)
    print(f"Parsed {len(entries)} entries")

    # Validate
    warnings = validate_entries(entries)
    if warnings:
        print(f"\n{len(warnings)} warnings:")
        for w in warnings:
            print(f"  - {w}")
    else:
        print("All validations passed!")

    # Show sector sum stats
    sums = [sum(e["sectors"].values()) for e in entries]
    print(
        f"\nSector sum stats: min={min(sums)}, max={max(sums)}, " f"avg={sum(sums)/len(sums):.1f}"
    )
    exact_100 = sum(1 for s in sums if s == 100)
    print(f"Entries with sector sum exactly 100: {exact_100}/{len(entries)}")

    # Print first 5 and last 5 as sample
    print("\n--- First 5 entries ---")
    for e in entries[:5]:
        sectors_str = ", ".join(f"{k}: {v}%" for k, v in e["sectors"].items() if v > 0)
        print(
            f"  #{e['rank_2024']} ({e['rank_2023'] or 'NEW'}) "
            f"{e['firm_name']}, {e['hq_city']}, {e['hq_state']}"
            f"{'†' if e['has_subsidiaries'] else ''}"
        )
        print(
            f"    Rev: ${e['revenue_2023_mil']}M | "
            f"Int'l: ${e['intl_revenue_mil']}M | "
            f"New: {'$' + str(e['new_contracts_2023_mil']) + 'M' if e['new_contracts_2023_mil'] else 'NA'}"
        )
        print(f"    Sectors: {sectors_str} | CM-at-Risk: {e['cm_at_risk_pct']}%")

    print("\n--- Last 5 entries ---")
    for e in entries[-5:]:
        sectors_str = ", ".join(f"{k}: {v}%" for k, v in e["sectors"].items() if v > 0)
        print(
            f"  #{e['rank_2024']} ({e['rank_2023'] or 'NEW'}) "
            f"{e['firm_name']}, {e['hq_city']}, {e['hq_state']}"
            f"{'†' if e['has_subsidiaries'] else ''}"
        )
        print(
            f"    Rev: ${e['revenue_2023_mil']}M | "
            f"Int'l: ${e['intl_revenue_mil']}M | "
            f"New: {'$' + str(e['new_contracts_2023_mil']) + 'M' if e['new_contracts_2023_mil'] else 'NA'}"
        )
        print(f"    Sectors: {sectors_str} | CM-at-Risk: {e['cm_at_risk_pct']}%")

    # Output JSON
    output_path = args.output or "enr_top_400_parsed.json"
    with open(output_path, "w") as f:
        json.dump(entries, f, indent=2)
    print(f"\nJSON output: {output_path}")


if __name__ == "__main__":
    main()
