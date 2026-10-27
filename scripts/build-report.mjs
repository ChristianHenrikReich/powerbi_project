import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const report = path.join(root, "solution", "reporting", "Sales.Report");
const json = (file) => JSON.parse(readFileSync(file, "utf8"));
const write = (file, value) => {
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, `${JSON.stringify(value, null, 2)}\n`, "utf8");
};
const pageId = json(path.join(report, "definition", "pages", "pages.json")).pageOrder[0];
const pageDir = path.join(report, "definition", "pages", pageId);
const pagePath = path.join(pageDir, "page.json");
const page = { ...json(pagePath), width: 1920, height: 1080 };
const snapDown = (n) => Math.floor(n / 8) * 8;
const snapUp = (n) => Math.ceil(n / 8) * 8;
const literal = (value) => ({
  expr: { Literal: { Value: typeof value === "boolean" ? String(value)
    : typeof value === "number" ? `${value}D` : `'${value.replaceAll("'", "''")}'` } },
});
const fill = (hex) => ({ solid: { color: literal(hex) } });
const props = (properties, selector) => [{ properties, ...(selector ? { selector } : {}) }];
const projection = (table, name, kind = "Measure") => ({
  field: { [kind]: { Expression: { SourceRef: { Entity: table } }, Property: name } },
  queryRef: `${table}.${name}`,
  nativeQueryRef: name,
});
const product = projection("Product", "Product", "Column");
const totalSales = projection("Sales", "Total Sales");
const totalQuantity = projection("Sales", "Total Quantity");
const averagePrice = projection("Sales", "Average Unit Price");
const query = (roles, sort = false) => ({
  queryState: Object.fromEntries(Object.entries(roles).map(([role, projections]) => [role, { projections }])),
  ...(sort ? { sortDefinition: { sort: [{ field: totalSales.field, direction: "Descending" }], isDefaultSort: true } } : {}),
});
const padding = (n) => props(Object.fromEntries(
  ["top", "bottom", "left", "right"].map((side) => [side, literal(n)]),
));
const region = ([left, top, right, bottom]) => {
  const cellW = (page.width - 64) / 12;
  const cellH = (page.height - 64) / 12;
  return {
    x: snapUp(32 + (left - 1) * cellW),
    y: snapUp(32 + (top - 1) * cellH),
    width: snapDown((right - left) * cellW - (right === 13 ? 0 : 24)),
    height: snapDown((bottom - top) * cellH - (bottom === 13 ? 0 : 24)),
  };
};
const chrome = (altText, title) => ({
  general: props({ altText: literal(altText) }),
  padding: padding(8),
  title: props({ show: literal(Boolean(title)), ...(title ? {
    text: literal(title), fontSize: literal(16), fontColor: fill("#242424"),
  } : {}) }),
  visualHeader: props({ show: literal(false) }),
});
const save = (name, type, rect, visual, order) => write(
  path.join(pageDir, "visuals", name, "visual.json"),
  {
    $schema: "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.9.0/schema.json",
    name,
    position: { ...rect, z: order, tabOrder: order },
    visual: { visualType: type, ...visual },
  },
);

write(pagePath, page);
save("page_title", "textbox", { ...region([1, 1, 9, 2]), height: 80 }, {
  objects: { general: props({ paragraphs: [{
    textRuns: [{ value: "Sales by product and category", textStyle: {
      fontFamily: "Segoe UI Semibold", fontSize: "32px", color: "#242424",
    } }],
    horizontalTextAlignment: "left",
  }] }) },
  visualContainerObjects: { ...chrome("Sales by product and category"), padding: padding(0) },
}, 0);

save("category_filter", "slicer", { ...region([9, 1, 13, 2]), height: 80 }, {
  query: query({ Values: [projection("Product", "Category", "Column")] }),
  objects: {
    data: props({ mode: literal("Dropdown") }),
    header: props({ show: literal(true), text: literal("Category") }),
  },
  visualContainerObjects: chrome("Filter all sales visuals by product category"),
}, 1);

const valueFont = Math.min(28, Math.max(12, Math.floor(page.height * 0.028)));
const labelFont = Math.min(14, Math.max(8, Math.floor(valueFont * 0.55)));
const cardHeight = snapUp(32 + 2 + Math.ceil(valueFont * 1.5) + Math.ceil(Math.max(labelFont, 12) * 1.5));
if (cardHeight > Math.floor(page.height * 0.15)) throw new Error("KPI cards exceed the canvas budget.");
const kpis = region([1, 2, 13, 4]);
for (const [index, [name, field, color, background]] of [
  ["total_sales", totalSales, "#0072B2", "#DEEFFF"],
  ["total_quantity", totalQuantity, "#595959", "#F2F2F2"],
].entries()) {
  const width = snapDown((kpis.width - 24) / 2);
  save(name, "cardVisual", {
    x: kpis.x + index * (width + 24),
    y: snapUp(kpis.y + (kpis.height - cardHeight) / 2),
    width, height: cardHeight,
  }, {
    query: query({ Data: [field] }),
    objects: {
      value: props({ fontSize: literal(valueFont), fontColor: fill(color) }, { id: "default" }),
      label: props({ fontSize: literal(labelFont), fontColor: fill("#242424") }, { id: "default" }),
      padding: props({ paddingUniform: literal(8) }, { id: "default" }),
      layout: props({ paddingUniform: literal(0) }, { id: "default" }),
      fillCustom: props({ show: literal(true), fillColor: fill(background) }, { id: "default" }),
    },
    visualContainerObjects: {
      ...chrome(`${field.nativeQueryRef} for the current category and product selection`),
      spacing: props({ customizeSpacing: literal(true), verticalSpacing: literal(2) }, { id: "default" }),
    },
  }, 2 + index);
}

save("product_ranking", "barChart", region([1, 4, 7, 13]), {
  query: query({ Category: [product], Y: [totalSales] }, true),
  objects: { dataPoint: props({ defaultColor: fill("#0072B2") }) },
  visualContainerObjects: chrome("Products ranked by total sales, highest first", "Sales by product"),
}, 4);

// A matrix gives dimension rows and measures separate binding roles.
save("product_detail", "pivotTable", region([7, 4, 13, 13]), {
  query: query({ Rows: [product], Values: [totalSales, totalQuantity, averagePrice] }, true),
  objects: {
    columnHeaders: props({ columnAdjustment: literal("growToFit"), autoSizeColumnWidth: literal(true) }),
  },
  visualContainerObjects: chrome("Sales, units, and quantity-weighted unit price by product", "Product detail"),
}, 5);
console.log(`Generated six visuals in ${pageDir}`);
