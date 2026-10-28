# Courtside Frontend (`./frontend`)

Self-contained Next.js web application for the **LLM 3×3 Basketball Agents** study. Visualises the four experiments (`pilot_v1`, `abl_comms_v1`, `abl_captain_v1`, `abl_memory_v1`), renders the cross-study metric tables from `/comparisons`, provides an interactive half-court game replay viewer for all 36 recorded game logs, and embeds the interactive **System Architecture** page.

## What `public/data` contains

`npm run data` writes one JSON file per experiment plus two shared files:

| Path | Contents |
| --- | --- |
| `catalog.json` | Experiment list, default experiment, dataset counts |
| `comparisons.json` | Per-experiment primary metrics and validity summary |
| `experiments/<id>.json` | Full overview: metrics, paired seeds, adaptation rows, config |
| `boxscore/<id>.json` | Per-game passes, assists, rebounds and turnovers, averaged per condition |
| `replays/<id>/<game>.json` | Frame-level replay for one game |
| `downloads/<id>/` | Verbatim `games.csv`, `teams.csv`, `possessions.csv`, `stats.json` |

`boxscore/` is derived from the JSONL game logs at build time, because the CSV
exports do not carry counting stats. The rules are in
`scripts/lib/boxscore.ts`; the root README §5 states them in prose.

## Quick start (local)

From inside `frontend/`:

```bash
npm install
npm run build
npm run start
```

Then open [http://localhost:3000](http://localhost:3000).

For local development with hot reload:

```bash
npm run dev
```

## Scripts

| Script | Description |
| --- | --- |
| `npm run dev` | Builds static data from `results/*.zip` (if needed) and starts the Next.js dev server |
| `npm run data` | Runs `scripts/build-data.ts` to extract and transform `results/*.zip` into `public/data/` |
| `npm run build` | Automatically runs `prebuild` (`npm run data`) followed by `next build` |
| `npm run start` | Starts the production server (`next start`) |
| `npm run sync-results` | Syncs `../results/*.zip` and `../system_architecture.html` into `frontend/` and updates `results/CHECKSUMS.sha256` |
| `npm test` | Runs Vitest unit and Python-parity tests |
| `npm run typecheck` | Runs TypeScript type checking (`tsc --noEmit`) |

## Deploying to Vercel

1. **Git integration (recommended):**
   - Import the repository in Vercel.
   - Set **Root Directory** to `frontend`.
   - Framework Preset: **Next.js** (auto-detected).
   - Build Command: `npm run build` (default).
   - Output Directory: `.next` (default).
2. **Vercel CLI (direct from `frontend/`):**
   ```bash
   cd frontend
   vercel --prod
   ```
   `.vercelignore` excludes generated `public/data/`, `.next/`, and `node_modules/` so the upload stays well under the Hobby plan limit (~37 MB of source zips), and Vercel runs `npm run build` during deployment.

