// NTBarSender.cs  (Indicator v27 — IsFirstTickOfBar fix)
// Apply to NQ 1m chart as an INDICATOR (not a strategy).
// Streams enriched bar data to War Machine Python bridge over TCP.
#region Using declarations
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using System.Linq;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Indicators;
#endregion


namespace NinjaTrader.NinjaScript.Indicators
{
    public class NTBarSender : Indicator
    {
        private const int    RECONNECT_MS   = 5000;
        private const double VALUE_AREA_PCT = 0.70;


        // ── bar-level accumulators (reset each bar) ──
        private double _barBidVol  = 0.0;
        private double _barAskVol  = 0.0;
        private double _barDelta   = 0.0;


        // ── session-level accumulators (reset each session) ──
        private double _sessionCumDelta = 0.0;
        private double _cumPriceVol     = 0.0;
        private double _cumVol          = 0.0;
        private double _sessionOpen     = double.NaN;


        // ── volume profile ──
        private Dictionary<double, double[]> _sessionVolByPrice
            = new Dictionary<double, double[]>(); // [0]=bidVol [1]=askVol
        private double _poc = 0.0;
        private double _vah = 0.0;
        private double _val = 0.0;


        // ── previous session values ──
        private double _prevDayHigh  = double.NaN;
        private double _prevDayLow   = double.NaN;
        private double _prevDayClose = double.NaN;


        // ── overnight range ──
        private double _overnightHigh = double.NaN;
        private double _overnightLow  = double.NaN;
        private bool   _rthStarted    = false;


        // ── TCP ──
        private TcpClient     _client;
        private NetworkStream _stream;
        private bool          _connected    = false;
        private Thread        _connectThread;
        private volatile bool _shutdown     = false;


        // ── secondary bar series indices ──
        private int _bars5m  = -1;
        private int _bars15m = -1;


        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description    = "Streams enriched bar data to War Machine over TCP";
                Name           = "NTBarSender";
                Calculate      = Calculate.OnEachTick;
                IsOverlay      = true;
                IsSuspendedWhileInactive = false;
                WarMachineHost = "127.0.0.1";
                WarMachinePort = 5570;
            }
            else if (State == State.Configure)
            {
                _bars5m  = AddDataSeries(BarsPeriodType.Minute, 5);
                _bars15m = AddDataSeries(BarsPeriodType.Minute, 15);
            }
            else if (State == State.DataLoaded)
            {
                Print("[NTBarSender] DataLoaded OK — starting ConnectLoop");
                _shutdown      = false;
                _connectThread = new Thread(ConnectLoop) { IsBackground = true };
                _connectThread.Start();
            }
            else if (State == State.Realtime)
            {
                Print("[NTBarSender] *** State.Realtime reached — live data active ***");
            }
            else if (State == State.Terminated)
            {
                Print("[NTBarSender] Terminated — closing TCP");
                Disconnect();
            }
        }


        protected override void OnMarketData(MarketDataEventArgs e)
        {
            if (e.MarketDataType != MarketDataType.Last) return;


            double price    = e.Price;
            double vol      = e.Volume;
            double priceKey = Math.Round(price / TickSize) * TickSize;


            _cumPriceVol += price * vol;
            _cumVol      += vol;


            bool isAsk = price >= GetCurrentAsk();
            bool isBid = price <= GetCurrentBid();


            if (isAsk)
            {
                _barAskVol       += vol;
                _barDelta        += vol;
                _sessionCumDelta += vol;
            }
            else if (isBid)
            {
                _barBidVol       += vol;
                _barDelta        -= vol;
                _sessionCumDelta -= vol;
            }


            if (!_sessionVolByPrice.ContainsKey(priceKey))
                _sessionVolByPrice[priceKey] = new double[2];
            if (isAsk)       _sessionVolByPrice[priceKey][1] += vol;
            else if (isBid)  _sessionVolByPrice[priceKey][0] += vol;
            else { _sessionVolByPrice[priceKey][0] += vol * 0.5; _sessionVolByPrice[priceKey][1] += vol * 0.5; }


            if (!_rthStarted)
            {
                if (double.IsNaN(_overnightHigh) || price > _overnightHigh) _overnightHigh = price;
                if (double.IsNaN(_overnightLow)  || price < _overnightLow)  _overnightLow  = price;
            }
        }


        protected override void OnBarUpdate()
        {
            if (BarsInProgress != 0) return;
            if (CurrentBar < 5)      return;
            if (!IsFirstTickOfBar)   return;

            if (double.IsNaN(_sessionOpen))
            {
                _sessionOpen = Open[1];
                _rthStarted  = true;
            }

            if (Bars.IsLastBarOfSession)
            {
                _prevDayHigh  = High[1];
                _prevDayLow   = Low[1];
                _prevDayClose = Close[1];

                _sessionVolByPrice.Clear();
                _poc = 0.0; _vah = 0.0; _val = 0.0;
                _barBidVol = 0.0; _barAskVol = 0.0; _barDelta = 0.0;
                _sessionCumDelta = 0.0; _cumPriceVol = 0.0; _cumVol = 0.0;
                _sessionOpen = double.NaN; _rthStarted = false;
                _overnightHigh = double.NaN; _overnightLow = double.NaN;
                return;
            }

            UpdateVolumeProfile();

            if (!_connected)
            {
                Print("[NTBarSender] Bar ready but not connected — skipping send");
                _barBidVol = 0.0; _barAskVol = 0.0; _barDelta = 0.0;
                return;
            }

            try
            {
                double vwapVal   = _cumVol > 0 ? _cumPriceVol / _cumVol : Close[1];
                double barRange  = High[1] - Low[1];
                double bodySize  = Math.Abs(Close[1] - Open[1]);
                double upperWick = High[1] - Math.Max(Open[1], Close[1]);
                double lowerWick = Math.Min(Open[1], Close[1]) - Low[1];
                double bodyPct   = barRange > 0 ? bodySize / barRange : 0.0;
                int    barDir    = Close[1] > Open[1] ? 1 : (Close[1] < Open[1] ? -1 : 0);

                double bidVol    = _barBidVol;
                double askVol    = _barAskVol;
                double barDelta  = _barDelta;
                double total     = bidVol + askVol;
                double imbalance = total > 0 ? (askVol - bidVol) / total : 0.0;

                int deltaDivergence = 0;
                if      (barDir ==  1 && barDelta < 0) deltaDivergence = -1;
                else if (barDir == -1 && barDelta > 0) deltaDivergence =  1;

                int stackedBull = 0, stackedBear = 0;
                if (_sessionVolByPrice.Count > 2)
                {
                    var sortedKeys = _sessionVolByPrice.Keys.OrderBy(p => p).ToList();
                    int streak = 0;
                    for (int i = 1; i < sortedKeys.Count; i++)
                    {
                        double bv = _sessionVolByPrice[sortedKeys[i]][0];
                        double av = _sessionVolByPrice[sortedKeys[i]][1];
                        if (av > 0 && bv / av >= 3.0) streak++; else streak = 0;
                        if (streak >= 3) stackedBear = streak;
                    }
                    streak = 0;
                    for (int i = sortedKeys.Count - 2; i >= 0; i--)
                    {
                        double bv = _sessionVolByPrice[sortedKeys[i]][0];
                        double av = _sessionVolByPrice[sortedKeys[i]][1];
                        if (bv > 0 && av / bv >= 3.0) streak++; else streak = 0;
                        if (streak >= 3) stackedBull = streak;
                    }
                }

                double close5m  = BarsArray[_bars5m].Count  > 1 ? BarsArray[_bars5m].GetClose(BarsArray[_bars5m].Count   - 2) : Close[1];
                double close15m = BarsArray[_bars15m].Count > 1 ? BarsArray[_bars15m].GetClose(BarsArray[_bars15m].Count  - 2) : Close[1];
                double high5m   = BarsArray[_bars5m].Count  > 1 ? BarsArray[_bars5m].GetHigh(BarsArray[_bars5m].Count     - 2) : High[1];
                double low5m    = BarsArray[_bars5m].Count  > 1 ? BarsArray[_bars5m].GetLow(BarsArray[_bars5m].Count      - 2) : Low[1];
                double high15m  = BarsArray[_bars15m].Count > 1 ? BarsArray[_bars15m].GetHigh(BarsArray[_bars15m].Count   - 2) : High[1];
                double low15m   = BarsArray[_bars15m].Count > 1 ? BarsArray[_bars15m].GetLow(BarsArray[_bars15m].Count    - 2) : Low[1];

                _barBidVol = 0.0; _barAskVol = 0.0; _barDelta = 0.0;

                string payload = string.Format(
                    "{{\"symbol\":\"{0}\",\"timestamp\":\"{1}\"," +
                    "\"open\":{2},\"high\":{3},\"low\":{4},\"close\":{5}," +
                    "\"volume\":{6},\"delta\":{7},\"cum_delta\":{8}," +
                    "\"bid_vol\":{9},\"ask_vol\":{10},\"imbalance\":{11}," +
                    "\"vwap\":{12},\"poc\":{13},\"vah\":{14},\"val\":{15}," +
                    "\"bar_range\":{16},\"upper_wick\":{17},\"lower_wick\":{18},\"body_pct\":{19},\"bar_dir\":{20}," +
                    "\"delta_div\":{21},\"stacked_bull\":{22},\"stacked_bear\":{23}," +
                    "\"session_open\":{24},\"prev_day_high\":{25},\"prev_day_low\":{26},\"prev_day_close\":{27}," +
                    "\"overnight_high\":{28},\"overnight_low\":{29}," +
                    "\"close_5m\":{30},\"high_5m\":{31},\"low_5m\":{32}," +
                    "\"close_15m\":{33},\"high_15m\":{34},\"low_15m\":{35}}}\n",
                    Instrument.FullName,
                    Time[1].ToString("yyyy-MM-ddTHH:mm:ss"),
                    Open[1].ToString("F2"),  High[1].ToString("F2"),
                    Low[1].ToString("F2"),   Close[1].ToString("F2"),
                    Volume[1],
                    barDelta.ToString("F2"), _sessionCumDelta.ToString("F2"),
                    bidVol.ToString("F2"),   askVol.ToString("F2"),
                    imbalance.ToString("F4"),
                    vwapVal.ToString("F2"),
                    _poc.ToString("F2"),     _vah.ToString("F2"), _val.ToString("F2"),
                    barRange.ToString("F2"), upperWick.ToString("F2"),
                    lowerWick.ToString("F2"), bodyPct.ToString("F4"), barDir,
                    deltaDivergence, stackedBull, stackedBear,
                    double.IsNaN(_sessionOpen)   ? "null" : _sessionOpen.ToString("F2"),
                    double.IsNaN(_prevDayHigh)   ? "null" : _prevDayHigh.ToString("F2"),
                    double.IsNaN(_prevDayLow)    ? "null" : _prevDayLow.ToString("F2"),
                    double.IsNaN(_prevDayClose)  ? "null" : _prevDayClose.ToString("F2"),
                    double.IsNaN(_overnightHigh) ? "null" : _overnightHigh.ToString("F2"),
                    double.IsNaN(_overnightLow)  ? "null" : _overnightLow.ToString("F2"),
                    close5m.ToString("F2"),  high5m.ToString("F2"),  low5m.ToString("F2"),
                    close15m.ToString("F2"), high15m.ToString("F2"), low15m.ToString("F2")
                );

                Print("[NTBarSender] Sending: " + payload.Trim());
                byte[] data = Encoding.UTF8.GetBytes(payload);
                _stream.Write(data, 0, data.Length);
                Print("[NTBarSender] Sent OK");
            }
            catch (Exception ex)
            {
                Print("[NTBarSender] Send error: " + ex.Message + " — reconnecting");
                _connected = false;
                _barBidVol = 0.0; _barAskVol = 0.0; _barDelta = 0.0;
                _connectThread = new Thread(ConnectLoop) { IsBackground = true };
                _connectThread.Start();
            }
        }


        private void UpdateVolumeProfile()
        {
            if (_sessionVolByPrice.Count == 0) return;


            double pocPrice = 0.0, pocVol = -1.0, totalVol = 0.0;
            foreach (var kv in _sessionVolByPrice)
            {
                double combined = kv.Value[0] + kv.Value[1];
                totalVol += combined;
                if (combined > pocVol) { pocVol = combined; pocPrice = kv.Key; }
            }
            _poc = pocPrice;


            var sortedPrices = _sessionVolByPrice.Keys.OrderBy(p => p).ToList();
            int pocIdx = sortedPrices.IndexOf(pocPrice);
            if (pocIdx < 0) { _vah = pocPrice; _val = pocPrice; return; }


            double target   = totalVol * VALUE_AREA_PCT;
            double enclosed = pocVol;
            int lo = pocIdx, hi = pocIdx;


            while (enclosed < target && (lo > 0 || hi < sortedPrices.Count - 1))
            {
                double volUp   = hi + 1 < sortedPrices.Count
                    ? _sessionVolByPrice[sortedPrices[hi + 1]][0] + _sessionVolByPrice[sortedPrices[hi + 1]][1] : 0;
                double volDown = lo - 1 >= 0
                    ? _sessionVolByPrice[sortedPrices[lo - 1]][0] + _sessionVolByPrice[sortedPrices[lo - 1]][1] : 0;


                if      (volUp >= volDown && hi + 1 < sortedPrices.Count) { hi++; enclosed += volUp;   }
                else if (lo - 1 >= 0)                                      { lo--; enclosed += volDown; }
                else if (hi + 1 < sortedPrices.Count)                      { hi++; enclosed += volUp;   }
                else break;
            }


            _vah = sortedPrices[hi];
            _val = sortedPrices[lo];
        }


        private void ConnectLoop()
        {
            while (!_connected && !_shutdown)
            {
                try
                {
                    Print("[NTBarSender] Connecting to " + WarMachineHost + ":" + WarMachinePort);
                    _client    = new TcpClient();
                    _client.Connect(WarMachineHost, WarMachinePort);
                    _stream    = _client.GetStream();
                    _connected = true;
                    Print("[NTBarSender] Connected OK");
                }
                catch (Exception ex)
                {
                    if (_shutdown) break;
                    Print("[NTBarSender] Connection failed: " + ex.Message + " — retrying in 5s");
                    Thread.Sleep(RECONNECT_MS);
                }
            }
        }


        private void Disconnect()
        {
            _shutdown  = true;
            _connected = false;
            try { _stream?.Close(); } catch { }
            try { _client?.Close(); } catch { }
        }


        [NinjaScriptProperty]
        [Display(Name = "War Machine Host", Description = "127.0.0.1 for local", Order = 1, GroupName = "War Machine")]
        public string WarMachineHost { get; set; }


        [NinjaScriptProperty]
        [Range(1, 65535)]
        [Display(Name = "War Machine Port", Description = "5570 for local", Order = 2, GroupName = "War Machine")]
        public int WarMachinePort { get; set; }
    }
}
