import pandas as pd
import os

BASE_DIR = r"C:\Users\SBS\Desktop\Hsouna"
CSV_FILE = os.path.join(BASE_DIR, "HOMMES.csv")

# Read the CSV
df = pd.read_csv(CSV_FILE)

# Drop duplicates by passport, keep the first occurrence
df = df.drop_duplicates(subset=["numero_passport"], keep="first")

# Save back to ALL.csv (overwrite) or to a new file
output_file = os.path.join(BASE_DIR, "ALL_dedup.csv")
df.to_csv(output_file, index=False)

print(f"Deduplicated file saved to: {output_file}")
