"""Import leads from Apollo.io (CSV export or Apollo API) into Sellbird.

Maps Apollo fields directly into Sellbird's companies and prospects tables:
- Company Name -> company.name
- Contact Person Name -> prospect.first_name, prospect.last_name
- Designation / Title -> prospect.title
- Mail ID -> prospect.email, prospect.email_status, prospect.email_verified
- Phone Number -> prospect.phone, company.phone
- Location -> company.location (City, State, India)
- Status -> prospect.status (default: 'new')

Usage:
    python scripts/import_apollo.py <path_to_apollo_export.csv>
    python scripts/import_apollo.py --sample   # generates a sample India manufacturing template
"""

import argparse
import asyncio
import csv
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sellbird.state import StateManager, Company, Prospect, _new_id, _norm


def clean_str(val) -> str:
    if val is None:
        return ""
    return str(val).strip()


def extract_col(row: dict, candidates: list[str]) -> str:
    """Find the first matching column name ignoring case and punctuation."""
    norm_row = {re.sub(r"[^a-z0-9]", "", k.lower()): v for k, v in row.items()}
    for cand in candidates:
        norm_cand = re.sub(r"[^a-z0-9]", "", cand.lower())
        if norm_cand in norm_row and norm_row[norm_cand]:
            return clean_str(norm_row[norm_cand])
    return ""


def pick_phone(row: dict) -> str:
    """Pick the best available phone number from Apollo columns."""
    for col in [
        "Work Direct Phone", "Mobile Phone", "Corporate Phone", "Direct Phone",
        "Phone", "Company Phone", "Primary Phone", "Sanitized Phone"
    ]:
        val = extract_col(row, [col])
        if val:
            return val
    return ""


def map_email_status(raw_status: str, email: str) -> tuple[str, bool]:
    s = (raw_status or "").lower()
    if not email:
        return ("", False)
    if any(w in s for w in ["verified", "valid"]):
        return ("verified", True)
    if any(w in s for w in ["extrapolated", "catch_all", "risky", "accept_all"]):
        return ("risky", False)
    if "unavailable" in s or "invalid" in s:
        return ("invalid", False)
    return ("guess", False)


async def import_csv_file(csv_path: Path) -> dict:
    state = StateManager()
    await state.init_db()

    if not csv_path.exists():
        print(f"[!] Error: File not found: {csv_path}")
        return {"companies": 0, "prospects": 0}

    # Open with utf-8-sig to handle Excel BOM
    with open(csv_path, mode="r", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print("[!] No rows found in CSV.")
        return {"companies": 0, "prospects": 0}

    company_cache = {}  # domain/name -> company_id
    imported_companies = 0
    imported_prospects = 0

    for r in rows:
        # Extract Company fields
        company_name = extract_col(r, ["Company", "Company Name", "Account Name", "Company Name for Emails"])
        website = extract_col(r, ["Website", "Company Website", "Domain", "Company Domain"])
        domain = _norm(website) if website else ""
        if not domain and company_name:
            domain = re.sub(r"[^a-z0-9]", "", company_name.lower()) + ".in"

        industry = extract_col(r, ["Industry", "Company Industry", "Keywords"]) or "Manufacturing"
        city = extract_col(r, ["City", "Company City"])
        state_loc = extract_col(r, ["State", "Company State"])
        country = extract_col(r, ["Country", "Company Country"]) or "India"
        location_parts = [p for p in [city, state_loc, country] if p]
        location = ", ".join(location_parts)

        phone = pick_phone(r)
        company_size = extract_col(r, ["# Employees", "Company Size", "Number of Employees"])

        comp_key = domain or company_name.lower()
        if not comp_key:
            continue

        if comp_key in company_cache:
            comp_id = company_cache[comp_key]
        else:
            comp = Company(
                name=company_name or domain,
                domain=domain,
                website=website if website.startswith("http") else (f"https://{website}" if website else ""),
                industry=industry,
                location=location,
                phone=phone,
                company_size=company_size,
                source="apollo",
            )
            comp_id = await state.add_company(comp)
            company_cache[comp_key] = comp_id
            imported_companies += 1

        # Extract Prospect fields
        first_name = extract_col(r, ["First Name", "Firstname"])
        last_name = extract_col(r, ["Last Name", "Lastname"])
        title = extract_col(r, ["Title", "Job Title", "Designation", "Role"])
        email = extract_col(r, ["Email", "Email Address", "Work Email"])
        raw_email_status = extract_col(r, ["Email Status", "Apollo Email Status", "Email Quality"])
        email_status, email_verified = map_email_status(raw_email_status, email)
        linkedin_url = extract_col(r, ["Person Linkedin Url", "LinkedIn Url", "Linkedin"])
        seniority = extract_col(r, ["Seniority"])
        stage_status = extract_col(r, ["Stage", "Status", "Outreach Status"]) or "new"

        if not email and not first_name and not last_name:
            continue

        prospect = Prospect(
            company_id=comp_id,
            first_name=first_name,
            last_name=last_name,
            title=title,
            email=email,
            email_status=email_status,
            email_verified=email_verified,
            phone=phone,
            phone_verified=bool(phone),
            linkedin_url=linkedin_url,
            seniority=seniority,
            company=company_name or domain,
            industry=industry,
            company_size=company_size,
            status=stage_status,
            source="apollo",
        )
        await state.add_prospect(prospect)
        imported_prospects += 1

    return {"companies": imported_companies, "prospects": imported_prospects, "total_rows": len(rows)}


def create_sample_csv(target_path: Path):
    headers = [
        "First Name", "Last Name", "Title", "Company Name", "Email", "Email Status",
        "Work Direct Phone", "Website", "Industry", "City", "State", "Country", "Stage"
    ]
    sample_data = [
        [
            "Rajesh", "Sharma", "Managing Director", "Apex Precision Forgings Pvt Ltd",
            "rajesh.sharma@apexforgings.in", "verified", "+91 98230 11223",
            "https://apexforgings.in", "Automotive & Forging", "Pune", "Maharashtra", "India", "new"
        ],
        [
            "Amit", "Patel", "CEO & Founder", "Gujarat Heavy Engineering Works",
            "amit.patel@gujarathwe.com", "verified", "+91 98790 44556",
            "https://gujarathwe.com", "Industrial Machinery", "Ahmedabad", "Gujarat", "India", "new"
        ],
        [
            "Suresh", "Rao", "Plant Head", "Vanguard Plastics & Packaging Ltd",
            "suresh.rao@vanguardplastics.co.in", "extrapolated", "+91 99400 77889",
            "https://vanguardplastics.co.in", "Chemicals & Plastics", "Chennai", "Tamil Nadu", "India", "new"
        ]
    ]
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with open(target_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(sample_data)
    print(f"[+] Sample Apollo template generated at: {target_path}")


def main():
    parser = argparse.ArgumentParser(description="Import leads from Apollo.io into Sellbird")
    parser.add_argument("csv_file", nargs="?", help="Path to Apollo CSV export file")
    parser.add_argument("--sample", action="store_true", help="Generate a sample CSV template for India manufacturing")
    args = parser.parse_args()

    if args.sample:
        sample_path = PROJECT_ROOT / "data" / "apollo_sample_india_manufacturing.csv"
        create_sample_csv(sample_path)
        return

    if not args.csv_file:
        parser.print_help()
        print("\nTip: To create a sample template run: python scripts/import_apollo.py --sample")
        return

    csv_path = Path(args.csv_file)
    print(f"\n[*] Importing leads from: {csv_path}")
    result = asyncio.run(import_csv_file(csv_path))
    print(f"\n[+] Import Summary:")
    print(f"    Total CSV Rows Read: {result.get('total_rows', 0)}")
    print(f"    New Companies Added: {result.get('companies', 0)}")
    print(f"    New Prospects Added: {result.get('prospects', 0)}")
    print(f"\n[+] Check them in the dashboard or run: sellbird export\n")


if __name__ == "__main__":
    main()
