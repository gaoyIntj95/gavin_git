import csv
from datetime import datetime
from pathlib import Path
import json
import shutil

from app.models.cbam_data import CbamData


def estimate_cbam_metrics(total_emission: float, product_quantity: float, eu_carbon_price: float) -> tuple[float, float]:
    carbon_footprint = round(total_emission / product_quantity, 6)
    carbon_tariff = round(total_emission * eu_carbon_price, 6)
    return carbon_footprint, carbon_tariff


def generate_cbam_template(path: Path, items: list[CbamData]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["product_name", "quantity", "unit", "carbon_footprint", "eu_carbon_price", "carbon_tariff"])
        for item in items:
            writer.writerow(
                [
                    item.product_name,
                    item.product_quantity,
                    item.unit,
                    item.carbon_footprint,
                    item.eu_carbon_price,
                    item.carbon_tariff,
                ]
            )
    return str(path)


def build_template_filename(project_id: int) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"cbam_template_{project_id}_{stamp}.csv"


def summarize_cbam(items: list[CbamData]) -> dict:
    total_quantity = round(sum(float(x.product_quantity or 0.0) for x in items), 6)
    total_tariff = round(sum(float(x.carbon_tariff or 0.0) for x in items), 6)
    return {
        "total_products": len(items),
        "total_quantity": total_quantity,
        "total_carbon_tariff": total_tariff,
        "items": [
            {
                "product_name": x.product_name,
                "product_quantity": float(x.product_quantity),
                "unit": x.unit,
                "carbon_footprint": float(x.carbon_footprint),
                "eu_carbon_price": float(x.eu_carbon_price),
                "carbon_tariff": float(x.carbon_tariff),
            }
            for x in items
        ],
    }


def build_cbam_package_filename(project_id: int) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"cbam_package_{project_id}_{stamp}.zip"


def generate_cbam_package(base_dir: Path, project_id: int, items: list[CbamData]) -> str:
    base_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    work_dir = base_dir / f"cbam_package_{project_id}_{stamp}"
    work_dir.mkdir(parents=True, exist_ok=True)

    csv_path = work_dir / f"cbam_items_{project_id}.csv"
    generate_cbam_template(csv_path, items)

    summary = summarize_cbam(items)
    summary_path = work_dir / "cbam_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest_path = work_dir / "README.txt"
    manifest_path.write_text(
        "\n".join(
            [
                "CBAM申报材料包",
                f"project_id={project_id}",
                f"generated_at={datetime.utcnow().isoformat()}Z",
                f"total_products={summary['total_products']}",
                f"total_quantity={summary['total_quantity']}",
                f"total_carbon_tariff={summary['total_carbon_tariff']}",
                "files:",
                f"- {csv_path.name}",
                f"- {summary_path.name}",
            ]
        ),
        encoding="utf-8",
    )

    zip_base = str(base_dir / f"cbam_package_{project_id}_{stamp}")
    archive = shutil.make_archive(zip_base, "zip", root_dir=work_dir)
    return archive
