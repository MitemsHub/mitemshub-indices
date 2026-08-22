//+------------------------------------------------------------------+
//|                                        Tests/Phase8Tests.mq5     |
//|  MITEMSHUB AI MARKET ENGINE — Phase 8 unit tests.                |
//|                                                                  |
//|  Covers the Journal layer (TradeJournal CSV per plan §33,        |
//|  DecisionLogger ring + verdict counts, PerformanceLogger         |
//|  incremental aggregation) and the Analytics layer                |
//|  (PerformanceAnalytics §18 metric set + splits, ExpectancyEngine |
//|  break-even floor math + verdicts, RegimeAnalytics per-regime    |
//|  breakdowns).  Same OnInit-assertion pattern as Phases 1-7 —     |
//|  runs headless in the Strategy Tester and is picked up by        |
//|  verify_all.ps1 automatically.                                   |
//+------------------------------------------------------------------+
#property strict
#property copyright "Synthetic Indices Bot"
#property version   "1.00"
#property description "MITEMSHUB Phase 8 unit tests — Journal + Analytics"

#include "../Core/Constants.mqh"
#include "../Journal/TradeJournal.mqh"
#include "../Journal/DecisionLogger.mqh"
#include "../Journal/PerformanceLogger.mqh"
#include "../Analytics/PerformanceAnalytics.mqh"
#include "../Analytics/ExpectancyEngine.mqh"
#include "../Analytics/RegimeAnalytics.mqh"

int g_pass = 0;
int g_fail = 0;

void Check(const string name, const bool ok, const string detail = "")
  {
   if(ok)
     {
      g_pass++;
      Print("[PHASE8] PASS  ", name);
     }
   else
     {
      g_fail++;
      Print("[PHASE8] FAIL  ", name, detail != "" ? "  -> " + detail : "");
     }
  }

bool CloseEnough(const double a, const double b, const double tol = 1e-9)
  {
   return(MathAbs(a - b) <= tol);
  }

//+------------------------------------------------------------------+
//| record factory                                                    |
//+------------------------------------------------------------------+
OutcomeRecord MakeRecord(const ENUM_STRATEGY strategy, const ENUM_REGIME regime,
                         const int direction, const double entry,
                         const double stop, const double target,
                         const double exit_price, const double return_r,
                         const double mae_r, const double mfe_r,
                         const ENUM_EXIT_REASON reason, const datetime opened_at,
                         const datetime closed_at, const int hold_bars)
  {
   OutcomeRecord o;
   o.strategy      = strategy;
   o.regime        = regime;
   o.direction     = direction;
   o.entry         = entry;
   o.stop_loss     = stop;
   o.take_profit   = target;
   o.exit_price    = exit_price;
   o.risk_distance = MathAbs(entry - stop);
   o.reward_risk   = (o.risk_distance > 0.0)
                     ? MathAbs(target - entry) / o.risk_distance : 0.0;
   o.return_r      = return_r;
   o.mae_r         = mae_r;
   o.mfe_r         = mfe_r;
   o.r1_reached    = (mfe_r >= 1.0);
   o.r2_reached    = (mfe_r >= 2.0);
   o.r3_reached    = (mfe_r >= 3.0);
   o.opened_at     = opened_at;
   o.closed_at     = closed_at;
   o.hold_bars     = hold_bars;
   o.exit_reason   = reason;
   o.won           = (return_r > 0.0);
   return(o);
  }

//+------------------------------------------------------------------+
//| TestTradeJournal — CSV per §33                                    |
//+------------------------------------------------------------------+
void TestTradeJournal()
  {
   Print("[PHASE8] --- TradeJournal (CSV) ---");
   string path = "phase8_test_journal.csv";
   FileDelete(path);                       // clean slate (ignore if absent)

   CTradeJournal j;
   Check("init creates the file", j.Init(path));
   Check("journal is open", j.IsOpen());

   OutcomeRecord win = MakeRecord(STRATEGY_BAND, REGIME_RANGE, 1,
                                  1700.0, 1699.0, 1701.2, 1701.2, 1.2,
                                  0.2, 1.5, EXIT_TARGET_HIT, 1700000000, 1700000900, 3);
   OutcomeRecord loss = MakeRecord(STRATEGY_BAND, REGIME_EXPANSION, -1,
                                   1700.0, 1701.0, 1698.8, 1701.0, -1.0,
                                   1.0, 0.4, EXIT_STOP_HIT, 1700001000, 1700001900, 3);
   Check("append win row", j.Append(win, "R_75", 0.10, 50.0, 0.9, 0.82));
   Check("append loss row", j.Append(loss, "R_75", 0.10, 50.0, 0.7, 0.61));
   Check("2 rows written", j.RowsWritten() == 2);
   j.Close();
   Check("closed", !j.IsOpen());

   Check("file has header", CTradeJournal::HasHeader(path));
   Check("3 lines = header + 2 rows", CTradeJournal::FileLineCount(path) == 3);

   //--- reopen and read the data rows back (line index 1 = first data row) -----
   string fields[];
   int fc = 0;
   bool rdr = CTradeJournal::ReadFields(path, 1, fields, fc);
   Check("reopen for read", rdr && fc >= 18);
   if(rdr && fc >= 18)
     {
      // columns: 0=opened_at 1=symbol 2=strategy 3=regime 4=direction ...
      //           17=exit_reason 18=closed_at 19=hold_bars
      Check("row1 strategy BAND_GEOMETRY", fields[2] == "BAND_GEOMETRY");
     }
   string f2[];
   int fc2 = 0;
   bool rdr2 = CTradeJournal::ReadFields(path, 2, f2, fc2);
   Check("row2 read", rdr2 && fc2 >= 18);
   if(rdr2 && fc2 >= 18)
     {
      Check("row2 symbol R_75", f2[1] == "R_75");
      Check("row2 strategy BAND_GEOMETRY", f2[2] == "BAND_GEOMETRY");
      Check("row2 regime EXPANSION", f2[3] == "EXPANSION");
      Check("row2 direction SELL", f2[4] == "SELL");
      Check("row2 exit reason STOP_HIT", f2[17] == "STOP_HIT");
     }

   //--- append-after-reopen keeps the header (no duplicate) ----------------------
   CTradeJournal j2;
   Check("reopen appends", j2.Init(path));
   Check("append after reopen", j2.Append(win, "R_75", 0.10, 50.0, 0.9, 0.82));
   j2.Close();
   Check("4 lines after append (header not duplicated)",
         CTradeJournal::FileLineCount(path) == 4);
   FileDelete(path);
  }

//+------------------------------------------------------------------+
//| TestDecisionLogger — ring buffer + counts                         |
//+------------------------------------------------------------------+
void TestDecisionLogger()
  {
   Print("[PHASE8] --- DecisionLogger ---");
   CDecisionLogger log;
   log.Log(100, DECISION_BUY, STRATEGY_BAND, REGIME_EXPANSION,
           SIGNAL_STRONG_BUY, 0.9, 0.85, 0.8, 1700.0, 1698.0, 1705.0, "band_ext");
   log.Log(200, DECISION_SELL, STRATEGY_BAND, REGIME_EXPANSION,
           SIGNAL_STRONG_SELL, 0.85, 0.8, 0.75, 1700.0, 1702.0, 1695.0, "band_fade");
   log.Log(300, DECISION_WAIT, STRATEGY_NONE, REGIME_RANGE,
           SIGNAL_WAIT, 0.4, 0.42, 0.3, 0.0, 0.0, 0.0, "regime_compression");

   Check("3 logged", log.Count() == 3 && log.Total() == 3);
   Check("counts by decision", log.Buys() == 1 && log.Sells() == 1 && log.Waits() == 1);

   DecisionLogEntry last;
   Check("Last() = the WAIT", log.Last(last) && last.decision == DECISION_WAIT);
   Check("Last() reasons preserved", last.reasons == "regime_compression");
   Check("Last() verdict WAIT", last.verdict == SIGNAL_WAIT);

   DecisionLogEntry first;
   Check("Get(0) = the BUY", log.Get(0, first) && first.decision == DECISION_BUY);
   Check("BUY geometry recorded", CloseEnough(first.take_profit, 1705.0));

   //--- ring wrap: capacity + 5 -> oldest 5 are dropped, total keeps growing -----
   for(int i = 0; i < DECISION_LOG_CAPACITY + 5; i++)
      log.Log(1000 + i, DECISION_WAIT, STRATEGY_NONE, REGIME_UNKNOWN,
              SIGNAL_WAIT, 0.3, 0.3, 0.2, 0.0, 0.0, 0.0, "no_setup");
   Check("ring capped at capacity", log.Count() == DECISION_LOG_CAPACITY);
   Check("total keeps growing", log.Total() == DECISION_LOG_CAPACITY + 8);
   Check("oldest dropped", !(log.Get(0, first) && first.ts == 100));

   //--- CSV mirror ---------------------------------------------------------------
   string dpath = "phase8_test_decisions.csv";
   FileDelete(dpath);
   CDecisionLogger log2;
   Check("decision CSV open", log2.OpenCSV(dpath));
   log2.Log(100, DECISION_BUY, STRATEGY_BAND, REGIME_EXPANSION,
            SIGNAL_STRONG_BUY, 0.9, 0.85, 0.8, 1700.0, 1698.0, 1705.0, "band_ext");
   log2.CloseCSV();
   Check("decision CSV written", CTradeJournal::FileLineCount(dpath) == 2);
   FileDelete(dpath);
  }

//+------------------------------------------------------------------+
//| TestPerformanceLogger — incremental aggregation                   |
//+------------------------------------------------------------------+
void TestPerformanceLogger()
  {
   Print("[PHASE8] --- PerformanceLogger ---");
   CPerformanceLogger pl;
   // sequence: +2, +1, -1, -3   (R only; hold bars 5,3,4,6)
   pl.AddOutcome(+2.0, 0.0, 5);
   pl.AddOutcome(+1.0, 0.0, 3);
   pl.AddOutcome(-1.0, 0.0, 4);
   pl.AddOutcome(-3.0, 0.0, 6);
   pl.Finalize();

   PerformanceSummary s = pl.Summary();
   Check("4 trades", s.trades == 4);
   Check("2W/2L", s.wins == 2 && s.losses == 2);
   Check("win rate 0.5", CloseEnough(s.win_rate, 0.5));
   Check("sumR -1.0", CloseEnough(s.sum_r, -1.0));
   Check("avg R -0.25", CloseEnough(s.avg_r, -0.25));
   Check("maxDD 4.0R (peak 3 -> trough -1)", CloseEnough(s.max_drawdown_r, 4.0));
   Check("consec wins 2", s.max_consec_wins == 2);
   Check("consec losses 2", s.max_consec_losses == 2);
   Check("avg hold 4.5", CloseEnough(s.avg_hold_bars, 4.5));
   Check("PF 0.75 (3/4)", CloseEnough(s.profit_factor, 0.75));
   Check("avg win +1.5", CloseEnough(s.avg_win_r, 1.5));
   Check("avg loss -2.0", CloseEnough(s.avg_loss_r, -2.0));

   //--- OutcomeRecord overload + summary CSV --------------------------------------
   OutcomeRecord recs[4];
   recs[0] = MakeRecord(STRATEGY_BAND, REGIME_RANGE, 1, 100.0, 99.0, 102.0,
                        102.0, 2.0, 0.2, 2.0, EXIT_TARGET_HIT, 1, 100, 5);
   recs[1] = MakeRecord(STRATEGY_BAND, REGIME_RANGE, 1, 100.0, 99.0, 102.0,
                        101.0, 1.0, 0.3, 1.5, EXIT_TARGET_HIT, 101, 200, 3);
   recs[2] = MakeRecord(STRATEGY_BAND, REGIME_TREND_UP, -1, 100.0, 101.0, 98.0,
                        101.0, -1.0, 1.0, 0.6, EXIT_STOP_HIT, 201, 300, 4);
   recs[3] = MakeRecord(STRATEGY_BAND, REGIME_TREND_DOWN, -1, 100.0, 101.0, 98.0,
                        103.0, -3.0, 3.0, 0.1, EXIT_STOP_HIT, 301, 400, 6);
   CPerformanceLogger pl2;
   for(int i = 0; i < 4; i++)
      pl2.AddOutcome(recs[i]);
   pl2.Finalize();
   PerformanceSummary s2 = pl2.Summary();
   Check("record overload agrees (trades)", s2.trades == 4);
   Check("record overload agrees (sumR)", CloseEnough(s2.sum_r, -1.0));
   Check("record overload agrees (maxDD)", CloseEnough(s2.max_drawdown_r, 4.0));
  }

//+------------------------------------------------------------------+
//| TestPerformanceAnalytics — §18 metric set + splits                |
//+------------------------------------------------------------------+
void TestPerformanceAnalytics()
  {
   Print("[PHASE8] --- PerformanceAnalytics ---");
   OutcomeRecord recs[4];
   double conf[4];
   recs[0] = MakeRecord(STRATEGY_BAND, REGIME_RANGE, 1, 100.0, 99.0, 102.0,
                        102.0, 2.0, 0.2, 2.0, EXIT_TARGET_HIT, 1, 100, 5); conf[0] = 0.4;
   recs[1] = MakeRecord(STRATEGY_BAND, REGIME_RANGE, 1, 100.0, 99.0, 102.0,
                        101.0, 1.0, 0.3, 1.5, EXIT_TARGET_HIT, 101, 200, 3); conf[1] = 0.9;
   recs[2] = MakeRecord(STRATEGY_BAND, REGIME_TREND_UP, -1, 100.0, 101.0, 98.0,
                        101.0, -1.0, 1.0, 0.6, EXIT_STOP_HIT, 201, 300, 4); conf[2] = 0.5;
   recs[3] = MakeRecord(STRATEGY_BAND, REGIME_TREND_DOWN, -1, 100.0, 101.0, 98.0,
                        103.0, -3.0, 3.0, 0.1, EXIT_STOP_HIT, 301, 400, 6); conf[3] = 0.8;

   PerformanceSummary m;
   CPerformanceAnalytics::Metrics(recs, 4, m);
   Check("metrics 4 trades", m.trades == 4);
   Check("metrics win rate 0.5", CloseEnough(m.win_rate, 0.5));
   Check("metrics sumR -1.0 (parity with logger)", CloseEnough(m.sum_r, -1.0));
   Check("metrics maxDD 4.0R", CloseEnough(m.max_drawdown_r, 4.0));
   Check("metrics PF 0.75", CloseEnough(m.profit_factor, 0.75));
   Check("metrics avg hold 4.5", CloseEnough(m.avg_hold_bars, 4.5));
   Check("metrics streaks 2/2", m.max_consec_wins == 2 && m.max_consec_losses == 2);

   //--- splits -------------------------------------------------------------------
   BucketStats by_dir[2];
   CPerformanceAnalytics::SplitByDirection(recs, 4, by_dir);
   Check("dir long n=2", by_dir[0].n == 2 && by_dir[1].n == 2);
   Check("dir long sum +3.0", CloseEnough(by_dir[0].sum_r, 3.0));
   Check("dir short sum -4.0", CloseEnough(by_dir[1].sum_r, -4.0));

   BucketStats by_reg[ANALYTICS_MAX_REGIMES];
   CPerformanceAnalytics::SplitByRegime(recs, 4, by_reg);
   Check("regime RANGE n=2", by_reg[REGIME_RANGE].n == 2);
   Check("regime TREND_UP n=1", by_reg[REGIME_TREND_UP].n == 1);
   Check("regime TREND_DOWN n=1", by_reg[REGIME_TREND_DOWN].n == 1);
   Check("regime RANGE avg +1.5", CloseEnough(by_reg[REGIME_RANGE].AvgR(), 1.5));

   BucketStats by_strat[ANALYTICS_MAX_STRATEGIES];
   CPerformanceAnalytics::SplitByStrategy(recs, 4, by_strat);
   Check("strategy BAND n=4", by_strat[STRATEGY_BAND].n == 4);

   BucketStats by_exit[ANALYTICS_MAX_EXIT_REASONS];
   CPerformanceAnalytics::SplitByExitReason(recs, 4, by_exit);
   Check("exit TARGET n=2", by_exit[EXIT_TARGET_HIT].n == 2);
   Check("exit STOP n=2", by_exit[EXIT_STOP_HIT].n == 2);
   Check("exit TARGET sum +3.0", CloseEnough(by_exit[EXIT_TARGET_HIT].sum_r, 3.0));

   BucketStats by_conf[2];
   CPerformanceAnalytics::SplitByConfidence(recs, 4, conf, 0.6, by_conf);
   Check("conf weak n=2 (0.4, 0.5)", by_conf[0].n == 2);
   Check("conf strong n=2 (0.9, 0.8)", by_conf[1].n == 2);
   Check("conf weak sum +1.0", CloseEnough(by_conf[0].sum_r, 1.0));
   Check("conf strong sum -2.0", CloseEnough(by_conf[1].sum_r, -2.0));
  }

//+------------------------------------------------------------------+
//| TestExpectancyEngine — break-even floor math + verdicts           |
//+------------------------------------------------------------------+
void TestExpectancyEngine()
  {
   Print("[PHASE8] --- ExpectancyEngine ---");
   //--- floor math (stage3_gate parity) ------------------------------------------
   Check("floor RR1.2 margin 0.05 = 0.5045",
         CloseEnough(CExpectancyEngine::BreakEvenFloor(1.2, 0.05), 1.0 / 2.2 + 0.05));
   Check("floor RR4.0 = 0.25",
         CloseEnough(CExpectancyEngine::BreakEvenFloor(4.0, 0.05), 0.25));
   Check("floor RR0.1 clamps to 0.60",
         CloseEnough(CExpectancyEngine::BreakEvenFloor(0.1, 0.05), 0.60));
   Check("floor RR0 falls back to 0.50",
         CloseEnough(CExpectancyEngine::BreakEvenFloor(0.0, 0.05), 0.50));
   Check("floor parity with TradeQualityEngine",
         CloseEnough(CExpectancyEngine::BreakEvenFloor(2.0, 0.05),
                     CTradeQualityEngine::BreakEvenFloor(2.0, 0.05)));

   //--- verdict: hits the floor but n below min_samples ----------------------------
   OutcomeRecord hit5[5];
   for(int i = 0; i < 5; i++)
      hit5[i] = MakeRecord(STRATEGY_BAND, REGIME_RANGE, 1, 100.0, 99.0, 101.2,
                           101.2, 1.2, 0.2, 1.5, EXIT_TARGET_HIT, i, i + 100, 3);
   ExpectancyVerdict v;
   CExpectancyEngine::Verdict(hit5, 5, 10, 0.05, v);   // min_samples 10
   Check("verdict n=5", v.n == 5);
   Check("verdict hit 1.0", CloseEnough(v.hit_rate, 1.0));
   Check("verdict floor for RR1.2", CloseEnough(v.break_even_floor, 1.0 / 2.2 + 0.05));
   Check("verdict not enough samples", !v.enough_samples && !v.beats_floor);

   CExpectancyEngine::Verdict(hit5, 5, 3, 0.05, v);     // min_samples 3
   Check("verdict beats with samples", v.enough_samples && v.beats_floor);

   //--- a 40% hitter at RR1.2 does NOT clear the 50.45% floor ----------------------
   OutcomeRecord mixed[5];
   mixed[0] = hit5[0];
   mixed[1] = hit5[1];
   for(int i = 2; i < 5; i++)
      mixed[i] = MakeRecord(STRATEGY_BAND, REGIME_RANGE, 1, 100.0, 99.0, 101.2,
                            99.0, -1.0, 1.0, 0.3, EXIT_STOP_HIT, i, i + 100, 3);
   ExpectancyVerdict v2;
   CExpectancyEngine::Verdict(mixed, 5, 3, 0.05, v2);
   Check("40% hitter does not beat 50.45% floor", v2.enough_samples && !v2.beats_floor);

   //--- per-strategy filter ---------------------------------------------------------
   OutcomeRecord two_strat[3];
   two_strat[0] = MakeRecord(STRATEGY_BAND, REGIME_RANGE, 1, 100.0, 99.0, 101.2,
                             101.2, 1.2, 0.1, 1.4, EXIT_TARGET_HIT, 1, 100, 3);
   two_strat[1] = MakeRecord(STRATEGY_BAND, REGIME_RANGE, 1, 100.0, 99.0, 101.2,
                             99.0, -1.0, 1.0, 0.2, EXIT_STOP_HIT, 101, 200, 3);
   two_strat[2] = MakeRecord(STRATEGY_TREND, REGIME_TREND_UP, 1, 100.0, 99.0, 102.0,
                             102.0, 2.0, 0.2, 2.0, EXIT_TARGET_HIT, 201, 300, 5);
   ExpectancyVerdict vb;
   CExpectancyEngine::VerdictForStrategy(two_strat, 3, STRATEGY_BAND, 2, 0.05, vb);
   Check("strategy filter n=2", vb.n == 2);
   Check("strategy filter hit 0.5", CloseEnough(vb.hit_rate, 0.5));
  }

//+------------------------------------------------------------------+
//| TestRegimeAnalytics — per-regime breakdown                        |
//+------------------------------------------------------------------+
void TestRegimeAnalytics()
  {
   Print("[PHASE8] --- RegimeAnalytics ---");
   OutcomeRecord recs[4];
   recs[0] = MakeRecord(STRATEGY_BAND, REGIME_RANGE, 1, 100.0, 99.0, 102.0,
                        102.0, 2.0, 0.2, 2.0, EXIT_TARGET_HIT, 1, 100, 5);
   recs[1] = MakeRecord(STRATEGY_BAND, REGIME_RANGE, 1, 100.0, 99.0, 102.0,
                        101.0, 1.0, 0.3, 1.5, EXIT_TARGET_HIT, 101, 200, 3);
   recs[2] = MakeRecord(STRATEGY_BAND, REGIME_TREND_UP, -1, 100.0, 101.0, 98.0,
                        101.0, -1.0, 1.0, 0.6, EXIT_STOP_HIT, 201, 300, 4);
   recs[3] = MakeRecord(STRATEGY_BAND, REGIME_TREND_DOWN, -1, 100.0, 101.0, 98.0,
                        103.0, -3.0, 3.0, 0.1, EXIT_STOP_HIT, 301, 400, 6);

   BucketStats by_reg[ANALYTICS_MAX_REGIMES];
   CPerformanceAnalytics::SplitByRegime(recs, 4, by_reg);
   Check("3 active regimes", CRegimeAnalytics::ActiveRegimes(by_reg) == 3);
   Check("concentration 0.5 (RANGE holds 2/4)",
         CloseEnough(CRegimeAnalytics::Concentration(by_reg, 4), 0.5));
   Check("best regime RANGE (+1.5R)",
         CRegimeAnalytics::BestRegime(by_reg) == (int)REGIME_RANGE);
   Check("worst regime TREND_DOWN (-3R)",
         CRegimeAnalytics::WorstRegime(by_reg) == (int)REGIME_TREND_DOWN);
   Check("alignment share RANGE = 0.5",
         CloseEnough(CRegimeAnalytics::AlignmentShare(recs, 4, REGIME_RANGE), 0.5));
   Check("alignment share COMPRESSION = 0",
         CloseEnough(CRegimeAnalytics::AlignmentShare(recs, 4, REGIME_COMPRESSION), 0.0));
  }

//+------------------------------------------------------------------+
//| Expert initialization                                              |
//+------------------------------------------------------------------+
int OnInit()
  {
   TestTradeJournal();
   TestDecisionLogger();
   TestPerformanceLogger();
   TestPerformanceAnalytics();
   TestExpectancyEngine();
   TestRegimeAnalytics();
   Print(StringFormat("[PHASE8] === %d passed, %d failed ===", g_pass, g_fail));
   if(g_fail == 0)
      Print("[PHASE8] SUITE PASSED - Phase 8 complete");
   else
      Print("[PHASE8] SUITE FAILED - Phase 8 incomplete");
   return(INIT_SUCCEEDED);
  }

void OnTick() { }
