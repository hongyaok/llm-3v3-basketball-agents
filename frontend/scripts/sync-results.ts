import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

const FRONTEND_ROOT = path.resolve(__dirname, "..");
const REPO_ROOT = path.resolve(FRONTEND_ROOT, "..");
const SOURCE_RESULTS_DIR = path.join(REPO_ROOT, "results");
const DEST_RESULTS_DIR = path.join(FRONTEND_ROOT, "results");
const SOURCE_ARCH_HTML = path.join(REPO_ROOT, "system_architecture.html");
const DEST_STATIC_DIR = path.join(FRONTEND_ROOT, "public", "static");
const DEST_ARCH_HTML = path.join(DEST_STATIC_DIR, "system_architecture.html");

function sha256File(filePath: string): string {
  const hash = crypto.createHash("sha256");
  hash.update(fs.readFileSync(filePath));
  return hash.digest("hex");
}

function main() {
  if (!fs.existsSync(SOURCE_RESULTS_DIR)) {
    throw new Error(`Source results directory does not exist: ${SOURCE_RESULTS_DIR}`);
  }
  fs.mkdirSync(DEST_RESULTS_DIR, { recursive: true });
  fs.mkdirSync(DEST_STATIC_DIR, { recursive: true });

  const zipFiles = fs
    .readdirSync(SOURCE_RESULTS_DIR)
    .filter((name) => name.endsWith(".zip"))
    .sort();

  if (zipFiles.length === 0) {
    throw new Error(`No .zip files found in ${SOURCE_RESULTS_DIR}`);
  }

  const checksumLines: string[] = [];
  for (const name of zipFiles) {
    const src = path.join(SOURCE_RESULTS_DIR, name);
    const dst = path.join(DEST_RESULTS_DIR, name);
    fs.copyFileSync(src, dst);
    const digest = sha256File(dst);
    checksumLines.push(`${digest}  ${name}`);
  }

  fs.writeFileSync(
    path.join(DEST_RESULTS_DIR, "CHECKSUMS.sha256"),
    checksumLines.join("\n") + "\n",
    "utf-8"
  );

  if (!fs.existsSync(SOURCE_ARCH_HTML)) {
    throw new Error(`Architecture HTML not found at ${SOURCE_ARCH_HTML}`);
  }
  fs.copyFileSync(SOURCE_ARCH_HTML, DEST_ARCH_HTML);

  console.log(
    `Synced ${zipFiles.length} zip archive(s) to ${DEST_RESULTS_DIR} and system_architecture.html to ${DEST_ARCH_HTML}`
  );
}

main();

