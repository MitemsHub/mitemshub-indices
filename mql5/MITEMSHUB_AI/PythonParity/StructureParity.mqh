//+------------------------------------------------------------------+
//|                                PythonParity/StructureParity.mqh  |
//|  MITEMSHUB AI MARKET ENGINE — Python structure parity port.      |
//|                                                                  |
//|  Faithful MQL5 port of the production Python feature extractor   |
//|  src/synthetic_trader/features/market_structure.py:              |
//|    detect_swings          (NON-strict EQUALITY fractals,         |
//|                             left=right=2, over candles[:-1],     |
//|                             median-outlier filter)               |
//|    detect_fvg             (3-bar fair-value gaps)                |
//|    market_structure_features (bos, internal_bos, sweeps, fvg,    |
//|                             structure_bias with the HH+HL /      |
//|                             LH+LL and momentum fallback)         |
//|    structural_direction   (bullish vs bearish score comparison)  |
//|                                                                  |
//|  Purpose: Tests/StructureLiveTests.mq5 streams M5 bars on the    |
//|  SYN75 chart inside the MT5 Strategy Tester and compares the     |
//|  reconciled CStructureEngine bias against THIS module's          |
//|  direction — so the Python engine's answer is reproduced inside  |
//|  the tester where Python cannot run.  Validated in lockstep by   |
//|  mql5/structure_parity_check.py, which asserts this port's       |
//|  outputs equal the real Python functions on crafted, random,     |
//|  and real-corpus bars.                                           |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_PYTHONPARITY_STRUCTUREPARITY_MQH
#define MITEMSHUB_PYTHONPARITY_STRUCTUREPARITY_MQH

struct StructureParityResult
  {
   int    direction;          // +1 LONG, -1 SHORT, 0 FLAT
   double structure_bias;     // 0.7 (HH+HL) / -0.7 (LH+LL) / momentum fallback
   double displacement_atr;   // |last body| / ATR(14)
   int    bos_up, bos_down;
   int    internal_bos_up, internal_bos_down;
   int    sweep_up, sweep_down;
   int    fvg_up, fvg_down;
   int    fvg_active_up, fvg_active_down;
   double recent_high, recent_low;
  };

class CStructureParity
  {
private:
   double SafeDiv(const double num, const double den, const double def = 0.0)
     {
      return(MathAbs(den) < 1e-12 ? def : num / den);
     }

   double Clamp(const double v, const double lo, const double hi)
     {
      return(v < lo ? lo : (v > hi ? hi : v));
     }

   // Python: sorted(all_highs_and_lows)[len // 2] — the upper-middle index.
   double MedianHighLow(const double &highs[], const double &lows[], const int count)
     {
      double all[];
      int n = count * 2;
      ArrayResize(all, n);
      for(int i = 0; i < count; i++)
        {
         all[i] = highs[i];
         all[count + i] = lows[i];
        }
      ArraySort(all);
      return(all[n / 2]);
     }

   // Non-strict fractal swings over candles[0..count-1] (Python detect_swings):
   // a swing high when highs[i] == max(window highs) — EQUALITY counts, so
   // flat tops ARE swings.  Emits the per-polarity price lists AND the
   // combined ordered sequence (kind: +1 high / -1 low) so internal-BOS can
   // reproduce Python's "last 4 swings, filtered by kind" view.
   int DetectSwings(const double &highs[], const double &lows[], const int count,
                    const int left, const int right, const double median,
                    double &sw_high[], double &sw_low[],
                    double &seq_price[], int &seq_kind[])
     {
      ArrayResize(sw_high, 0);
      ArrayResize(sw_low, 0);
      ArrayResize(seq_price, 0);
      ArrayResize(seq_kind, 0);
      if(count < left + right + 1)
         return(0);
      double out_high[], out_low[], out_sp[];
      int    out_sk[];
      ArrayResize(out_high, count);
      ArrayResize(out_low, count);
      ArrayResize(out_sp, count);
      ArrayResize(out_sk, count);
      int nh = 0, nl = 0, ns = 0;
      double thr_high = median * 5.0;
      double thr_low = median / 5.0;
      for(int i = left; i < count - right; i++)
        {
         if(highs[i] > thr_high || lows[i] < thr_low)
            continue;                       // outlier candle — Python skips it
         double wmax = highs[i - left], wmin = lows[i - left];
         for(int j = i - left + 1; j <= i + right; j++)
           {
            if(highs[j] > wmax) wmax = highs[j];
            if(lows[j] < wmin)  wmin = lows[j];
           }
         if(highs[i] == wmax)
           {
            out_high[nh++] = highs[i];
            out_sp[ns] = highs[i];
            out_sk[ns] = 1;
            ns++;
           }
         if(lows[i] == wmin)
           {
            out_low[nl++] = lows[i];
            out_sp[ns] = lows[i];
            out_sk[ns] = -1;
            ns++;
           }
        }
      ArrayResize(sw_high, nh);
      ArrayResize(sw_low, nl);
      ArrayResize(seq_price, ns);
      ArrayResize(seq_kind, ns);
      for(int i = 0; i < nh; i++) sw_high[i] = out_high[i];
      for(int i = 0; i < nl; i++) sw_low[i] = out_low[i];
      for(int i = 0; i < ns; i++)
        {
         seq_price[i] = out_sp[i];
         seq_kind[i] = out_sk[i];
        }
      return(ns);
     }

   // SMA ATR over the last `period` true ranges (Python indicators.atr — a
   // simple mean of the last period true ranges, NOT Wilder smoothing).
   double AtrSma(const double &highs[], const double &lows[], const double &closes[],
                 const int count, const int period)
     {
      if(count <= 0)
         return(0.0);
      double trs[];
      ArrayResize(trs, count);
      trs[0] = highs[0] - lows[0];
      double prev_close = closes[0];
      for(int i = 1; i < count; i++)
        {
         double tr = highs[i] - lows[i];
         double d1 = MathAbs(highs[i] - prev_close);
         double d2 = MathAbs(lows[i] - prev_close);
         if(d1 > tr) tr = d1;
         if(d2 > tr) tr = d2;
         trs[i] = tr;
         prev_close = closes[i];
        }
      int take = count < period ? count : period;
      double s = 0.0;
      for(int i = count - take; i < count; i++)
         s += trs[i];
      return(s / take);
     }

   // 3-bar fair-value gaps (Python detect_fvg): bullish when candle i's low
   // clears candle i-2's high AND i-1's body is up; bearish mirrored.  Later
   // gaps overwrite, so the result is the MOST RECENT gap per direction.
   void DetectFvg(const double &opens[], const double &highs[], const double &lows[],
                  const double &closes[], const int count,
                  bool &bull, bool &bear,
                  double &bull_bottom, double &bull_top,
                  double &bear_top, double &bear_bottom)
     {
      bull = bear = false;
      bull_bottom = bull_top = bear_top = bear_bottom = 0.0;
      for(int i = 2; i < count; i++)
        {
         double a_high = highs[i - 2];
         double a_low = lows[i - 2];
         double b_body = closes[i - 1] - opens[i - 1];
         if(lows[i] > a_high && b_body > 0.0)
           {
            bull = true;
            bull_bottom = a_high;
            bull_top = lows[i];
           }
         if(highs[i] < a_low && b_body < 0.0)
           {
            bear = true;
            bear_top = a_low;
            bear_bottom = highs[i];
           }
        }
     }

public:
   //--- Reproduce market_structure_features + structural_direction over the
   //--- last `count` closed bars (oldest-first arrays, count = window size).
   void Compute(const double &opens[], const double &highs[], const double &lows[],
                const double &closes[], const int count, StructureParityResult &out)
     {
      out.direction = 0;
      out.structure_bias = 0.0;
      out.displacement_atr = 0.0;
      out.bos_up = out.bos_down = out.internal_bos_up = out.internal_bos_down = 0;
      out.sweep_up = out.sweep_down = 0;
      out.fvg_up = out.fvg_down = out.fvg_active_up = out.fvg_active_down = 0;
      out.recent_high = out.recent_low = 0.0;
      if(count < 5)
        {
         if(count > 0)
           {
            out.recent_high = highs[count - 1];
            out.recent_low = lows[count - 1];
           }
         return;
        }
      double last_close = closes[count - 1];
      double last_high = highs[count - 1];
      double last_low = lows[count - 1];
      int prior = count - 1;                    // Python: candles[:-1]

      // swings over the PRIOR bars (the last/current bar can't form a swing)
      double median = MedianHighLow(highs, lows, prior);
      double sw_high[], sw_low[], seq_price[];
      int seq_kind[];
      DetectSwings(highs, lows, prior, 2, 2, median, sw_high, sw_low, seq_price, seq_kind);
      int nh = ArraySize(sw_high), nl = ArraySize(sw_low);

      // recent levels with Python's fallback (max/min of the last-20 prior bars)
      double recent_high, recent_low;
      if(nh > 0)
         recent_high = sw_high[nh - 1];
      else
        {
         int start = prior - 20;
         if(start < 0) start = 0;
         recent_high = highs[start];
         for(int i = start + 1; i < prior; i++)
            if(highs[i] > recent_high) recent_high = highs[i];
        }
      if(nl > 0)
         recent_low = sw_low[nl - 1];
      else
        {
         int start = prior - 20;
         if(start < 0) start = 0;
         recent_low = lows[start];
         for(int i = start + 1; i < prior; i++)
            if(lows[i] < recent_low) recent_low = lows[i];
        }
      out.recent_high = recent_high;
      out.recent_low = recent_low;

      double avg_range = AtrSma(highs, lows, closes, count, 14);
      out.displacement_atr = SafeDiv(MathAbs(last_close - opens[count - 1]), avg_range);

      out.bos_up = last_close > recent_high ? 1 : 0;
      out.bos_down = last_close < recent_low ? 1 : 0;
      out.sweep_up = (last_high > recent_high && last_close < recent_high) ? 1 : 0;
      out.sweep_down = (last_low < recent_low && last_close > recent_low) ? 1 : 0;

      bool f_bull, f_bear;
      double bb, bt, rt, rb;
      DetectFvg(opens, highs, lows, closes, count, f_bull, f_bear, bb, bt, rt, rb);
      out.fvg_up = f_bull ? 1 : 0;
      out.fvg_down = f_bear ? 1 : 0;
      out.fvg_active_up = (f_bull && last_close > bb) ? 1 : 0;
      out.fvg_active_down = (f_bear && last_close < rt) ? 1 : 0;

      // internal BOS: the LAST 4 swings (combined order), then per-polarity
      // the two most recent within that slice (Python swings[-4:] filter).
      int ns = ArraySize(seq_price);
      int h_count = 0, l_count = 0;
      double h_last = 0.0, h_prev = 0.0, l_last = 0.0, l_prev = 0.0;
      int start = ns - 4;
      if(start < 0) start = 0;
      for(int i = start; i < ns; i++)
        {
         if(seq_kind[i] > 0)
           {
            h_prev = h_last;
            h_last = seq_price[i];
            h_count++;
           }
         else
           {
            l_prev = l_last;
            l_last = seq_price[i];
            l_count++;
           }
        }
      out.internal_bos_up = (h_count >= 2 && h_last > h_prev) ? 1 : 0;
      out.internal_bos_down = (l_count >= 2 && l_last < l_prev) ? 1 : 0;

      // structure_bias: HH+HL / LH+LL from the last two swings per polarity,
      // else normalized ~20-bar momentum (Python's fallback).
      double sb = 0.0;
      bool higher_high = false, higher_low = false, lower_high = false, lower_low = false;
      if(nh >= 2)
        {
         higher_high = sw_high[nh - 1] > sw_high[nh - 2];
         lower_high = sw_high[nh - 1] < sw_high[nh - 2];
        }
      if(nl >= 2)
        {
         higher_low = sw_low[nl - 1] > sw_low[nl - 2];
         lower_low = sw_low[nl - 1] < sw_low[nl - 2];
        }
      if(higher_high && higher_low)
         sb = 0.7;
      else if(lower_high && lower_low)
         sb = -0.7;
      else if(count >= 10)
        {
         int nn = count < 20 ? count : 20;
         double close_n = closes[count - nn];
         double den = close_n > 1e-9 ? close_n : 1e-9;
         double price_change = (last_close - close_n) / den;
         double avg_rng = AtrSma(highs, lows, closes, count, count < 14 ? count : 14);
         if(avg_rng > 0.0)
            sb = Clamp(price_change / (avg_rng / den) * 0.5, -1.0, 1.0);
        }
      out.structure_bias = sb;

      // structural_direction score comparison
      double bull = out.bos_up
                  + 0.5 * out.internal_bos_up
                  + out.sweep_down
                  + out.fvg_up
                  + 0.5 * out.fvg_active_up
                  + (sb > 0.0 ? sb : 0.0);
      double bear = out.bos_down
                  + 0.5 * out.internal_bos_down
                  + out.sweep_up
                  + out.fvg_down
                  + 0.5 * out.fvg_active_down
                  + (sb < 0.0 ? -sb : 0.0);
      if(bull > bear)
         out.direction = 1;
      else if(bear > bull)
         out.direction = -1;
     }
  };

#endif // MITEMSHUB_PYTHONPARITY_STRUCTUREPARITY_MQH
