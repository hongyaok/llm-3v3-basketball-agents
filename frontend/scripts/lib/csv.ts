import { parse } from "csv-parse/sync";

/**
 * Faithful port of Python `_read_csv(path)` using `encoding="utf-8-sig"` and `csv.DictReader`.
 */
export function parseCsvText(content: string): Array<Record<string, string>> {
  const cleaned = content.charCodeAt(0) === 0xfeff ? content.slice(1) : content;
  if (!cleaned.trim()) return [];
  return parse(cleaned, {
    columns: true,
    skip_empty_lines: true,
    relax_quotes: false,
    bom: true,
  }) as Array<Record<string, string>>;
}

