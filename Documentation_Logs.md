# Supply Chain Game – Decision Log

## Day 1 – 30 March 2026

### 1. Initialization and Setup (1:00pm)
We set up fulfillment from our Calopeia warehouse to all other regions to make up for the lost demand that we had till now.

### 2. New Factory in Entworpe (1:45pm)

**Decision:** Opened a new factory in Entworpe with capacity **31 drums/day**.

**Rationale:**
- Entworpe underwent a **regime change**: demand activity jumped from 1.1% of days historically to 7.8% recently, with consistent 250-unit bulk orders.
- Time-decayed average demand = 23.5 units/day. With a 1.3x buffer → 31 drums/day capacity.
- At current loss levels, Entworpe represents **$9.3M/year** in lost revenue (highest of all regions).
- Build cost: $500K fixed + 31 × $50K equipment = **$2.05M**. Estimated payback: ~349 days.
- Net revenue per drum after production ($1,000) and fulfillment ($200) costs: $250/drum.
- Between typical orders (~12 days apart), factory produces 372 units — enough for one 250-unit order plus 122-unit buffer.
- The factory will take 90 days to complete construction.

**Current cash position:** $6.6M — investment is comfortably funded.

### 3. New Factory in Tyran (2:00pm)

**Decision:** Opened a new factory in Tyran with capacity **21 drums/day**.

**Rationale:**
- Tyran has the **worst service rate** of the remaining regions at 3.0%, with **$7.7M/year** in lost revenue (highest after Entworpe).
- Demand is steady: 92.2% of recent days active, ~16.0 units/day (time-decayed), avg order size ~19 drums.
- Calopeia factory spare capacity after Entworpe goes local = 14.5 d/d — not enough to cover Tyran's 16.0 d/d, so a local factory is required.
- Time-decayed avg demand = 16.0 units/day × 1.3 buffer → 21 drums/day capacity.
- Build cost: $500K fixed + 21 × $50K equipment = **$1.55M**. Estimated payback: ~388 days.
- Net revenue per drum after production ($1,000) and fulfillment ($200) costs: $250/drum.
- The factory will take 90 days to complete construction.

**Cash position after Entworpe + Tyran:** ~$6.6M − $2.05M − $1.55M = **~$3.0M remaining**.

### 4. New Factory in Sorange (3:15pm)

**Decision:** Opened a new factory in Sorange with capacity **21 drums/day**.

**Rationale (based on fresh data pull at Day 770):**
- Sorange demand is **increasing sharply**: demand nearly doubled across 30-day thirds (277 → 381 → 541 drums), with 100% of the last 30 days active.
- Time-decayed average demand = 15.6 units/day (90d), rising to 18.4 (30d). With 1.3x buffer → 21 drums/day capacity.
- Service rate is only **24.1%** — losing 3 out of 4 orders.
- Annual lost revenue estimated at **$4.5M/year**.
- Build cost: $500K fixed + 21 × $50K equipment = **$1.55M**. Estimated payback: ~397 days.
- Net revenue per drum after production ($1,000) and fulfillment ($200) costs: $250/drum.
- The factory will take 90 days to complete construction.

**Cash position:** $3.77M at Day 770 — tight after three factory investments but still positive. Revenue from Calopeia operations continues to generate cash flow while factories are under construction.

**Next steps to consider:**
- Build warehouses in Entworpe, Tyran, and Sorange to buffer stock once their factories complete (~Day 847–860).
- Avoid Fardo for now — $400/drum fulfillment cost results in only $50/drum net margin and a 2,054-day payback.
- Re-run the optimization pipeline after factories come online to reassess Calopeia warehouse (s,Q) parameters — demand served by Calopeia will drop significantly once three local factories are operational.
- Monitor cash balance closely; three simultaneous factory builds with no immediate revenue return.
