//+------------------------------------------------------------------+
//|                                       Tests/Phase5Tests.mq5      |
//|  MITEMSHUB AI MARKET ENGINE — Phase 5 unit tests.                |
//|                                                                  |
//|  Covers: ConfidenceEngine (Python confidence math + signal       |
//|  states), ScoringEngine (weighted composite + sub-scores),       |
//|  TradeQualityEngine (R-multiple journal + break-even floor).     |
//|                                                                  |
//|  Mirrors mql5/phase5_logic_check.py assertion-for-assertion,     |
//|  which additionally checks the mirror against the REAL Python    |
//|  decision_engine methods (_classify_signal_strength,             |
//|  _dynamic_min_confidence, _drift_confidence_penalty) and         |
//|  stage3_gate.break_even_floor — so the compiled engine carries    |
//|  the Python semantics transitively.                              |
//+------------------------------------------------------------------+
#property strict
#property copyright "Synthetic Indices Bot"
#property version   "1.00"
#property description "MITEMSHUB Phase 5 unit tests — Decision"

#include "../Core/Constants.mqh"
#include "../Decision/ConfidenceEngine.mqh"
#include "../Decision/ScoringEngine.mqh"
#include "../Decision/TradeQualityEngine.mqh"

int g_pass = 0;
int g_fail = 0;

void Check(const string name, const bool ok, const string detail = "")
  {
   if(ok)
     {
      g_pass++;
      Print("[PHASE5] PASS  ", name);
     }
   else
     {
      g_fail++;
      Print("[PHASE5] FAIL  ", name, detail != "" ? "  -> " + detail : "");
     }
  }

bool CloseEnough(const double a, const double b, const double tol = 1e-9)
  {
   return(MathAbs(a - b) <= tol);
  }

//--- shared assertion matrix (lockstep with mql5/phase5_logic_check.py) -------
void TestConfidenceEngine()
  {
   Print("[PHASE5] --- ConfidenceEngine ---");
   // classify
   Check("classify strong_buy w/ setup 0.70",
         CConfidenceEngine::Classify(0.70, 0.48, true, true) == SIGNAL_STRONG_BUY);
   Check("classify strong_buy boundary 0.52",
         CConfidenceEngine::Classify(0.52, 0.48, true, true) == SIGNAL_STRONG_BUY);
   Check("classify weak_buy below strong w/ setup 0.51",
         CConfidenceEngine::Classify(0.51, 0.48, true, true) == SIGNAL_WEAK_BUY);
   Check("classify weak_buy w/o setup 0.65 (not strong)",
         CConfidenceEngine::Classify(0.65, 0.48, false, true) == SIGNAL_WEAK_BUY);
   Check("classify wait below min",
         CConfidenceEngine::Classify(0.40, 0.48, false, true) == SIGNAL_WAIT);
   Check("classify strong_sell w/ setup",
         CConfidenceEngine::Classify(0.80, 0.48, true, false) == SIGNAL_STRONG_SELL);
   Check("classify weak_sell w/o setup",
         CConfidenceEngine::Classify(0.60, 0.48, false, false) == SIGNAL_WEAK_SELL);
   Check("classify strong_buy w/ setup at 0.55 even above raised min",
         CConfidenceEngine::Classify(0.55, 0.60, true, true) == SIGNAL_STRONG_BUY);
   // dynamic min confidence
   Check("dynamic_min below sample threshold = 0.48",
         CloseEnough(CConfidenceEngine::DynamicMinConfidence(0.18, 10, 0.0), 0.48));
   Check("dynamic_min brier=0.18 -> 0.5126667",
         CloseEnough(CConfidenceEngine::DynamicMinConfidence(0.18, 100, 0.0),
                     0.48 + 0.07 * (0.07 / 0.15)));
   Check("dynamic_min brier=0.05 (clamped) -> 0.55",
         CloseEnough(CConfidenceEngine::DynamicMinConfidence(0.05, 100, 0.0), 0.55));
   Check("dynamic_min brier=0.30 (clamped) -> 0.48",
         CloseEnough(CConfidenceEngine::DynamicMinConfidence(0.30, 100, 0.0), 0.48));
   Check("dynamic_min negative brier clamped -> 0.55 (Python has no guard)",
         CloseEnough(CConfidenceEngine::DynamicMinConfidence(-1.0, 100, 0.0), 0.55));
   // drift penalty
   Check("drift penalty 0 steps -> 0.02",
         CloseEnough(CConfidenceEngine::DriftPenalty(0), 0.02));
   Check("drift penalty 250 steps -> 0.01",
         CloseEnough(CConfidenceEngine::DriftPenalty(250), 0.01));
   Check("drift penalty 500 steps -> 0.0",
         CloseEnough(CConfidenceEngine::DriftPenalty(500), 0.0));
   Check("drift penalty 1000 steps -> 0.0",
         CloseEnough(CConfidenceEngine::DriftPenalty(1000), 0.0));
   // gate
   double minc = 0.0;
   ENUM_SIGNAL_STRENGTH g = CConfidenceEngine::Gate(0.80, 0.90, true, true,
                                                    0.18, 100, 0, minc);
   Check("gate() returns strong_buy", g == SIGNAL_STRONG_BUY);
   Check("gate() min_confidence = 0.5327 (0.5127 + drift penalty 0.02)",
         CloseEnough(minc, 0.5326666667, 1e-6));
  }

void TestScoringEngine()
  {
   Print("[PHASE5] --- ScoringEngine ---");
   Check("regime alignment exact = 1.0",
         CloseEnough(CScoringEngine::RegimeAlignment(REGIME_TREND_UP, REGIME_TREND_UP), 1.0));
   Check("regime alignment trend family = 0.7",
         CloseEnough(CScoringEngine::RegimeAlignment(REGIME_EXPANSION, REGIME_TREND_UP), 0.7));
   Check("regime alignment range family = 0.7",
         CloseEnough(CScoringEngine::RegimeAlignment(REGIME_COMPRESSION, REGIME_RANGE), 0.7));
   Check("regime alignment transition = 0.4",
         CloseEnough(CScoringEngine::RegimeAlignment(REGIME_TRANSITION, REGIME_TREND_DOWN), 0.4));
   Check("regime alignment conflict = 0.2",
         CloseEnough(CScoringEngine::RegimeAlignment(REGIME_TREND_DOWN, REGIME_RANGE), 0.2));
   Check("risk score rr=4.0 stop-fit = 1.0",
         CloseEnough(CScoringEngine::RiskScore(4.0, 2.0, 0.005, 0.015), 1.0));
   Check("risk score rr=1.0 = 0.65",
         CloseEnough(CScoringEngine::RiskScore(1.0, 2.0, 0.005, 0.015), 0.65));
   Check("risk score rr=0 -> 0.0",
         CloseEnough(CScoringEngine::RiskScore(0.0, 2.0, 0.005, 0.015), 0.0));
   Check("risk score stop over cap -> 0.85",
         CloseEnough(CScoringEngine::RiskScore(4.0, 2.0, 0.03, 0.015), 0.85));
   Check("composite all 1.0 -> 1.0",
         CloseEnough(CScoringEngine::Composite(1, 1, 1, 1, 1), 1.0));
   Check("composite (0.6,1,0.5,1,1) -> 0.83",
         CloseEnough(CScoringEngine::Composite(0.6, 1.0, 0.5, 1.0, 1.0), 0.83));

   StrategyCandidate cand;
   cand.decision = DECISION_BUY;
   cand.entry = 100.0;
   cand.stop_loss = 99.5;
   cand.take_profit = 102.0;
   cand.setup_quality = 0.8;
   cand.required_regime = REGIME_EXPANSION;
   ScoreBreakdown b;
   double comp = CScoringEngine::Evaluate(cand, REGIME_EXPANSION, 0.5, -1.0, b);
   Check("evaluate setup=0.8", CloseEnough(b.setup_score, 0.8));
   Check("evaluate regime=1.0", CloseEnough(b.regime_score, 1.0));
   Check("evaluate structure neutral 0.5", CloseEnough(b.structure_score, 0.5));
   Check("evaluate execution default 1.0", CloseEnough(b.execution_score, 1.0));
   Check("evaluate risk 1.0 (rr=4, stop 0.5%)", CloseEnough(b.risk_score, 1.0));
   Check("evaluate composite (0.8,1,0.5,1,1) -> 0.86",
         CloseEnough(comp, 0.3 * 0.8 + 0.25 + 0.05 + 0.25 + 0.10));
   string expl = CScoringEngine::Explain(b, "EXPANSION");
   Check("explain mentions REGIME=EXPANSION", StringFind(expl, "REGIME=EXPANSION") >= 0);
   Check("explain mentions SETUP_QUALITY=80", StringFind(expl, "SETUP_QUALITY=80") >= 0);

   StrategyCandidate cand2;
   cand2.decision = DECISION_SELL;
   cand2.entry = 100.0;
   cand2.stop_loss = 99.0;
   cand2.take_profit = 101.0;
   cand2.setup_quality = 0.6;
   cand2.required_regime = REGIME_RANGE;
   ScoreBreakdown b2;
   CScoringEngine::Evaluate(cand2, REGIME_TREND_DOWN, 0.2, 1.0, b2);
   Check("evaluate2 regime conflict 0.2", CloseEnough(b2.regime_score, 0.2));
   Check("evaluate2 risk 0.65", CloseEnough(b2.risk_score, 0.65));
   Check("evaluate2 composite 0.5125",
         CloseEnough(b2.composite, 0.3 * 0.6 + 0.25 * 0.2 + 0.1 * 0.2 + 0.25 * 0.65 + 0.1));
  }

void TestTradeQualityEngine()
  {
   Print("[PHASE5] --- TradeQualityEngine ---");
   Check("break_even rr=3 margin=0.05 -> 0.30",
         CloseEnough(CTradeQualityEngine::BreakEvenFloor(3.0, 0.05), 0.30));
   Check("break_even rr=1 -> 0.55",
         CloseEnough(CTradeQualityEngine::BreakEvenFloor(1.0, 0.05), 0.55));
   Check("break_even rr=0 -> 0.50",
         CloseEnough(CTradeQualityEngine::BreakEvenFloor(0.0, 0.05), 0.50));
   Check("break_even rr=10 -> 0.14091",
         CloseEnough(CTradeQualityEngine::BreakEvenFloor(10.0, 0.05), 1.0 / 11.0 + 0.05));
   Check("break_even rr=100 clamped -> 0.10",
         CloseEnough(CTradeQualityEngine::BreakEvenFloor(100.0, 0.05), 0.10));

   CTradeQualityEngine tq;
   StrategyCandidate c1;
   c1.strategy = STRATEGY_BAND;
   c1.decision = DECISION_BUY;
   c1.entry = 100.0;
   c1.stop_loss = 99.5;
   c1.take_profit = 102.0;
   c1.setup_quality = 0.8;
   c1.required_regime = REGIME_EXPANSION;

   tq.StartPosition(c1, 100.0, 0);
   tq.UpdatePosition(101.0, 99.8);            // MFE 2.0R, MAE 0.4R
   double r1 = tq.ClosePosition(101.5, EXIT_TARGET_HIT, 300);
   Check("trade long return_r = 3.0", CloseEnough(r1, 3.0));

   StrategyCandidate c2;
   c2.strategy = STRATEGY_BAND;
   c2.decision = DECISION_SELL;
   c2.entry = 100.0;
   c2.stop_loss = 100.5;
   c2.take_profit = 98.0;
   c2.setup_quality = 0.7;
   c2.required_regime = REGIME_EXPANSION;
   tq.StartPosition(c2, 100.0, 300);
   tq.UpdatePosition(100.2, 99.0);            // MFE 2.0R
   double r2 = tq.ClosePosition(99.0, EXIT_TARGET_HIT, 600);
   Check("trade short return_r = 2.0", CloseEnough(r2, 2.0));

   // Record 0 is the long: assert the full anatomy.
   OutcomeRecord rec0;
   Check("get record 0", tq.GetRecord(0, rec0));
   Check("rec long mfe 2.0", CloseEnough(rec0.mfe_r, 2.0));
   Check("rec long mae 0.4", CloseEnough(rec0.mae_r, 0.4));
   Check("rec long r1+r2 reached, r3 not",
         rec0.r1_reached && rec0.r2_reached && !rec0.r3_reached);
   Check("rec long hold 1", rec0.hold_bars == 1);
   Check("rec long won", rec0.won);
   Check("rec long rr 4.0", CloseEnough(rec0.reward_risk, 4.0));
   Check("rec long exit reason TARGET_HIT", rec0.exit_reason == EXIT_TARGET_HIT);

   int n;
   double hit_rate, avg_r, expectancy, avg_rr, floor;
   bool ok = tq.Statistics(STRATEGY_BAND, n, hit_rate, avg_r, expectancy,
                           avg_rr, floor);
   Check("stats ok", ok);
   Check("stats n=2", n == 2);
   Check("stats hit 1.0", CloseEnough(hit_rate, 1.0));
   Check("stats avg_r 2.5", CloseEnough(avg_r, 2.5));
   Check("stats avg_rr 4.0", CloseEnough(avg_rr, 4.0));
   Check("stats break_even 0.25", CloseEnough(floor, 0.25));
  }

//+------------------------------------------------------------------+
//| Expert initialization — run the whole matrix then the verdict.   |
//+------------------------------------------------------------------+
int OnInit()
  {
   TestConfidenceEngine();
   TestScoringEngine();
   TestTradeQualityEngine();
   Print(StringFormat("[PHASE5] === %d passed, %d failed ===", g_pass, g_fail));
   if(g_fail == 0)
      Print("[PHASE5] SUITE PASSED - Phase 5 complete");
   else
      Print("[PHASE5] SUITE FAILED - Phase 5 incomplete");
   return(INIT_SUCCEEDED);
  }

void OnTick() { }
