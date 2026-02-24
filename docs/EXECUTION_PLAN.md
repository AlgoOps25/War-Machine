# War Machine Execution Plan
## Phase 4 → Phase 5 → Debug Cycle

---

## Current Status (Feb 24, 2026)

### System:
- ✅ Core trading logic deployed to Railway
- ✅ 3 closed trades (0% win rate, -$1,143 P&L)
- ✅ Phase 4 modules committed (signal_analytics, performance_monitor, etc.)
- ⚠️ Phase 4 not yet integrated into main trading loop
- ⚠️ Insufficient data for optimization (need 20+ trades)

### Your Plan:
1. **Deploy Phase 4 Monitoring First** ⭐
2. **Then Option B (Phase 5 Development)**
3. **Then Option C (Debug Current Setup)**

---

## Timeline Overview

```
Week 1-2: Phase 4 Integration
  ├─ Day 1-2: Integrate monitoring (2-3 hours)
  ├─ Day 3-14: Collect comprehensive data (passive)
  └─ End Week 2: First analysis checkpoint

Week 3-4: Phase 5 Start + Continue Data Collection
  ├─ Begin ML feature extraction
  ├─ Build initial models
  └─ Continue collecting Phase 4 data

Week 5-8: Phase 5 Development + Debug Cycle
  ├─ Week 5: ML Signal Scoring
  ├─ Week 6: Multi-Timeframe Sync
  ├─ Week 7: Portfolio Optimization
  ├─ Week 8: Adaptive Parameters
  └─ Ongoing: Debug based on Phase 4 data

Week 9+: Phase 5 Deployment + Continuous Optimization
  ├─ Deploy ML-enhanced system
  ├─ Monitor performance
  └─ Iterate based on results
```

---

## Phase 4: Deploy Monitoring (Week 1-2)

### **Duration:** 2-3 hours active work + 2 weeks passive data collection

### **Objective:** 
Complete visibility into every signal from generation to execution.

### **Guide:** 
📚 [`PHASE_4_DEPLOYMENT_GUIDE.md`](./PHASE_4_DEPLOYMENT_GUIDE.md)

### **Integration Checklist:**

**Day 1 (2-3 hours):**
- [ ] Import Phase 4 modules in sniper.py
- [ ] Add signal generation tracking
- [ ] Add validation result tracking
- [ ] Add armed signal tracking
- [ ] Add trade execution linking
- [ ] Integrate alert system in main loop
- [ ] Add EOD digest generation
- [ ] Test locally
- [ ] Deploy to Railway
- [ ] Verify deployment in logs

**Days 2-14 (Passive):**
- [ ] Monitor signal funnel daily
- [ ] Check hourly digests
- [ ] Review EOD summaries
- [ ] Verify data populating signal_events table
- [ ] Collect 20+ closed trades

**End of Week 2:**
- [ ] Run `adaptive_historical_tuner.py`
- [ ] Review performance by grade, ticker, time
- [ ] Generate first optimization report
- [ ] **Decision Point:** Proceed to Phase 5 or address critical issues

### **Expected Outcomes:**
- ✅ Signal-to-trade funnel visible
- ✅ Real-time alerts working
- ✅ Daily/hourly digests generating
- ✅ 20+ closed trades collected
- ✅ Data ready for ML training (Phase 5)

### **Red Flags:**
- 🚨 No signals generating (<10/day)
- 🚨 High rejection rate (>80%)
- 🚨 No trades executing
- 🚨 System errors in Railway logs

**If red flags appear:** Stop and debug before proceeding to Phase 5.

---

## Phase 5: ML & Advanced Features (Week 3-8)

### **Duration:** 4-6 weeks

### **Prerequisites:**
- ✅ Phase 4 deployed and collecting data
- ✅ 20+ closed trades (minimum)
- ✅ Signal funnel data available
- ✅ No critical system issues

### **Guide:** 
📚 [`PHASE_5_ROADMAP.md`](./PHASE_5_ROADMAP.md)

### **Development Sequence:**

**Week 3-4: ML Signal Scoring**
- [ ] Build feature extraction pipeline
- [ ] Extract features from historical signals
- [ ] Train Random Forest classifier
- [ ] Backtest ML-enhanced signals
- [ ] Integrate into sniper.py
- [ ] Deploy and monitor

**Target:** ML model accuracy ≥70%, win rate improves 5-10%

**Week 5: Multi-Timeframe Synchronization**
- [ ] Build MTF data fetcher (D1, H4, H1, M15)
- [ ] Implement alignment logic
- [ ] Test MTF filtering
- [ ] Integrate into signal_validator.py
- [ ] Deploy and monitor

**Target:** Reduce false signals by 20-30%

**Week 6: Portfolio Optimization**
- [ ] Implement Kelly position sizing
- [ ] Add correlation checks
- [ ] Build sector exposure limits
- [ ] Integrate into position_manager.py
- [ ] Test with paper trading
- [ ] Deploy to production

**Target:** Kelly sizing beats fixed sizing by 15%+

**Week 7: Adaptive Parameter Tuning**
- [ ] Build market regime detector
- [ ] Create regime-based parameter adjustment
- [ ] Backtest adaptive params
- [ ] Integrate into config loader
- [ ] Deploy and monitor

**Target:** Optimized performance per market regime

**Week 8: Enhanced Exit Management**
- [ ] Implement trailing stops (post-T1)
- [ ] Add time-based exits
- [ ] Build partial profit-taking logic
- [ ] Integrate into position_manager.py
- [ ] Test and deploy

**Target:** Trailing stops lock in 10-15% more profit

### **Success Metrics (End of Phase 5):**
- ✅ Win rate: 65-75%
- ✅ Sharpe ratio: 2.0+
- ✅ Max drawdown: <10%
- ✅ Profitable 70%+ of weeks

### **Parallel Execution:**

While building Phase 5, Phase 4 continues collecting data in production. This means:
- You're building ML models based on growing dataset
- You can validate Phase 5 features against live Phase 4 data
- No downtime - War Machine keeps trading

---

## Option C: Debug Current Setup (Ongoing)

### **Duration:** Ongoing, every 2-4 weeks

### **Prerequisites:**
- ✅ Phase 4 deployed
- ✅ 20+ closed trades collected
- ✅ Signal funnel data available

### **Guide:** 
📚 [`DEBUGGING_GUIDE.md`](./DEBUGGING_GUIDE.md)

### **Debugging Cycle (Every 2-4 weeks):**

**Step 1: Run Historical Analysis**
```bash
python adaptive_historical_tuner.py
```

**Step 2: Query Signal Funnel**
```sql
SELECT stage, COUNT(*) 
FROM signal_events 
WHERE session_date >= CURRENT_DATE - INTERVAL '14 days'
GROUP BY stage;
```

**Step 3: Validate Grade Performance**
```sql
SELECT grade, win_rate, expected_wr 
FROM grade_performance_analysis;
```

**Step 4: Analyze Bottlenecks**
- Too few signals?
- High rejection rate?
- Low arm rate?
- Execution issues?

**Step 5: Run Parameter Optimizer**
```bash
python parameter_optimizer.py --min-trades 30
```

**Step 6: Apply Recommendations**
- Update stop widths
- Adjust targets
- Whitelist/blacklist tickers
- Block poor time windows

**Step 7: Deploy and Monitor**
```bash
git add config.py
git commit -m "feat: Apply optimizer recommendations"
git push origin main
```

**Step 8: Repeat in 2-4 weeks**

### **When to Debug:**

**Checkpoint 1 (After 20 trades):**
- Basic analysis
- Identify obvious issues
- Quick parameter tweaks

**Checkpoint 2 (After 50 trades):**
- Full optimization
- Statistical significance reached
- Major parameter adjustments

**Checkpoint 3 (After 100 trades):**
- Comprehensive review
- ML model retraining
- Strategy validation

**Ongoing (Every 2 weeks):**
- Monitor key metrics
- Quick adjustments
- Continuous optimization

---

## Integration Points: Phase 4 + Phase 5 + Debug

### **How They Work Together:**

```
Phase 4 (Monitoring)
    ↓
  Collects Data
    ↓
    ├─→ Feeds Phase 5 (ML Training)
    |
    └─→ Enables Option C (Debugging)
         ↓
    Parameter Adjustments
         ↓
    Improved Performance
         ↓
    More Quality Data
         ↓
    Better ML Models
         ↓
    Cycle Continues...
```

### **Data Flow:**

1. **Phase 4 tracks every signal:**
   - Generation → Validation → Armed → Traded
   - Stores in `signal_events` table

2. **Phase 5 trains on this data:**
   - Extract features from signal_events
   - Train ML models
   - Predict win probability

3. **Option C optimizes based on results:**
   - Analyze closed positions
   - Identify patterns
   - Tune parameters
   - Feed back into system

4. **Improved system generates better data:**
   - Higher quality signals
   - Better ML training data
   - More accurate predictions
   - Virtuous cycle

---

## Weekly Routine (After Full Deployment)

### **Daily (During Market Hours):**
- Monitor hourly P&L digests
- Watch for circuit breaker alerts
- Check Railway logs for errors

### **Daily (After Market Close):**
- Review EOD digest
- Check closed positions
- Verify data quality

### **Friday (Weekly Review):**
- Read weekly digest
- Review win rate by grade
- Check signal funnel metrics
- Identify any trends

### **Bi-Weekly (Optimization Cycle):**
- Run `adaptive_historical_tuner.py`
- Run `parameter_optimizer.py`
- Review recommendations
- Apply approved changes
- Deploy updates

### **Monthly (Deep Analysis):**
- Comprehensive performance review
- ML model retraining
- Strategy validation
- Plan next phase improvements

---

## Risk Management

### **During Phase 4 Deployment:**
- ⚠️ Low risk (monitoring doesn't affect trading)
- ✅ Can rollback if issues
- ✅ Test locally before deploying

### **During Phase 5 Development:**
- ⚠️ Medium risk (new features could break things)
- ✅ Develop in parallel, don't disrupt Phase 4
- ✅ Test extensively before integrating
- ✅ Paper trade new features before live

### **During Parameter Optimization:**
- ⚠️ Low risk (gradual adjustments)
- ✅ Apply changes incrementally
- ✅ Monitor for 2-3 days after changes
- ✅ Rollback if performance degrades

---

## Success Criteria

### **Phase 4 Success:**
- [ ] Signal funnel visible in database
- [ ] Alerts triggering correctly
- [ ] Daily/hourly digests generating
- [ ] 20+ trades collected in 2 weeks
- [ ] No critical errors

### **Phase 5 Success:**
- [ ] ML model accuracy ≥70%
- [ ] Win rate improves by 5-10%
- [ ] Sharpe ratio increases
- [ ] Max drawdown decreases
- [ ] System stable

### **Debugging Success:**
- [ ] Grade performance matches targets
- [ ] Stop hit rate 20-30%
- [ ] Target hit rate 60-70%
- [ ] No persistent losing streaks
- [ ] Consistent weekly profitability

---

## Troubleshooting

### **Issue: Phase 4 deployment fails**
- Check import statements
- Verify all Phase 4 files committed
- Check Railway logs for errors
- Test locally first

### **Issue: Phase 5 ML model performs poorly**
- Need more training data (aim for 200+ trades)
- Check for data leakage
- Try different model (XGBoost vs Random Forest)
- Validate feature engineering

### **Issue: System stops generating signals**
- Check scanner is running
- Verify ticker list
- Review signal criteria (too strict?)
- Check Railway service status

### **Issue: Win rate not improving**
- Run debugger after 50+ trades
- Check if grading too lenient
- Review stop placement
- Validate entry timing
- Consider market conditions

---

## Next Steps (Immediate)

### **Today:**
1. Pull latest code: `git pull origin main`
2. Open [`PHASE_4_DEPLOYMENT_GUIDE.md`](./PHASE_4_DEPLOYMENT_GUIDE.md)
3. Start integration (Step 1: Imports)
4. Work through each integration point
5. Test locally

### **Tomorrow:**
6. Deploy to Railway
7. Monitor logs
8. Verify first signals being tracked
9. Check hourly digest at top of hour

### **Week 1:**
- Monitor daily
- Verify all tracking points
- Check EOD digests
- Collect 5-10 trades

### **Week 2:**
- Collect 10-20 more trades
- Run first historical analysis
- Review signal funnel
- **Decision point:** Start Phase 5 or debug first

---

## Resource Links

### **Deployment Guides:**
- 📚 [Phase 4 Deployment Guide](./PHASE_4_DEPLOYMENT_GUIDE.md) - Integration instructions
- 📚 [Phase 5 Roadmap](./PHASE_5_ROADMAP.md) - ML features
- 📚 [Debugging Guide](./DEBUGGING_GUIDE.md) - Systematic debugging

### **Analysis Tools:**
- `adaptive_historical_tuner.py` - Performance analysis
- `parameter_optimizer.py` - Parameter recommendations
- `db_diagnostic.py` - Database inspection

### **Railway Dashboard:**
- [Your War Machine Deployment](https://railway.app)
- PostgreSQL database
- Logs and metrics

---

## Summary

**Your 3-Part Plan:**

1. **✅ Phase 4 (Week 1-2):** Deploy monitoring → Collect data
2. **🛠️ Phase 5 (Week 3-8):** Build ML features → Enhanced system
3. **🔍 Option C (Ongoing):** Debug with data → Continuous optimization

**Timeline:** 8-10 weeks to fully optimized, ML-enhanced system

**Current Priority:** Start with Phase 4 deployment (2-3 hours work)

**Ready to begin?** Open [`PHASE_4_DEPLOYMENT_GUIDE.md`](./PHASE_4_DEPLOYMENT_GUIDE.md) and start with Step 1!
