# Global Macro Index Upgrade Plan

Date: 2026-05-10
Owner: GAI_MEDashBoard
Status: Ready for execution

---

## 1. Plan Objective

Upgrade the existing global macro dashboard into a measurable regime engine that can:
1. Determine macro direction with a 20-indicator diffusion method.
2. Integrate 13F positioning signals and internal rotation signals.
3. Distinguish leading vs coincident dynamics for better trend judgement.
4. Produce a transparent traffic-light regime output (Green / Yellow / Red).

---

## 2. Scope

In scope:
1. 20-indicator signal framework (monthly normalized direction).
2. Regime score and traffic-light rules.
3. 13F module (quarterly, lag-aware) with crowding diagnostics.
4. Internal rotation module (cyclical vs defensive market internals).
5. Dashboard presentation (new Panel E) and documentation updates.
6. Android Compose integration (Panel E in Kotlin + Jetpack Compose). ✅ **Confirmed**

Out of scope (Phase 1):
1. Automated trading execution.
2. Intraday signal engine.
3. Country-by-country custom threshold optimization.
4. Indicator weighting optimization (all binary 0/1 equal weight in v1; weighted v2 planned — see §14).

---

## 3. Core Definitions

### 3.1 Signal Definition
Each indicator outputs a direction score each month:
- 1 = pro-expansion / risk-on direction.
- 0 = non-expansion / risk-off direction.

Score formula:

```
Score_t = Σ(i=1..20) s_i,t
```

Diffusion formula:

```
Diffusion_t = Score_t / 20 × 100%
```

### 3.2 Traffic-Light Rule

| Regime | Condition | Diffusion | Interpretation |
|--------|-----------|-----------|----------------|
| 🟢 Green (Expansion) | Score >= 15 | >= 75% | Strong majority of indicators confirm expansion |
| 🟡 Yellow (Transition) | 10 <= Score <= 14 | 50%–70% | Mixed signals, trend uncertain |
| 🔴 Red (Contraction) | Score <= 9 | <= 45% | Majority of indicators signal contraction |

> **Calibration note**: The 15/10/9 thresholds correspond to 75%/50%/45% diffusion rates.
> These should be validated against historical regime transitions (Section 8, Phase 4) and
> adjusted via semi-annual calibration review if false-switch frequency is too high.

### 3.3 Anti-Whipsaw Controls
1. Two-period confirmation: regime switch requires 2 consecutive periods in the new zone.
2. Data sufficiency gate: if valid indicators < 16, mark as **Low Confidence**.
3. Group cap: max 5 effective points from any single group (prevents one category dominating).

---

## 4. Indicator Architecture (20 Signals)

### 4.1 Group A — Demand and Leading Activity (5)
1. US PMI (>50 and 3M slope up)
2. Taiwan PMI (>50 and 3M slope up)
3. China PMI (>50 and 3M slope up)
4. Euro industrial confidence proxy (>50 and 3M slope up) — *Note: Eurostat ICI is a balance indicator; codebase already applies +50 normalization in `fetch_eurostat_ici()`*
5. US New Orders YoY (>0)

### 4.2 Group B — Trade and Coincident Flow (5)
6. Taiwan Exports YoY (>0 and improving 3M avg)
7. Korea Exports YoY (>0 and improving 3M avg)
8. US Retail Sales YoY (>0)
9. OECD CLI breadth (>= 3 of 5 economies above 100) — *The 5 economies: US, China, Japan, EU (G4E), Korea*
10. NDC leading index (3M slope up)

### 4.3 Group C — Cost, Liquidity, Financial Conditions (5)
11. Core CPI-PPI scissors (narrowing or negative)
12. China PPI YoY (3M slope up)
13. HY spread (3M down)
14. 10Y-3M spread (>0 and rising 3M)
15. Taiwan M1B-M2 spread (>0 or 3M slope up)

### 4.4 Group D — Market Internal and Positioning (5)
16. VIX (3M down)
17. TWD/USD (Taiwan dollar appreciating trend over 3M)
18. Copper YoY (>0)
19. Internal rotation index (cyclical vs defensive relative strength >0 and 3M slope up) — **NEW**
20. 13F cyclical-vs-defensive net add ratio (>0) — **NEW**

Note:
- #19 and #20 are newly added modules.
- #20 is quarterly and lagged; it anchors medium-term positioning rather than short-term timing.

### 4.5 Data Source Mapping

| # | Indicator | Source | API / Method | Status |
|---|-----------|--------|-------------|--------|
| 1 | US PMI | ISM via DBnomics + FRED NAPM | `fetch_ism_pmi()` | ✅ Implemented |
| 2 | Taiwan PMI | CIER Excel | `fetch_taiwan_pmi()` | ✅ Implemented |
| 3 | China PMI | NBS API | `fetch_china_nbs_pmi()` | ✅ Implemented |
| 4 | Euro ICI | Eurostat SDMX JSON | `fetch_eurostat_ici()` | ✅ Implemented |
| 5 | US New Orders YoY | FRED AMTMNO | `fetch_us_new_orders_yoy()` | ✅ Implemented |
| 6 | Taiwan Exports YoY | MOF scraping | `fetch_taiwan_exports_amount()` + `compute_yoy()` | ✅ Implemented |
| 7 | Korea Exports YoY | FRED XTEXVA01KRM664S | `fetch_korea_exports_yoy()` | ✅ Implemented |
| 8 | US Retail Sales YoY | FRED RSAFS | `fetch_fred()` + `compute_yoy()` | ✅ Implemented |
| 9 | OECD CLI breadth | DBnomics OECD/MEI | `fetch_dbnomics()` × 5 economies | ✅ Data available, ⚠️ breadth logic needed |
| 10 | NDC leading index | NDC JSON API | `fetch_ndc_leading_index()` | ✅ Implemented |
| 11 | CPI-PPI scissors | FRED CPILFESL, PPIFES | `fetch_fred()` + `compute_yoy()` | ✅ Implemented |
| 12 | China PPI YoY | NBS API | `fetch_china_nbs_ppi_yoy()` | ✅ Implemented |
| 13 | HY spread | FRED BAMLH0A0HYM2 | `fetch_hy_spread()` | ✅ Implemented |
| 14 | 10Y-3M spread | FRED T10Y3M | `fetch_t10y3m()` | ✅ Implemented |
| 15 | TW M1B-M2 spread | CBC PDF | `fetch_cbc_money_supply()` | ✅ Implemented |
| 16 | VIX | FRED VIXCLS | `fetch_fred()` | ✅ Implemented |
| 17 | TWD/USD | FRED DEXTAUS | `fetch_twd_usd()` | ✅ Implemented |
| 18 | Copper YoY | FRED PCOPPUSDM | `fetch_copper_yoy()` | ✅ Implemented |
| 19 | Internal rotation | Yahoo Finance sector ETFs | 🔴 **New development required** | ❌ Not implemented |
| 20 | 13F net add ratio | SEC EDGAR FULL-INDEX | 🔴 **New development required** | ❌ Not implemented |

### 4.6 Implementation Status Summary

- **Already implemented in `data_fetcher.py`**: 16 of 20 indicators (raw data available)
- **Need new scoring logic**: All 20 (binary direction scoring is new)
- **Need new data sources**: 2 (#19 rotation, #20 13F)
- **Need new aggregation logic**: 1 (#9 OECD CLI breadth — data exists but breadth calc is new)

---

## 5. 13F Module Design

### 5.1 Data Source

- **Primary**: SEC EDGAR FULL-INDEX quarterly filings
  - URL pattern: `https://www.sec.gov/Archives/edgar/full-index/{YEAR}/QTR{Q}/company.idx`
  - Parse **all** 13F-HR filings (full universe, no manager filtering) ✅ **Confirmed**
  - Quarterly cadence: filings due 45 days after quarter end
  - Aggregate across all filers to derive sector-level net add/reduce totals
- **Fallback**: WhaleWisdom API or cached local copy if EDGAR is rate-limited

### 5.2 Primary Signal (in 20-score)
1. 13F cyclical-vs-defensive net add ratio.
   - Cyclical sectors: Consumer Discretionary, Industrials, Materials, Financials
   - Defensive sectors: Consumer Staples, Utilities, Healthcare, Real Estate

### 5.3 Secondary Diagnostics (display only)
1. Concentration risk (top-10 weight, HHI).
2. Crowding score (consensus overlap across major managers).
3. Entry/Exit breadth (new positions minus liquidated positions).

### 5.4 Data Lag Handling
1. Explicitly display report date and market-usable date.
2. Use high-frequency proxy confirmation:
   - sector/style ETF flows
   - HY spread trend
   - volatility term structure
3. **Fallback if 13F unavailable**: Use simplified proxy = HY spread direction + VIX term structure slope as positioning substitute (mark as "Proxy" confidence).

---

## 6. Internal Rotation Module Design

1. Build cyclical basket vs defensive basket relative strength index. ✅ **Basket composition frozen**
   - **Cyclical basket**: XLY (Consumer Disc.) + XLI (Industrials) + XLB (Materials) + XLF (Financials)
   - **Defensive basket**: XLP (Consumer Staples) + XLU (Utilities) + XLV (Healthcare) + XLRE (Real Estate)
   - Ratio = equal-weight cyclical basket return / equal-weight defensive basket return (rolling 3M)
2. Add market breadth confirms:
   - advance/decline ratio
   - new highs/new lows
   - equal-weight vs cap-weight performance gap
3. Output one monthly binary direction for score integration.
4. **Data source**: Yahoo Finance API for sector ETF prices (monthly close).
5. **Fallback**: If Yahoo Finance is unavailable, use FRED sector-level industrial production indices as proxy.

---

## 7. Dashboard Upgrade Design

### 7.1 Panel Placement

The Global Macro Index will be added as a **new Panel E** in the sidebar navigation, keeping existing panels A–D intact:

```
A：終端需求感測        (existing)
B：獲利與成本感測      (existing)
C：流動性與風險感測    (existing)
D：股市比對            (existing)
E：全球總經指數  ← NEW (Global Macro Index)
```

### 7.2 New Macro Index Section
Display:
1. Current Score, Diffusion %, Regime light (🟢/🟡/🔴).
2. Confidence tag (Normal / Low Confidence).
3. 20-signal heatmap (1/0 by indicator, grouped by A/B/C/D).
4. Top 3 positive drivers and top 3 negative drags.
5. 13F and rotation diagnostic cards.

### 7.3 Historical Regime Timeline
1. Show regime transitions over at least 10 years.
2. Annotate major macro events for sanity check (e.g., 2008 GFC, 2015 China scare, 2018 Q4 selloff, 2020 COVID, 2022 rate hike cycle).

---

## 8. Implementation Plan by Phase

### Phase 0 — Specification Freeze (Day 1)
1. Finalize the 20 indicators and rules.
2. Freeze thresholds and anti-whipsaw rules.
3. ~~Confirm cyclical/defensive basket constituents.~~ ✅ Frozen: XLY+XLI+XLB+XLF vs XLP+XLU+XLV+XLRE
4. ~~Confirm 13F manager universe.~~ ✅ Confirmed: All 13F filers (full EDGAR universe)

**Deliverable:**
- Rulebook section approved.

### Phase 1 — Data and Scoring Engine (Days 2–5)
1. Add signal transformation functions in data layer.
   - Leverage existing 16 implemented fetch functions.
   - Add 3M slope calculation utility.
   - Add binary scoring wrapper for each indicator.
2. Build monthly normalization and binary scoring pipeline.
3. Add confidence and missing-data handling.
4. Add OECD CLI breadth aggregation logic (#9).

**Deliverable:**
- `Score_t` and `Diffusion_t` generated reproducibly.
- Unit tests for scoring logic covering edge cases.

### Phase 2 — 13F and Rotation Integration (Days 6–9)
1. Implement SEC EDGAR 13F parser and aggregation.
2. Implement sector ETF-based internal rotation index.
3. Implement breadth checks (advance/decline, new highs/lows).
4. Integrate both into macro score framework.
5. Implement fallback proxies for both modules.

**Deliverable:**
- Signals #19 and #20 live.
- Fallback proxies verified.

### Phase 3 — Web UI Delivery (Days 10–12)
1. Add Panel E (Global Macro Index) to dashboard sidebar.
2. Add heatmap, driver cards, timeline.
3. Add notes for data lag and confidence.
4. Ensure responsive layout (dual-column for wide screens).

**Deliverable:**
- End-user visible Global Macro Index panel (Streamlit).

### Phase 3.5 — Android Compose Integration (Days 13–15) ✅ **Confirmed**
1. Add `MacroIndexScreen.kt` as 5th Compose screen.
2. Implement regime engine logic in `DashboardViewModel.kt` (reuse scoring rules from Python).
3. Add data fetching for rotation ETFs and 13F aggregation in `ApiClient.kt`.
4. Add 5th bottom navigation tab "總經指數" to `MainScreen.kt`.
5. UI elements: regime traffic light, 20-signal heatmap grid, driver cards, confidence badge.
6. Match visual style with existing A–D panels (Material 3 dark theme).

**Deliverable:**
- Android Panel E functional and visually aligned with web UI.
- APK build passes (`gradlew.bat assembleDebug`).

### Phase 4 — Validation and Documentation (Days 16–18)
1. Backtest key windows:
   - **Crisis periods**: 2008 GFC, 2020 COVID crash, 2022 rate hike cycle
   - **False-positive tests**: 2015–2016 China slowdown scare, 2018 Q4 correction (no recession followed)
   - **Note**: 2008 GFC requires `lookback_years ≥ 18` in `build_macro_index_history()`. Default is 10 — set to 18 for Phase 4 validation runs only (performance trade-off acceptable in offline analysis).
2. Evaluate false-switch frequency and lead/lag quality.
3. Calibrate thresholds if false-switch rate exceeds target.
4. Update README and plan references.
5. Final APK build and regression test for Android.

**Deliverable:**
- Validation summary with confusion-matrix style analysis.
- Updated docs.
- Production-ready APK.

---

## 9. Acceptance Criteria

1. System outputs monthly Score, Diffusion %, and regime light.
2. 20 indicators each have clear direction rules and documented provenance.
3. 13F and internal rotation are both included in final output.
4. Regime transitions follow two-period confirmation rule.
5. Dashboard clearly shows confidence and data lag caveats.
6. Backtest report includes at least **five** stress/test periods (3 crisis + 2 false-positive).
7. All existing Panel A–D functionality remains unaffected (regression-free).
8. Fallback proxies activate gracefully when primary sources fail.
9. Android Compose Panel E is functional with matching UI elements.
10. APK compiles successfully and passes regression testing.

---

## 10. Risks and Mitigations

1. **13F lag risk**
   - Mitigation: proxy confirmation and explicit lag labeling.

2. **Indicator multicollinearity**
   - Mitigation: group cap and periodic correlation audit.

3. **Missing/unstable data sources**
   - Mitigation: fallback sources and confidence downgrade.

4. **Threshold drift over cycles**
   - Mitigation: semi-annual calibration review.

5. **SEC EDGAR access barriers** *(NEW)*
   - Risk: EDGAR has rate limits (10 req/sec) and periodic downtime.
   - Mitigation: local quarterly caching, exponential backoff retry, quarterly-only refresh schedule.

6. **Scope creep from new modules** *(NEW)*
   - Risk: 13F parser and rotation module are non-trivial and may exceed Day 6–9 timeline.
   - Mitigation: implement simplified proxy versions first (Phase 2a), full versions as Phase 2b if time permits.

7. **Yahoo Finance unofficial API instability** *(NEW)*
   - Risk: Yahoo Finance's v8/finance/chart endpoint is undocumented; has broken historically without notice, affecting #19 (rotation) and #20 (13F proxy).
   - Mitigation: add fallback to FRED sector-level indices (already documented in §6), implement circuit-breaker that downgrades to proxy confidence label rather than crashing.
   - Affected modules: `fetch_sector_rotation()`, `fetch_13f_proxy()`

---

## 11. Immediate Next Actions

1. Confirm final threshold set (15/10/9 boundaries) against historical data.
2. ~~Confirm cyclical/defensive basket constituents.~~ ✅ Done — frozen as proposed.
3. ~~Confirm 13F manager universe.~~ ✅ Done — all 13F filers, full universe.
4. ~~Decide Android Compose integration.~~ ✅ Done — included as Phase 3.5.
5. Start Phase 0 rulebook freeze and implementation.

---

## 12. Definition of Done

The Global Macro Index upgrade is considered complete when:
1. The 20-signal regime engine is running monthly in production.
2. 13F + internal rotation are visible and interpretable in dashboard UI.
3. Historical regime timeline and confidence flags are available.
4. Documentation is updated and reproducible for future extension.
5. Android Compose app includes Panel E with regime display and heatmap.
6. Backtest validation report is reviewed and thresholds confirmed.

---

## 13. Resolved Decisions

> Owner decisions confirmed on 2026-05-10:

| # | Question | Decision |
|---|----------|----------|
| 1 | Android scope | ✅ **Yes** — Panel E included in Kotlin Compose. Added Phase 3.5 (Days 13–15). |
| 2 | Indicator weighting | ✅ **Yes** — v1 uses equal weight; weighted scoring planned for v2 (see §14). |
| 3 | Cyclical/Defensive basket | ✅ **Accepted as proposed** — XLY+XLI+XLB+XLF vs XLP+XLU+XLV+XLRE. |
| 4 | 13F manager universe | ✅ **All filers** — Full SEC EDGAR 13F universe, no filtering. |

### Remaining Open
5. **Update frequency**: Macro Index updates monthly — should it also show a "real-time estimate" using daily-frequency indicators (VIX, HY, TWD)? *(Deferred to Phase 4 review)*

---

## 14. v2 Roadmap — Weighted Scoring ✅ **Confirmed for future phase**

After v1 (equal-weight binary) is validated through Phase 4 backtesting, v2 will explore:

1. **Leading indicator premium**: Assign 1.5× weight to leading indicators (Group A #1–5: PMI×4 + US New Orders YoY; #10 NDC) vs 1.0× for coincident.
2. **Cross-correlation penalty**: Reduce effective weight of highly correlated indicator pairs (e.g., US PMI ↔ US New Orders).
3. **Regime-dependent weights**: In transition zones (Yellow), upweight financial conditions (#13 HY, #14 10Y-3M) which historically have better turning-point accuracy.
4. **Calibration method**: Use rolling 15-year backtest to optimize weights via regime-hit-rate maximization.

> Implementation timeline: After v1 has operated for 6+ months with sufficient regime transitions to evaluate.
