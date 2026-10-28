import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";

const FRONTEND_ROOT = path.resolve(__dirname, "..");
const REPO_ROOT = path.resolve(FRONTEND_ROOT, "..");
const BUILD_SCRIPT = path.join(REPO_ROOT, "scripts", "build_frontend_results.py");
const SOURCE_ARCH_HTML = path.join(REPO_ROOT, "system_architecture.html");
const DEST_STATIC_DIR = path.join(FRONTEND_ROOT, "public", "static");
const DEST_ARCH_HTML = path.join(DEST_STATIC_DIR, "system_architecture.html");

function resolvePythonBin(): string {
  const winVenv = path.join(REPO_ROOT, ".venv", "Scripts", "python.exe");
  if (fs.existsSync(winVenv)) return winVenv;
  const nixVenv = path.join(REPO_ROOT, ".venv", "bin", "python");
  if (fs.existsSync(nixVenv)) return nixVenv;
  return "python";
}

function main() {
  const pythonBin = resolvePythonBin();
  execFileSync(pythonBin, [BUILD_SCRIPT], {
    cwd: REPO_ROOT,
    stdio: "inherit",
  });

  if (fs.existsSync(SOURCE_ARCH_HTML)) {
    fs.mkdirSync(DEST_STATIC_DIR, { recursive: true });
    fs.copyFileSync(SOURCE_ARCH_HTML, DEST_ARCH_HTML);
  } else if (!fs.existsSync(DEST_ARCH_HTML)) {
    throw new Error(`Architecture HTML not found at ${SOURCE_ARCH_HTML} or ${DEST_ARCH_HTML}`);
  }
}

main();
