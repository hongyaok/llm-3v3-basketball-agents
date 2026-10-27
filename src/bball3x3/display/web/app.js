"use strict";

const $ = (selector, parent = document) => parent.querySelector(selector);
const $$ = (selector, parent = document) => [...parent.querySelectorAll(selector)];
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmt = (value, digits = 2) => value == null || !Number.isFinite(Number(value)) ? "—" : Number(value).toLocaleString("en", {minimumFractionDigits:digits, maximumFractionDigits:digits});
const sign = (value, digits = 3) => value == null ? "—" : `${value > 0 ? "+" : value < 0 ? "−" : ""}${fmt(Math.abs(value), digits)}`;
const title = value => String(value ?? "").replaceAll("_", " ").toLowerCase().replace(/^./, c => c.toUpperCase());
const clock = value => value == null ? "—" : `${Math.floor(Math.max(0, value) / 60)}:${String(Math.floor(Math.max(0, value) % 60)).padStart(2, "0")}`;
const icons = {
  arrow:'<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3 10h13m-5-5 5 5-5 5"/></svg>',
  download:'<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 2v10m-4-4 4 4 4-4M3 12v5h14v-5"/></svg>',
};
let experiment, game, currentView = "", frameIndex = 0, playbackFrame = null, replayRequest = 0;
let playbackFraction = 0;
let experimentOptions = [], experimentDefault = null, experimentLoadRequest = 0;
let comparisonsRequest = 0;
let inspectorTab = "decisions", focusedPlayer = null, showTrails = true;
let timelineSpan = 40, timelineStart = 0, courtAnimation = null;
const displayedPositions = new Map();
const cache = new Map();
const colors = ["#24795a", "#d97745"];
const conditionIndex = id => Math.max(0, experiment.conditions.findIndex(c => c.id === id));
const conditionColor = id => colors[conditionIndex(id) % colors.length];
const conditionLabel = id => experiment.conditions.find(c => c.id === id)?.label || id;
const teamColor = team => conditionColor(game?.conditions[team]);
const isOrange = team => conditionIndex(game?.conditions[team]) === 1;
const metricById = id => experiment.metrics.find(m => m.id === id);
const legend = () => `<div class="legend">${experiment.conditions.map((c,i) => `<span><i class="dot ${i ? "orange" : ""}"></i>${esc(c.label)}</span>`).join("")}</div>`;
const featureNames = {comms:"Communication",captain:"Captain calls",memory_write:"Memory updates"};
const experimentParam = () => `experiment=${encodeURIComponent(experiment.experiment_id)}`;
const downloadUrl = name => `/downloads/${name}?${experimentParam()}`;
const featureSummary = condition => Object.entries(featureNames).map(([key,label]) => `${label} ${condition.features[key]===null?'unknown':condition.features[key]?'on':'off'}`).join(" · ");
const comparisonText = () => experiment.conditions.map(c=>c.label).join(" / ");
const conditionSymbol = (condition,fallback) => condition.id.match(/^([A-Z])_/)?.[1]||fallback;
const studyTitle = () => experiment.study?.title || "Team comparison";
const comparedFeature = () => experiment.study?.changed_features?.map(key=>featureNames[key]).join(" and ") || "Team conditions";
const matchupMeasures = () => experiment.study?.measures || {primary:["ppp"],context:[],adaptation:["ppp"],note:""};

async function getJSON(path) {
  const response = await fetch(path);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || `Request failed (${response.status})`);
  return body;
}
function toast(message) {
  const node = $("#toast"); node.textContent = message; node.classList.add("visible");
  setTimeout(() => node.classList.remove("visible"), 3500);
}
function heading(eyebrow, name, description, actions = "") {
  return `<div class="page-heading"><div><div class="eyebrow">${eyebrow}</div><h1>${name}</h1><p>${description}</p></div>${actions ? `<div class="heading-actions">${actions}</div>` : ""}</div>`;
}
function metricValue(metric, condition) {
  const value = metric.conditions[condition];
  if (value?.rate == null) return `<span class="status-label" title="${esc(JSON.stringify(value?.status_counts))}">${esc(title(value?.status || "Unavailable"))}</span>`;
  return `<span class="table-value">${metric.percent ? `${fmt(value.rate * 100, 2)}%` : fmt(value.rate, 3)}</span>${value.status === "partial" ? '<small>Available games only</small>' : ""}`;
}
function primaryMeasures() {
  const [baseline,comparison]=experiment.conditions;
  const focus=matchupMeasures();
  return `<section class="card primary-measures"><div class="card-head"><div><h2>Measures for this matchup</h2><p>${esc(baseline.label)} versus ${esc(comparison.label)}</p></div><span class="pill">Primary</span></div><div class="measure-grid">${focus.primary.map(id=>{
    const metric=metricById(id);
    if(!metric)return "";
    const effect=metric.paired?.effect_mean;
    const inapplicable=[baseline,comparison].filter(condition=>metric.conditions[condition.id]?.status==="not_applicable");
    const paired=effect==null?(inapplicable.length?"Paired effect not applicable across these conditions":"Paired effect unavailable"):
      `${sign(effect*(metric.percent?100:1),metric.percent?2:3)}${metric.percent?' pp':''} paired effect`;
    return `<div class="measure-card"><strong>${esc(metric.name)}</strong><small>${esc(metric.description)}</small><div class="measure-values"><div><span>${esc(baseline.label)}</span>${metricValue(metric,baseline.id)}</div><div><span>${esc(comparison.label)}</span>${metricValue(metric,comparison.id)}</div></div><p>${esc(paired)}</p></div>`;
  }).join("")}</div>${focus.note?`<p class="measure-note">${esc(focus.note)}</p>`:""}</section>`;
}
function validityPanel() {
  const [baseline,comparison]=experiment.conditions;
  const iar=experiment.validity.iar,sir=experiment.validity.sir;
  const sirValue=sir.rate==null?esc(title(sir.status||"Unavailable")):`${fmt(sir.rate*100,2)}%`;
  return `<section class="card validity-card"><div class="card-head"><div><h2>System validity</h2><p>Invalid actions are assigned to a condition; state consistency applies to the whole game.</p></div></div><div class="validity-grid"><div><span>Invalid action rate · ${esc(baseline.label)}</span>${metricValue(iar,baseline.id)}</div><div><span>Invalid action rate · ${esc(comparison.label)}</span>${metricValue(iar,comparison.id)}</div><div><span>State inconsistency rate · all teams</span><strong>${sirValue}</strong><small>${fmt(sir.numerator,0)} inconsistent / ${fmt(sir.denominator,0)} checked transitions</small></div></div></section>`;
}
async function comparisons() {
  const request=++comparisonsRequest;
  $("#main").innerHTML=heading("ALL EXPERIMENTS", "The ablations, side by side.",
    "Each card reports one experiment. Rates and paired estimates stay within that matchup.")+
    '<div class="loading-state"><span class="spinner"></span><p>Loading saved comparisons.</p></div>';
  try {
    const data=await getJSON("/api/comparisons");
    if(request!==comparisonsRequest||currentView!=="comparisons")return;
    const cards=data.experiments.map(row=>{
      const [baseline,variant]=row.conditions;
      const ppp=row.primary_metrics.find(metric=>metric.id==="ppp");
      const paired=ppp?.paired,ci=paired?.bootstrap_95_ci;
      const extra=row.primary_metrics.filter(metric=>metric.id!=="ppp");
      const iar=row.validity.iar,sir=row.validity.sir;
      return `<article class="card comparison-card"><div class="comparison-card-head"><span class="eyebrow">${esc(conditionSymbol(baseline,'A'))} VS ${esc(conditionSymbol(variant,'B'))}</span><h2>${esc(row.title)}</h2><p>${esc(baseline.label)} versus ${esc(variant.label)}</p></div>
        <div class="comparison-body"><div class="comparison-ppp"><h3>Pooled PPP <small>points / possession</small></h3><div class="comparison-values"><div><span>${esc(baseline.label)}</span>${ppp?metricValue(ppp,baseline.id):"—"}</div><div><span>${esc(variant.label)}</span>${ppp?metricValue(ppp,variant.id):"—"}</div></div></div>
        <div class="comparison-effect"><span>Paired PPP effect · ${esc(baseline.label)} minus ${esc(variant.label)}</span><strong>${paired?.effect_mean==null?"Unavailable":sign(paired.effect_mean)}</strong><small>${ci?`95% CI ${sign(ci[0])} to ${sign(ci[1])} · p ${fmt(paired.p_value,3)} · ${fmt(paired.n_seeds,0)} seeds`:"Paired analysis not available"}</small></div>
        ${extra.length?`<div class="comparison-other"><h3>Other primary measures</h3>${extra.map(metric=>`<div class="comparison-measure"><strong>${esc(metric.name)}</strong><div><span>${esc(baseline.label)} ${metricValue(metric,baseline.id)}</span><span>${esc(variant.label)} ${metricValue(metric,variant.id)}</span></div></div>`).join("")}</div>`:""}
        <div class="comparison-validity"><h3>System validity</h3><p>IAR · ${esc(baseline.label)} ${metricValue(iar,baseline.id)} / ${esc(variant.label)} ${metricValue(iar,variant.id)}</p><p>SIR · all teams <strong>${sir.rate==null?esc(title(sir.status||"Unavailable")):`${fmt(sir.rate*100,2)}%`}</strong> <small>(${fmt(sir.numerator,0)}/${fmt(sir.denominator,0)} transitions)</small></p></div>
        <p class="comparison-note">${esc(row.measure_note)}</p></div><div class="comparison-card-foot"><span>${row.summary.complete_games}/${row.summary.games} complete games · ${row.logs_matched}/${row.summary.games} replays</span><a class="text-link" href="#overview?experiment=${encodeURIComponent(row.experiment_id)}">Open experiment →</a></div></article>`;
    }).join("");
    $("#main").innerHTML=heading("ALL EXPERIMENTS", "The ablations, side by side.",
      `${data.experiments.length} saved comparisons. Each card uses its own games, conditions and paired analysis.`)+
      `<div class="comparison-grid">${cards}</div><p class="comparison-caveat">Pooled PPP values describe each condition. A paired effect comes from matched seeds within that experiment and can differ from subtracting the pooled values. Results from different experiments are not pooled together.</p>`;
  } catch(error) {if(request===comparisonsRequest&&currentView==="comparisons")showError(error);}
}
function overview() {
  const [a,b] = experiment.conditions;
  const summary = experiment.summary;
  const ppp = metricById("ppp");
  const effect = ppp.paired || {};
  const ci = effect.bootstrap_95_ci;
  const crossing = ci && ci[0] <= 0 && ci[1] >= 0;
  const previews = [...experiment.games].sort((x,y) => Math.abs(x.score.A-x.score.B)-Math.abs(y.score.A-y.score.B)).slice(0,4);
  $("#main").innerHTML = heading("SAVED EXPERIMENT", `The ${studyTitle().toLowerCase()}.`,
    `${summary.games} games · ${summary.seeds} paired seeds · ${esc(experiment.model.replace("databricks-", ""))}`,
    `<a class="button" href="${downloadUrl('stats.json')}" download="${esc(experiment.experiment_id)}_stats.json">${icons.download} Export statistics</a><a class="button primary" href="#replay?${experimentParam()}">Explore the court ${icons.arrow}</a>`) +
    `<div class="overview-hero"><section class="card experiment-card"><div class="eyebrow">${esc(comparedFeature().toUpperCase())} · MATCHED SEEDS</div><div class="matchup"><div class="team-side"><div class="team-symbol">${esc(conditionSymbol(a,'A'))}</div><h2>${esc(a.label)}</h2><p>${esc(featureSummary(a))}</p></div><div class="versus">VS</div><div class="team-side"><div class="team-symbol orange">${esc(conditionSymbol(b,'B'))}</div><h2>${esc(b.label)}</h2><p>${esc(featureSummary(b))}</p></div></div><div class="feature-tags"><span>3 agents / team</span><span>${esc(comparedFeature())} compared</span><span>First possession alternated</span><span>Recorded referee calls</span></div></section>
    <section class="card pilot-card"><div class="pilot-top"><span class="eyebrow">PAIRED PPP EFFECT</span><span class="pill">Saved analysis</span></div><div class="pilot-number">${sign(effect.effect_mean)}<span>points / possession</span></div><p>${esc(a.label)} minus ${esc(b.label)}, averaged across paired seeds. ${crossing ? "The interval includes zero." : "See the interval and paired test below."}</p><div class="pilot-ci"><span>95% CI <strong>${ci ? `${sign(ci[0])} to ${sign(ci[1])}` : "Unavailable"}</strong></span><span>p <strong>${fmt(effect.wilcoxon?.p_value,3)}</strong></span></div></section></div>
    <div class="kpis"><section class="card kpi"><div class="kpi-label"><span>Game wins · ${esc(comparisonText())}</span><span>↗</span></div><div class="metric-value"><span class="green-text">${a.wins}</span> <small>/</small> <span class="orange-text">${b.wins}</span></div><div class="wins-bar"><span style="width:${100*a.wins/summary.games}%"></span><span style="width:${100*b.wins/summary.games}%"></span></div><p>${summary.draws ? `${summary.draws} drawn games` : "All games have a recorded winner"}</p></section>
    <section class="card kpi"><div class="kpi-label"><span>Pooled PPP · ${esc(comparisonText())}</span><span>◉</span></div><div class="metric-value"><span class="green-text">${fmt(ppp.conditions[a.id].rate)}</span> <small>/</small> <span class="orange-text">${fmt(ppp.conditions[b.id].rate)}</span></div><p>Total points divided by possessions</p></section>
    <section class="card kpi"><div class="kpi-label"><span>Possessions observed</span><span>⌁</span></div><div class="metric-value">${fmt(summary.possessions,0)}</div><p>Across ${fmt(summary.events,0)} resolved events</p></section>
    <section class="card kpi"><div class="kpi-label"><span>Completed games</span><span>✓</span></div><div class="metric-value">${summary.complete_games} <small>/ ${summary.games}</small></div><p>${summary.invariant_violations} logged state invariant violations</p></section></div>
    ${primaryMeasures()}
    ${validityPanel()}
    <div class="chart-grid"><section class="card"><div class="card-head"><div><h2>A closer look at each seed</h2><p>${esc(a.label)} PPP minus ${esc(b.label)} PPP</p></div><span class="pill">Paired</span></div><div class="card-body"><div id="seed-chart"></div><p class="chart-note">Each bar averages both first-possession variants. <strong>Click a seed to inspect its games.</strong></p></div></section>
    <section class="card"><div class="card-head"><div><h2>Through the game</h2><p>Condition-level rates by regulation-time quintile</p></div><select id="adaptation-metric" class="metric-select" aria-label="Adaptation metric">${matchupMeasures().adaptation.filter(id=>experiment.adaptation.some(r=>r.metric===id&&r.rate!==null)).map(id=>`<option value="${id}">${esc(metricById(id)?.name||id)}</option>`).join("")}</select></div><div class="card-body">${legend()}<div id="adaptation-chart"></div><p class="chart-note">Counts pooled across games. Unobserved bins stay blank; overtime is separate when present.</p></div></section></div>
    ${metricsTable()}
    <div class="section-heading"><h2>From the numbers to the game</h2><a href="#games?${experimentParam()}" class="text-link">All ${summary.games} games →</a></div><div class="game-preview-grid">${previews.map(gameTile).join("")}</div>`;
  $("#seed-chart").innerHTML = seedChart(effect.paired_seeds || []);
  $$("[data-seed]").forEach(el => el.addEventListener("click", () => {location.hash = `games?${experimentParam()}&seed=${encodeURIComponent(el.dataset.seed)}`;}));
  $("#adaptation-metric").addEventListener("change", drawAdaptation);
  drawAdaptation(); bindReplayLinks();
}
function metricsTable() {
  const focus=matchupMeasures(),preferred=[...focus.primary,...focus.context];
  const rank=m=>preferred.includes(m.id)?preferred.indexOf(m.id):preferred.length+experiment.metrics.indexOf(m);
  const ordered=[...experiment.metrics].sort((a,b)=>rank(a)-rank(b));
  return `<section class="card table-card"><div class="card-head"><div><h2>The experiment, metric by metric</h2><p>Primary measures appear first. Condition columns pool valid counts; effects use paired seeds.</p></div>${legend()}</div><div class="table-wrap"><table class="metric-table"><thead><tr><th>Metric</th>${experiment.conditions.map(c => `<th>${esc(c.label)}</th>`).join("")}<th>Paired effect</th><th>95% interval</th><th>p-value</th></tr></thead><tbody>${ordered.map(m => {
    const paired=m.paired, percent=m.percent, effect=paired?.effect_mean, ci=paired?.bootstrap_95_ci;
    const tag=focus.primary.includes(m.id)?"Primary":focus.context.includes(m.id)?"Context":"";
    return `<tr><td>${esc(m.name)}${tag?`<span class="metric-priority">${tag}</span>`:""}<small>${esc(m.description)}</small></td>${experiment.conditions.map(c=>`<td style="color:${conditionColor(c.id)}">${metricValue(m,c.id)}</td>`).join("")}<td>${effect == null ? '<span class="status-label">Not estimable</span>' : `${sign(effect*(percent?100:1),percent?2:3)}${percent?' pp':''}`}</td><td class="mono">${ci ? `${sign(ci[0]*(percent?100:1),percent?2:3)}, ${sign(ci[1]*(percent?100:1),percent?2:3)}` : "—"}</td><td class="mono">${fmt(paired?.wilcoxon?.p_value,3)}</td></tr>`;
  }).join("")}</tbody></table></div><div class="table-foot">Effect = ${esc(experiment.conditions[0].label)} − ${esc(experiment.conditions[1].label)}. “pp” means percentage points. Missing or disabled measures are not zero. p-values are the saved two-sided Wilcoxon results.</div></section>`;
}
function seedChart(rows) {
  if (!rows.length) return '<div class="empty-state">No paired seed estimates available.</div>';
  const width=510, height=305, x0=66, x1=464, top=36, bottom=268;
  const extent=Math.max(.25,...rows.map(r=>Math.abs(r.difference)))*1.12;
  const x=value=>x0+(value+extent)/(extent*2)*(x1-x0), y=i=>top+i*(bottom-top)/Math.max(rows.length-1,1);
  const ticks=[-extent/1.12,-extent/2.24,0,extent/2.24,extent/1.12];
  return `<svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Paired seed differences in points per possession"><text x="70" y="16" fill="${colors[1]}">← ${esc(experiment.conditions[1].label)} ahead</text><text x="345" y="16">${esc(experiment.conditions[0].label)} ahead →</text>${ticks.map(t=>`<line class="${t===0?'axis':'grid'}" x1="${x(t)}" x2="${x(t)}" y1="25" y2="280"/><text x="${x(t)}" y="299" text-anchor="middle">${fmt(t,2)}</text>`).join("")}${rows.map((r,i)=>`<g class="seed-target" data-seed="${esc(r.seed)}" tabindex="0" role="button" aria-label="Inspect seed ${esc(r.seed)}, difference ${fmt(r.difference,3)}"><title>Seed ${esc(r.seed)} · ${sign(r.difference)} PPP · click to inspect</title><rect x="0" y="${y(i)-11}" width="510" height="22" fill="transparent"/><text x="45" y="${y(i)+3}" text-anchor="end">${esc(r.seed)}</text><rect x="${Math.min(x(0),x(r.difference))}" y="${y(i)-5}" width="${Math.max(2,Math.abs(x(r.difference)-x(0)))}" height="10" rx="3" fill="${r.difference>=0?colors[0]:colors[1]}"/><circle cx="${x(r.difference)}" cy="${y(i)}" r="3.5" fill="${r.difference>=0?colors[0]:colors[1]}"/><text x="${r.difference<0?x(r.difference)-6:x(r.difference)+6}" y="${y(i)+3}" text-anchor="${r.difference<0?'end':'start'}" style="font-size:8px">${sign(r.difference,2)}</text></g>`).join("")}</svg>`;
}
function drawAdaptation() {
  const metric=$("#adaptation-metric").value;
  const rows=experiment.adaptation.filter(r=>r.metric===metric);
  const bins=["q1","q2","q3","q4","q5"];
  if(rows.some(r=>r.time_bin==="ot"&&r.rate!=null)) bins.push("ot");
  const series=experiment.conditions.map(c=>({label:c.label,color:conditionColor(c.id),values:bins.map(b=>rows.find(r=>r.condition===c.id&&r.time_bin===b)?.rate??null)}));
  $("#adaptation-chart").innerHTML=lineChart(series,bins.map(b=>b==="ot"?"OT":`Q${b[1]}`),metric!=="ppp",275);
}
function lineChart(series, labels, percent=false, height=275, active=null) {
  const w=500,left=46,right=478,top=28,bottom=height-36;
  const values=series.flatMap(s=>s.values).filter(v=>v!=null);
  if (!values.length) return '<div class="empty-state">No observations for this measure.</div>';
  const max=Math.max(...values,.001)*1.16;
  const x=i=>left+i/(Math.max(labels.length-1,1))*(right-left),y=v=>bottom-v/max*(bottom-top);
  const ticks=Array.from({length:5},(_,i)=>i*max/4);
  return `<svg class="chart" viewBox="0 0 ${w} ${height}" role="img" aria-label="${esc(series.map(s=>s.label).join(' and '))} over time">${ticks.map(t=>`<line class="grid" x1="${left}" x2="${right}" y1="${y(t)}" y2="${y(t)}"/><text x="${left-10}" y="${y(t)+4}" text-anchor="end">${percent?fmt(t*100,t<.01?2:0)+'%':fmt(t,t<2?2:0)}</text>`).join("")}${labels.map((t,i)=>labels.length>12&&i!==0&&i!==labels.length-1?"":`<text x="${x(i)}" y="${height-10}" text-anchor="middle">${esc(t)}</text>`).join("")}${series.map(s=>{let path="",connected=false;s.values.forEach((v,i)=>{if(v==null){connected=false;return;}path+=`${connected?'L':'M'}${x(i)},${y(v)} `;connected=true;});return `<path d="${path}" fill="none" stroke="${s.color}" stroke-width="2.5" stroke-linejoin="round"/>${s.values.map((v,i)=>v==null||labels.length>12?"":`<circle cx="${x(i)}" cy="${y(v)}" r="4" fill="${s.color}" stroke="white" stroke-width="2"><title>${esc(s.label)} · ${esc(labels[i])}: ${percent?fmt(v*100,3)+'%':fmt(v,3)}</title></circle>`).join("")}`;}).join("")}${active!=null?`<line class="chart-cursor" x1="${x(active)}" x2="${x(active)}" y1="${top}" y2="${bottom}" stroke="#9bad8c" stroke-dasharray="3 3"/>`:""}</svg>`;
}
function gameTile(g) {
  return `<button class="card game-tile" data-replay="${esc(g.id)}" ${g.available?"":"disabled"}><div class="tile-top"><span>SEED ${esc(g.seed)}</span><span>${esc(g.first_possession)} STARTS</span></div><div class="tile-score"><span class="green-text">${fmt(g.score.A,0)}</span><span class="dash">:</span><span class="orange-text">${fmt(g.score.B,0)}</span></div><div class="tile-bottom"><span>${fmt(g.events,0)} events · ${g.end_reason==='WIN_SCORE'?'Target reached':'Clock expired'}</span><span>Replay ↗</span></div></button>`;
}
function bindReplayLinks() {
  $$("[data-replay]").forEach(el=>el.addEventListener("click",()=>{location.hash=`replay?${experimentParam()}&game=${encodeURIComponent(el.dataset.replay)}`;}));
  $$("svg [role=button]").forEach(el=>el.addEventListener("keydown",event=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();el.dispatchEvent(new MouseEvent("click",{bubbles:true}));}}));
}
function gameLibrary(params) {
  $("#main").innerHTML=heading("RECORDED GAMES", "Every game. Every decision.", "Compare matched seeds, inspect a close finish, or follow a game from the opening possession.", `<a class="button" href="${downloadUrl('games.csv')}" download="${esc(experiment.experiment_id)}_games.csv">${icons.download} Export games</a>`)+
    `<div class="toolbar"><div class="filters"><input class="search" id="game-search" type="search" placeholder="Search by seed or game ID…" aria-label="Search games" value="${esc(params.get('seed')||'')}"><select id="first-filter" aria-label="Filter by first possession"><option value="">Either team starts</option><option value="A">Team A starts</option><option value="B">Team B starts</option></select><select id="winner-filter" aria-label="Filter by winner"><option value="">All results</option>${experiment.conditions.map(c=>`<option value="${esc(c.id)}">${esc(c.label)} wins</option>`).join("")}</select></div><span class="muted" id="game-count"></span></div><section class="card"><div class="table-wrap"><table><thead><tr><th>Game / seed</th><th>Starts</th><th>${esc(comparisonText())}</th><th>Winner</th><th>Events</th><th>End condition</th><th></th></tr></thead><tbody id="games-body"></tbody></table></div></section><p class="chart-note" style="margin-top:14px">A/B in the game ID identifies the first-possession variant. Conditions stay attached to the physical teams recorded in each log.</p>`;
  ["#game-search","#first-filter","#winner-filter"].forEach(id=>$(id).addEventListener("input",filterGames));filterGames();
}
function filterGames() {
  const query=$("#game-search").value.toLowerCase().trim(), first=$("#first-filter").value, winner=$("#winner-filter").value;
  const rows=experiment.games.filter(g=>(!query||g.id.toLowerCase().includes(query))&&(!first||g.first_possession===first)&&(!winner||g.winner===winner));
  $("#game-count").textContent=`${rows.length} of ${experiment.games.length} games`;
  $("#games-body").innerHTML=rows.length?rows.map(g=>`<tr class="game-row"><td><strong>Seed ${esc(g.seed)}</strong><small class="game-id">${esc(g.id)}</small></td><td><span class="status-label">Team ${esc(g.first_possession)}</span></td><td><div class="mini-score"><b class="green-text">${fmt(g.score.A,0)}</b><span>:</span><b class="orange-text">${fmt(g.score.B,0)}</b></div></td><td style="color:${conditionColor(g.winner)}">${esc(g.winner?conditionLabel(g.winner):'No winner')}</td><td class="mono">${fmt(g.events,0)}</td><td>${esc(title(g.end_reason))}<small>${g.complete?'Complete':'Incomplete'}</small></td><td><button class="button small" data-replay="${esc(g.id)}" ${g.available?'':'disabled'}>${g.available?'Replay ↗':'Log missing'}</button></td></tr>`).join(""):'<tr><td colspan="7"><div class="empty-state">No games match these filters.</div></td></tr>';
  bindReplayLinks();
}
async function replay(params) {
  const id=params.get("game")||game?.id||experiment.games.find(g=>g.available)?.id;
  const request=++replayRequest;
  $("#main").innerHTML='<div class="loading-state"><span class="spinner"></span><h1>Loading the court</h1><p>Reading the recorded states and event evidence.</p></div>';
  try {
    if (!id) throw new Error("No local game logs are available for replay.");
    const key=`${experiment.experiment_id}:${id}`;
    const selected=cache.get(key)||await getJSON(`/api/games/${encodeURIComponent(id)}?${experimentParam()}`);
    if(request!==replayRequest||currentView!=="replay")return;
    if(cache.size>=4)cache.delete(cache.keys().next().value);
    cache.set(key,selected);game=selected;frameIndex=0;focusedPlayer=null;timelineStart=0;timelineSpan=40;
    if(courtAnimation)cancelAnimationFrame(courtAnimation);
    courtAnimation=null;playbackFraction=0;displayedPositions.clear();
    const initialEvent=Number(params.get("event"))||0;
    frameIndex=Math.max(0,game.frames.findIndex(f=>f.event_idx===initialEvent));
    replayShell();renderFrame();
  } catch(error) {if(request===replayRequest&&currentView==="replay")showError(error);}
}
function replayShell() {
  $("#main").innerHTML=heading("THE GAME, UNDER A MICROSCOPE", "Back on the court.", "Scrub through recorded events. Select a player to follow their decision.", `<a class="button" href="#games">← Game library</a>`)+
    game.warnings.map(w=>`<div class="callout warning">${esc(w)}</div>`).join("")+
    `<div class="replay-toolbar"><div class="filters"><select id="replay-game" class="replay-select" aria-label="Select game">${experiment.games.filter(g=>g.available).map(g=>`<option value="${esc(g.id)}" ${g.id===game.id?'selected':''}>Seed ${esc(g.seed)} · ${esc(g.first_possession)} starts · ${fmt(g.score.A,0)} : ${fmt(g.score.B,0)}</option>`).join("")}</select><select id="possession-select" class="replay-select" aria-label="Jump to possession"><option value="">Jump to possession…</option>${game.possessions.map(p=>`<option value="${esc(p.start_event_idx)}">${esc(p.possession_id)} · ${esc(p.physical_team)} · ${esc(p.points)} pts</option>`).join("")}</select></div><div class="filters"><button id="trails-toggle" class="button small" aria-pressed="${showTrails}">Movement trails ${showTrails?'on':'off'}</button><button id="share-event" class="button small">Link to event ↗</button></div></div>
    <div class="replay-layout"><div><section class="card court-card"><div id="scoreboard" class="scoreboard"></div><div id="court" class="court-wrap"></div><div id="court-meta" class="court-meta"></div><div class="playback"><div class="timeline-label"><span id="timeline-current"></span><span id="timeline-total"></span></div><input id="event-slider" class="range" type="range" min="0" max="${game.frames.length-1}" value="${frameIndex}" step="1" aria-label="Game event"><div id="timeline-markers" class="timeline-markers"></div><div class="play-controls"><div class="play-buttons"><button id="previous-event" class="button icon" aria-label="Previous event">‹</button><button id="play-button" class="button lime" aria-label="Play replay">▶ Play</button><button id="next-event" class="button icon" aria-label="Next event">›</button><button id="next-score" class="button small">Next score ↗</button></div><div class="filters"><span class="key-hint">SPACE TO PLAY · ← → TO STEP</span><select id="speed" class="speed" aria-label="Playback speed"><option value="1200">0.5×</option><option value="600" selected>1×</option><option value="300">2×</option><option value="150">4×</option></select></div></div></div></section>
    <section class="card score-history"><div class="card-head"><div><h3>The score over time</h3></div>${legend()}</div><div class="card-body" id="score-history"></div></section></div>
    <aside class="card inspector"><div class="inspector-header"><div class="eyebrow" id="inspector-event"></div><h2 id="inspector-title"></h2><p id="inspector-description"></p></div><div class="inspector-tabs" role="tablist" aria-label="Event details">${["decisions","team talk","outcome"].map(tab=>`<button role="tab" data-tab="${tab}" aria-selected="${tab===inspectorTab}" class="${tab===inspectorTab?'active':''}">${title(tab)}</button>`).join("")}</div><div id="inspector-body" class="inspector-body" role="tabpanel"></div></aside></div>
    <div class="section-heading"><h2>Game moments</h2><span class="muted" style="font-size:10px">Scores, turnovers &amp; referee calls</span></div><div id="event-moments" class="event-buttons"></div>`;
  $("#possession-select").innerHTML='<option value="">Jump to possession…</option>'+game.possessions.map(p=>`<option value="${esc(p.possession_id)}">${esc(p.possession_id)} · ${esc(p.physical_team)} · ${esc(p.points)} pts</option>`).join("");
  $("#speed").innerHTML='<option value="1200">1.2 s / event</option><option value="600" selected>0.6 s / event</option><option value="300">0.3 s / event</option><option value="150">0.15 s / event</option>';
  $("#speed").setAttribute("aria-label","Seconds per recorded event");
  $("#event-slider").setAttribute("aria-label","Recorded event in visible timeline window");
  $("#event-slider").insertAdjacentHTML("beforebegin",'<div class="timeline-tools"><button id="timeline-prev" class="button small" type="button">← Earlier</button><label for="timeline-zoom">Timeline</label><select id="timeline-zoom" class="speed"><option value="40" selected>40 events</option><option value="80">80 events</option><option value="all">Full game</option></select><button id="timeline-next" class="button small" type="button">Later →</button><span id="timeline-window-label" class="mono"></span></div>');
  $("#timeline-markers").insertAdjacentHTML("afterend",'<div class="timeline-legend"><span class="score">Score</span><span class="turnover">Turnover</span><span class="call">Referee call</span></div>');
  $("#replay-game").addEventListener("change",e=>{location.hash=`replay?${experimentParam()}&game=${encodeURIComponent(e.target.value)}`;});
  $("#event-slider").addEventListener("input",e=>{pause();goFrame(Number(e.target.value));});
  $("#previous-event").addEventListener("click",()=>{pause();goFrame(frameIndex-1,true);});
  $("#next-event").addEventListener("click",()=>{pause();goFrame(frameIndex+1,true);});
  $("#play-button").addEventListener("click",togglePlay);
  $("#speed").addEventListener("change",()=>{if(playbackFrame!==null){pause();togglePlay();}});
  $("#next-score").addEventListener("click",()=>{pause();const index=game.frames.findIndex((f,i)=>i>frameIndex&&f.resolution?.scoring_events?.length);if(index>=0)goFrame(index);else toast("No further scoring events in this game.");});
  $("#possession-select").addEventListener("change",e=>{if(e.target.value){pause();const index=possessionFrameIndex(e.target.value);if(index>=0)goFrame(index);}});
  $("#timeline-zoom").addEventListener("change",e=>{timelineSpan=e.target.value==="all"?Infinity:Number(e.target.value);timelineStart=0;renderTimeline();});
  $("#timeline-prev").addEventListener("click",()=>{pause();goFrame(Math.max(0,timelineStart-timelineSpan));});
  $("#timeline-next").addEventListener("click",()=>{pause();goFrame(Math.min(game.frames.length-1,timelineStart+timelineSpan));});
  $("#timeline-markers").addEventListener("click",e=>{const marker=e.target.closest("[data-frame]");if(marker){pause();goFrame(Number(marker.dataset.frame));}});
  $("#trails-toggle").addEventListener("click",e=>{showTrails=!showTrails;e.target.textContent=`Movement trails ${showTrails?'on':'off'}`;e.target.setAttribute("aria-pressed",showTrails);renderCourt();});
  $("#share-event").addEventListener("click",async()=>{const hash=`#replay?${experimentParam()}&game=${encodeURIComponent(game.id)}&event=${game.frames[frameIndex].event_idx}`;history.replaceState(null,"",hash);try{await navigator.clipboard.writeText(location.href);toast("Link copied to this recorded event.");}catch{toast("The address bar now links to this event.");}});
  $$("[data-tab]").forEach(el=>el.addEventListener("click",()=>{inspectorTab=el.dataset.tab;renderInspector();}));
  const moments=game.frames.map((f,i)=>({f,i})).filter(({f})=>f.resolution?.scoring_events?.length||f.resolution?.turnovers?.length||(f.referee?.decision?.call&&f.referee.decision.call!=="NONE"));
  $("#event-moments").innerHTML=moments.map(({f,i})=>`<button class="event-chip" data-frame="${i}"><small>${f.event_idx}</small>${esc(eventTitle(f))}</button>`).join("")||'<p class="chart-note">No scoring, turnover or referee-call moments recorded.</p>';
  $("#event-moments").addEventListener("click",e=>{const moment=e.target.closest("[data-frame]");if(moment){pause();goFrame(Number(moment.dataset.frame));}});
}
function eventTitle(f) {
  if(f.event_idx===0)return "Opening possession";
  const scores=f.resolution?.scoring_events||[];
  if(scores.length)return scores.map(s=>`${s.team} +${s.points} ${s.source==='FREE_THROW'?'free throw':'points'}`).join(" · ");
  const call=f.referee?.decision;
  if(call&&call.call!=="NONE")return title(call.foul_type||call.violation_type||call.call);
  const turnover=f.resolution?.turnovers?.[0];
  if(turnover)return `${turnover.team} · ${title(turnover.reason)}`;
  const before=game?.frames[Math.max(0,game.frames.indexOf(f)-1)]?.state;
  const holder=before?.ball?.holder;
  const action=f.resolution?.actions?.[holder];
  return action?`${holder} · ${title(action)}`:f.state.ball.status==='LOOSE'?"Loose-ball phase":"Resolved event";
}
function possessionFrameIndex(id) {
  if(game.possessions[0]?.possession_id===id)return 0;
  const after=game.frames.findIndex(f=>f.resolution?.possession_after?.possession_id===id);
  if(after>=0)return after;
  const possession=game.possessions.find(p=>p.possession_id===id);
  return possession?game.frames.findIndex(f=>f.event_idx>=Number(possession.start_event_idx)&&f.state.offense===possession.physical_team):-1;
}
function activePossessionId(f) {
  if(frameIndex===0)return game.possessions[0]?.possession_id||"";
  const after=f.resolution?.possession_after?.possession_id;
  if(after)return after;
  const event=f.event_idx;
  return [...game.possessions].reverse().find(p=>
    p.physical_team===f.state.offense&&Number(p.start_event_idx)<=event&&
    (!p.end_event_idx||Number(p.end_event_idx)>=event)
  )?.possession_id||"";
}
function momentKinds(f) {
  const kinds=[];
  if(f.resolution?.scoring_events?.length)kinds.push("score");
  if(f.resolution?.turnovers?.length)kinds.push("turnover");
  if(f.referee?.decision?.call&&f.referee.decision.call!=="NONE")kinds.push("call");
  return kinds;
}
function renderTimeline() {
  const last=game.frames.length-1,span=Math.min(timelineSpan,game.frames.length);
  if(!Number.isFinite(timelineSpan))timelineStart=0;
  else if(frameIndex<timelineStart||frameIndex>=timelineStart+span)
    timelineStart=Math.floor(frameIndex/span)*span;
  const end=Math.min(last,timelineStart+span-1),slider=$("#event-slider");
  slider.min=timelineStart;slider.max=end;slider.value=frameIndex;
  slider.setAttribute("aria-valuetext",`Event ${game.frames[frameIndex].event_idx}: ${eventTitle(game.frames[frameIndex])}`);
  $("#timeline-window-label").textContent=`Events ${game.frames[timelineStart].event_idx}–${game.frames[end].event_idx} of ${game.frames[last].event_idx}`;
  $("#timeline-prev").disabled=timelineStart===0||!Number.isFinite(timelineSpan);
  $("#timeline-next").disabled=end===last||!Number.isFinite(timelineSpan);
  const markerHost=$("#timeline-markers");
  const windowKey=`${timelineStart}:${end}`;
  if(markerHost.dataset.window===windowKey)return;
  markerHost.dataset.window=windowKey;
  markerHost.innerHTML=game.frames.slice(timelineStart,end+1).map((f,offset)=>{
    const kinds=momentKinds(f);
    if(!kinds.length)return "";
    const i=timelineStart+offset,pct=(i-timelineStart)/Math.max(end-timelineStart,1)*100;
    const label=`Event ${f.event_idx}: ${kinds.join(", ")} — ${eventTitle(f)}`;
    return `<button type="button" class="timeline-marker ${kinds[0]}" style="left:${pct}%" data-frame="${i}" aria-label="${esc(label)}" title="${esc(label)}"></button>`;
  }).join("");
}
function eventActor(f,index) {
  if(index===0)return null;
  const before=game.frames[index-1].state.ball.holder;
  if(f.resolution?.scoring_events?.length)
    return before&&["SHOOT","FREE_THROW"].includes(f.resolution?.actions?.[before])?before:null;
  const turnover=f.resolution?.turnovers?.find(item=>item.player);
  if(turnover)return turnover.player;
  const call=f.referee?.decision;
  if(call?.call&&call.call!=="NONE"&&call.offender)return call.offender;
  return before&&f.resolution?.actions?.[before]?before:null;
}
function eventCues(f,index) {
  if(index===0)return [];
  const cues=[];
  for(const score of f.resolution?.scoring_events||[])
    cues.push({kind:"score",text:`Team ${score.team} +${score.points} · ${title(score.source)}`});
  for(const turnover of f.resolution?.turnovers||[])
    cues.push({kind:"turnover",text:`Turnover ${turnover.player||turnover.team} · ${title(turnover.reason)}`});
  const call=f.referee?.decision;
  if(call?.call&&call.call!=="NONE")
    cues.push({kind:"call",text:`${title(call.foul_type||call.violation_type||call.call)}${call.offender?` · ${call.offender}`:""}`});
  if(!cues.length){
    const actor=eventActor(f,index),action=f.resolution?.actions?.[actor];
    if(actor&&action)cues.push({kind:"action",text:`${actor} · ${title(action)}`});
  }
  return cues;
}
function goFrame(index,animate=false) {playbackFraction=0;frameIndex=Math.max(0,Math.min(game.frames.length-1,index));renderFrame(animate);}
function pause() {
  if(playbackFrame!==null)cancelAnimationFrame(playbackFrame);
  playbackFrame=null;
  const button=$("#play-button");
  if(button){button.textContent="▶ Play";button.setAttribute("aria-label","Play replay");}
}
function togglePlay() {
  if(playbackFrame!==null){pause();return;}
  if(frameIndex===game.frames.length-1)goFrame(0);
  if(courtAnimation!==null)renderCourt(false);
  const button=$("#play-button");button.textContent="Ⅱ Pause";button.setAttribute("aria-label","Pause replay");
  const pace=Number($("#speed").value);
  const reducedMotion=window.matchMedia&&window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const anchorFrame=frameIndex;
  const anchorTime=performance.now()-playbackFraction*pace;
  const tick=now=>{
    if(playbackFrame===null)return;
    const elapsed=Math.max(0,now-anchorTime);
    const index=Math.min(game.frames.length-1,anchorFrame+Math.floor(elapsed/pace));
    if(index===game.frames.length-1){goFrame(index);pause();return;}
    if(index!==frameIndex){frameIndex=index;renderFrame(false);}
    playbackFraction=(elapsed/pace)%1;
    if(!reducedMotion)paintPlaybackCourt(playbackFraction);
    playbackFrame=requestAnimationFrame(tick);
  };
  playbackFrame=requestAnimationFrame(tick);
}
function renderFrame(animate=false) {
  const f=game.frames[frameIndex],s=f.state;
  $("#scoreboard").innerHTML=`<div class="score-team"><span><i class="dot"></i> ${esc(conditionLabel(game.conditions.A))}</span><strong class="score-digits">${s.score.A}</strong></div><div class="clock">${clock(s.game_clock_s)}<small>${s.phase==='OT'?'OVERTIME':'GAME CLOCK'}</small></div><div class="score-team"><strong class="score-digits">${s.score.B}</strong><span>${esc(conditionLabel(game.conditions.B))} <i class="dot orange"></i></span></div>`;
  $("#court-meta").innerHTML=`<span>SHOT CLOCK <strong>${fmt(s.shot_clock_s,1)}s</strong></span><span>POSSESSION <strong>${esc(s.offense)}</strong>${s.needs_clear?' · CLEAR REQUIRED':''}</span><span>FOULS <strong>A ${s.team_fouls.A} / B ${s.team_fouls.B}</strong></span>`;
  $("#timeline-current").textContent=`EVENT ${f.event_idx} · ${eventTitle(f)}`;
  $("#timeline-total").textContent=`${game.frames.length-1} recorded events`;
  renderTimeline();
  $("#possession-select").value=activePossessionId(f);
  $("#previous-event").disabled=frameIndex===0;$("#next-event").disabled=frameIndex===game.frames.length-1;
  $("#inspector-event").textContent=`EVENT ${String(f.event_idx).padStart(3,"0")} / ${clock(s.game_clock_s)}`;
  $("#inspector-title").textContent=eventTitle(f);
  $("#inspector-description").textContent=f.event_idx===0?"The initial state, before any decisions.":`${f.resolution?.possession_before?.possession_id||'Recorded event'} · Court shows the state after resolution.`;
  renderCourt(animate);renderInspector();
  if(!$("#event-cue"))$("#court").insertAdjacentHTML("afterbegin",'<div id="event-cue" class="event-cue" aria-live="off"></div>');
  $("#event-cue").innerHTML=eventCues(f,frameIndex).map(cue=>`<span class="event-cue-badge ${cue.kind}">${esc(cue.text)}</span>`).join("");
  if(!$("#score-history svg"))
    $("#score-history").innerHTML=lineChart(["A","B"].map(t=>({label:conditionLabel(game.conditions[t]),color:teamColor(t),values:game.frames.map(row=>row.state.score[t])})),game.frames.map(row=>String(row.event_idx)),false,135,0);
  const cursor=$("#score-history .chart-cursor");
  if(cursor){const x=46+frameIndex/Math.max(game.frames.length-1,1)*(478-46);cursor.setAttribute("x1",x);cursor.setAttribute("x2",x);}
  $$(".event-chip").forEach(el=>el.classList.toggle("active",Number(el.dataset.frame)===frameIndex));
}
function renderCourt(animate=false) {
  if(!$("#court .court-svg")){
  const f=game.frames[frameIndex],s=f.state;
  const cell=Number(game.court.cell_m)||1,width=(Number(game.court.width_m)||15)/cell,depth=(Number(game.court.depth_m)||11)/cell;
  const scale=Math.min(710/width,520/depth),ox=(800-width*scale)/2,oy=34;
  const xy=pos=>[ox+(pos[0]+.5)*scale,oy+(pos[1]+.5)*scale];
  const basket=xy(game.court.basket||[7,1]),radius=(Number(game.court.arc_radius_m)||6.75)/cell*scale;
  const arc=Array.from({length:61},(_,i)=>{const a=i*Math.PI/60;return `${i?'L':'M'}${basket[0]+radius*Math.cos(a)},${basket[1]+radius*Math.sin(a)}`;}).join(" ");
  const players=Object.values(s.players).sort((a,b)=>a.id.localeCompare(b.id)),groups=new Map();
  players.forEach(p=>{const key=JSON.stringify(p.pos);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(p.id);});
  const playerSVG=players.map(p=>{
    const members=groups.get(JSON.stringify(p.pos)),a=members.indexOf(p.id)*Math.PI*2/members.length;
    const pos=xy(p.pos),prev=xy(p.prev_pos||p.pos),x=pos[0]+(members.length>1?Math.cos(a)*13:0),y=pos[1]+(members.length>1?Math.sin(a)*13:0);
    const orange=isOrange(p.team),color=orange?'#efb087':'#d1eea5',holder=p.has_ball||s.ball.holder===p.id;
    const trail=showTrails&&(prev[0]!==pos[0]||prev[1]!==pos[1])?`<path class="court-trail" d="M${prev} L${pos}" stroke="${color}" stroke-width="2" stroke-opacity=".4" stroke-dasharray="5 5"/><circle class="court-trail" cx="${prev[0]}" cy="${prev[1]}" r="4" fill="${color}" opacity=".4"/>`:"";
    return `${trail}<g class="court-player" data-player="${esc(p.id)}" tabindex="0" role="button" aria-label="Inspect ${esc(p.id)}"><title>${esc(p.id)} · (${p.pos.join(', ')}) · ${esc(f.resolution?.actions?.[p.id]||p.movement)}${holder?' · ball holder':''}</title>${holder?`<circle cx="${x}" cy="${y}" r="24" fill="none" stroke="#efc66e" stroke-width="2" stroke-dasharray="4 3"/>`:""}<circle cx="${x}" cy="${y}" r="18" fill="${color}" stroke="${focusedPlayer===p.id?'white':'#23402f'}" stroke-width="${focusedPlayer===p.id?4:2}"/><text x="${x}" y="${y+4}" text-anchor="middle" font-size="12" font-weight="700" fill="#243c2a">${esc(p.id)}</text></g>`;
  }).join("");
  const ball=xy(s.ball.pos),holder=players.find(p=>p.has_ball||p.id===s.ball.holder),bp=holder?xy(holder.pos):ball;
  $("#court").innerHTML=`<svg class="court-svg" viewBox="0 0 800 600" role="img" aria-label="Half-court positions after event ${f.event_idx}"><defs><pattern id="court-grid" width="${scale}" height="${scale}" patternUnits="userSpaceOnUse" x="${ox}" y="${oy}"><path d="M ${scale} 0 L 0 0 0 ${scale}" fill="none" stroke="#d4dfb7" stroke-opacity=".045"/></pattern><clipPath id="court-clip"><rect x="${ox}" y="${oy}" width="${width*scale}" height="${depth*scale}"/></clipPath></defs><rect x="${ox}" y="${oy}" width="${width*scale}" height="${depth*scale}" fill="#264633"/><rect x="${ox}" y="${oy}" width="${width*scale}" height="${depth*scale}" fill="url(#court-grid)" stroke="#829c70" stroke-opacity=".6" stroke-width="2"/><g clip-path="url(#court-clip)" fill="none" stroke="#9db584" stroke-width="2" stroke-opacity=".45"><path d="${arc}"/><rect x="${basket[0]-2.45*scale/cell}" y="${oy}" width="${4.9*scale/cell}" height="${5.8*scale/cell}" fill="#a6be84" fill-opacity=".025"/><circle cx="${basket[0]}" cy="${oy+5.8*scale/cell}" r="${1.8*scale/cell}"/><path d="M${basket[0]-32} ${basket[1]-12}h64" stroke-width="4"/><circle cx="${basket[0]}" cy="${basket[1]}" r="11" stroke="#ead8a0" stroke-width="2.5"/><path d="M${basket[0]-1.25*scale/cell} ${basket[1]} A${1.25*scale/cell} ${1.25*scale/cell} 0 0 0 ${basket[0]+1.25*scale/cell} ${basket[1]}"/></g><text x="400" y="${oy+depth*scale-19}" text-anchor="middle" font-size="14" font-weight="600" letter-spacing="6" fill="#86a573" opacity=".35">COURTSIDE</text>${playerSVG}<g aria-label="Basketball"><circle cx="${bp[0]+(holder?23:0)}" cy="${bp[1]+(holder?15:0)}" r="7" fill="#e8aa56" stroke="#5c472d" stroke-width="1.5"/><path d="M${bp[0]+(holder?23:0)-6} ${bp[1]+(holder?15:0)}h12" stroke="#72502b"/></g><text x="400" y="588" text-anchor="middle" font-size="9" letter-spacing="2" fill="#91aa85">${width} × ${depth} GRID · RECORDED POSITIONS · ${esc(s.ball.status)}</text></svg>`;
  $$("[data-player]").forEach(el=>{const focus=()=>{focusedPlayer=focusedPlayer===el.dataset.player?null:el.dataset.player;inspectorTab="decisions";renderCourt();renderInspector();};el.addEventListener("click",focus);el.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();focus();}});});
  }
  updateCourtNodes(animate);
}
function courtPlayerPositions(index,xy) {
  const state=game.frames[index]?.state;
  if(!state)return null;
  const groups=new Map(),positions=new Map();
  for(const player of Object.values(state.players)){
    const key=JSON.stringify(player.pos);
    if(!groups.has(key))groups.set(key,[]);
    groups.get(key).push(player.id);
  }
  for(const player of Object.values(state.players)){
    const members=groups.get(JSON.stringify(player.pos));
    const angle=members.indexOf(player.id)*Math.PI*2/members.length;
    const [x,y]=xy(player.pos);
    positions.set(player.id,[x+(members.length>1?Math.cos(angle)*13:0),y+(members.length>1?Math.sin(angle)*13:0)]);
  }
  return positions;
}
function paintPlaybackCourt(progress) {
  const current=game.frames[frameIndex].state,next=game.frames[frameIndex+1].state;
  const svg=$("#court .court-svg");
  const cell=Number(game.court.cell_m)||1,width=(Number(game.court.width_m)||15)/cell,depth=(Number(game.court.depth_m)||11)/cell;
  const scale=Math.min(710/width,520/depth),ox=(800-width*scale)/2,oy=34;
  const xy=pos=>[ox+(pos[0]+.5)*scale,oy+(pos[1]+.5)*scale];
  const from=courtPlayerPositions(frameIndex,xy),to=courtPlayerPositions(frameIndex+1,xy);
  for(const node of svg.querySelectorAll(".court-player")){
    const id=node.dataset.player,start=from.get(id),end=to.get(id);
    if(!start||!end)continue;
    const position=[start[0]+(end[0]-start[0])*progress,start[1]+(end[1]-start[1])*progress];
    node.setAttribute("transform",`translate(${position[0]} ${position[1]})`);
    displayedPositions.set(id,position);
  }
  const ballPosition=state=>{
    const holder=Object.values(state.players).find(p=>p.has_ball||p.id===state.ball.holder);
    const [x,y]=xy(holder?holder.pos:state.ball.pos);
    return [x+(holder?23:0),y+(holder?15:0)];
  };
  const ballStart=ballPosition(current),ballEnd=ballPosition(next);
  const ball=[ballStart[0]+(ballEnd[0]-ballStart[0])*progress,ballStart[1]+(ballEnd[1]-ballStart[1])*progress];
  svg.querySelector('g[aria-label="Basketball"]').setAttribute("transform",`translate(${ball[0]} ${ball[1]})`);
  displayedPositions.set("__ball__",ball);
  if(current.phase===next.phase&&typeof current.game_clock_s==="number"&&typeof next.game_clock_s==="number")
    $("#scoreboard .clock").firstChild.nodeValue=clock(current.game_clock_s+(next.game_clock_s-current.game_clock_s)*progress);
  if(typeof current.shot_clock_s==="number"&&current.shot_clock_s>=next.shot_clock_s)
    $("#court-meta strong").textContent=`${fmt(current.shot_clock_s+(next.shot_clock_s-current.shot_clock_s)*progress,1)}s`;
}
function updateCourtNodes(animate) {
  const f=game.frames[frameIndex],s=f.state,svg=$("#court .court-svg");
  const cell=Number(game.court.cell_m)||1,width=(Number(game.court.width_m)||15)/cell,depth=(Number(game.court.depth_m)||11)/cell;
  const scale=Math.min(710/width,520/depth),ox=(800-width*scale)/2,oy=34;
  const xy=pos=>[ox+(pos[0]+.5)*scale,oy+(pos[1]+.5)*scale];
  const players=Object.values(s.players).sort((a,b)=>a.id.localeCompare(b.id));
  const targets=new Map(),from=new Map(),nodes=new Map();
  const playerNodes=new Map([...svg.querySelectorAll(".court-player")].map(node=>[node.dataset.player,node]));
  const playerPositions=courtPlayerPositions(frameIndex,xy);
  const actor=eventActor(f,frameIndex),trail=[];
  for(const p of players){
    const [baseX,baseY]=xy(p.pos),[prevX,prevY]=xy(p.prev_pos||p.pos);
    const [x,y]=playerPositions.get(p.id);
    const color=isOrange(p.team)?'#efb087':'#d1eea5',holder=p.has_ball||s.ball.holder===p.id;
    if(showTrails&&(prevX!==baseX||prevY!==baseY))
      trail.push(`<path d="M${prevX} ${prevY} L${baseX} ${baseY}" stroke="${color}" stroke-width="2" stroke-opacity=".5" stroke-dasharray="5 5"/><circle cx="${prevX}" cy="${prevY}" r="4" fill="${color}" opacity=".5"/>`);
    const node=playerNodes.get(p.id);
    const action=f.resolution?.actions?.[p.id]||p.movement||"No action recorded";
    node.setAttribute("aria-label",`Inspect ${p.id}: ${title(action)}${holder?', ball holder':''}`);
    node.setAttribute("aria-pressed",String(focusedPlayer===p.id));
    node.innerHTML=`<title>${esc(p.id)} · (${p.pos.join(', ')}) · ${esc(title(action))}${holder?' · ball holder':''}</title><circle class="actor-ring" r="28" fill="none" stroke="#ffd785" stroke-width="3" display="${actor===p.id?'inline':'none'}"/><circle class="holder-ring" r="24" fill="none" stroke="#efc66e" stroke-width="2" stroke-dasharray="4 3" display="${holder?'inline':'none'}"/><circle class="player-disc" r="18" fill="${color}" stroke="${focusedPlayer===p.id?'white':'#23402f'}" stroke-width="${focusedPlayer===p.id?4:2}"/><text y="4" text-anchor="middle" font-size="12" font-weight="700" fill="#243c2a">${esc(p.id)}</text>`;
    targets.set(p.id,[x,y]);from.set(p.id,displayedPositions.get(p.id)||[x,y]);nodes.set(p.id,node);
  }
  svg.querySelectorAll(".court-trail").forEach(node=>node.remove());
  let trailLayer=svg.querySelector("#court-trails");
  if(!trailLayer){
    trailLayer=document.createElementNS("http://www.w3.org/2000/svg","g");
    trailLayer.id="court-trails";
    svg.insertBefore(trailLayer,svg.querySelector(".court-player"));
  }
  trailLayer.innerHTML=trail.join("");
  const ballGroup=svg.querySelector('g[aria-label="Basketball"]');
  ballGroup.innerHTML='<circle r="7" fill="#e8aa56" stroke="#5c472d" stroke-width="1.5"/><path d="M-6 0h12" stroke="#72502b"/>';
  const holder=players.find(p=>p.has_ball||p.id===s.ball.holder);
  const ballBase=holder?xy(holder.pos):xy(s.ball.pos);
  const ballTarget=[ballBase[0]+(holder?23:0),ballBase[1]+(holder?15:0)];
  targets.set("__ball__",ballTarget);from.set("__ball__",displayedPositions.get("__ball__")||ballTarget);nodes.set("__ball__",ballGroup);
  svg.setAttribute("aria-label",`Half-court positions after event ${f.event_idx}`);
  svg.querySelector("svg > text:last-of-type").textContent=`${width} × ${depth} GRID · RECORDED POSITIONS · ${s.ball.status}`;
  if(courtAnimation)cancelAnimationFrame(courtAnimation);
  courtAnimation=null;
  const reducedMotion=window.matchMedia&&window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const pace=Number($("#speed").value);
  const duration=animate&&!reducedMotion?Math.min(320,pace):0;
  const previous=game.frames[frameIndex-1]?.state;
  const clockText=$("#scoreboard .clock")?.firstChild;
  const shotClockText=$("#court-meta strong");
  function draw(progress){
    for(const [id,target] of targets){
      const start=from.get(id);
      const x=start[0]+(target[0]-start[0])*progress;
      const y=start[1]+(target[1]-start[1])*progress;
      nodes.get(id).setAttribute("transform",`translate(${x} ${y})`);
      displayedPositions.set(id,[x,y]);
    }
    if(duration&&previous?.phase===s.phase&&typeof previous.game_clock_s==="number"&&
       typeof s.game_clock_s==="number"&&clockText)
      clockText.nodeValue=clock(previous.game_clock_s+(s.game_clock_s-previous.game_clock_s)*progress);
    if(duration&&typeof previous?.shot_clock_s==="number"&&
       previous.shot_clock_s>=s.shot_clock_s&&shotClockText)
      shotClockText.textContent=`${fmt(previous.shot_clock_s+(s.shot_clock_s-previous.shot_clock_s)*progress,1)}s`;
  }
  if(!duration){draw(1);return;}
  draw(0);
  const started=performance.now();
  const step=now=>{
    const progress=Math.min(1,(now-started)/duration);
    draw(progress);
    courtAnimation=progress<1?requestAnimationFrame(step):null;
  };
  courtAnimation=requestAnimationFrame(step);
}
function renderInspector() {
  const f=game.frames[frameIndex];
  $$("[data-tab]").forEach(el=>{const active=el.dataset.tab===inspectorTab;el.classList.toggle("active",active);el.setAttribute("aria-selected",active);});
  let html="";
  if(inspectorTab==="decisions") {
    html=f.decisions.map(d=>`<div class="decision ${focusedPlayer===d.player?'active-player':''}"><div class="decision-top"><span class="player-badge ${isOrange(d.team)?'orange':''}">${esc(d.player)}</span><span class="decision-action">${esc(title(d.executed_action||'No action'))}</span><span class="muted">${esc(d.executed_target||'')}</span></div><p>${esc(d.rationale||'No rationale recorded.')}</p>${d.invalid_reason?`<small>Remapped from ${esc(d.proposed_action)} · ${esc(title(d.invalid_reason))}</small>`:''}${d.memory_ref?`<small>Memory: ${esc(d.memory_ref)}</small>`:''}</div>`).join("")||'<div class="empty-state">No player decisions recorded for this event.</div>';
  } else if(inspectorTab==="team talk") {
    html='<div class="channel-heading">Captain calls</div>'+f.captain_calls.map(c=>`<div class="message-card"><div class="message-meta"><span class="player-badge ${isOrange(c.team)?'orange':''}">${esc(c.team)}</span><strong>${esc(c.maintain?'Maintain previous call':'Captain')}</strong>${c.cs?` · ${esc(c.cs)}`:''}</div><p>${esc(c.tactic||'No tactic recorded.')}</p>${(c.directives||[]).map(d=>`<small>${esc(d.to)} → ${esc(d.act)} ${esc(d.target||'')}</small>`).join('')}</div>`).join("");
    html+='<div class="channel-heading">Teammate messages</div>'+f.messages.map(m=>`<div class="message-card ${m.suppressed?'suppressed':''}"><div class="message-meta"><span class="player-badge ${isOrange(m.team)?'orange':''}">${esc(m.sender)}</span><span>${esc(m.kind)}${m.directive?.to?` → ${esc(m.directive.to)}`:''}</span></div><p>${esc(m.text)}</p><small>${m.suppressed?'Suppressed · communication disabled':`Delivered at event ${m.delivered_at??'not recorded'}`}</small></div>`).join("");
    if(!f.messages.length)html+='<p class="chart-note">No teammate messages recorded at this event.</p>';
    const disabled=Object.entries(game.coordination).filter(([,v])=>!v.comms).map(([team])=>team);
    if(disabled.length)html+=`<p class="chart-note" style="margin-top:15px">Teammate communication is disabled for team ${esc(disabled.join(', '))}. Captain calls are a separate feature.</p>`;
  } else {
    const r=f.resolution||{},ref=f.referee||{},decision=ref.decision||{};
    const entries=[['Possession before',r.possession_before?`${r.possession_before.possession_id} · ${r.possession_before.team}`:'—'],['Possession after',r.possession_after?`${r.possession_after.possession_id} · ${r.possession_after.team}`:'—'],['Referee call',title(decision.foul_type||decision.violation_type||decision.call||'Not recorded')],['Offender',decision.offender||'—'],['Cited rules',(decision.rule_ids_cited||[]).join(', ')||'None'],['Referee status',ref.failure_code||ref.rejection_reason||'No recorded failure']];
    html=entries.map(([k,v])=>`<div class="outcome-row"><span>${esc(k)}</span><strong>${esc(v)}</strong></div>`).join('');
    html+=(r.scoring_events||[]).map(e=>`<div class="callout" style="margin-top:12px">Team ${esc(e.team)} +${e.points} · ${esc(title(e.source))}</div>`).join('');
    html+=(r.turnovers||[]).map(e=>`<div class="callout warning" style="margin-top:12px">Turnover · ${esc(e.player||e.team)} · ${esc(title(e.reason))}</div>`).join('');
    html+=`<details class="raw-detail"><summary>Recorded resolution</summary><pre>${esc(JSON.stringify(r,null,2))}</pre></details><details class="raw-detail"><summary>Referee reply &amp; retrieved rules</summary><pre>${esc(JSON.stringify({retrieved:ref.retrieved_chunk_ids,reply:ref.raw_output,failure:ref.parse_error},null,2))}</pre></details>`;
  }
  $("#inspector-body").innerHTML=html;
}
function notes() {
  const config=experiment.config,s=experiment.statistics,model=s.possession_model||{},summary=experiment.summary;
  const pppInterval=metricById("ppp")?.paired?.bootstrap_95_ci;
  const intervalNote=pppInterval?(pppInterval[0]<=0&&pppInterval[1]>=0?
    "The saved PPP confidence interval includes zero, so it does not establish an advantage for either condition.":
    "The saved PPP confidence interval excludes zero; inspect the paired estimate and study design before interpreting it."):
    "No paired PPP confidence interval is available for this export.";
  $("#main").innerHTML=heading("METHODS & DATA", "Know what you’re looking at.", "The saved experiment is the source of truth. Missing evidence stays visible.")+`<div class="notes-grid"><section class="card"><div class="card-head"><h2>Experiment design</h2></div><div class="card-body"><p><strong>${summary.games} games, ${summary.seeds} paired seeds.</strong> Each seed is played twice, alternating the first possession. The compared conditions are ${esc(experiment.conditions[0].label)} and ${esc(experiment.conditions[1].label)}. Game logs still identify physical teams as A and B; condition labels identify the ablation variants.</p><p>${esc(experiment.conditions[0].label)}: ${esc(featureSummary(experiment.conditions[0]))}. ${esc(experiment.conditions[1].label)}: ${esc(featureSummary(experiment.conditions[1]))}. The player and referee use the models in the saved configuration.</p><div class="config-grid" style="margin-top:20px"><div>Player model<strong>${esc(config.llm_players?.model||experiment.model)}</strong></div><div>Player temperature<strong>${fmt(config.llm_players?.temperature,1)}</strong></div><div>Referee<strong>${esc(config.llm_referee?.model||'Not recorded')}</strong></div><div>Referee temperature<strong>${fmt(config.llm_referee?.temperature,1)}</strong></div><div>Rule retrieval<strong>Top ${esc(config.llm_referee?.top_k_rules??'—')} excerpts</strong></div><div>Memory backend<strong>${esc(config.memory_settings?.backend||'Not recorded')}</strong></div></div></div></section>
    <section class="card"><div class="card-head"><h2>Reading the results</h2></div><div class="card-body"><p><strong>Condition columns are pooled rates:</strong> valid numerators are summed and divided by summed denominators. They are descriptive summaries.</p><p><strong>Paired effects come directly from stats.json:</strong> differences are averaged within seed across the two games, then across eligible seeds. The ${fmt(s.bootstrap_replicates,0)}-replicate bootstrap resamples seeds; the p-value comes from a two-sided Wilcoxon test.</p><p>These are different estimands: subtracting two pooled PPP values need not equal the paired effect. ${esc(intervalNote)}</p><p>Reported p-values are per-metric results; no multiple-comparison correction is added by this dashboard.</p></div></section>
    <section class="card"><div class="card-head"><h2>Evidence &amp; limitations</h2></div><div class="card-body"><ul><li><strong>Replay uses saved state snapshots.</strong> Positions are shown after resolution; trails connect each player’s recorded previous and current position. Movement between snapshots is smoothed for illustration. No shot trajectory is inferred.</li><li><strong>Messages carry their delivery timing.</strong> A message produced at one event may be delivered at the following event. Suppressed messages are labelled.</li><li><strong>Unavailable metrics stay unavailable.</strong> A measure can be not applicable when a condition disables its feature. Other empty measures may lack exposure or source evidence.</li><li><strong>Possession models:</strong> additive ${esc(title(model.additive?.status||'not recorded'))}; condition-by-time ${esc(title(model.condition_by_time?.status||'not recorded'))}. Failed fits are not presented as estimates.</li><li><strong>Recorded API cost:</strong> $${fmt(summary.logged_cost_usd)}. A zero logged amount does not establish that provider usage was free.</li><li><strong>Matched replay logs:</strong> ${experiment.sources.logs_matched} / ${summary.games}. Original source paths may come from another machine; local logs are matched by game ID.</li></ul></div></section>
    <section class="card"><div class="card-head"><h2>Take the source data with you</h2></div><div class="card-body"><p>The dashboard reads the existing CSV exports, saved statistical results, and JSONL game logs. Viewing games makes no model calls and does not modify the experiment.</p><div class="downloads"><a class="button" href="${downloadUrl('games.csv')}" download>Games CSV ${icons.download}</a><a class="button" href="${downloadUrl('teams.csv')}" download>Teams CSV ${icons.download}</a><a class="button" href="${downloadUrl('possessions.csv')}" download>Possessions CSV ${icons.download}</a><a class="button" href="${downloadUrl('stats.json')}" download>Statistics JSON ${icons.download}</a></div><p style="margin-top:24px">Experiment <strong>${esc(experiment.experiment_id)}</strong><br>Analysis seed <strong>${esc(s.analysis_seed??'Not recorded')}</strong><br>Local display <strong>Courtside / v1</strong></p></div></section></div>`;
}
function showError(error) {$("#main").innerHTML=`<div class="loading-state"><h1>This view couldn’t load.</h1><p>${esc(error.message)}</p><a class="button" href="#overview" style="margin-top:20px">Return to overview</a></div>`;}
async function loadExperiment(id) {
  if(!experimentOptions.some(option=>option.id===id))throw new Error(`Unknown experiment: ${id}`);
  const request=++experimentLoadRequest;
  const data=await getJSON(`/api/experiment?experiment=${encodeURIComponent(id)}`);
  if(request!==experimentLoadRequest)return false;
  pause();replayRequest++;
  if(courtAnimation)cancelAnimationFrame(courtAnimation);
  courtAnimation=null;playbackFraction=0;displayedPositions.clear();
  cache.clear();game=null;experiment=data;
  $("#experiment-select").value=id;
  $("#experiment-id").textContent=id;
  $("#study-title").textContent=studyTitle();
  $("#study-matchup").textContent=experiment.conditions.map(c=>c.label).join(" × ");
  $("#nav-count").textContent=data.summary.games;
  $("#footer-source").textContent=`${data.summary.games} games · ${data.summary.seeds} paired seeds · ${id}`;
  document.title=`Courtside — ${studyTitle()}`;
  $$("[data-nav]").forEach(link=>{link.href=`#${link.dataset.nav}?${experimentParam()}`;});
  return true;
}
function route() {
  if(!experiment)return;
  const [view,query=""]=(location.hash.slice(1)||(experimentOptions.length>1?"comparisons":"overview")).split("?");
  const params=new URLSearchParams(query);
  const selected=params.get("experiment");
  if(selected&&selected!==experiment.experiment_id){
    loadExperiment(selected).then(loaded=>{if(loaded)route();}).catch(showError);
    return;
  }
  pause();
  if(courtAnimation)cancelAnimationFrame(courtAnimation);
  courtAnimation=null;
  currentView=["comparisons","overview","games","replay","notes"].includes(view)?view:"overview";
  $$("[data-nav]").forEach(el=>{const active=el.dataset.nav===currentView;el.classList.toggle("active",active);if(active)el.setAttribute("aria-current","page");else el.removeAttribute("aria-current");});
  if(currentView==="comparisons")comparisons();
  else if(currentView==="replay")replay(params);
  else if(currentView==="games")gameLibrary(params);
  else if(currentView==="notes")notes();else overview();
  window.scrollTo(0,0);
}
window.addEventListener("hashchange",route);
document.addEventListener("keydown",event=>{
  if(currentView!=="replay"||!game||!$("#play-button")||event.target.closest("input,select,textarea,button,[role=button],summary,a"))return;
  if(event.code==="Space"){event.preventDefault();togglePlay();}
  if(event.key==="ArrowRight"){event.preventDefault();pause();goFrame(frameIndex+1,true);}
  if(event.key==="ArrowLeft"){event.preventDefault();pause();goFrame(frameIndex-1,true);}
});
document.addEventListener("visibilitychange",()=>{if(document.hidden)pause();});
getJSON("/api/experiments").then(async catalog=>{
  experimentOptions=catalog.experiments;experimentDefault=catalog.default;
  const select=$("#experiment-select");
  select.innerHTML=experimentOptions.map(option=>`<option value="${esc(option.id)}">${esc(option.title)} · ${esc(option.conditions.join(' vs '))}</option>`).join("");
  select.disabled=experimentOptions.length<2;
  select.addEventListener("change",()=>{location.hash=`overview?experiment=${encodeURIComponent(select.value)}`;});
  const [,query=""]=(location.hash.slice(1)||"overview").split("?");
  const requested=new URLSearchParams(query).get("experiment")||experimentDefault;
  if(await loadExperiment(requested))route();
}).catch(showError);
