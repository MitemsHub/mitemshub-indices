//+------------------------------------------------------------------+
//|                                  Strategies/VolBurstFade.mqh     |
//|  MITEMSHUB AI — VOLATILITY MOMENTUM-BURST FADE (v26.17)          |
//|                                                                  |
//|  WHY: the validated CB-TICKFADE fades SPIKES — a Boom/Crash      |
//|  microstructure event (one huge gap tick) that Volatility indices|
//|  never produce (they tick in small constant-lambda steps). This  |
//|  module ports the fade *logic* (arm -> retrace window -> fire -> |
//|  confirm/release) to the Volatility analogue of a spike: a       |
//|  MOMENTUM BURST — a fast net displacement over the last N ticks. |
//|                                                                  |
//|  State machine (mirrors CrashBoomEngine::OnTickFade):            |
//|    IDLE    — watch velocity = bid - bid(look_ticks ago).         |
//|    PENDING — |velocity| >= vel_pts arms a burst: pre = price     |
//|              before the burst, peak = extreme (extends while the |
//|              burst runs). Fade fires when the retrace            |
//|              (peak->current)/range enters [retr_min, retr_max];  |
//|              expires on full retrace through pre, on timeout, or |
//|              when the retrace overshoots the window.             |
//|    Fired   — v26.13 protocol: the burst stays pending until the  |
//|              EA confirms the order (Confirm: consume + cooldown) |
//|              or releases it (Release: re-arm, fresh geometry).   |
//|                                                                  |
//|  Geometry mirrors the v26.15 fade family: SL/TP in ATR units,    |
//|  R:R gate, positions managed by the EA's standard trailing.      |
//|                                                                  |
//|  STATUS: EXPERIMENTAL. Every threshold is a guess until it is    |
//|  replayed against recorded Volatility 100 ticks (the same        |
//|  data-first pipeline the CB fade went through). The master input |
//|  InpVolBurstFade defaults OFF — the module cannot trade until a  |
//|  preset turns it on deliberately.                                |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_VOL_BURST_FADE_MQH
#define MITEMSHUB_VOL_BURST_FADE_MQH

#define VB_RING_SIZE 64

class CVolBurstFade
{
private:
   bool     m_enabled;

   //--- parameters (validated copies of the inputs)
   int      m_look_ticks;      // velocity lookback (ticks)
   double   m_vel_pts;         // net move (points) over lookback to arm a burst
   double   m_retr_min;        // min retrace fraction to fire
   double   m_retr_max;        // max retrace fraction (window closes beyond)
   int      m_timeout_sec;     // pending burst expiry
   double   m_sl_atr;          // stop distance in ATR units
   double   m_tp_atr;          // target in ATR units
   double   m_min_rr;          // R:R gate at signal time
   int      m_cooldown_sec;    // quiet period after a confirmed fire

   //--- tick ring
   double   m_ring[VB_RING_SIZE];
   int      m_head;
   int      m_count;

   //--- burst state: 0 = idle, 1 = pending fade
   int      m_state;
   int      m_burst_dir;       // +1 = up-burst (fade SELL), -1 = down-burst (fade BUY)
   double   m_pre;             // price before the burst
   double   m_peak;            // burst extreme (extends while it runs)
   datetime m_t0;              // burst arm time
   bool     m_fired;           // order in flight — confirm/release protocol
   datetime m_last_fire;       // cooldown anchor
   double   m_atr;             // entry-TF ATR fed by the EA per bar

public:
   CVolBurstFade()
   {
      m_enabled=false;
      m_look_ticks=8;  m_vel_pts=4.0;
      m_retr_min=0.30; m_retr_max=0.60;
      m_timeout_sec=600;
      m_sl_atr=0.3;    m_tp_atr=3.2;  m_min_rr=2.0;
      m_cooldown_sec=300;
      m_head=0; m_count=0;
      m_state=0; m_burst_dir=0;
      m_pre=0; m_peak=0; m_t0=0;
      m_fired=false; m_last_fire=0; m_atr=0;
   }

   void Init(const bool enabled, const int look, const double vel_pts,
             const double retr_min, const double retr_max,
             const int timeout_sec, const double sl_atr, const double tp_atr,
             const double min_rr, const int cooldown_sec)
   {
      m_enabled      = enabled;
      m_look_ticks   = MathMax(2, look);
      m_vel_pts      = MathMax(_Point, vel_pts);
      m_retr_min     = MathMax(0.05, MathMin(retr_min, 0.9));
      m_retr_max     = MathMax(m_retr_min + 0.05, MathMin(retr_max, 1.0));
      m_timeout_sec  = MathMax(60, timeout_sec);
      m_sl_atr       = MathMax(0.1, sl_atr);
      m_tp_atr       = MathMax(0.5, tp_atr);
      m_min_rr       = MathMax(0.5, min_rr);
      m_cooldown_sec = MathMax(0, cooldown_sec);
      m_head=0; m_count=0;
      m_state=0; m_burst_dir=0; m_pre=0; m_peak=0; m_t0=0;
      m_fired=false; m_last_fire=0; m_atr=0;
      if(m_enabled)
         PrintFormat("[VB-BURST] armed (EXPERIMENTAL): vel>=%.1fpts over %d ticks | window %.0f-%.0f%% | "
                     "SL=%.2fxATR TP=%.2fxATR minRR=%.1f | TO=%ds cooldown=%ds",
                     m_vel_pts, m_look_ticks, m_retr_min*100, m_retr_max*100,
                     m_sl_atr, m_tp_atr, m_min_rr, m_timeout_sec, m_cooldown_sec);
   }

   //--- the EA feeds the entry-TF ATR once per bar (same series as hATR_E)
   void SetATR(const double atr) { if(atr > 0) m_atr = atr; }
   bool Enabled()           const { return m_enabled; }
   string GetDashboard()    const
   {
      if(!m_enabled)              return "OFF";
      if(m_state == 0)            return "watching";
      return StringFormat("%s-burst %ds", (m_burst_dir > 0 ? "UP" : "DN"),
                          (int)(TimeCurrent() - m_t0));
   }

   //--- v26.13 protocol twin: EA reports the order was ACCEPTED — consume the
   //    burst (state cleared, cooldown anchored). Rejected/aborted → Release()
   //    so the pending burst can re-fire with fresh geometry.
   void Confirm()
   {
      m_state     = 0;
      m_fired     = false;
      m_last_fire = TimeCurrent();
   }
   void Release() { m_fired = false; }

   //--- per-tick driver. can_trade: caller's entry gates — the burst is always
   //    tracked, but only fires when the gates are open.
   //    Returns 1=BUY, -1=SELL, 0=nothing; fills entry/sl/tp/reason on fire.
   int OnTick(const double bid, double &entry, double &sl, double &tp,
              string &reason, const bool can_trade)
   {
      if(!m_enabled) return 0;

      //--- ring push (cheap: no time math needed for velocity, price only)
      m_ring[m_head] = bid;
      m_head = (m_head + 1) % VB_RING_SIZE;
      if(m_count < VB_RING_SIZE) m_count++;

      if(m_count < m_look_ticks + 1) return 0;   // warmup

      datetime now = TimeCurrent();

      //--- IDLE: detect a burst = net displacement over the lookback window
      if(m_state == 0)
      {
         int    iback = (m_head - 1 - m_look_ticks + 2*VB_RING_SIZE) % VB_RING_SIZE;
         double vel   = bid - m_ring[iback];
         if(MathAbs(vel) >= m_vel_pts && m_atr > 0)
         {
            if(m_cooldown_sec > 0 && m_last_fire > 0 &&
               (int)(now - m_last_fire) < m_cooldown_sec)
               return 0;   // cooling down — stay idle
            m_state     = 1;
            m_fired     = false;
            m_burst_dir = (vel > 0) ? 1 : -1;
            m_pre       = m_ring[iback];
            m_peak      = bid;
            m_t0        = now;
            PrintFormat("[VB-BURST] %s vel=%+.1fpts/%dticks",
                        (m_burst_dir > 0 ? "UP" : "DN"), vel, m_look_ticks);
         }
         return 0;
      }

      //--- PENDING: extend the peak while the burst runs, measure the retrace
      if(m_burst_dir > 0 && bid > m_peak) m_peak = bid;
      if(m_burst_dir < 0 && bid < m_peak) m_peak = bid;

      double range = MathAbs(m_peak - m_pre);
      if(range <= 0) { m_state = 0; return 0; }

      double retrace = (m_burst_dir > 0) ? (m_peak - bid) / range
                                         : (bid - m_peak) / range;
      int    age     = (int)(now - m_t0);

      // full retrace through the pre-burst price — fade window gone
      if((m_burst_dir > 0 && bid <= m_pre) || (m_burst_dir < 0 && bid >= m_pre))
      {
         PrintFormat("[VB-BURST-EXPIRE] full retrace after %ds", age);
         m_state = 0;
         return 0;
      }
      if(age > m_timeout_sec) { m_state = 0; return 0; }   // silent timeout
      if(m_fired)             return 0;                    // order in flight

      if(retrace < m_retr_min) return 0;                   // not deep enough yet
      if(retrace > m_retr_max)
      {
         PrintFormat("[VB-BURST-EXPIRE] retrace %.0f%% > %.0f%% max after %ds",
                     retrace*100, m_retr_max*100, age);
         m_state = 0;
         return 0;
      }

      if(!can_trade)      return 0;   // gates closed — keep tracking
      if(m_atr <= 0)      return 0;   // no geometry reference yet

      //--- geometry: fade the burst, SL/TP in ATR units (v26.15 fade family)
      entry   = bid;
      double stop_d = m_sl_atr * m_atr;
      double tp_d   = m_tp_atr * m_atr;

      if(m_burst_dir > 0)   // up-burst -> fade SELL
      {
         sl = entry + stop_d;
         tp = entry - tp_d;
         double rr = (entry - tp) / MathMax(sl - entry, _Point);
         if(rr < m_min_rr)
         {
            PrintFormat("[VB-SKIP] RR %.1f < %.1f", rr, m_min_rr);
            m_state = 0;
            return 0;
         }
         reason = StringFormat("VB-BURST-SELL vel=%.1fpts retrace=%.0f%% t=%ds",
                               range, retrace*100, age);
         PrintFormat("[VB-BURSTFADE] SELL retrace=%.0f%% t=%ds", retrace*100, age);
         m_fired = true;
         return -1;
      }
      else                  // down-burst -> fade BUY
      {
         sl = entry - stop_d;
         tp = entry + tp_d;
         double rr = (tp - entry) / MathMax(entry - sl, _Point);
         if(rr < m_min_rr)
         {
            PrintFormat("[VB-SKIP] RR %.1f < %.1f", rr, m_min_rr);
            m_state = 0;
            return 0;
         }
         reason = StringFormat("VB-BURST-BUY vel=%.1fpts retrace=%.0f%% t=%ds",
                               range, retrace*100, age);
         PrintFormat("[VB-BURSTFADE] BUY retrace=%.0f%% t=%ds", retrace*100, age);
         m_fired = true;
         return 1;
      }
   }
};
#endif // MITEMSHUB_VOL_BURST_FADE_MQH
