"""Regenerate the sample report's six visuals using only the Python standard library."""

from __future__ import annotations

import json
import math
from pathlib import Path

REPORT_ROOT = Path(__file__).resolve().parent.parent / "solution" / "reporting" / "Sales.Report"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def snap_down(value: float) -> int:
    return math.floor(value / 8) * 8


def snap_up(value: float) -> int:
    return math.ceil(value / 8) * 8


def literal(value: str | bool | int | float) -> dict:
    if isinstance(value, bool):
        encoded = str(value).lower()
    elif isinstance(value, (int, float)):
        encoded = f"{value}D"
    else:
        encoded = "'" + value.replace("'", "''") + "'"
    return {"expr": {"Literal": {"Value": encoded}}}


def fill(color: str) -> dict:
    return {"solid": {"color": literal(color)}}


def props(properties: dict, selector: dict | None = None) -> list[dict]:
    result = {"properties": properties}
    if selector is not None:
        result["selector"] = selector
    return [result]


def projection(table: str, name: str, kind: str = "Measure") -> dict:
    return {
        "field": {kind: {"Expression": {"SourceRef": {"Entity": table}}, "Property": name}},
        "queryRef": f"{table}.{name}",
        "nativeQueryRef": name,
    }


def query(roles: dict, sort_by: dict | None = None) -> dict:
    result = {"queryState": {
        role: {"projections": projections} for role, projections in roles.items()
    }}
    if sort_by is not None:
        result["sortDefinition"] = {
            "sort": [{"field": sort_by["field"], "direction": "Descending"}],
            "isDefaultSort": True,
        }
    return result


def padding(value: int) -> list[dict]:
    return props({side: literal(value) for side in ("top", "bottom", "left", "right")})


def region(bounds: tuple[int, int, int, int], page: dict) -> dict:
    left, top, right, bottom = bounds
    cell_width = (page["width"] - 64) / 12
    cell_height = (page["height"] - 64) / 12
    return {
        "x": snap_up(32 + (left - 1) * cell_width),
        "y": snap_up(32 + (top - 1) * cell_height),
        "width": snap_down((right - left) * cell_width - (0 if right == 13 else 24)),
        "height": snap_down((bottom - top) * cell_height - (0 if bottom == 13 else 24)),
    }


def chrome(alt_text: str, title: str | None = None) -> dict:
    title_properties = {"show": literal(bool(title))}
    if title:
        title_properties.update({
            "text": literal(title), "fontSize": literal(16), "fontColor": fill("#242424"),
        })
    return {
        "general": props({"altText": literal(alt_text)}),
        "padding": padding(8),
        "title": props(title_properties),
        "visualHeader": props({"show": literal(False)}),
    }


def save_visual(
    page_dir: Path, name: str, visual_type: str, rect: dict, visual: dict, order: int
) -> None:
    write_json(page_dir / "visuals" / name / "visual.json", {
        "$schema": (
            "https://developer.microsoft.com/json-schemas/fabric/item/report/"
            "definition/visualContainer/2.9.0/schema.json"
        ),
        "name": name,
        "position": {**rect, "z": order, "tabOrder": order},
        "visual": {"visualType": visual_type, **visual},
    })


def build_report(report: Path = REPORT_ROOT) -> Path:
    pages_root = report / "definition" / "pages"
    page_id = read_json(pages_root / "pages.json")["pageOrder"][0]
    page_dir = pages_root / page_id
    page_path = page_dir / "page.json"
    page = {**read_json(page_path), "width": 1920, "height": 1080}
    product = projection("Product", "Product", "Column")
    total_sales = projection("Sales", "Total Sales")
    total_quantity = projection("Sales", "Total Quantity")
    average_price = projection("Sales", "Average Unit Price")

    write_json(page_path, page)
    save_visual(page_dir, "page_title", "textbox", {
        **region((1, 1, 9, 2), page), "height": 80,
    }, {
        "objects": {"general": props({"paragraphs": [{
            "textRuns": [{
                "value": "Sales by product and category",
                "textStyle": {
                    "fontFamily": "Segoe UI Semibold", "fontSize": "32px", "color": "#242424",
                },
            }],
            "horizontalTextAlignment": "left",
        }]})},
        "visualContainerObjects": {
            **chrome("Sales by product and category"), "padding": padding(0),
        },
    }, 0)

    save_visual(page_dir, "category_filter", "slicer", {
        **region((9, 1, 13, 2), page), "height": 80,
    }, {
        "query": query({"Values": [projection("Product", "Category", "Column")]}),
        "objects": {
            "data": props({"mode": literal("Dropdown")}),
            "header": props({"show": literal(True), "text": literal("Category")}),
        },
        "visualContainerObjects": chrome("Filter all sales visuals by product category"),
    }, 1)

    value_font = min(28, max(12, math.floor(page["height"] * 0.028)))
    label_font = min(14, max(8, math.floor(value_font * 0.55)))
    card_height = snap_up(
        32 + 2 + math.ceil(value_font * 1.5) + math.ceil(max(label_font, 12) * 1.5)
    )
    if card_height > math.floor(page["height"] * 0.15):
        raise ValueError("KPI cards exceed the canvas budget.")
    kpis = region((1, 2, 13, 4), page)
    for index, (name, field, color, background) in enumerate((
        ("total_sales", total_sales, "#0072B2", "#DEEFFF"),
        ("total_quantity", total_quantity, "#595959", "#F2F2F2"),
    )):
        width = snap_down((kpis["width"] - 24) / 2)
        save_visual(page_dir, name, "cardVisual", {
            "x": kpis["x"] + index * (width + 24),
            "y": snap_up(kpis["y"] + (kpis["height"] - card_height) / 2),
            "width": width,
            "height": card_height,
        }, {
            "query": query({"Data": [field]}),
            "objects": {
                "value": props({
                    "fontSize": literal(value_font), "fontColor": fill(color),
                }, {"id": "default"}),
                "label": props({
                    "fontSize": literal(label_font), "fontColor": fill("#242424"),
                }, {"id": "default"}),
                "padding": props({"paddingUniform": literal(8)}, {"id": "default"}),
                "layout": props({"paddingUniform": literal(0)}, {"id": "default"}),
                "fillCustom": props({
                    "show": literal(True), "fillColor": fill(background),
                }, {"id": "default"}),
            },
            "visualContainerObjects": {
                **chrome(
                    f"{field['nativeQueryRef']} for the current category and product selection"
                ),
                "spacing": props({
                    "customizeSpacing": literal(True), "verticalSpacing": literal(2),
                }, {"id": "default"}),
            },
        }, 2 + index)

    save_visual(page_dir, "product_ranking", "barChart", region((1, 4, 7, 13), page), {
        "query": query({"Category": [product], "Y": [total_sales]}, total_sales),
        "objects": {"dataPoint": props({"defaultColor": fill("#0072B2")})},
        "visualContainerObjects": chrome(
            "Products ranked by total sales, highest first", "Sales by product"
        ),
    }, 4)

    save_visual(page_dir, "product_detail", "pivotTable", region((7, 4, 13, 13), page), {
        "query": query({
            "Rows": [product], "Values": [total_sales, total_quantity, average_price],
        }, total_sales),
        "objects": {
            "columnHeaders": props({
                "columnAdjustment": literal("growToFit"), "autoSizeColumnWidth": literal(True),
            }),
        },
        "visualContainerObjects": chrome(
            "Sales, units, and quantity-weighted unit price by product", "Product detail"
        ),
    }, 5)
    return page_dir


if __name__ == "__main__":
    print(f"Generated six visuals in {build_report()}")
