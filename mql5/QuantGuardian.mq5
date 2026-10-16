//+------------------------------------------------------------------+
//| QuantGuardian.mq5 - Risk Guardian + signal executor              |
//| Polls the SaaS API (WebRequest). Allow the API URL in            |
//| Tools > Options > Expert Advisors > Allow WebRequest.            |
//| If mt5_bridge.py is connected for this account, the queue is     |
//| delivered on the socket and this poll receives nothing.          |
//+------------------------------------------------------------------+
#property strict
#include <Trade/Trade.mqh>

input string InpApiUrl     = "http://127.0.0.1:8000";
input string InpLicenseKey = "";
input double InpInitialBal = 0;      // initial balance (prop firm)
input int    InpPollMs     = 500;
input int    InpHeartbeatS = 5;
input long   InpMagic      = 770077;
input int    InpBars       = 300;    // history bars sent on first push (chart symbol/timeframe)

CTrade   trade;
datetime g_lastHb = 0;
double   g_dayStartEquity = 0;
int      g_day = -1;
bool     g_blockNew = false;
datetime g_lastBar = 0;
bool     g_sentHistory = false;
bool     g_licenseOk = true;
datetime g_lastLicenseCheck = 0;
ulong    g_pendingReports[];  // position ids whose report failed, retried on timer

//--- minimal JSON helpers (flat objects, no nesting)
string JsonStr(const string &j, const string key)
{
   string k = "\"" + key + "\":\"";
   int p = StringFind(j, k);
   if(p < 0) return "";
   p += StringLen(k);
   int e = StringFind(j, "\"", p);
   return StringSubstr(j, p, e - p);
}

double JsonNum(const string &j, const string key)
{
   string k = "\"" + key + "\":";
   int p = StringFind(j, k);
   if(p < 0) return 0;
   p += StringLen(k);
   int e = p;
   while(e < StringLen(j) && StringFind("0123456789.-", StringSubstr(j, e, 1)) >= 0) e++;
   return StringToDouble(StringSubstr(j, p, e - p));
}

bool Http(const string method, const string path, const string body, string &resp)
{
   char data[], result[];
   string rh;
   string headers = "Content-Type: application/json\r\nX-License-Key: " + InpLicenseKey + "\r\n";
   if(body != "") StringToCharArray(body, data, 0, StringLen(body));
   int code = WebRequest(method, InpApiUrl + path, headers, 3000, data, result, rh);
   if(code == 402 || code == 403)
   {
      if(g_licenseOk) Alert(code == 402 ? "QuantGuardian: subscription unpaid, trading paused"
                                        : "QuantGuardian: license revoked/invalid, trading paused");
      g_licenseOk = false;
      return false;
   }
   if(code != 200 && code != 202) return false;
   g_licenseOk = true;
   resp = CharArrayToString(result);
   return true;
}

void CloseAll()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(PositionSelectByTicket(t) && PositionGetInteger(POSITION_MAGIC) == InpMagic)
         trade.PositionClose(t);
   }
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong t = OrderGetTicket(i);
      if(OrderGetInteger(ORDER_MAGIC) == InpMagic) trade.OrderDelete(t);
   }
}

void Heartbeat()
{
   MqlDateTime dt; TimeCurrent(dt);
   if(dt.day_of_year != g_day) { g_day = dt.day_of_year; g_dayStartEquity = AccountInfoDouble(ACCOUNT_EQUITY); }
   string body = StringFormat(
      "{\"account_number\":\"%I64d\",\"balance\":%.2f,\"equity\":%.2f,\"day_start_equity\":%.2f,\"open_trades\":%d}",
      AccountInfoInteger(ACCOUNT_LOGIN), AccountInfoDouble(ACCOUNT_BALANCE),
      AccountInfoDouble(ACCOUNT_EQUITY), g_dayStartEquity, PositionsTotal());
   string r;
   if(!Http("POST", "/api/v1/telemetry/heartbeat", body, r)) return;
   string action = JsonStr(r, "action");
   g_blockNew = (action == "BLOCK_NEW" || action == "FORCE_FLAT");
   if(action == "FORCE_FLAT") { Print("FORCE_FLAT: closing everything"); CloseAll(); }
}

void Execute(const string sig)
{
   string side = JsonStr(sig, "side"), sym = JsonStr(sig, "symbol");
   double vol = JsonNum(sig, "volume"), slp = JsonNum(sig, "sl_points"), tpp = JsonNum(sig, "tp_points");
   if(side == "CLOSE") { CloseAll(); return; }
   if(g_blockNew) { Print("Signal rejected by Risk Guardian"); return; }
   if(vol <= 0) vol = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
   double pt = SymbolInfoDouble(sym, SYMBOL_POINT);
   if(side == "BUY")
   {
      double p = SymbolInfoDouble(sym, SYMBOL_ASK);
      trade.Buy(vol, sym, p, slp > 0 ? p - slp * pt : 0, tpp > 0 ? p + tpp * pt : 0);
   }
   else if(side == "SELL")
   {
      double p = SymbolInfoDouble(sym, SYMBOL_BID);
      trade.Sell(vol, sym, p, slp > 0 ? p + slp * pt : 0, tpp > 0 ? p - tpp * pt : 0);
   }
}

void PollSignals()
{
   string r;
   string path = StringFormat("/api/v1/terminal/pending?account_number=%I64d", AccountInfoInteger(ACCOUNT_LOGIN));
   if(!Http("GET", path, "", r)) return;
   int p = 0;
   while((p = StringFind(r, "{", p + 1)) >= 0)
   {
      int e = StringFind(r, "}", p);
      if(e < 0) break;
      Execute(StringSubstr(r, p, e - p + 1));
      p = e;
   }
}

int OnInit()
{
   if(InpLicenseKey == "") { Print("License key required"); return INIT_PARAMETERS_INCORRECT; }
   trade.SetExpertMagicNumber(InpMagic);
   string body = StringFormat(
      "{\"license_key\":\"%s\",\"account_number\":\"%I64d\",\"broker_server\":\"%s\",\"initial_balance\":%.2f}",
      InpLicenseKey, AccountInfoInteger(ACCOUNT_LOGIN), AccountInfoString(ACCOUNT_SERVER),
      InpInitialBal > 0 ? InpInitialBal : AccountInfoDouble(ACCOUNT_BALANCE));
   string r;
   if(!Http("POST", "/api/v1/license/activate", body, r)) { Print("Activation failed"); return INIT_FAILED; }
   EventSetMillisecondTimer(InpPollMs);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) { EventKillTimer(); }

void PushCandles()
{
   datetime cur = iTime(_Symbol, _Period, 0);
   if(cur == 0 || cur == g_lastBar) return;
   MqlRates r[];
   ArraySetAsSeries(r, false);                                   // oldest first
   int got = CopyRates(_Symbol, _Period, 1, g_sentHistory ? 3 : InpBars, r);  // closed bars only
   if(got <= 0) return;
   string arr = "";
   for(int i = 0; i < got; i++)
      arr += (i ? "," : "") + "{\"t\":" + IntegerToString((long)r[i].time) +
             ",\"o\":" + DoubleToString(r[i].open, _Digits) + ",\"h\":" + DoubleToString(r[i].high, _Digits) +
             ",\"l\":" + DoubleToString(r[i].low, _Digits) + ",\"c\":" + DoubleToString(r[i].close, _Digits) + "}";
   string body = StringFormat(
      "{\"account_number\":\"%I64d\",\"symbol\":\"%s\",\"utc_offset\":%I64d,\"point\":%s,\"tick_size\":%s,"
      "\"tick_value\":%s,\"vol_min\":%s,\"vol_step\":%s,\"vol_max\":%s,\"candles\":[%s]}",
      AccountInfoInteger(ACCOUNT_LOGIN), _Symbol, (long)(TimeTradeServer() - TimeGMT()),
      DoubleToString(_Point, 10), DoubleToString(SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE), 10),
      DoubleToString(SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE), 10),
      DoubleToString(SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN), 2),
      DoubleToString(SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP), 2),
      DoubleToString(SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX), 2), arr);
   string resp;
   if(Http("POST", "/api/v1/market/candles", body, resp)) { g_lastBar = cur; g_sentHistory = true; }
}

//--- report a fully closed position (aggregates all its deals)
bool ReportPosition(const ulong posId)
{
   if(PositionSelectByTicket(posId)) return true;   // partial close: still open, report later
   if(!HistorySelectByPosition(posId)) return false;
   string side = "", sym = "";
   double volIn = 0, openPx = 0, closePx = 0, pnl = 0;
   long openT = 0, closeT = 0;
   for(int i = 0; i < HistoryDealsTotal(); i++)
   {
      ulong d = HistoryDealGetTicket(i);
      long entry = HistoryDealGetInteger(d, DEAL_ENTRY);
      pnl += HistoryDealGetDouble(d, DEAL_PROFIT) + HistoryDealGetDouble(d, DEAL_SWAP) + HistoryDealGetDouble(d, DEAL_COMMISSION);
      if(entry == DEAL_ENTRY_IN)
      {
         double v = HistoryDealGetDouble(d, DEAL_VOLUME);
         openPx = (openPx * volIn + HistoryDealGetDouble(d, DEAL_PRICE) * v) / (volIn + v);  // VWAP on scale-ins
         volIn += v;
         if(openT == 0) openT = HistoryDealGetInteger(d, DEAL_TIME);
         side = HistoryDealGetInteger(d, DEAL_TYPE) == DEAL_TYPE_BUY ? "BUY" : "SELL";
         sym = HistoryDealGetString(d, DEAL_SYMBOL);
      }
      else
      {
         closePx = HistoryDealGetDouble(d, DEAL_PRICE);
         closeT = HistoryDealGetInteger(d, DEAL_TIME);
      }
   }
   if(side == "" || closeT == 0) return true;   // nothing reportable
   int dg = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   string body = StringFormat(
      "{\"account_number\":\"%I64d\",\"ticket\":\"%I64u\",\"side\":\"%s\",\"symbol\":\"%s\",\"volume\":%s,"
      "\"open_price\":%s,\"close_price\":%s,\"pnl\":%.2f,\"opened_at\":%I64d,\"closed_at\":%I64d,\"utc_offset\":%I64d}",
      AccountInfoInteger(ACCOUNT_LOGIN), posId, side, sym, DoubleToString(volIn, 2),
      DoubleToString(openPx, dg), DoubleToString(closePx, dg), pnl, openT, closeT,
      (long)(TimeTradeServer() - TimeGMT()));
   string r;
   return Http("POST", "/api/v1/terminal/trades", body, r);
}

void OnTradeTransaction(const MqlTradeTransaction &trans, const MqlTradeRequest &req, const MqlTradeResult &res)
{
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD || !HistoryDealSelect(trans.deal)) return;
   if(HistoryDealGetInteger(trans.deal, DEAL_MAGIC) != InpMagic) return;
   long entry = HistoryDealGetInteger(trans.deal, DEAL_ENTRY);
   if(entry != DEAL_ENTRY_OUT && entry != DEAL_ENTRY_OUT_BY) return;
   ulong posId = (ulong)HistoryDealGetInteger(trans.deal, DEAL_POSITION_ID);
   if(!ReportPosition(posId))
   {
      int n = ArraySize(g_pendingReports);
      ArrayResize(g_pendingReports, n + 1);
      g_pendingReports[n] = posId;
   }
}

void RetryReports()
{
   for(int i = ArraySize(g_pendingReports) - 1; i >= 0; i--)
      if(ReportPosition(g_pendingReports[i])) ArrayRemove(g_pendingReports, i, 1);
}

void OnTimer()
{
   if(!g_licenseOk)
   {
      // paused: only re-check the license once a minute (heartbeat flips g_licenseOk back on success)
      if(TimeCurrent() - g_lastLicenseCheck < 60) return;
      g_lastLicenseCheck = TimeCurrent();
      Heartbeat();
      return;
   }
   if(TimeCurrent() - g_lastHb >= InpHeartbeatS) { g_lastHb = TimeCurrent(); Heartbeat(); RetryReports(); }
   PushCandles();
   PollSignals();
}
