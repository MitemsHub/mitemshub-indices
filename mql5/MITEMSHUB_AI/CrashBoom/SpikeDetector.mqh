//+------------------------------------------------------------------+
//|                                       CrashBoom/SpikeDetector.mqh|
//|  MITEMSHUB AI — SPIKE DETECTOR for Crash/Boom indices           |
//|                                                                  |
//|  Monitors:                                                       |
//|  1. Tick speed (ticks per second) — spikes often preceded by     |
//|     tick speed changes                                           |
//|  2. Candle body size relative to rolling average — grind candles  |
//|     are small, spike candles are huge                            |
//|  3. Consecutive candle direction — long grind = many same-dir    |
//|     candles = spike likely coming                                |
//|  4. Time since last spike — longer gap = higher probability      |
//|                                                                  |
//|  Outputs:                                                        |
//|  - spike_probability (0.0 - 1.0)                                |
//|  - spike_just_happened (bool, within last N bars)                |
//|  - grind_direction (1=UP grind, -1=DOWN grind, 0=none)          |
//|  - grind_duration (bars since direction change)                  |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_SPIKE_DETECTOR_MQH
#define MITEMSHUB_SPIKE_DETECTOR_MQH

#define SPIKE_HISTORY 100  // ring buffer size for tick/candle tracking

class CSpikeDetector
{
private:
   //--- Tick speed tracking
   datetime m_last_tick_time;
   int      m_tick_count;
   double   m_ticks_per_sec;          // current tick speed
   double   m_ticks_per_sec_ema;      // smoothed tick speed
   double   m_tick_speed_history[SPIKE_HISTORY];
   int      m_tick_head, m_tick_count_buf;
   
   //--- Candle body tracking
   double   m_body_history[SPIKE_HISTORY];    // absolute body sizes
   double   m_body_ema;                        // average body size
   int      m_body_head, m_body_count;
   
   //--- Spike detection state
   datetime m_last_spike_time;        // when last spike occurred
   int      m_last_spike_bar;         // bar index of last spike
   double   m_spike_threshold;        // body size = this x average = spike
   double   m_last_spike_ratio;       // v25.3: spike body / body EMA at detection (micro-fade risk input)
   double   m_lambda_per_bar;         // v26.9: learned constant spike rate (spikes/bar, EWMA)
   int      m_spike_gap_n;            // v26.9: observed inter-spike bar gaps counted
   int      m_spike_gap_bar;          // v26.9: bars since the last spike (gap accumulator)
   int      m_bar_sec;                // v26.9: seconds per bar of the λ feed (gap→sec conversion)
   
   //--- Grind detection
   int      m_grind_direction;        // 1=UP, -1=DOWN, 0=none
   int      m_grind_duration;         // bars in current grind
   double   m_grind_body_avg;         // avg body during grind
   
   //--- Spike probability components
   double   m_prob_body_ratio;        // how big is current body vs avg
   double   m_prob_tick_change;       // tick speed change factor
   double   m_prob_grind_length;      // grind duration factor
   double   m_prob_time_since_spike;  // v26.9: constant-λ Poisson hazard term (replaces the bars-since-spike "overdue" heuristic)
   double   m_min_gap_obs;            // v26.9: shortest observed inter-spike gap (bars, refractory tail)

   double   EMA_update(double current, double prev_ema, double alpha)
   {
      return alpha * current + (1.0 - alpha) * prev_ema;
   }

public:
   CSpikeDetector()
   {
      m_last_tick_time = 0;
      m_tick_count = 0;
      m_ticks_per_sec = 0;
      m_ticks_per_sec_ema = 0;
      m_tick_head = 0;
      m_tick_count_buf = 0;
      
      ArrayInitialize(m_body_history, 0);
      ArrayInitialize(m_tick_speed_history, 0);
      m_body_ema = 0;
      m_body_head = 0;
      m_body_count = 0;
      
      m_last_spike_time = 0;
      m_last_spike_bar = 0;
      m_spike_threshold = 3.0;  // default: 3x average body = spike
      m_last_spike_ratio = 0;
      m_lambda_per_bar   = 0;
      m_prob_time_since_spike = 0;
      m_min_gap_obs      = 0;
      m_spike_gap_n      = 0;
      m_spike_gap_bar    = 0;
      m_min_gap_obs      = 0;
      m_bar_sec          = 0;
      
      m_grind_direction = 0;
      m_grind_duration = 0;
      m_grind_body_avg = 0;
      
      m_prob_body_ratio = 0;
      m_prob_tick_change = 0;
      m_prob_grind_length = 0;
      m_prob_time_since_spike = 0;
   }

   //--- Call on every tick
   void OnTick()
   {
      datetime now = TimeCurrent();
      if(m_last_tick_time > 0)
      {
         double dt = (double)(now - m_last_tick_time);
         if(dt > 0 && dt < 10)  // ignore gaps > 10 sec
         {
            m_ticks_per_sec = EMA_update(1.0/dt, m_ticks_per_sec_ema, 0.3);
            m_ticks_per_sec_ema = m_ticks_per_sec;
            
            // Store in ring buffer
            m_tick_speed_history[m_tick_head] = m_ticks_per_sec;
            m_tick_head = (m_tick_head + 1) % SPIKE_HISTORY;
            if(m_tick_count_buf < SPIKE_HISTORY) m_tick_count_buf++;
         }
      }
      m_last_tick_time = now;
      m_tick_count++;
   }

   //--- Call on every closed bar
   //    spike_body_threshold: multiplier over avg body to count as spike
   //    spike_lookback: how many bars back to check for spike
   void OnBar(const ENUM_TIMEFRAMES tf, int lookback_bars, double spike_body_threshold)
   {
      m_spike_threshold = spike_body_threshold;
      m_bar_sec         = PeriodSeconds(tf);   // v26.9: λ bar length for gap→sec conversion
      
      //--- Age the last spike bar (so SpikeJustHappened tracks bars-ago correctly)
      //--- v26.9: also accumulate the inter-spike gap (in bars) for the
      //    constant-λ spike-rate learning below. The 15.19M-tick deriv study
      //    (EA_UPGRADE_RESEARCH.md) shows spike arrivals are Poisson — the
      //    hazard is flat in elapsed time, so "overdue" is a fallacy. We keep
      //    the elapsed gap only for the refractory tail, then the model
      //    saturates at the learned constant rate.
      if(m_last_spike_bar > 0) m_last_spike_bar++;
      if(m_last_spike_bar > 0) m_spike_gap_bar++;
      
      //--- Update body history
      double body = MathAbs(iClose(_Symbol, tf, 1) - iOpen(_Symbol, tf, 1));
      m_body_history[m_body_head] = body;
      m_body_head = (m_body_head + 1) % SPIKE_HISTORY;
      if(m_body_count < SPIKE_HISTORY) m_body_count++;
      
      //--- Recalculate body EMA (robust: exclude outlier spikes > 2x current EMA)
      //    This prevents spikes from inflating the average and making future
      //    spikes harder to detect. Critical for catching smaller spikes (5-20 pts)
      //    that represent 34% of all Boom 1000 spike events.
      if(m_body_count >= 10)
      {
         double sum = 0;
         int n = MathMin(m_body_count, 50);
         int included = 0;
         for(int i = 0; i < n; i++)
         {
            double bar_body = m_body_history[(m_body_head - 1 - i + SPIKE_HISTORY) % SPIKE_HISTORY];
            // Exclude bars that are > 2x current EMA (these are spikes, not grind)
            if(m_body_ema <= 0 || bar_body <= m_body_ema * 2.0)
            {
               sum += bar_body;
               included++;
            }
         }
         if(included >= 5)  // need at least 5 non-spike bars
            m_body_ema = sum / included;
         else
         {
            // Fallback: use all bars if not enough non-spike bars
            double full_sum = 0;
            for(int i = 0; i < n; i++)
               full_sum += m_body_history[(m_body_head - 1 - i + SPIKE_HISTORY) % SPIKE_HISTORY];
            m_body_ema = full_sum / n;
         }
      }
      
      //--- Detect spike on the bar that just closed (index 1)
      bool spike_detected = false;
      if(m_body_ema > 0 && body >= m_body_ema * m_spike_threshold)
      {
         spike_detected = true;
         m_last_spike_time = iTime(_Symbol, tf, 1);
         m_last_spike_bar = 1;  // reset to 1 (this bar)
         m_last_spike_ratio = body / m_body_ema;  // v25.3: for micro-fade risk scaling
         
         //--- v26.9: constant-λ spike-rate learning — the observed inter-spike
         //    gap closes here; EWMA of 1/gap estimates the spike rate λ.
         if(m_spike_gap_bar > 0)
         {
            double gap = (double)m_spike_gap_bar;
            m_lambda_per_bar = (m_spike_gap_n == 0) ? (1.0 / gap)
                             : EMA_update(1.0 / gap, m_lambda_per_bar, 0.05);
            m_spike_gap_n++;
            if(m_min_gap_obs <= 0 || gap < m_min_gap_obs) m_min_gap_obs = gap;
         }
         m_spike_gap_bar = 0;
      }
      
      //--- Update grind detection (look at last N bars)
      UpdateGrind(tf, lookback_bars);
      
      //--- Update probability components
      UpdateProbabilities(tf, lookback_bars, spike_detected);
   }

   //--- Detect spike on the FORMING bar (real-time, for M5 or tick-based)
   //    Returns true if the current bar is shaping up to be a spike
   bool DetectLiveSpike(const ENUM_TIMEFRAMES tf, double spike_body_threshold)
   {
      if(m_body_ema <= 0) return false;
      
      double body = MathAbs(iClose(_Symbol, tf, 0) - iOpen(_Symbol, tf, 0));
      return (body >= m_body_ema * spike_body_threshold * 0.7);  // 70% threshold = early warning
   }

private:
   //--- Update grind direction and duration
   void UpdateGrind(const ENUM_TIMEFRAMES tf, int lookback)
   {
      if(Bars(_Symbol, tf) < lookback + 5) return;
      
      // Count consecutive same-direction bars starting from bar 1
      int direction = 0;
      int duration = 0;
      double body_sum = 0;
      
      for(int i = 1; i <= lookback; i++)
      {
         double close0 = iClose(_Symbol, tf, i);
         double open0  = iOpen(_Symbol, tf, i);
         double bar_body = close0 - open0;  // positive = UP, negative = DOWN
         
         int bar_dir = (bar_body > 0) ? 1 : -1;
         
         if(duration == 0)
         {
            direction = bar_dir;
            duration = 1;
         }
         else if(bar_dir == direction)
         {
            duration++;
         }
         else
         {
            break;  // grind broken
         }
         
         body_sum += MathAbs(bar_body);
      }
      
      m_grind_direction = (duration >= 3) ? direction : 0;  // min 3 bars = grind
      m_grind_duration = duration;
      m_grind_body_avg = (duration > 0) ? body_sum / duration : 0;
   }

   //--- Update probability components
   void UpdateProbabilities(const ENUM_TIMEFRAMES tf, int lookback, bool spike_just_happened)
   {
      //--- Component 1: Body ratio (current body vs average)
      //    Higher ratio = more exhaustion = more likely to spike
      if(m_body_ema > 0 && m_body_count > 10)
      {
         double recent_avg = 0;
         int n = MathMin(5, m_body_count);
         for(int i = 0; i < n; i++)
            recent_avg += m_body_history[(m_body_head - 1 - i + SPIKE_HISTORY) % SPIKE_HISTORY];
         recent_avg /= n;
         
         // During grind, bodies are SMALL (below average)
         // When they start shrinking further, spike is near
         m_prob_body_ratio = (m_body_ema > 0) ? recent_avg / m_body_ema : 1.0;
         m_prob_body_ratio = MathMax(0, MathMin(1, 1.0 - m_prob_body_ratio));  // normalize
      }
      
      //--- Component 2: Tick speed change
      //    Sudden tick speed increase often precedes spikes
      if(m_tick_count_buf > 20)
      {
         double recent_speed = 0;
         for(int i = 0; i < 10; i++)
            recent_speed += m_tick_speed_history[(m_tick_head - 1 - i + SPIKE_HISTORY) % SPIKE_HISTORY];
         recent_speed /= 10;
         
         double old_speed = 0;
         for(int i = 10; i < 20; i++)
            old_speed += m_tick_speed_history[(m_tick_head - 1 - i + SPIKE_HISTORY) % SPIKE_HISTORY];
         old_speed /= 10;
         
         m_prob_tick_change = (old_speed > 0) ? MathMin(1.0, recent_speed / old_speed - 1.0) : 0;
         m_prob_tick_change = MathMax(0, MathMin(1, m_prob_tick_change));
      }
      
      //--- Component 3: Grind length
      //    Longer grind = higher spike probability
      //    Empirical: >10 bars grind = moderate risk, >20 = high risk
      m_prob_grind_length = MathMin(1.0, (double)m_grind_duration / 25.0);
      
      //--- Component 4: v26.9 CONSTANT-λ POISSON HAZARD (was "time since spike")
      //    Old model: longer gap → higher "overdue" score (gambler's fallacy —
      //    a memoryless process never becomes overdue). New model: P(spike in
      //    the next bar) is constant at λ once past the refractory tail, so
      //    the component reports the LEARNED RATE itself, not elapsed time.
      if(m_lambda_per_bar > 0 && m_spike_gap_n >= 3)
      {
         // refractory tail: hazard ramps 0→λ over the first few bars after a
         // spike (empirically the shortest observed gaps set the tail length),
         // then stays flat at λ forever — no overdue term.
         double tail_bars = MathMax(2.0, m_min_gap_obs);
         m_prob_time_since_spike = (m_spike_gap_bar < tail_bars)
            ? m_lambda_per_bar * ((double)m_spike_gap_bar / tail_bars)
            : m_lambda_per_bar;
         m_prob_time_since_spike = MathMin(1.0, m_prob_time_since_spike);
      }
      else
      {
         m_prob_time_since_spike = m_lambda_per_bar > 0 ? m_lambda_per_bar : 0.05;
      }
   }

public:
   //--- Set spike detection threshold (body size multiplier)
   void SetSpikeThreshold(double threshold) { m_spike_threshold = threshold; }
   double GetSpikeThreshold() const { return m_spike_threshold; }
   
   //--- v25.3: spike body ratio at last detection (0 = none since reset)
   double GetLastSpikeBodyRatio() const { return m_last_spike_ratio; }
   
   //--- v26.9: expose the learned λ (spikes/bar) + mean inter-spike gap
   double GetLambdaPerBar() const { return m_lambda_per_bar; }
   double GetMeanGapBars()  const { return m_lambda_per_bar > 0 ? 1.0 / m_lambda_per_bar : 0; }
   int    GetSpikeGapCount() const { return m_spike_gap_n; }
   //--- v26.9: mean inter-spike gap in SECONDS (needs the bar length; 0 until learned)
   double GetMeanGapSec()   const { return (m_bar_sec > 0 && m_lambda_per_bar > 0) ? (1.0 / m_lambda_per_bar) * m_bar_sec : 0; }

   //--- Get combined spike probability (0.0 to 1.0)
   //    v26.9 weights: body_ratio 35%, tick_change 25%, grind_length 25%,
   //    constant-λ hazard 15% (the old 25% "time-since-spike" weight was
   //    cut because the term no longer grows with elapsed time — it now
   //    reflects the learned constant rate only, avoiding spurious
   //    probability inflation on long gaps that misled the live gates on
   //    2026-08-30, e.g. prob=0.26 printed on a 29.6-min-old spike).
   double GetSpikeProbability() const
   {
      double prob = m_prob_body_ratio    * 0.35
                  + m_prob_tick_change   * 0.25
                  + m_prob_grind_length  * 0.25
                  + m_prob_time_since_spike * 0.15;
      return MathMax(0, MathMin(1, prob));
   }
   
   //--- Did a spike just happen? (within last N bars)
   bool SpikeJustHappened(int max_bars_ago) const
   {
      if(m_last_spike_bar <= 0) return false;
      return (m_last_spike_bar <= max_bars_ago);
   }
   
   //--- Get grind state
   int  GetGrindDirection()  const { return m_grind_direction; }
   int  GetGrindDuration()   const { return m_grind_duration; }
   double GetGrindBodyAvg()  const { return m_grind_body_avg; }
   
   //--- Get tick speed
   double GetTicksPerSec()     const { return m_ticks_per_sec; }
   double GetBodyEma()         const { return m_body_ema; }
   
   //--- Get individual probability components (for dashboard)
   double ProbBodyRatio()      const { return m_prob_body_ratio; }
   double ProbTickChange()     const { return m_prob_tick_change; }
   double ProbGrindLength()    const { return m_prob_grind_length; }
   double ProbTimeSinceSpike() const { return m_prob_time_since_spike; }
   
   //--- Reset state (new symbol or new session)
   void Reset()
   {
   m_last_spike_time = 0;
   m_last_spike_bar = 0;
   m_last_spike_ratio = 0;
   m_lambda_per_bar = 0;
   m_spike_gap_n = 0;
   m_spike_gap_bar = 0;
   m_min_gap_obs = 0;
   m_grind_direction = 0;
      m_grind_duration = 0;
      m_tick_count = 0;
      m_ticks_per_sec = 0;
      m_ticks_per_sec_ema = 0;
      m_tick_head = 0;
      m_tick_count_buf = 0;
      m_body_head = 0;
      m_body_count = 0;
      m_body_ema = 0;
      ArrayInitialize(m_body_history, 0);
      ArrayInitialize(m_tick_speed_history, 0);
      m_prob_body_ratio = 0;
      m_prob_tick_change = 0;
      m_prob_grind_length = 0;
      m_prob_time_since_spike = 0;
   }
};

#endif

