import { readFile, readdir, stat } from "node:fs/promises";
import { join, resolve } from "node:path";

const root = resolve(new URL(".", import.meta.url).pathname, "..");
const echartsPackage = JSON.parse(await readFile(join(root, "node_modules/echarts/package.json"), "utf8"));
if (echartsPackage.license !== "Apache-2.0") {
  throw new Error(`unexpected echarts license: ${echartsPackage.license}`);
}
const assets = await readdir(join(root, "dist/assets"));
const jsFiles = assets.filter((name) => name.endsWith(".js"));
if (jsFiles.length === 0) throw new Error("production JavaScript bundle is missing");
const sizes = await Promise.all(jsFiles.map(async (name) => (await stat(join(root, "dist/assets", name))).size));
const totalBytes = sizes.reduce((total, size) => total + size, 0);
// ECharts is intentionally bundled for the operations visualization. Keep a
// hard upper bound so a future import of the full package cannot silently
// inflate the browser payload.
if (totalBytes > 900_000) throw new Error(`JavaScript bundle exceeds 900000 bytes: ${totalBytes}`);
const bundle = await Promise.all(jsFiles.map((name) => readFile(join(root, "dist/assets", name), "utf8"))).then((items) => items.join("\n"));
if (!bundle.includes("echarts")) throw new Error("ECharts is not present in the production bundle");
console.log(JSON.stringify({ status: "passed", echarts_license: echartsPackage.license, javascript_bytes: totalBytes }));
