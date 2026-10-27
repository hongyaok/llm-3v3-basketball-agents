import fs from "node:fs";
import path from "node:path";
import { unzipSync } from "fflate";

export interface ZipEntryMap {
  [entryPath: string]: Uint8Array;
}

export function validateSafeEntryPath(entryName: string): string {
  const normalized = entryName.replace(/\\/g, "/");
  if (normalized.startsWith("/") || /^[A-Za-z]:/.test(normalized)) {
    throw new Error(`Unsafe absolute zip entry path: ${entryName}`);
  }
  const parts = normalized.split("/");
  if (parts.some((p) => p === "..")) {
    throw new Error(`Unsafe zip entry path traversal: ${entryName}`);
  }
  return normalized;
}

export function shouldSkipZipEntry(entryName: string): boolean {
  const normalized = validateSafeEntryPath(entryName);
  if (!normalized || normalized.endsWith("/")) {
    return true;
  }
  const parts = normalized.split("/");
  if (parts.includes("__MACOSX")) {
    return true;
  }
  const base = path.posix.basename(normalized);
  if (base === ".DS_Store") {
    return true;
  }
  return false;
}

/**
 * Extract non-directory entries from a zip buffer or file path using pure JS (`fflate`).
 * Safely skips directory entries even when the archive stores non-zero data on directory records
 * (as in `interim_31games.zip`).
 */
export function readZipEntries(zipFilePathOrBuffer: string | Uint8Array): ZipEntryMap {
  const buffer =
    typeof zipFilePathOrBuffer === "string"
      ? new Uint8Array(fs.readFileSync(zipFilePathOrBuffer))
      : zipFilePathOrBuffer;

  const rawEntries = unzipSync(buffer, {
    filter(file) {
      return !shouldSkipZipEntry(file.name);
    },
  });

  const out: ZipEntryMap = {};
  for (const [name, data] of Object.entries(rawEntries)) {
    const clean = validateSafeEntryPath(name);
    if (!shouldSkipZipEntry(clean)) {
      out[clean] = data;
    }
  }
  return out;
}

export function decodeUtf8(bytes: Uint8Array): string {
  const text = Buffer.from(bytes.buffer, bytes.byteOffset, bytes.byteLength).toString("utf-8");
  return text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
}

