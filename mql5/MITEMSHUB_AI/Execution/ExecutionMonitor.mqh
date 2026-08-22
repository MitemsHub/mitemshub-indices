//+------------------------------------------------------------------+
//|                                    Execution/ExecutionMonitor.mqh |
//|  MITEMSHUB AI MARKET ENGINE — Phase 7 ExecutionMonitor.          |
//|                                                                  |
//|  Turns a raw MT5 retcode into an actionable failure class        |
//|  (plan §15: rejection, invalid stops, volume errors, market      |
//|  closed, requotes, trade context, connection, insufficient       |
//|  margin, symbol restrictions) and decides the recovery policy:   |
//|  some failures are transient (retry/backoff), some are permanent |
//|  (fix the request), some are account-level (wait for the broker).|
//|  Every attempt lands in the journal via the OrderResult trail.   |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_EXECUTION_EXECUTIONMONITOR_MQH
#define MITEMSHUB_EXECUTION_EXECUTIONMONITOR_MQH

#include "../Core/Constants.mqh"
#include "OrderManager.mqh"

class CExecutionMonitor
  {
public:
   //--- Classify a retcode into a failure class ------------------------------
   static ENUM_EXEC_FAILURE Classify(const ulong retcode)
     {
      switch((uint)retcode)
        {
         case TRADE_RETCODE_DONE:              return(EXEC_FAILURE_NONE);
         case TRADE_RETCODE_REQUOTE:           return(EXEC_FAILURE_REQUOTE);
         case TRADE_RETCODE_REJECT:
         case TRADE_RETCODE_CANCEL:            return(EXEC_FAILURE_REJECT);
         case TRADE_RETCODE_INVALID_VOLUME:    return(EXEC_FAILURE_INVALID_VOLUME);
         case TRADE_RETCODE_INVALID_PRICE:     return(EXEC_FAILURE_INVALID_PRICE);
         case TRADE_RETCODE_INVALID_STOPS:     return(EXEC_FAILURE_INVALID_STOPS);
         case TRADE_RETCODE_TRADE_DISABLED:    return(EXEC_FAILURE_TRADE_DISABLED);
         case TRADE_RETCODE_MARKET_CLOSED:     return(EXEC_FAILURE_MARKET_CLOSED);
         case TRADE_RETCODE_NO_MONEY:
         case TRADE_RETCODE_PRICE_CHANGED:
         case TRADE_RETCODE_PRICE_OFF:         return(EXEC_FAILURE_MARGIN);
         case TRADE_RETCODE_SERVER_DISABLES_AT:
         case TRADE_RETCODE_CLIENT_DISABLES_AT:return(EXEC_FAILURE_AT_DISABLED);
         case TRADE_RETCODE_LOCKED:
         case TRADE_RETCODE_FROZEN:            return(EXEC_FAILURE_LOCKED);
         case TRADE_RETCODE_LIMIT_ORDERS:
         case TRADE_RETCODE_LIMIT_VOLUME:
         case TRADE_RETCODE_INVALID_ORDER:     return(EXEC_FAILURE_LIMIT);
         case TRADE_RETCODE_CONNECTION:        return(EXEC_FAILURE_CONNECTION);
         default:                              return(EXEC_FAILURE_UNKNOWN);
        }
     }

   static string ClassifyName(const ENUM_EXEC_FAILURE f)
     {
      switch(f)
        {
         case EXEC_FAILURE_NONE:            return("NONE");
         case EXEC_FAILURE_REQUOTE:         return("REQUOTE");
         case EXEC_FAILURE_REJECT:          return("REJECT");
         case EXEC_FAILURE_INVALID_VOLUME:  return("INVALID_VOLUME");
         case EXEC_FAILURE_INVALID_PRICE:   return("INVALID_PRICE");
         case EXEC_FAILURE_INVALID_STOPS:   return("INVALID_STOPS");
         case EXEC_FAILURE_TRADE_DISABLED:  return("TRADE_DISABLED");
         case EXEC_FAILURE_MARKET_CLOSED:   return("MARKET_CLOSED");
         case EXEC_FAILURE_MARGIN:          return("MARGIN");
         case EXEC_FAILURE_AT_DISABLED:     return("AT_DISABLED");
         case EXEC_FAILURE_LOCKED:          return("LOCKED");
         case EXEC_FAILURE_LIMIT:           return("LIMIT");
         case EXEC_FAILURE_CONNECTION:      return("CONNECTION");
         default:                           return("UNKNOWN");
        }
     }

   //--- Recovery policy --------------------------------------------------------
   // Transient failures: the request is fine but the environment is not —
   // back off and retry (AT block, margin, connection, requote).  Permanent
   // failures (invalid volume/stops/price) mean a bug in the request path
   // and must NOT be retried blindly.
   static bool ShouldBackOff(const ENUM_EXEC_FAILURE f)
     {
      return(f == EXEC_FAILURE_AT_DISABLED
             || f == EXEC_FAILURE_MARGIN
             || f == EXEC_FAILURE_CONNECTION
             || f == EXEC_FAILURE_REQUOTE);
     }

   //--- Journal helpers --------------------------------------------------------
   static string Describe(const OrderResult &res)
     {
      return(StringFormat("accepted=%d verified=%d retcode=%u %s [%s]",
                          res.accepted, res.position_verified,
                          (uint)res.retcode,
                          ClassifyName(Classify(res.retcode)),
                          res.message));
     }
  };

#endif // MITEMSHUB_EXECUTION_EXECUTIONMONITOR_MQH
