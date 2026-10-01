const fs = require("node:fs");

const app = fs.readFileSync("frontend/app.js", "utf8");
const media = fs.readFileSync("frontend/retailer-media.js", "utf8");
const html = fs.readFileSync("frontend/index.html", "utf8");

const required = [
  ["frontend/app.js", app, "window.weweApiFetch = apiFetch;"],
  ["frontend/retailer-media.js", media, "/retailers/me/products/"],
  ["frontend/retailer-media.js", media, "new FormData()"],
  ["frontend/index.html", html, '<script src="app.js"></script>'],
  ["frontend/index.html", html, '<script src="retailer-media.js"></script>'],
];

for (const [file, content, marker] of required) {
  if (!content.includes(marker)) {
    throw new Error(`${file} is missing required frontend integration marker: ${marker}`);
  }
}

if (media.includes('""": "&quot;"')) {
  throw new Error("retailer-media.js contains the known malformed HTML-escape mapping.");
}

console.log("WEWE frontend smoke checks passed.");
