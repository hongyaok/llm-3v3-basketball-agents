import { describe, expect, it, beforeAll, afterAll } from "vitest";
import { spawn, type ChildProcess } from "node:child_process";
import path from "node:path";

const FRONTEND_ROOT = path.resolve(__dirname, "../..");
const PORT = 38765;
const BASE_URL = `http://127.0.0.1:${PORT}`;

describe("next start production server smoke tests", () => {
  let serverProc: ChildProcess | null = null;

  beforeAll(async () => {
    const nextBin = path.join(
      FRONTEND_ROOT,
      "node_modules",
      "next",
      "dist",
      "bin",
      "next"
    );
    serverProc = spawn(
      process.execPath,
      [nextBin, "start", "-p", String(PORT), "-H", "127.0.0.1"],
      {
        cwd: FRONTEND_ROOT,
        stdio: "pipe",
      }
    );

    const deadline = Date.now() + 20000;
    while (Date.now() < deadline) {
      try {
        const res = await fetch(`${BASE_URL}/`);
        if (res.ok) return;
      } catch {
        // wait for server
      }
      await new Promise((r) => setTimeout(r, 250));
    }
    throw new Error("Timed out waiting for next start");
  });

  afterAll(() => {
    if (serverProc) {
      serverProc.kill();
    }
  });

  it("serves landing page at / with interactive task router, proposal narrative, no brand logo svg, and all 3 ablations", async () => {
    const res = await fetch(`${BASE_URL}/`);
    expect(res.status).toBe(200);
    const html = await res.text();
    expect(html).toContain("What would you like to do?");
    expect(html).toContain("DSA4213");
    expect(html).toContain("The ablations, side by side.");
    expect(html).toContain("Communication ablation");
    expect(html).toContain("Captain ablation");
    expect(html).toContain("Memory updates ablation");
    expect(html).not.toMatch(/class="brand"[^>]*>\s*<svg/);

    const compRes = await fetch(`${BASE_URL}/comparisons`);
    expect(compRes.status).toBe(200);
    const compHtml = await compRes.text();
    expect(compHtml).toContain("The ablations, side by side.");
  });

  it("serves overview, games, methods, and replay routes including log-only s106_B", async () => {
    for (const route of [
      "/experiments/abl_comms_v1",
      "/experiments/abl_captain_v1",
      "/experiments/abl_memory_v1",
      "/experiments/abl_comms_v1/games",
      "/experiments/abl_comms_v1/methods",
      "/experiments/abl_comms_v1/replay",
      "/experiments/abl_comms_v1/replay/abl_comms_v1_s101_A",
      "/experiments/abl_comms_v1/replay/abl_comms_v1_s106_B",
    ]) {
      const res = await fetch(`${BASE_URL}${route}`);
      expect(res.status, `Route ${route}`).toBe(200);
    }
  });

  it("serves architecture route and updated static system_architecture.html", async () => {
    const archPage = await fetch(`${BASE_URL}/architecture`);
    expect(archPage.status).toBe(200);
    const archPageHtml = await archPage.text();
    expect(archPageHtml).toContain("/static/system_architecture.html");

    const staticHtmlRes = await fetch(
      `${BASE_URL}/static/system_architecture.html`
    );
    expect(staticHtmlRes.status).toBe(200);
    const staticHtml = await staticHtmlRes.text();
    expect(staticHtml).toContain("mistral-small-3.2-24b-instruct");
    expect(staticHtml).not.toContain("nemotron-3-super-120b");
    expect(staticHtml).not.toContain("system_architecture_detailed.html");
    expect(staticHtml).toContain('href="system_architecture.html"');
  });

  it("serves static downloads and replay JSON and returns 404 for unknown routes", async () => {
    const csvRes = await fetch(
      `${BASE_URL}/data/downloads/abl_comms_v1/games.csv`
    );
    expect(csvRes.status).toBe(200);
    expect(csvRes.headers.get("content-disposition")).toBe("attachment");
    const csvText = await csvRes.text();
    expect(csvText).toContain("abl_comms_v1_s101_A");

    const replayRes = await fetch(
      `${BASE_URL}/data/replays/abl_comms_v1/abl_comms_v1_s106_B.json`
    );
    expect(replayRes.status).toBe(200);
    const replayJson = await replayRes.json();
    expect(replayJson.id).toBe("abl_comms_v1_s106_B");

    const notFoundExp = await fetch(`${BASE_URL}/experiments/unknown_exp`);
    expect(notFoundExp.status).toBe(404);

    const notFoundGame = await fetch(
      `${BASE_URL}/experiments/abl_comms_v1/replay/unknown_game`
    );
    expect(notFoundGame.status).toBe(404);
  });
});
