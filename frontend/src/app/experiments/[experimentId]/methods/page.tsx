import React from "react";
import { notFound } from "next/navigation";
import { getCatalogData, getExperimentOverview } from "@/lib/data-server";
import { featureSummary, fmt, metricById, title } from "@/lib/format";
import { DownloadIcon, PageHeading } from "@/components/SharedUi";

export const dynamic = "error";
export const dynamicParams = false;

export function generateStaticParams() {
  const catalog = getCatalogData();
  return catalog.experiments.map((exp) => ({
    experimentId: exp.id,
  }));
}

export default async function MethodsPage({
  params,
}: {
  params: Promise<{ experimentId: string }>;
}) {
  const { experimentId } = await params;
  let experiment;
  try {
    experiment = getExperimentOverview(experimentId);
  } catch {
    notFound();
  }

  const config = experiment.config;
  const s = experiment.statistics;
  const model = s.possession_model || {};
  const summary = experiment.summary;
  const pppInterval = metricById(experiment.metrics, "ppp")?.paired
    ?.bootstrap_95_ci;

  const intervalNote = pppInterval
    ? pppInterval[0] <= 0 && pppInterval[1] >= 0
      ? "The saved PPP confidence interval includes zero, so it does not establish an advantage for either condition."
      : "The saved PPP confidence interval excludes zero; inspect the paired estimate and study design before interpreting it."
    : "No paired PPP confidence interval is available for this export.";

  const dlBase = `/data/downloads/${encodeURIComponent(
    experiment.experiment_id
  )}`;

  return (
    <>
      <PageHeading
        eyebrow="METHODS & DATA"
        name="Know what you’re looking at."
        description="The saved experiment is the source of truth. Missing evidence stays visible."
      />
      <div className="notes-grid">
        <section className="card">
          <div className="card-head">
            <h2>Experiment design</h2>
          </div>
          <div className="card-body">
            <p>
              <strong>
                {summary.games} games, {summary.seeds} paired seeds.
              </strong>{" "}
              Each seed is played twice, alternating the first possession. The
              compared conditions are {experiment.conditions[0].label} and{" "}
              {experiment.conditions[1].label}. Game logs still identify
              physical teams as A and B; condition labels identify the ablation
              variants.
            </p>
            <p>
              {experiment.conditions[0].label}:{" "}
              {featureSummary(experiment.conditions[0])}.{" "}
              {experiment.conditions[1].label}:{" "}
              {featureSummary(experiment.conditions[1])}. The player and referee
              use the models in the saved configuration.
            </p>
            <div className="config-grid" style={{ marginTop: "20px" }}>
              <div>
                Player model
                <strong>
                  {config.llm_players?.model || experiment.model}
                </strong>
              </div>
              <div>
                Player temperature
                <strong>{fmt(config.llm_players?.temperature, 1)}</strong>
              </div>
              <div>
                Referee
                <strong>
                  {config.llm_referee?.model || "Not recorded"}
                </strong>
              </div>
              <div>
                Referee temperature
                <strong>{fmt(config.llm_referee?.temperature, 1)}</strong>
              </div>
              <div>
                Rule retrieval
                <strong>
                  Top {config.llm_referee?.top_k_rules ?? "—"} excerpts
                </strong>
              </div>
              <div>
                Memory backend
                <strong>
                  {config.memory_settings?.backend || "Not recorded"}
                </strong>
              </div>
            </div>
          </div>
        </section>

        <section className="card">
          <div className="card-head">
            <h2>Reading the results</h2>
          </div>
          <div className="card-body">
            <p>
              <strong>Condition columns are pooled rates:</strong> valid
              numerators are summed and divided by summed denominators. They are
              descriptive summaries.
            </p>
            <p>
              <strong>Paired effects come directly from stats.json:</strong>{" "}
              differences are averaged within seed across the two games, then
              across eligible seeds. The {fmt(s.bootstrap_replicates, 0)}
              -replicate bootstrap resamples seeds; the p-value comes from a
              two-sided Wilcoxon test.
            </p>
            <p>
              These are different estimands: subtracting two pooled PPP values
              need not equal the paired effect. {intervalNote}
            </p>
            <p>
              Reported p-values are per-metric results; no multiple-comparison
              correction is added by this dashboard.
            </p>
          </div>
        </section>

        <section className="card">
          <div className="card-head">
            <h2>Evidence &amp; limitations</h2>
          </div>
          <div className="card-body">
            <ul>
              <li>
                <strong>Replay uses saved state snapshots.</strong> Positions
                are shown after resolution; trails connect each player’s
                recorded previous and current position. Movement between
                snapshots is smoothed for illustration. No shot trajectory is
                inferred.
              </li>
              <li>
                <strong>Messages carry their delivery timing.</strong> A message
                produced at one event may be delivered at the following event.
                Suppressed messages are labelled.
              </li>
              <li>
                <strong>Unavailable metrics stay unavailable.</strong> A measure
                can be not applicable when a condition disables its feature.
                Other empty measures may lack exposure or source evidence.
              </li>
              <li>
                <strong>Possession models:</strong> additive{" "}
                {title(model.additive?.status || "not recorded")};
                condition-by-time{" "}
                {title(model.condition_by_time?.status || "not recorded")}.
                Failed fits are not presented as estimates.
              </li>
              <li>
                <strong>Recorded API cost:</strong> $
                {fmt(summary.logged_cost_usd)}. A zero logged amount does not
                establish that provider usage was free.
              </li>
              <li>
                <strong>Matched replay logs:</strong>{" "}
                {experiment.sources.logs_matched} / {summary.games} exported
                games
                {experiment.unexported_games?.length
                  ? ` (plus ${experiment.unexported_games.length} additional log-only game: ${experiment.unexported_games
                      .map((g) => g.id)
                      .join(", ")})`
                  : ""}
                . Original source paths may come from another machine; local
                logs are matched by game ID.
              </li>
            </ul>
          </div>
        </section>

        <section className="card">
          <div className="card-head">
            <h2>Take the source data with you</h2>
          </div>
          <div className="card-body">
            <p>
              The dashboard reads the existing CSV exports, saved statistical
              results, and JSONL game logs. Viewing games makes no model calls
              and does not modify the experiment.
            </p>
            <div className="downloads">
              <a
                className="button"
                href={`${dlBase}/games.csv`}
                download={`${experiment.experiment_id}_games.csv`}
              >
                Games CSV <DownloadIcon />
              </a>
              <a
                className="button"
                href={`${dlBase}/teams.csv`}
                download={`${experiment.experiment_id}_teams.csv`}
              >
                Teams CSV <DownloadIcon />
              </a>
              <a
                className="button"
                href={`${dlBase}/possessions.csv`}
                download={`${experiment.experiment_id}_possessions.csv`}
              >
                Possessions CSV <DownloadIcon />
              </a>
              <a
                className="button"
                href={`${dlBase}/stats.json`}
                download={`${experiment.experiment_id}_stats.json`}
              >
                Statistics JSON <DownloadIcon />
              </a>
            </div>
            <p style={{ marginTop: "24px" }}>
              Experiment <strong>{experiment.experiment_id}</strong>
              <br />
              Analysis seed{" "}
              <strong>{s.analysis_seed ?? "Not recorded"}</strong>
              <br />
              Display <strong>Courtside / v1</strong>
            </p>
          </div>
        </section>
      </div>

      {experiment.plots && experiment.plots.length > 0 ? (
        <section className="card" style={{ marginTop: "20px" }}>
          <div className="card-head">
            <div>
              <h2>Saved adaptation figures</h2>
              <p>
                Exported static plots included in{" "}
                <code>{experiment.experiment_id}/plots/</code>
              </p>
            </div>
            <span className="pill">Exported PNG</span>
          </div>
          <div className="card-body">
            <div className="saved-plots-grid">
              {experiment.plots.map((plot) => (
                <div key={plot.file} className="saved-plot-card">
                  <strong>
                    {metricById(experiment.metrics, plot.metric)?.name ||
                      plot.metric.toUpperCase()}
                  </strong>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={`/data/plots/${encodeURIComponent(
                      experiment.experiment_id
                    )}/${encodeURIComponent(plot.file)}`}
                    alt={`${experiment.experiment_id} ${plot.metric} adaptation plot`}
                    loading="lazy"
                  />
                </div>
              ))}
            </div>
          </div>
        </section>
      ) : null}
    </>
  );
}

