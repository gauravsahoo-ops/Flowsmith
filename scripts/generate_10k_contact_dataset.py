"""Deterministic generator for Flowsmith 10,000 Contact CSV dataset.

Dataset Specification:
- Total rows: 10,000 (excluding header)
- Unique records: 9,800
- Exact duplicate records: 200 (injected from the first 200 rows)
- Seed: 42 (completely deterministic)
- Fields (Salesforce Contact standard fields):
  FirstName, LastName, Email, Phone, Department, Title,
  MailingStreet, MailingCity, MailingState, MailingPostalCode,
  MailingCountry, Description
"""

import csv
import hashlib
import json
import random
from pathlib import Path

FIRST_NAMES = [
    "James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael", "Linda",
    "David", "Elizabeth", "William", "Barbara", "Richard", "Susan", "Joseph", "Jessica",
    "Thomas", "Sarah", "Charles", "Karen", "Christopher", "Nancy", "Daniel", "Lisa",
    "Matthew", "Betty", "Anthony", "Margaret", "Mark", "Sandra", "Donald", "Ashley",
    "Steven", "Kimberly", "Paul", "Emily", "Andrew", "Donna", "Joshua", "Michelle",
    "Kenneth", "Carol", "Kevin", "Amanda", "Brian", "Dorothy", "George", "Melissa",
    "Edward", "Deborah", "Ronald", "Stephanie", "Timothy", "Rebecca", "Jason", "Sharon"
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
    "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
    "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson",
    "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker",
    "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores",
    "Green", "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell", "Carter"
]

DEPARTMENTS = ["Engineering", "Sales", "Operations", "Finance", "Legal", "Marketing", "Customer Support", "Product", "Human Resources"]
TITLES = ["Director", "Manager", "Lead Specialist", "Vice President", "Consultant", "Engineer", "Analyst", "Coordinator", "Administrator"]
CITIES = [
    ("New York", "NY", "10001", "United States"),
    ("San Francisco", "CA", "94105", "United States"),
    ("Austin", "TX", "78701", "United States"),
    ("Seattle", "WA", "98101", "United States"),
    ("Chicago", "IL", "60601", "United States"),
    ("Boston", "MA", "02108", "United States"),
    ("Denver", "CO", "80202", "United States"),
    ("Atlanta", "GA", "30303", "United States")
]

FIELDS = [
    "FirstName", "LastName", "Email", "Phone", "Department", "Title",
    "MailingStreet", "MailingCity", "MailingState", "MailingPostalCode",
    "MailingCountry", "Description"
]

def generate_dataset(output_path: Path, manifest_path: Path, seed: int = 42):
    rng = random.Random(seed)
    records = []

    # Generate 9,800 unique records
    for i in range(1, 9801):
        fn = rng.choice(FIRST_NAMES)
        ln = rng.choice(LAST_NAMES)
        email = f"contact_{i}_{fn.lower()}.{ln.lower()}@flowsmith-bench.example.com"
        phone = f"+1-555-{rng.randint(100, 999):03d}-{rng.randint(1000, 9999):04d}"
        dept = rng.choice(DEPARTMENTS)
        title = rng.choice(TITLES)
        city, state, zip_code, country = rng.choice(CITIES)
        street = f"{rng.randint(100, 9999)} Enterprise Blvd, Suite {rng.randint(100, 900)}"
        desc = f"Synthetic enterprise benchmark contact #{i}. Verification record for Flowsmith performance testing."

        record = {
            "FirstName": fn,
            "LastName": ln,
            "Email": email,
            "Phone": phone,
            "Department": dept,
            "Title": title,
            "MailingStreet": street,
            "MailingCity": city,
            "MailingState": state,
            "MailingPostalCode": zip_code,
            "MailingCountry": country,
            "Description": desc,
        }
        records.append(record)

    # Inject 200 exact duplicates from the first 200 rows at deterministic intervals
    duplicates = [dict(records[j]) for j in range(200)]
    for dup in duplicates:
        records.append(dup)

    assert len(records) == 10000, f"Expected 10,000 records, got {len(records)}"

    # Write CSV with standard UTF-8 encoding
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)

    # Compute checksum
    sha256 = hashlib.sha256()
    with open(output_path, "rb") as f:
        while chunk := f.read(65536):
            sha256.update(chunk)
    checksum = sha256.hexdigest()
    file_size = output_path.stat().st_size

    manifest = {
        "dataset_name": "flowsmith_salesforce_contact_10000.csv",
        "total_rows": 10000,
        "unique_rows": 9800,
        "duplicate_rows": 200,
        "columns": FIELDS,
        "target_salesforce_object": "Contact",
        "file_size_bytes": file_size,
        "sha256_checksum": checksum,
        "random_seed": seed,
        "generator_script": "scripts/generate_10k_contact_dataset.py"
    }

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"Generated {output_path} successfully.")
    print(f"Total Rows: {len(records)}")
    print(f"File Size: {file_size} bytes")
    print(f"SHA256: {checksum}")
    print(f"Manifest saved to {manifest_path}")

if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    csv_file = root / "flowsmith_salesforce_contact_10000.csv"
    manifest_file = root / "docs" / "performance" / "flowsmith_salesforce_contact_10000_manifest.json"
    manifest_file.parent.mkdir(parents=True, exist_ok=True)
    generate_dataset(csv_file, manifest_file)
