// NTBarSender.cs
// NinjaScript Strategy — streams bar payloads to War Machine over TCP.
//
// INSTALL:
//   1. Open NinjaTrader 8
//   2. Tools → NinjaScript Editor → right-click Strategies → Add Strategy
//   3. Paste this file contents → Compile (F5)
//   4. Apply to NQ JUN26 chart (1-Minute bars, Tick Replay ON)
//   5. Set WAR_MACHINE_HOST = the IP of your Railway/local Python server
//   6. Set WAR_MACHINE_PORT = 5570 (matches NTBridge DEFAULT_PORT)
//
// PAYLOAD (one JSON line per bar close):
//   {"symbol":"NQ JUN26","timestamp":"2026-04-08T09:35:00",
//    "open":18200.25,"high":18215.50,"low":18195.00,"close":18210.75,
//    "volume":1842,"cum_delta":312.0,"vwap":18205.10,
//    "poc":18200.00,"vah":18220.00,"val":18185.00}

#region Using declarations
using System;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using NinjaTrader.Cbi;
using NinjaTrader.Gui.Tools;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;
using NinjaTrader.Data;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTBarSender : Strategy
    {
        // ── Configuration ─────────────────────────────────────────────────
        private const string WAR_MACHINE_HOST = "127.0.0.1";  // Change for Railway IP
        private const int    WAR_MACHINE_PORT = 5570;
        private const int    RECONNECT_MS     = 5000;

        // ── State ─────────────────────────────────────────────────────────
        private TcpClient   _client;
        private NetworkStream _stream;
        private bool        _connected = false;
        private Thread      _connectThread;

        // ── Order Flow indicators ─────────────────────────────────────────
        // These require Order Flow+ to be active on the account.
        // If Order Flow+ is pending, delta will fall back to (close - open) proxy.
        private OrderFlowCumulativeDelta _cumDelta;
        private OrderFlowVWAP            _vwap;
        private OrderFlowVolumeProfile   _volProfile;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description = "Streams bar data to War Machine over TCP";
                Name        = "NTBarSender";
                Calculate   = Calculate.OnBarClose;
                IsOverlay   = true;
            }
            else if (State == State.Configure)
            {
                // Add Order Flow indicators — requires Order Flow+ subscription
                _cumDelta   = OrderFlowCumulativeDelta(CumulativeDeltaType.BidAsk, CumulativeDeltaMode.Bars, 0, 0);
                _vwap       = OrderFlowVWAP(Anchored.Session, 0, 0);
                _volProfile = OrderFlowVolumeProfile(200, 1, 70, 3);

                AddChartIndicator(_cumDelta);
                AddChartIndicator(_vwap);
            }
            else if (State == State.DataLoaded)
            {
                // Connect in background so NT UI stays responsive
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
            // Only send on primary series, confirmed bars
            if (BarsInProgress != 0 || CurrentBar < 2)
                return;

            if (!_connected)
                return;

            try
            {
                // ── Pull indicator values ─────────────────────────────────
                double cumDeltaVal = 0;
                try   { cumDeltaVal = _cumDelta.DeltaClose.GetValueAt(CurrentBar); }
                catch { cumDeltaVal = Close[0] - Open[0]; }  // proxy if OF+ pending

                double vwapVal = 0;
                try   { vwapVal = _vwap.Value.GetValueAt(CurrentBar); }
                catch { vwapVal = Close[0]; }

                double poc = 0, vah = 0, val = 0;
                try
                {
                    poc = _volProfile.PointOfControl.GetValueAt(CurrentBar);
                    vah = _volProfile.ValueAreaHigh.GetValueAt(CurrentBar);
                    val = _volProfile.ValueAreaLow.GetValueAt(CurrentBar);
                }
                catch
                {
                    poc = Close[0];
                    vah = High[0];
                    val = Low[0];
                }

                // ── Build JSON payload ────────────────────────────────────
                string ts      = Time[0].ToString("yyyy-MM-ddTHH:mm:ss");
                string symbol  = Instrument.FullName;
                string payload = string.Format(
                    "{{\"symbol\":\"{0}\",\"timestamp\":\"{1}\"," +
                    "\"open\":{2},\"high\":{3},\"low\":{4},\"close\":{5}," +
                    "\"volume\":{6},\"cum_delta\":{7},\"vwap\":{8}," +
                    "\"poc\":{9},\"vah\":{10},\"val\":{11}}}\n",
                    symbol, ts,
                    Open[0].ToString("F2"),
                    High[0].ToString("F2"),
                    Low[0].ToString("F2"),
                    Close[0].ToString("F2"),
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
                _connected = false;
                _connectThread = new Thread(ConnectLoop) { IsBackground = true };
                _connectThread.Start();
            }
        }

        // ── TCP helpers ────────────────────────────────────────────────────

        private void ConnectLoop()
        {
            while (!_connected)
            {
                try
                {
                    Print("[NTBarSender] Connecting to " + WAR_MACHINE_HOST + ":" + WAR_MACHINE_PORT);
                    _client    = new TcpClient();
                    _client.Connect(WAR_MACHINE_HOST, WAR_MACHINE_PORT);
                    _stream    = _client.GetStream();
                    _connected = true;
                    Print("[NTBarSender] ✅ Connected to War Machine");
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
            try { _stream?.Close(); }  catch { }
            try { _client?.Close(); }  catch { }
        }
    }
}
