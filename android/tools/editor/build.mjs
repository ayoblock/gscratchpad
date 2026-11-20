// 可复现打包：esbuild 把 CodeMirror 6 打成单文件，再内联进 index.html。
// 内联的原因：WebView 每个 asset 请求都有固定开销，把 css/js 合进 HTML 能把首屏加载压下来。
import * as esbuild from "esbuild";
import { readFileSync, writeFileSync } from "node:fs";

const OUT_DIR = "../../app/src/main/assets/editor";

const result = await esbuild.build({
  entryPoints: ["src/editor.js"],
  bundle: true,
  minify: true,
  format: "iife",
  target: "chrome100",
  write: false,
  logLevel: "info",
});

const js = result.outputFiles[0].text;
const css = readFileSync("src/editor.css", "utf8");
const template = readFileSync("src/index.template.html", "utf8");

const html = template
  .replace("/*__CSS__*/", () => css)
  .replace("/*__JS__*/", () => js);

writeFileSync(`${OUT_DIR}/index.html`, html);
writeFileSync(`${OUT_DIR}/editor.js`, js);
writeFileSync(`${OUT_DIR}/editor.css`, css);
console.log(`index.html ${html.length} bytes (inline js+cs)`);
