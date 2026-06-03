# Redis Market Data Poller Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Point Redis connection to the VM and reduce market data poller interval to 1 minute.

**Architecture:** Two config/code changes — update `REDIS_HOST` in `.env` to point to `156.67.27.164`, and change the poller sleep from 10s to 60s in `main.py`. The existing market-hours detection logic already skips API calls when markets are closed.

**Tech Stack:** FastAPI, Redis (async), Docker, Upstox API

---

### Task 1: Update Redis Host Configuration

**Files:**
- Modify: `.env`

- [ ] **Step 1: Update REDIS_HOST in .env**

Change `REDIS_HOST` from `127.0.0.1` to `156.67.27.164`:

```
REDIS_HOST=156.67.27.164
```

- [ ] **Step 2: Verify the change**

```bash
grep REDIS_HOST .env
```

Expected output:
```
REDIS_HOST=156.67.27.164
```

---

### Task 2: Change Poller Interval to 1 Minute

**Files:**
- Modify: `app/main.py:33`

- [ ] **Step 1: Update the sleep interval**

In `app/main.py`, line 33, change:

```python
await asyncio.sleep(10)
```

to:

```python
await asyncio.sleep(60)
```

- [ ] **Step 2: Verify the change**

```bash
grep -n "asyncio.sleep" app/main.py
```

Expected output:
```
33:            await asyncio.sleep(60)
```

---

### Task 3: Start the Backend and Verify Redis Connection

- [ ] **Step 1: Start the server**

```bash
cd /Users/madhusha/companies/arinedge/dev/portal/backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- [ ] **Step 2: Check logs for Redis connection**

Look for log line:
```
Connected to Redis at 156.67.27.164:6379
```

- [ ] **Step 3: Verify market data endpoint returns data**

```bash
curl http://localhost:8000/api/v1/market-data
```

Expected: JSON response with `market_status`, `indices`, `fii`, `dii` fields.

- [ ] **Step 4: Verify poller heartbeat**

Check logs for:
```
Market data poller started
```

And after 60s:
```
Stored N live market data points
```
(or cached response if market closed)
