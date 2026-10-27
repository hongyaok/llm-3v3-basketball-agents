import React from "react";
import Link from "next/link";
import type { ComparisonsSummary } from "@/lib/types";
import { conditionSymbol, fmt, sign, title } from "@/lib/format";
import { ArrowIcon, MetricValue, PageHeading } from "@/components/SharedUi";

export function ComparisonsSection({
  data,
  isEmbedded = false,
}: {
  data: ComparisonsSummary;
  isEmbedded?: boolean;
}) {
  return (
    <section id="comparisons" className={isEmbedded ? "landing-comparisons-section" : ""}>
      {isEmbedded ? (
        <div className="section-editorial-head">
          <div>
            <span className="eyebrow">04 · EMPIRICAL RESULTS</span>
            <h2>The ablations, side by side.</h2>
            <p>
              {data.experiments.length} saved comparisons. Each card uses its own
              games, conditions and paired analysis.
            </p>
          </div>
          <Link className="button" href="/comparisons">
            Open dedicated comparison view <ArrowIcon />
          </Link>
        </div>
      ) : (
        <PageHeading
          eyebrow="ALL EXPERIMENTS"
          name="The ablations, side by side."
          description={`${data.experiments.length} saved comparisons. Each card uses its own games, conditions and paired analysis.`}
          actions={
            <Link className="button" href="/">
              ← Research hub &amp; path chooser
            </Link>
          }
        />
      )}

      <div className="comparison-grid">
        {data.experiments.map((row, idx) => {
          const [baseline, variant] = row.conditions;
          const ppp = row.primary_metrics.find((m) => m.id === "ppp");
          const paired = ppp?.paired;
          const ci = paired?.bootstrap_95_ci;
          const extra = row.primary_metrics.filter((m) => m.id !== "ppp");
          const iar = row.validity.iar;
          const sir = row.validity.sir;

          return (
            <article key={row.experiment_id} className="card comparison-card">
              <div className="comparison-card-head">
                <div className="comparison-card-meta">
                  <span className="eyebrow">
                    0{idx + 1} · {conditionSymbol(baseline, "A")} VS{" "}
                    {conditionSymbol(variant, "B")}
                  </span>
                  <span className="comparison-exp-badge mono">
                    {row.experiment_id}
                  </span>
                </div>
                <h2>{row.title}</h2>
                <p>
                  {baseline.label} versus {variant.label}
                </p>
              </div>

              <div className="comparison-body">
                <div className="comparison-ppp">
                  <h3>
                    Pooled PPP <small>points / possession</small>
                  </h3>
                  <div className="comparison-values">
                    <div>
                      <span>{baseline.label}</span>
                      {ppp ? (
                        <MetricValue metric={ppp} condition={baseline.id} />
                      ) : (
                        "—"
                      )}
                    </div>
                    <div>
                      <span>{variant.label}</span>
                      {ppp ? (
                        <MetricValue metric={ppp} condition={variant.id} />
                      ) : (
                        "—"
                      )}
                    </div>
                  </div>
                </div>

                <div className="comparison-effect">
                  <span>
                    Paired PPP effect · {baseline.label} minus {variant.label}
                  </span>
                  <strong>
                    {paired?.effect_mean == null
                      ? "Unavailable"
                      : sign(paired.effect_mean)}
                  </strong>
                  <small>
                    {ci
                      ? `95% CI ${sign(ci[0])} to ${sign(ci[1])} · p ${fmt(
                          paired?.p_value,
                          3
                        )} · ${fmt(paired?.n_seeds, 0)} seeds`
                      : "Paired analysis not available"}
                  </small>
                </div>

                {extra.length ? (
                  <div className="comparison-other">
                    <h3>Other primary measures</h3>
                    {extra.map((metric) => (
                      <div key={metric.id} className="comparison-measure">
                        <strong>{metric.name}</strong>
                        <div>
                          <span>
                            {baseline.label}{" "}
                            <MetricValue
                              metric={metric}
                              condition={baseline.id}
                            />
                          </span>
                          <span>
                            {variant.label}{" "}
                            <MetricValue
                              metric={metric}
                              condition={variant.id}
                            />
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : null}

                <div className="comparison-validity">
                  <h3>System validity</h3>
                  <p>
                    IAR · {baseline.label}{" "}
                    <MetricValue metric={iar} condition={baseline.id} /> /{" "}
                    {variant.label}{" "}
                    <MetricValue metric={iar} condition={variant.id} />
                  </p>
                  <p>
                    SIR · all teams{" "}
                    <strong>
                      {sir.rate == null
                        ? title(sir.status || "Unavailable")
                        : `${fmt(sir.rate * 100, 2)}%`}
                    </strong>{" "}
                    <small>
                      ({fmt(sir.numerator, 0)}/{fmt(sir.denominator, 0)}{" "}
                      transitions)
                    </small>
                  </p>
                </div>

                <p className="comparison-note">{row.measure_note}</p>
              </div>

              <div className="comparison-card-foot">
                <span>
                  {row.summary.complete_games}/{row.summary.games} complete
                  games · {row.logs_matched}/{row.summary.games} replays
                </span>
                <div className="comparison-card-actions">
                  <Link
                    className="text-link"
                    href={`/experiments/${encodeURIComponent(
                      row.experiment_id
                    )}/replay`}
                  >
                    Watch replay
                  </Link>
                  <Link
                    className="text-link primary-text-link"
                    href={`/experiments/${encodeURIComponent(row.experiment_id)}`}
                  >
                    Open experiment →
                  </Link>
                </div>
              </div>
            </article>
          );
        })}
      </div>
      <p className="comparison-caveat">
        Pooled PPP values describe each condition. A paired effect comes from
        matched seeds within that experiment and can differ from subtracting the
        pooled values. Results from different experiments are not pooled
        together.
      </p>
    </section>
  );
}
