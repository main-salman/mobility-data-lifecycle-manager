#!/usr/bin/env python3
import os, sys, csv, json, argparse
from datetime import datetime, timedelta
import concurrent.futures
import boto3

def normalize(s): return (s or "").strip().lower().replace(" ", "_")

def city_prefix(country, state, city):
    country_n, state_n, city_n = normalize(country), normalize(state), normalize(city)
    return f"data/{country_n}/{state_n}/{city_n}/" if state_n else f"data/{country_n}/{city_n}/"

def present_dates_for_city(s3, bucket, prefix):
    paginator = s3.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=bucket, Prefix=prefix, Delimiter="/")
    dates = set()
    for page in pages:
        for cp in page.get("CommonPrefixes", []):
            p = cp.get("Prefix", "")
            pos = p.rfind("date=")
            if pos != -1:
                ds = p[pos+5:pos+5+10]
                try: datetime.strptime(ds, "%Y-%m-%d"); dates.add(ds)
                except: pass
    return dates

def daterange(a, b):
    cur = a
    while cur <= b:
        yield cur
        cur += timedelta(days=1)

def group_missing_into_ranges(missing_sorted):
    if not missing_sorted: return []
    ranges = []
    s = prev = datetime.strptime(missing_sorted[0], "%Y-%m-%d")
    for ds in missing_sorted[1:]:
        d = datetime.strptime(ds, "%Y-%m-%d")
        if d == prev + timedelta(days=1): prev = d; continue
        ranges.append((s, prev)); s = prev = d
    ranges.append((s, prev))
    return ranges

def load_cities_csv(path):
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            country = row.get("country") or row.get("Country") or ""
            state = row.get("state_province") or row.get("State/Province") or row.get("state") or ""
            city = row.get("city") or row.get("City") or ""
            if country and city: out.append({"country": country, "state_province": state, "city": city})
    return out

def load_cities_json(path):
    with open(path, "r", encoding="utf-8") as f: data = json.load(f)
    out = []
    for c in data:
        country = c.get("country") or c.get("Country") or ""
        state = c.get("state_province") or c.get("State/Province") or c.get("state") or ""
        city = c.get("city") or c.get("City") or ""
        if country and city: out.append({"country": country, "state_province": state, "city": city})
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", default=os.getenv("S3_BUCKET_MOVEMENT_PINGS_TRIPS", "qoli-mobile-movement-ping-trips-dev"))
    ap.add_argument("--from", dest="from_date", required=True)
    ap.add_argument("--to", dest="to_date", required=True)
    ap.add_argument("--cities-file", help="CSV headers: country,state_province,city")
    ap.add_argument("--cities-json", help="Defaults to db/cities.json")
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--out-csv")
    args = ap.parse_args()

    start = datetime.strptime(args.from_date, "%Y-%m-%d")
    end = datetime.strptime(args.to_date, "%Y-%m-%d")
    if end < start: print("to_date must be >= from_date", file=sys.stderr); sys.exit(2)
    expected = {d.strftime("%Y-%m-%d") for d in daterange(start, end)}

    if args.cities_file:
        cities = load_cities_csv(args.cities_file)
    else:
        jp = args.cities_json or os.path.join("db", "cities.json")
        if not os.path.exists(jp): print("No cities source provided and db/cities.json not found.", file=sys.stderr); sys.exit(2)
        cities = load_cities_json(jp)
    if not cities: print("No cities loaded.", file=sys.stderr); sys.exit(2)

    s3 = boto3.client("s3")
    os.makedirs("reports", exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_csv = args.out_csv or os.path.join("reports", f"missing_dates_{ts}.csv")

    def process_city(c):
        prefix = city_prefix(c["country"], c.get("state_province", ""), c["city"])
        present = present_dates_for_city(s3, args.bucket, prefix)
        missing = sorted(expected - present)
        ranges = group_missing_into_ranges(missing)
        return {
            "country": c["country"], "state_province": c.get("state_province", ""), "city": c["city"],
            "prefix": prefix, "missing_dates": missing,
            "missing_ranges": [(a.strftime("%Y-%m-%d"), b.strftime("%Y-%m-%d")) for (a,b) in ranges],
        }

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.threads) as ex:
        for f in concurrent.futures.as_completed([ex.submit(process_city, c) for c in cities]):
            results.append(f.result())

    for r in sorted(results, key=lambda x: (normalize(x["country"]), normalize(x["state_province"]), normalize(x["city"]))):
        label = f'{r["country"]} / {r["state_province"]} / {r["city"]}'.replace(" /  /", " /")
        if not r["missing_dates"]:
            print(f"[OK] {label}: no missing days")
        else:
            ranges_str = "; ".join([f'{a}→{b}' if a != b else a for (a,b) in r["missing_ranges"]])
            print(f"[MISS] {label}: {len(r['missing_dates'])} days missing [{ranges_str}]")

    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["country","state_province","city","prefix","missing_count","missing_ranges","missing_dates"])
        for r in results:
            w.writerow([r["country"], r["state_province"], r["city"], r["prefix"],
                        len(r["missing_dates"]),
                        json.dumps(r["missing_ranges"], ensure_ascii=False),
                        json.dumps(r["missing_dates"], ensure_ascii=False)])
    print(f"\nWrote report to {out_csv}")

if __name__ == "__main__":
    main()
