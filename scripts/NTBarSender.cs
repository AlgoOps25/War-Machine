// NTBarSender.cs  (v4 — configurable host/port via NT8 UI)
//
// Streams bar payloads to War Machine over TCP.
// Works on any NT8 account — funded or unfunded.
//
// INSTALL:
//   1. NinjaTrader 8 → Tools → NinjaScript Editor
//   2. Find NTBarSender under Strategies → double-click to open
//   3. Ctrl+A → Delete → paste this file → F5 to compile
//   4. Apply to NQ JUN26 chart (1-Minute bars)
//   5. In the strategy parameters dialog set:
//        WarMachineHost = 127.0.0.1       (local)  OR
//        WarMachineHost = crossover.proxy.rlwy.net  (Railway)
//        WarMachinePort = 5570            (local)  OR
//        WarMachinePort = 24283           (Railway)
//
// UPGRADE PATH (after funding + Order Flow+ active):
//   Search for "ORDER FLOW+ UPGRADE" comments and swap the blocks back in.
//   JSON payload schema is identical — War Machine needs no changes.
//
// PAYLOAD (one JSON line per confirmed bar close):
//   {"symbol":"NQ JUN26","timestamp":"2026-04-08T09:35:00",
//    "open":18200.25,"high":18215.50,"low":18195.00,"close":18210.75,
//    "volume":1842,"cum_delta":10.50,"vwap":18205.10,
//    "poc":18200.00,"vah":18215.50,"val":18195.00}

#region Using declarations
using System;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using NinjaTrader.Cbi;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;
using NinjaTrader.Data;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTBarSender : Strategy
    {
        // ── Constants ──────────────────────────────────────────────────────────────
        private const int RECONNECT_MS = 5000;
        private const int VOL_LOOKBACK = 20;  // bars for POC/VAH/VAL calculation

        // ── Native indicators (no add-ons required) ────────────────────────────────
        // VWAP approximation: SMA of typical price (smooths toward volume-weighted mean)
        // ORDER FLOW+ UPGRADE: replace with OrderFlowVWAP field
        private NinjaTrader.NinjaScript.Indicators.SMA _vwapProxy;

        // ── TCP state ──────────────────────────────────────────────────────────────
        private TcpClient     _client;
        private NetworkStream _stream;
        private bool          _connected     = false;
        private Thread        _connectThread;

        // ── Delta accumulator ──────────────────────────────────────────────────────
        // Cumulative delta proxy: running sum of (close - open) each bar.
        // Resets at session open. Positive = net buying, negative = net selling.
        // ORDER FLOW+ UPGRADE: replace with OrderFlowCumulativeDelta field
        private double _sessionDelta = 0.0;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description    = "Streams bar data to War Machine over TCP (native NT8, no add-ons)";
                Name           = "NTBarSender";
                Calculate      = Calculate.OnBarClose;
                IsOverlay      = true;
                // Default to LOCAL — change to Railway values in the UI for production
                WarMachineHost = "127.0.0.1";
                WarMachinePort = 5570;
            }
            else if (State == State.Configure)
            {
                // SMA of typical price as VWAP proxy — no add-ons needed
                // ORDER FLOW+ UPGRADE: _vwapProxy = OrderFlowVWAP(Anchored.Session, 0, 0);
                _vwapProxy = SMA(Typical, 20);
                AddChartIndicator(_vwapProxy);
            }
            else if (State == State.DataLoaded)
            {
                _connectThread = new Thread(ConnectLoop) { IsBackground = true };
                _connectThread.Start();
            }
            else if (State == State.Terminated)
            {
                Disconnect();
            }
        }

        protected override void OnBarUpdate()
        {
            if (BarsInProgress != 0 || CurrentBar < VOL_LOOKBACK + 2)
                return;

            if (!_connected)
                return;

            try
            {
                // ── Cumulative Delta proxy ─────────────────────────────────────────
                // ORDER FLOW+ UPGRADE: cumDeltaVal = _cumDelta.DeltaClose.GetValueAt(CurrentBar)
                if (Bars.IsFirstBarOfSession)
                    _sessionDelta = 0.0;

                _sessionDelta += (Close[0] - Open[0]);
                double cumDeltaVal = _sessionDelta;

                // ── VWAP proxy ────────────────────────────────────────────────────
                // ORDER FLOW+ UPGRADE: vwapVal = _vwap.Value.GetValueAt(CurrentBar)
                double vwapVal = _vwapProxy[0];

                // ── POC / VAH / VAL proxy ─────────────────────────────────────────
                // Highest-volume bar close over lookback = POC
                // Highest high / lowest low over lookback = VAH / VAL
                // ORDER FLOW+ UPGRADE: replace loop with OrderFlowVolumeProfile values
                double poc    = Close[0];
                double maxVol = double.MinValue;
                double vah    = double.MinValue;
                double val    = double.MaxValue;

                for (int i = 0; i < VOL_LOOKBACK; i++)
                {
                    double barVol = Volume[i];
                    if (barVol > maxVol) { maxVol = barVol; poc = Close[i]; }
                    if (High[i] > vah) vah = High[i];
                    if (Low[i]  < val) val = Low[i];
                }

                // ── JSON payload ──────────────────────────────────────────────────
                string ts      = Time[0].ToString("yyyy-MM-ddTHH:mm:ss");
                string symbol  = Instrument.FullName;
                string payload = string.Format(
                    "{{\"symbol\":\"{0}\",\"timestamp\":\"{1}\"," +
                    "\"open\":{2},\"high\":{3},\"low\":{4},\"close\":{5}," +
                    "\"volume\":{6},\"cum_delta\":{7},\"vwap\":{8}," +
                    "\"poc\":{9},\"vah\":{10},\"val\":{11}}}\n",
                    symbol, ts,
                    Open[0].ToString("F2"),  High[0].ToString("F2"),
                    Low[0].ToString("F2"),   Close[0].ToString("F2"),
                    Volume[0],
                    cumDeltaVal.ToString("F2"),
                    vwapVal.ToString("F2"),
                    poc.ToString("F2"),
                    vah.ToString("F2"),
                    val.ToString("F2")
                );

                byte[] data = Encoding.UTF8.GetBytes(payload);
                _stream.Write(data, 0, data.Length);
            }
            catch (Exception ex)
            {
                Print("[NTBarSender] Send error: " + ex.Message + " — reconnecting");
                _connected     = false;
                _connectThread = new Thread(ConnectLoop) { IsBackground = true };
                _connectThread.Start();
            }
        }

        // ── TCP helpers ────────────────────────────────────────────────────────────

        private void ConnectLoop()
        {
            while (!_connected)
            {
                try
                {
                    Print("[NTBarSender] Connecting to " + WarMachineHost + ":" + WarMachinePort);
                    _client    = new TcpClient();
                    _client.Connect(WarMachineHost, WarMachinePort);
                    _stream    = _client.GetStream();
                    _connected = true;
                    Print("[NTBarSender] Connected to War Machine @ " + WarMachineHost + ":" + WarMachinePort);
                }
                catch (Exception ex)
                {
                    Print("[NTBarSender] Connection failed: " + ex.Message + " — retrying in 5s");
                    Thread.Sleep(RECONNECT_MS);
                }
            }
        }

        private void Disconnect()
        {
            _connected = false;
            try { _stream?.Close(); } catch { }
            try { _client?.Close(); } catch { }
        }

        // ── UI Parameters (configurable in NT8 strategy dialog) ────────────────────

        [NinjaScriptProperty]
        [Display(Name = "War Machine Host", Description = "127.0.0.1 for local | crossover.proxy.rlwy.net for Railway", Order = 1, GroupName = "War Machine")]
        public string WarMachineHost { get; set; }

        [NinjaScriptProperty]
        [Range(1, 65535)]
        [Display(Name = "War Machine Port", Description = "5570 for local | 24283 for Railway", Order = 2, GroupName = "War Machine")]
        public int WarMachinePort { get; set; }
    }
}
