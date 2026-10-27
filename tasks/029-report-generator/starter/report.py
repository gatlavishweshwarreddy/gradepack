from loader import load_records
from normaliser import normalise
from aggregator import group_by, sum_field


def generate(raw_records):
    records = normalise(load_records(raw_records))

    by_region_groups  = group_by(records, "region")
    by_product_groups = group_by(records, "product")

    by_region  = {k: sum_field(v, "amount") for k, v in by_region_groups.items()}
    by_product = {k: sum_field(v, "amount") for k, v in by_product_groups.items()}

    # BUG: sums the product subtotals AND region subtotals (double counting)
    grand_total = sum(by_region.values()) + sum(by_product.values())

    return {
        "by_region":   by_region,
        "by_product":  by_product,
        "grand_total": round(grand_total, 2),
    }
