"""Generate the synthetic dataset.

    uv run python -m opsagent.datagen --out ../data/synthetic

Output:
    catalog.json        vendors, purchase orders and payments (seeded into Postgres)
    ground_truth.json   expected extraction, decision and findings per invoice
    invoices/           the invoice files (PDF, scanned PDF, JPG, PNG)
"""

import argparse
import json
import random
import shutil
from collections import Counter
from pathlib import Path

from opsagent.datagen.render import render_file
from opsagent.datagen.scenarios import DatasetBuilder


def generate(out: Path, seed: int) -> None:
    builder = DatasetBuilder(seed=seed)
    builder.build()

    invoices_dir = out / "invoices"
    if invoices_dir.exists():
        shutil.rmtree(invoices_dir)
    invoices_dir.mkdir(parents=True)

    render_rng = random.Random(seed + 1)
    names: list[str] = []
    for i, planned in enumerate(builder.invoices, start=1):
        content, ext = render_file(planned.draft, planned.template, planned.render, render_rng)
        name = f"INV-{i:03d}.{ext}"
        (invoices_dir / name).write_bytes(content)
        names.append(name)

    catalog = builder.catalog()
    truths = builder.ground_truth(names)
    (out / "catalog.json").write_text(
        catalog.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    (out / "ground_truth.json").write_text(
        json.dumps([t.model_dump(mode="json") for t in truths], indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    counts = (len(truths), len(catalog.purchase_orders), len(catalog.payments))
    print("{} invoices, {} POs, {} payments".format(*counts))
    print("scenarios:", dict(Counter(t.scenario for t in truths)))
    print("renders:  ", dict(Counter(t.render.value for t in truths)))
    print("templates:", dict(Counter(t.template for t in truths)))
    print("actions:  ", dict(Counter(t.expected_action.value for t in truths)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("../data/synthetic"))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    generate(args.out, args.seed)


if __name__ == "__main__":
    main()
