//+------------------------------------------------------------------+
//|                                    UI/VisualSignals.mqh          |
//|  MITEMSHUB AI MARKET ENGINE — Phase 9 VisualSignals.             |
//|                                                                  |
//|  Draws the trade/analysis trail on the chart: entry arrows, exit |
//|  markers, stop-loss / take-profit / breakeven-trail lines,       |
//|  structure points, liquidity levels and regime-change markers —  |
//|  each reason-coded by color (plan §23 / §34).                    |
//|                                                                  |
//|  Bounded by construction: markers live in a fixed ring of        |
//|  UI_MAX_MARKERS slots.  Adding beyond capacity EVICTS the oldest |
//|  slot; if the incoming marker type differs from the slot's       |
//|  current object type the old object is recreated (delete +       |
//|  one-time create), so the object count can never exceed          |
//|  UI_MAX_MARKERS + the panel overhead.  The object-count gate     |
//|  (Phase9Tests) asserts that bound directly.                      |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_UI_VISUALSIGNALS_MQH
#define MITEMSHUB_UI_VISUALSIGNALS_MQH

#include "../Core/Constants.mqh"
#include "Panel.mqh"

enum ENUM_MARKER_TYPE
  {
   MARKER_ENTRY_LONG    = 0,
   MARKER_ENTRY_SHORT,
   MARKER_EXIT,            // exit marker (filled at close)
   MARKER_STOP_LOSS,       // HLINE at the stop price
   MARKER_TAKE_PROFIT,     // HLINE at the target price
   MARKER_BREAKEVEN_TRAIL, // HLINE at the (moved) breakeven stop
   MARKER_STRUCTURE,       // swing high/low point
   MARKER_LIQUIDITY,       // liquidity level HLINE
   MARKER_REGIME_CHANGE    // VLINE at a regime transition
  };

struct SignalMarker
  {
   ENUM_MARKER_TYPE type;
   datetime         time;
   double           price;
   string           label;
  };

class CVisualSignals : public CUiPanel
  {
protected:
   SignalMarker m_ring[UI_MAX_MARKERS];
   int          m_head;     // next slot to fill
   int          m_slots;    // slots currently occupied

   ENUM_OBJECT MarkerObjectType(const ENUM_MARKER_TYPE type) const
     {
      switch(type)
        {
         case MARKER_STOP_LOSS:
         case MARKER_TAKE_PROFIT:
         case MARKER_BREAKEVEN_TRAIL:
         case MARKER_LIQUIDITY:
            return(OBJ_HLINE);
         case MARKER_REGIME_CHANGE:
            return(OBJ_VLINE);
         default:
            return(OBJ_ARROW);
        }
     }

   color MarkerColor(const ENUM_MARKER_TYPE type) const
     {
      switch(type)
        {
         case MARKER_ENTRY_LONG:     return(clrDodgerBlue);
         case MARKER_ENTRY_SHORT:    return(clrOrangeRed);
         case MARKER_EXIT:           return(clrGray);
         case MARKER_STOP_LOSS:      return(clrRed);
         case MARKER_TAKE_PROFIT:    return(clrGreen);
         case MARKER_BREAKEVEN_TRAIL:return(clrBlue);
         case MARKER_STRUCTURE:      return(clrCyan);
         case MARKER_LIQUIDITY:      return(clrYellow);
         case MARKER_REGIME_CHANGE:  return(clrMagenta);
         default:                    return(clrSilver);
        }
     }

   //--- render one slot's marker (create-once, update-after) ----------------
   void RenderSlot(const int slot)
     {
      SignalMarker m = m_ring[slot];      // MQL5: no local reference variables
      string name  = m_names[slot];       // the registered object name
      ENUM_OBJECT type = MarkerObjectType(m.type);

      // Type switch on slot reuse: delete and re-create so the object type
      // matches the marker.  Registry slot stays the same (bounded).
      if(CachedType(name) != (int)type)
        {
         if(m_created > 0)
            ObjectDelete(m_chart, name);
         bool ok = ObjectCreate(m_chart, name, type, 0, 0, 0);
         if(ok)
            m_created++;
         m_types[slot] = type;
        }

      SetInt(name, OBJPROP_COLOR, (long)MarkerColor(m.type));
      SetInt(name, OBJPROP_BACK, true);
      if(type == OBJ_HLINE)
        {
         SetDouble(name, OBJPROP_PRICE, m.price);
         SetInt(name, OBJPROP_STYLE, (long)STYLE_DASH);
        }
      else if(type == OBJ_VLINE)
        {
         // NOTE: this MT5 build exposes OBJPROP_TIME as an INTEGER property
         // (ObjectSetInteger), not a double — verified by probe compile.
         SetInt(name, OBJPROP_TIME, (long)m.time);
         SetInt(name, OBJPROP_STYLE, (long)STYLE_DOT);
        }
      else
        {
         SetInt(name, OBJPROP_TIME, (long)m.time);
         SetDouble(name, OBJPROP_PRICE, m.price);
         SetInt(name, OBJPROP_WIDTH, 2);
         if(m.type == MARKER_ENTRY_LONG || m.type == MARKER_EXIT)
           {
            SetInt(name, OBJPROP_ARROWCODE, 233);   // up arrow
            SetInt(name, OBJPROP_ANCHOR, ANCHOR_TOP);
           }
         else
           {
            SetInt(name, OBJPROP_ARROWCODE, 234);   // down arrow
            SetInt(name, OBJPROP_ANCHOR, ANCHOR_BOTTOM);
           }
        }
      SetText(name, m.label, MarkerColor(m.type), 8);
     }

public:
   CVisualSignals()
     {
      m_head  = 0;
      m_slots = 0;
     }

   void Init(const long chart, const string prefix)
     {
      CUiPanel::Init(chart, prefix);
     }

   int SlotsUsed() const { return(m_slots); }

   //--- add a marker (bounded ring; evicts the oldest beyond capacity) ------
   void Add(const ENUM_MARKER_TYPE type, const datetime time,
            const double price, const string label)
     {
      int slot = m_head;
      if(m_slots < UI_MAX_MARKERS)
         m_slots++;
      m_head = (m_head + 1) % UI_MAX_MARKERS;

      m_ring[slot].type  = type;
      m_ring[slot].time  = time;
      m_ring[slot].price = price;
      m_ring[slot].label = label;

      // One-time registration of the slot's object name (bounded ring).
      if(Slot("M" + IntegerToString(slot)) < 0)
         CreateObject("M" + IntegerToString(slot), MarkerObjectType(type));
      RenderSlot(slot);
     }

   //--- remove all markers (object count returns to the panel baseline) -----
   void ClearMarkers()
     {
      while(m_count > 0)
         Remove(m_names[0]);
      m_head  = 0;
      m_slots = 0;
     }

   //--- helper: draw a full trade anatomy in one call ------------------------
   void DrawTrade(const int direction, const datetime time, const double entry,
                  const double sl, const double tp, const double be_price)
     {
      Add(direction > 0 ? MARKER_ENTRY_LONG : MARKER_ENTRY_SHORT,
          time, entry, "entry");
      Add(MARKER_STOP_LOSS, time, sl, "SL");
      Add(MARKER_TAKE_PROFIT, time, tp, "TP");
      if(be_price > 0.0)
         Add(MARKER_BREAKEVEN_TRAIL, time, be_price, "BE");
     }
  };

#endif // MITEMSHUB_UI_VISUALSIGNALS_MQH
