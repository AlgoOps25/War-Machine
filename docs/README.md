# War Machine Documentation

## 📊 Current Status (Feb 24, 2026)

- **Trades:** 3 closed (0W-3L, -$1,143 P&L)
- **System:** Core logic deployed to Railway
- **Phase 4:** Modules ready, not yet integrated
- **Next:** Deploy Phase 4 monitoring (2-3 hours)

---

## 📚 Documentation Overview

### **🎯 [Master Execution Plan](./EXECUTION_PLAN.md)**
**Your complete roadmap for the next 8-10 weeks.**

- Phase 4: Deploy monitoring (Week 1-2)
- Phase 5: ML features (Week 3-8)
- Option C: Debug cycle (Ongoing)

Timeline, checkpoints, and success metrics included.

---

### **⚙️ [Phase 4 Deployment Guide](./PHASE_4_DEPLOYMENT_GUIDE.md)**
**START HERE - Integration instructions for monitoring.**

**Time Required:** 2-3 hours  
**When:** Today  
**What:** 7 integration points across sniper.py, signal_validator.py, position_manager.py

**Outcome:**
- Complete signal-to-trade visibility
- Real-time alerts
- Daily/hourly digests
- Data ready for optimization

---

### **🤖 [Phase 5 Roadmap](./PHASE_5_ROADMAP.md)**
**ML features and advanced optimization.**

**Time Required:** 4-6 weeks  
**When:** After Phase 4 + 2 weeks data collection  
**Prerequisites:** 20+ trades, Phase 4 deployed

**Components:**
- ML signal scoring
- Multi-timeframe synchronization
- Portfolio optimization
- Adaptive parameter tuning
- Enhanced exit management

**Expected Outcome:**
- Win rate: 65-75%
- Sharpe ratio: 2.0+
- Max drawdown: <10%

---

### **🔍 [Debugging Guide](./DEBUGGING_GUIDE.md)**
**Systematic debugging and optimization.**

**When:** After 20+ trades collected  
**Frequency:** Every 2-4 weeks  

**Process:**
1. Run historical analysis
2. Query signal funnel
3. Validate grade performance
4. Analyze stop/target effectiveness
5. Run parameter optimizer
6. Apply recommendations
7. Deploy and monitor

**Use when:**
- Win rate below expectations
- Stop hit rate too high/low
- Consistent losses
- Need parameter tuning

---

## 🚀 Quick Start

### **1. Deploy Phase 4 Monitoring (Today)**

```bash
# Pull latest code
cd /path/to/War-Machine
git pull origin main

# Open deployment guide
cat docs/PHASE_4_DEPLOYMENT_GUIDE.md

# Follow Step 1-7
# Integrate monitoring into sniper.py, signal_validator.py, position_manager.py

# Test locally
python sniper.py

# Deploy to Railway
git add .
git commit -m "feat: Integrate Phase 4 monitoring"
git push origin main
```

**Time:** 2-3 hours  
**Result:** Complete monitoring deployed

---

### **2. Collect Data (Week 1-2)**

**Passive monitoring - let War Machine trade and collect data.**

**Daily tasks:**
- Check Railway logs
- Review hourly digests
- Verify signal tracking

**Goal:** 20+ closed trades

---

### **3. First Analysis (End of Week 2)**

```bash
# Run historical analysis
python adaptive_historical_tuner.py

# Review results
cat historical_report_*.txt

# Check signal funnel
psql $DATABASE_URL -c "
  SELECT stage, COUNT(*) 
  FROM signal_events 
  WHERE session_date >= CURRENT_DATE - 14 
  GROUP BY stage;
"
```

**Decision point:** Start Phase 5 or debug issues first?

---

### **4. Start Phase 5 (Week 3+)**

If Phase 4 data looks good:
- Open [Phase 5 Roadmap](./PHASE_5_ROADMAP.md)
- Begin ML signal scoring (Week 3-4)
- Continue through components sequentially

---

### **5. Debug Cycle (Every 2-4 weeks)**

After 20, 50, 100 trades:
- Open [Debugging Guide](./DEBUGGING_GUIDE.md)
- Run analysis tools
- Apply optimizations
- Deploy updates

---

## 📈 Analysis Tools

### **Historical Performance Analysis**
```bash
# Set Railway database URL
export DATABASE_URL="postgresql://..."

# Run analysis
python adaptive_historical_tuner.py

# Output: Performance by grade, ticker, stop effectiveness
```

### **Database Diagnostic**
```bash
# Check what's in database
python db_diagnostic.py

# Shows: Total positions, status breakdown, sample records
```

### **Parameter Optimizer**
```bash
# Get optimization recommendations (after 30+ trades)
python parameter_optimizer.py --min-trades 30

# Output: Stop width, target adjustments, ticker whitelist/blacklist
```

---

## 📊 Key Metrics to Track

### **Signal Funnel (Daily):**
- Signals generated
- Validation pass rate
- Armed rate
- Trade execution rate

**Healthy funnel:**
- Generated: 100 (baseline)
- Validated: 30-50 (30-50%)
- Armed: 15-25 (50-80% of validated)
- Traded: 10-20 (60-80% of armed)

### **Grade Performance (Weekly):**
- A+ win rate (target: 75%)
- A win rate (target: 65%)
- A- win rate (target: 55%)

### **Risk Metrics (Daily):**
- Stop hit rate (target: 20-30%)
- Target hit rate (target: 60-70%)
- Max drawdown
- Win/loss streaks

### **Portfolio (Daily):**
- Total P&L
- Win rate %
- Average P&L per trade
- Sharpe ratio (after 50+ trades)

---

## 🔗 Quick Links

### **Railway Dashboard:**
- [Your Deployment](https://railway.app)
- PostgreSQL database
- Logs and metrics

### **GitHub Repository:**
- [War Machine Repo](https://github.com/AlgoOps25/War-Machine)
- Commits and deployment history

### **Documentation Files:**
- [EXECUTION_PLAN.md](./EXECUTION_PLAN.md) - Master plan
- [PHASE_4_DEPLOYMENT_GUIDE.md](./PHASE_4_DEPLOYMENT_GUIDE.md) - Integration guide
- [PHASE_5_ROADMAP.md](./PHASE_5_ROADMAP.md) - ML features
- [DEBUGGING_GUIDE.md](./DEBUGGING_GUIDE.md) - Systematic debugging

---

## ⚠️ Important Notes

### **Data Requirements:**
- **Phase 4 deployment:** No prerequisites
- **First analysis:** 20+ trades minimum
- **Robust optimization:** 50+ trades
- **ML training:** 200+ trades (Phase 5)

### **Timeline Expectations:**
- **Week 1-2:** Deploy Phase 4 + collect initial data
- **Week 3-8:** Phase 5 development (parallel to data collection)
- **Week 9+:** Fully optimized ML-enhanced system

### **Risk Management:**
- Start with Phase 4 (low risk, monitoring only)
- Test Phase 5 features extensively before deploying
- Apply parameter changes incrementally
- Always have rollback plan

---

## 🎯 Success Criteria

### **Phase 4 (After 2 weeks):**
- [ ] Signal funnel visible
- [ ] Alerts working
- [ ] 20+ trades collected
- [ ] No critical errors

### **Phase 5 (After 8 weeks):**
- [ ] ML model deployed
- [ ] Win rate 65-75%
- [ ] Sharpe ratio 2.0+
- [ ] Stable operation

### **Ongoing Optimization:**
- [ ] Grade performance meets targets
- [ ] Stop hit rate 20-30%
- [ ] Consistent weekly profitability
- [ ] Continuous improvement

---

## 📞 Troubleshooting

### **Issue: Phase 4 deployment fails**
→ See [PHASE_4_DEPLOYMENT_GUIDE.md](./PHASE_4_DEPLOYMENT_GUIDE.md) - Troubleshooting section

### **Issue: No signals generating**
→ See [DEBUGGING_GUIDE.md](./DEBUGGING_GUIDE.md) - Signal Funnel Analysis

### **Issue: Win rate too low**
→ See [DEBUGGING_GUIDE.md](./DEBUGGING_GUIDE.md) - Grade Validation

### **Issue: ML model performs poorly**
→ See [PHASE_5_ROADMAP.md](./PHASE_5_ROADMAP.md) - Risk Considerations

---

## 📝 Summary

**Your Path Forward:**

1. **Today:** Deploy Phase 4 (2-3 hours)
2. **Week 1-2:** Collect data (passive)
3. **Week 3+:** Start Phase 5 development
4. **Every 2 weeks:** Run debug cycle
5. **Week 9+:** Fully optimized system

**Next Action:** Open [PHASE_4_DEPLOYMENT_GUIDE.md](./PHASE_4_DEPLOYMENT_GUIDE.md) and begin Step 1.

---

**Let's build a consistently profitable trading system! 🚀**
