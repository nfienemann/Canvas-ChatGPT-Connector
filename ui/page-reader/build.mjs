import { build } from "esbuild";
import { readFile, writeFile } from "node:fs/promises";
import { dirname, resolve, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const assets = resolve(root, "../../src/canvas_bridge/assets");
const result = await build({
  absWorkingDir: root,
  entryPoints: ["reader.js"],
  bundle: true, minify: true, format: "iife", target: "es2022",
  outfile: join(assets, "page-reader.js"), legalComments: "eof", metafile: true,
});
const download = await build({
  absWorkingDir: root,
  entryPoints: ["download.js"],
  bundle: true, minify: true, format: "iife", target: "es2022",
  outfile: join(assets, "original-download.js"), legalComments: "eof", metafile: true,
});
const packages = new Map();
for (const input of Object.keys({...result.metafile.inputs, ...download.metafile.inputs})) {
  if (!input.includes("node_modules/")) continue;
  let folder = dirname(resolve(root, input));
  while (folder !== dirname(folder)) {
    try {
      const pkg = JSON.parse(await readFile(join(folder, "package.json"), "utf8"));
      if (pkg.name && pkg.license) {
        packages.set(pkg.name, { folder, pkg });
        break;
      }
    } catch { /* Walk to the containing package manifest. */ }
    folder = dirname(folder);
  }
}
const notices = [];
for (const [name, {folder, pkg}] of [...packages].sort(([a],[b]) => a.localeCompare(b))) {
  let license;
  for (const file of ["LICENSE", "LICENSE.md", "LICENSE.txt"]) {
    try { license = await readFile(join(folder, file), "utf8"); break; } catch {}
  }
  if (!license) throw Error(`Missing license for bundled dependency ${name}`);
  const normalizedLicense = license.trim().replaceAll("\r\n", "\n").replace(/[\t ]+$/gm, "");
  notices.push(`${name} ${pkg.version} (${pkg.license})\n${normalizedLicense}`);
}
await writeFile(join(assets, "page-reader-NOTICES.txt"), notices.join("\n\n--------------------\n\n") + "\n");
