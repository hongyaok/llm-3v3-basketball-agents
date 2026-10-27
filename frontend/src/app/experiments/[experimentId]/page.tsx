import React from "react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getCatalogData, getExperimentOverview } from "@/lib/data-server";
import {
  FEATURE_NAMES,
  conditionColor,
  conditionSymbol,
  featureSummary,
  fmt,
  metricById,
  sign,
  title,
} from "@/lib/format";
import {
  ArrowIcon,
  DownloadIcon,
  Legend,
  MetricValue,
  PageHeading,
} from "@/components/SharedUi";
import { AdaptationCard, SeedChart } from "@/components/OverviewClient";
import type { GameSummaryRow } from "@/lib/types";

export const dynamic = "error";
export const dynamicParams = false;

export function generateStaticParams() {
  const catalog = getCatalogData();
  return catalog.experiments.map((exp) => ({
    experimentId: exp.id,
  }));
}

function GameTile({
  experimentId,
  g,
}: {
  experimentId: string;
  g: GameSummaryRow;
}) {
  if (!g.available) {
    return (
      <div className="card game-tile" aria-disabled="true">
        <div className="tile-top">
          <span>SEED {g.seed}</span>
          <span>{g.first_possession} STARTS</span>
        </div>
        <div className="tile-score">
          <span className="green-text">{fmt(g.score.A, 0)}</span>
          <span className="dash">:</span>
          <span className="orange-text">{fmt(g.score.B, 0)}</span>
        </div>
        <div className="tile-bottom">
          <span>
            {fmt(g.events, 0)} events ·{" "}
            {g.end_reason === "WIN_SCORE" ? "Target reached" : "Clock expired"}
          </span>
          <span>Log missing</span>
        </div>
      </div>
    );
  }
  return (
    <Link
      className="card game-tile"
      href={`/experiments/${encodeURIComponent(
        experimentId
      )}/replay/${encodeURIComponent(g.id)}`}
    >
      <div className="tile-top">
        <span>SEED {g.seed}</span>
        <span>{g.first_possession} STARTS</span>
      </div>
      <div className="tile-score">
        <span className="green-text">{fmt(g.score.A, 0)}</span>
        <span className="dash">:</span>
        <span className="orange-text">{fmt(g.score.B, 0)}</span>
      </div>
      <div className="tile-bottom">
        <span>
          {fmt(g.events, 0)} events ·{" "}
          {g.end_reason === "WIN_SCORE" ? "Target reached" : "Clock expired"}
        </span>
        <span>Replay ↗</span>
      </div>
    </Link>
  );
}

export default async function ExperimentOverviewPage({
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

  const [a, b] = experiment.conditions;
  const summary = experiment.summary;
  const ppp = metricById(experiment.metrics, "ppp")!;
  const effect = ppp.paired || {};
  const ci = effect.bootstrap_95_ci;
  const crossing = ci && ci[0] <= 0 && ci[1] >= 0;

  const previews = [...experiment.games]
    .sort(
      (x, y) =>
        Math.abs((x.score.A ?? 0) - (x.score.B ?? 0)) -
        Math.abs((y.score.A ?? 0) - (y.score.B ?? 0))
    )
    .slice(0, 4);

  const studyTitle = experiment.study?.title || "Team comparison";
  const comparedFeature =
    experiment.study?.changed_features
      ?.map((key) => FEATURE_NAMES[key])
      .join(" and ") || "Team conditions";
  const comparisonText = experiment.conditions.map((c) => c.label).join(" / ");
  const focus = experiment.study?.measures || {
    primary: ["ppp"],
    context: [],
    adaptation: ["ppp"],
    note: "",
  };

  const preferred = [...focus.primary, ...focus.context];
  const rank = (m: (typeof experiment.metrics)[number]) =>
    preferred.includes(m.id)
      ? preferred.indexOf(m.id)
      : preferred.length + experiment.metrics.indexOf(m);
  const orderedMetrics = [...experiment.metrics].sort(
    (x, y) => rank(x) - rank(y)
  );

  const iar = experiment.validity.iar;
  const sir = experiment.validity.sir;
  const sirValue =
    sir.rate == null
      ? title(sir.status || "Unavailable")
      : `${fmt(sir.rate * 100, 2)}%`;

  return (
    <>
      <PageHeading
        eyebrow="SAVED EXPERIMENT"
        name={`The ${studyTitle.toLowerCase()}.`}
        description={`${summary.games} games · ${summary.seeds} paired seeds · ${experiment.model.replace(
          "databricks-",
          ""
        )}`}
        actions={
          <>
            <a
              className="button"
              href={`/data/downloads/${encodeURIComponent(
                experiment.experiment_id
              )}/stats.json`}
              download={`${experiment.experiment_id}_stats.json`}
            >
              <DownloadIcon /> Export statistics
            </a>
            <Link
              className="button primary"
              href={`/experiments/${encodeURIComponent(
                experiment.experiment_id
              )}/replay`}
            >
              Explore the court <ArrowIcon />
            </Link>
          </>
        }
      />

      <div className="overview-hero">
        <section className="card experiment-card">
          <div className="eyebrow">
            {comparedFeature.toUpperCase()} · MATCHED SEEDS
          </div>
          <div className="matchup">
            <div className="team-side">
              <div className="team-symbol">{conditionSymbol(a, "A")}</div>
              <h2>{a.label}</h2>
              <p>{featureSummary(a)}</p>
            </div>
            <div className="versus">VS</div>
            <div className="team-side">
              <div className="team-symbol orange">
                {conditionSymbol(b, "B")}
              </div>
              <h2>{b.label}</h2>
              <p>{featureSummary(b)}</p>
            </div>
          </div>
          <div className="feature-tags">
            <span>3 agents / team</span>
            <span>{comparedFeature} compared</span>
            <span>First possession alternated</span>
            <span>Recorded referee calls</span>
          </div>
        </section>

        <section className="card pilot-card">
          <div className="pilot-top">
            <span className="eyebrow">PAIRED PPP EFFECT</span>
            <span className="pill">Saved analysis</span>
          </div>
          <div className="pilot-number">
            {sign(effect.effect_mean)}
            <span>points / possession</span>
          </div>
          <p>
            {a.label} minus {b.label}, averaged across paired seeds.{" "}
            {crossing
              ? "The interval includes zero."
              : "See the interval and paired test below."}
          </p>
          <div className="pilot-ci">
            <span>
              95% CI{" "}
              <strong>
                {ci ? `${sign(ci[0])} to ${sign(ci[1])}` : "Unavailable"}
              </strong>
            </span>
            <span>
              p <strong>{fmt(effect.wilcoxon?.p_value, 3)}</strong>
            </span>
          </div>
        </section>
      </div>

      <div className="kpis">
        <section className="card kpi">
          <div className="kpi-label">
            <span>Game wins · {comparisonText}</span>
            <span>↗</span>
          </div>
          <div className="metric-value">
            <span className="green-text">{a.wins}</span> <small>/</small>{" "}
            <span className="orange-text">{b.wins}</span>
          </div>
          <div className="wins-bar">
            <span style={{ width: `${(100 * a.wins) / summary.games}%` }} />
            <span style={{ width: `${(100 * b.wins) / summary.games}%` }} />
          </div>
          <p>
            {summary.draws
              ? `${summary.draws} drawn games`
              : "All games have a recorded winner"}
          </p>
        </section>

        <section className="card kpi">
          <div className="kpi-label">
            <span>Pooled PPP · {comparisonText}</span>
            <span>◉</span>
          </div>
          <div className="metric-value">
            <span className="green-text">
              {fmt(ppp.conditions[a.id].rate)}
            </span>{" "}
            <small>/</small>{" "}
            <span className="orange-text">
              {fmt(ppp.conditions[b.id].rate)}
            </span>
          </div>
          <p>Total points divided by possessions</p>
        </section>

        <section className="card kpi">
          <div className="kpi-label">
            <span>Possessions observed</span>
            <span>⌁</span>
          </div>
          <div className="metric-value">{fmt(summary.possessions, 0)}</div>
          <p>Across {fmt(summary.events, 0)} resolved events</p>
        </section>

        <section className="card kpi">
          <div className="kpi-label">
            <span>Completed games</span>
            <span>✓</span>
          </div>
          <div className="metric-value">
            {summary.complete_games} <small>/ {summary.games}</small>
          </div>
          <p>{summary.invariant_violations} logged state invariant violations</p>
        </section>
      </div>

      <section className="card primary-measures">
        <div className="card-head">
          <div>
            <h2>Measures for this matchup</h2>
            <p>
              {a.label} versus {b.label}
            </p>
          </div>
          <span className="pill">Primary</span>
        </div>
        <div className="measure-grid">
          {focus.primary.map((id) => {
            const metric = metricById(experiment.metrics, id);
            if (!metric) return null;
            const eff = metric.paired?.effect_mean;
            const inapplicable = [a, b].filter(
              (cond) =>
                metric.conditions[cond.id]?.status === "not_applicable"
            );
            const pairedText =
              eff == null
                ? inapplicable.length
                  ? "Paired effect not applicable across these conditions"
                  : "Paired effect unavailable"
                : `${sign(
                    eff * (metric.percent ? 100 : 1),
                    metric.percent ? 2 : 3
                  )}${metric.percent ? " pp" : ""} paired effect`;

            return (
              <div key={id} className="measure-card">
                <strong>{metric.name}</strong>
                <small>{metric.description}</small>
                <div className="measure-values">
                  <div>
                    <span>{a.label}</span>
                    <MetricValue metric={metric} condition={a.id} />
                  </div>
                  <div>
                    <span>{b.label}</span>
                    <MetricValue metric={metric} condition={b.id} />
                  </div>
                </div>
                <p>{pairedText}</p>
              </div>
            );
          })}
        </div>
        {focus.note ? <p className="measure-note">{focus.note}</p> : null}
      </section>

      <section className="card validity-card">
        <div className="card-head">
          <div>
            <h2>System validity</h2>
            <p>
              Invalid actions are assigned to a condition; state consistency
              applies to the whole game.
            </p>
          </div>
        </div>
        <div className="validity-grid">
          <div>
            <span>Invalid action rate · {a.label}</span>
            <MetricValue metric={iar} condition={a.id} />
          </div>
          <div>
            <span>Invalid action rate · {b.label}</span>
            <MetricValue metric={iar} condition={b.id} />
          </div>
          <div>
            <span>State inconsistency rate · all teams</span>
            <strong>{sirValue}</strong>
            <small>
              {fmt(sir.numerator, 0)} inconsistent / {fmt(sir.denominator, 0)}{" "}
              checked transitions
            </small>
          </div>
        </div>
      </section>

      <div className="chart-grid">
        <section className="card">
          <div className="card-head">
            <div>
              <h2>A closer look at each seed</h2>
              <p>
                {a.label} PPP minus {b.label} PPP
              </p>
            </div>
            <span className="pill">Paired</span>
          </div>
          <div className="card-body">
            <div id="seed-chart">
              <SeedChart
                experimentId={experiment.experiment_id}
                conditions={experiment.conditions}
                rows={effect.paired_seeds || []}
              />
            </div>
            <p className="chart-note">
              Each bar averages both first-possession variants.{" "}
              <strong>Click a seed to inspect its games.</strong>
            </p>
          </div>
        </section>

        <AdaptationCard experiment={experiment} />
      </div>

      <section className="card table-card">
        <div className="card-head">
          <div>
            <h2>The experiment, metric by metric</h2>
            <p>
              Primary measures appear first. Condition columns pool valid
              counts; effects use paired seeds.
            </p>
          </div>
          <Legend conditions={experiment.conditions} />
        </div>
        <div className="table-wrap">
          <table className="metric-table">
            <thead>
              <tr>
                <th>Metric</th>
                {experiment.conditions.map((c) => (
                  <th key={c.id}>{c.label}</th>
                ))}
                <th>Paired effect</th>
                <th>95% interval</th>
                <th>p-value</th>
              </tr>
            </thead>
            <tbody>
              {orderedMetrics.map((m) => {
                const paired = m.paired;
                const percent = m.percent;
                const eff = paired?.effect_mean;
                const mCi = paired?.bootstrap_95_ci;
                const tag = focus.primary.includes(m.id)
                  ? "Primary"
                  : focus.context.includes(m.id)
                    ? "Context"
                    : "";

                return (
                  <tr key={m.id}>
                    <td>
                      {m.name}
                      {tag ? (
                        <span className="metric-priority">{tag}</span>
                      ) : null}
                      <small>{m.description}</small>
                    </td>
                    {experiment.conditions.map((c) => (
                      <td
                        key={c.id}
                        style={{
                          color: conditionColor(experiment.conditions, c.id),
                        }}
                      >
                        <MetricValue metric={m} condition={c.id} />
                      </td>
                    ))}
                    <td>
                      {eff == null ? (
                        <span className="status-label">Not estimable</span>
                      ) : (
                        `${sign(
                          eff * (percent ? 100 : 1),
                          percent ? 2 : 3
                        )}${percent ? " pp" : ""}`
                      )}
                    </td>
                    <td className="mono">
                      {mCi
                        ? `${sign(
                            mCi[0] * (percent ? 100 : 1),
                            percent ? 2 : 3
                          )}, ${sign(
                            mCi[1] * (percent ? 100 : 1),
                            percent ? 2 : 3
                          )}`
                        : "—"}
                    </td>
                    <td className="mono">
                      {fmt(paired?.wilcoxon?.p_value, 3)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="table-foot">
          Effect = {a.label} − {b.label}. “pp” means percentage points. Missing
          or disabled measures are not zero. p-values are the saved two-sided
          Wilcoxon results.
        </div>
      </section>

      <div className="section-heading">
        <h2>From the numbers to the game</h2>
        <Link
          href={`/experiments/${encodeURIComponent(
            experiment.experiment_id
          )}/games`}
          className="text-link"
        >
          All {summary.games + (experiment.unexported_games?.length ?? 0)} games
          →
        </Link>
      </div>
      <div className="game-preview-grid">
        {previews.map((g) => (
          <GameTile
            key={g.id}
            experimentId={experiment.experiment_id}
            g={g}
          />
        ))}
      </div>
    </>
  );
}

