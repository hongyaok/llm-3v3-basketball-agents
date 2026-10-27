# Courtside Frontend (`./frontend`)

Self-contained Next.js web application for the **LLM 3×3 Basketball Agents** study. Visualises the three ablation experiments (`abl_comms_v1`, `abl_captain_v1`, `abl_memory_v1`), provides an interactive half-court game replay viewer for all 32 recorded game logs (31 exported + 1 log-only), and embeds the interactive **System Architecture** page.

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

