"""Write the demo elder's care plan (and a believable week of doses) into the deployed tables.

    python scripts/seed_demo.py <CarePlansTableName> <AdherenceTableName>

Table names are in the `sam deploy` outputs. Uses your normal AWS credentials and region.
"""
import os
import sys

import boto3

os.environ["RAKSHA_MODE"] = "aws"  # real tables, not the local simulation
sys.path.insert(0, ".")
from raksha_mcp import bootstrap  # noqa: E402  (local mode is off when RAKSHA_MODE=aws)


def main(care_plans_table, adherence_table):
    bootstrap.TABLES["CARE_PLANS_TABLE"] = (care_plans_table, "patient_id", None)
    bootstrap.TABLES["ADHERENCE_TABLE"] = (adherence_table, "patient_id", "timestamp")
    bootstrap.seed_demo_data(boto3.resource("dynamodb"))
    print(f"Seeded {bootstrap.DEMO_PATIENT_ID} in {care_plans_table} and {adherence_table}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
