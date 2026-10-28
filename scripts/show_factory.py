import glob
import json

ids = ["043", "044", "048", "050", "052"]
print("Factory output: judge review and probe results for each promoted task\n")
for i in ids:
    for f in glob.glob(f"reviews/{i}-*.json"):
        r = json.load(open(f))
        pr = r.get("probe_results") or []
        name = f.split("/")[-1][:-5]
        verdict = str(r.get("verdict"))
        fair = str(r.get("fair"))
        print(f"  {name:36s} judge: {verdict:7s} fair: {fair:5s} probes solved: {sum(pr)}/{len(pr)}  -> {r.get('classification')}")

seen, out = set(), []
for line in reversed([l.strip() for l in open("LESSONS.md") if l.startswith("- ")]):
    if line not in seen:
        seen.add(line)
        out.append(line)
print("\nLessons learned from rejected drafts (fed into the next drafting prompt):")
for line in reversed(out[:5]):
    short = line if len(line) <= 118 else line[:118].rsplit(" ", 1)[0] + " ..."
    print("  " + short)
