//+------------------------------------------------------------------+
//|                                  CrashBoom/TickPatternAnalyzer.mqh|
//|  MITEMSHUB AI — TICK PATTERN ANALYZER for Crash/Boom            |
//|                                                                  |
//|  Monitors individual ticks for spike precursors:                 |
//|  1. Tick speed acceleration — sudden speedup before spike        |
//|  2. Tick direction clustering — many same-direction ticks        |
//|  3. Tick size anomaly — unusually large ticks                    |
//|  4. Pause detection — silence before explosion                   |
//|  5. Microstructure shift — change in tick distribution           |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_TICK_PATTERN_ANALYZER_MQH
#define MITEMSHUB_TICK_PATTERN_ANALYZER_MQH

#define TICK_RING_SIZE 500

class CTickPatternAnalyzer
{
private:
   //--- Tick ring buffer
   double   m_tick_prices[TICK_RING_SIZE];
   datetime m_tick_times[TICK_RING_SIZE];
   int      m_tick_head;
   int      m_tick_count;
   
   //--- Tick speed tracking ( finer grain than SpikeDetector)
   double   m_speed_window[60];      // ticks per second over 60 windows
   int      m_speed_head;
   int      m_speed_count;
   double   m_current_speed;
   double   m_avg_speed;
   double   m_max_speed;
   
   //--- Direction clustering
   int      m_dir_up_count;          // consecutive up ticks
   int      m_dir_dn_count;          // consecutive down ticks
   int      m_max_cluster;           // longest cluster seen
   double   m_cluster_ratio;         // current cluster / average cluster
   
   //--- Tick size anomaly
   double   m_tick_sizes[TICK_RING_SIZE];
   double   m_tick_size_ema;
   double   m_anomaly_ratio;         // current tick size / avg
   
   //--- Pause detection
   datetime m_last_tick_time;
   double   m_pause_duration;        // seconds since last tick
   bool     m_pause_detected;        // true if pause > threshold
   
   //--- Microstructure
   double   m_bid_ask_ratio;         // up ticks / total ticks in window
   double   m_volatility_ratio;      // recent vol / historical vol
   double   m_entropy;               // tick direction randomness
   
   //--- Spike precursor score
   double   m_precursor_score;       // combined 0-1 score
   
   //--- Time tracking
   datetime m_last_window_time;
   int      m_ticks_in_window;

public:
   CTickPatternAnalyzer()
   {
      m_tick_head = 0;
      m_tick_count = 0;
      m_speed_head = 0;
      m_speed_count = 0;
      m_current_speed = 0;
      m_avg_speed = 0;
      m_max_speed = 0;
      m_dir_up_count = 0;
      m_dir_dn_count = 0;
      m_max_cluster = 0;
      m_cluster_ratio = 0;
      m_tick_size_ema = 0;
      m_anomaly_ratio = 0;
      m_last_tick_time = 0;
      m_pause_duration = 0;
      m_pause_detected = false;
      m_bid_ask_ratio = 0.5;
      m_volatility_ratio = 1.0;
      m_entropy = 1.0;
      m_precursor_score = 0;
      m_last_window_time = 0;
      m_ticks_in_window = 0;
      
      ArrayInitialize(m_tick_prices, 0);
      ArrayInitialize(m_tick_times, 0);
      ArrayInitialize(m_tick_sizes, 0);
      ArrayInitialize(m_speed_window, 0);
   }

   //--- Call on EVERY tick with bid/ask
   void OnTick(double bid, double ask)
   {
      datetime now = TimeCurrent();
      double mid = (bid + ask) / 2.0;
      
      //--- Store in ring buffer
      m_tick_prices[m_tick_head] = mid;
      m_tick_times[m_tick_head] = now;
      m_tick_head = (m_tick_head + 1) % TICK_RING_SIZE;
      if(m_tick_count < TICK_RING_SIZE) m_tick_count++;
      
      //--- Calculate tick size (change from previous tick)
      if(m_tick_count > 1)
      {
         int prev = (m_tick_head - 2 + TICK_RING_SIZE) % TICK_RING_SIZE;
         double tick_size = MathAbs(mid - m_tick_prices[prev]);
         m_tick_sizes[m_tick_head] = tick_size;
         
         // Update tick size EMA
         if(m_tick_size_ema <= 0)
            m_tick_size_ema = tick_size;
         else
            m_tick_size_ema = 0.1 * tick_size + 0.9 * m_tick_size_ema;
         
         // Anomaly ratio
         m_anomaly_ratio = (m_tick_size_ema > 0) ? tick_size / m_tick_size_ema : 1.0;
      }
      
      //--- Tick speed (ticks per second)
      if(m_last_tick_time > 0)
      {
         double dt = (double)(now - m_last_tick_time);
         if(dt > 0 && dt < 5)  // ignore gaps > 5 sec
         {
            double speed = 1.0 / dt;
            m_current_speed = 0.3 * speed + 0.7 * m_current_speed;
            
            // Store speed window
            m_speed_window[m_speed_head] = m_current_speed;
            m_speed_head = (m_speed_head + 1) % 60;
            if(m_speed_count < 60) m_speed_count++;
         }
      }
      m_last_tick_time = now;
      
      //--- Direction clustering
      if(m_tick_count > 1)
      {
         int prev = (m_tick_head - 2 + TICK_RING_SIZE) % TICK_RING_SIZE;
         int dir = (mid > m_tick_prices[prev]) ? 1 : -1;
         
         if(dir > 0)
         {
            m_dir_up_count++;
            m_dir_dn_count = 0;
         }
         else
         {
            m_dir_dn_count++;
            m_dir_up_count = 0;
         }
         
         int current_cluster = MathMax(m_dir_up_count, m_dir_dn_count);
         if(current_cluster > m_max_cluster)
            m_max_cluster = current_cluster;
      }
      
      //--- Pause detection
      m_pause_duration = (double)(now - m_last_tick_time);
      m_pause_detected = (m_pause_duration > 2.0);  // >2 sec gap = pause
      
      //--- Update every 100 ticks
      if(m_tick_count % 100 == 0)
         UpdateMicrostructure();
      
      //--- Calculate precursor score
      CalculatePrecursorScore();
   }

private:
   //--- Update microstructure metrics
   void UpdateMicrostructure()
   {
      if(m_tick_count < 50) return;
      
      //--- Bid/ask ratio (directional pressure)
      int up_count = 0;
      int total = MathMin(100, m_tick_count);
      for(int i = 0; i < total; i++)
      {
         int idx = (m_tick_head - 1 - i + TICK_RING_SIZE) % TICK_RING_SIZE;
         int prev = (idx - 1 + TICK_RING_SIZE) % TICK_RING_SIZE;
         if(m_tick_prices[idx] > m_tick_prices[prev]) up_count++;
      }
      m_bid_ask_ratio = (double)up_count / total;
      
      //--- Volatility ratio (recent vs historical)
      double recent_vol = 0;
      double hist_vol = 0;
      int n = MathMin(50, m_tick_count - 1);
      for(int i = 0; i < n; i++)
      {
         int idx = (m_tick_head - 1 - i + TICK_RING_SIZE) % TICK_RING_SIZE;
         int prev = (idx - 1 + TICK_RING_SIZE) % TICK_RING_SIZE;
         double change = m_tick_prices[idx] - m_tick_prices[prev];
         
         if(i < 20)
            recent_vol += change * change;
         hist_vol += change * change;
      }
      recent_vol = MathSqrt(recent_vol / 20);
      hist_vol = MathSqrt(hist_vol / n);
      m_volatility_ratio = (hist_vol > 0) ? recent_vol / hist_vol : 1.0;
      
      //--- Entropy (randomness of tick directions)
      double p_up = m_bid_ask_ratio;
      double p_dn = 1.0 - p_up;
      m_entropy = 0;
      if(p_up > 0 && p_up < 1)
         m_entropy = -(p_up * MathLog(p_up) + p_dn * MathLog(p_dn)) / MathLog(2);
      // Entropy ranges 0 (all same direction) to 1 (50/50 random)
   }

   //--- Calculate combined precursor score
   void CalculatePrecursorScore()
   {
      double score = 0;
      
      //--- Component 1: Speed acceleration (0-1)
      //    Sudden speed increase = precursor
      if(m_speed_count >= 10)
      {
         double recent_speed = 0;
         for(int i = 0; i < 10; i++)
            recent_speed += m_speed_window[(m_speed_head - 1 - i + 60) % 60];
         recent_speed /= 10;
         
         double old_speed = 0;
         for(int i = 10; i < 20; i++)
            old_speed += m_speed_window[(m_speed_head - 1 - i + 60) % 60];
         old_speed /= 10;
         
         double speed_ratio = (old_speed > 0) ? recent_speed / old_speed : 1.0;
         double speed_score = MathMin(1.0, MathMax(0, (speed_ratio - 1.0) * 2));
         score += speed_score * 0.25;
      }
      
      //--- Component 2: Direction clustering (0-1)
      //    Long clusters = grind = spike coming
      int max_dir = MathMax(m_dir_up_count, m_dir_dn_count);
      double cluster_score = MathMin(1.0, (double)max_dir / 30.0);
      score += cluster_score * 0.25;
      
      //--- Component 3: Tick size anomaly (0-1)
      //    Unusually large ticks = precursor
      double anomaly_score = MathMin(1.0, MathMax(0, (m_anomaly_ratio - 1.0) / 3.0));
      score += anomaly_score * 0.20;
      
      //--- Component 4: Pause detection (0 or 1)
      //    Silence before explosion
      double pause_score = m_pause_detected ? 0.8 : 0;
      score += pause_score * 0.15;
      
      //--- Component 5: Low entropy (0-1)
      //    Low entropy = directional = grind
      double entropy_score = 1.0 - m_entropy;
      score += entropy_score * 0.15;
      
      m_precursor_score = MathMin(1.0, MathMax(0, score));
   }

public:
   //--- Get spike precursor score (0.0 to 1.0)
   double GetPrecursorScore() const { return m_precursor_score; }
   
   //--- Get individual components (for dashboard)
   double GetCurrentSpeed()     const { return m_current_speed; }
   double GetAvgSpeed()         const { return m_avg_speed; }
   int    GetDirectionCluster() const { return MathMax(m_dir_up_count, m_dir_dn_count); }
   double GetAnomalyRatio()     const { return m_anomaly_ratio; }
   bool   IsPauseDetected()     const { return m_pause_detected; }
   double GetBidAskRatio()      const { return m_bid_ask_ratio; }
   double GetVolatilityRatio()  const { return m_volatility_ratio; }
   double GetEntropy()          const { return m_entropy; }
   int    GetTickCount()        const { return m_tick_count; }
   
   //--- Reset
   void Reset()
   {
      m_tick_head = 0;
      m_tick_count = 0;
      m_speed_head = 0;
      m_speed_count = 0;
      m_current_speed = 0;
      m_dir_up_count = 0;
      m_dir_dn_count = 0;
      m_max_cluster = 0;
      m_tick_size_ema = 0;
      m_last_tick_time = 0;
      m_precursor_score = 0;
      ArrayInitialize(m_tick_prices, 0);
      ArrayInitialize(m_tick_times, 0);
      ArrayInitialize(m_tick_sizes, 0);
      ArrayInitialize(m_speed_window, 0);
   }
};

#endif
