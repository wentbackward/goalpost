# Social Analytics Dashboard — Design Document

**Project:** Goalpost — Paul Gresham Advisory LLC  
**Version:** 1.0  
**Date:** April 2026  
**Status:** Ready for Implementation

---

## 1. Overview

This document specifies the frontend dashboard for the Goalpost social analytics platform. The backend is a FastAPI collector running at `fragola:8060` that aggregates post metrics across X/Twitter, LinkedIn, Instagram, Facebook, and YouTube. The dashboard is a read-mostly client that renders that data; it does not write to any social platform.

---

## 2. Technology Recommendation

### Recommended Stack: Next.js 15 (App Router) + Tailwind CSS + Tremor + Recharts

**Decision rationale:**

| Criterion | Next.js + Tremor | React + Vite | SvelteKit |
|---|---|---|---|
| Component ecosystem | Largest | Large | Growing |
| Dashboard UI library fit | Tremor is React-native | Any | Svelte-specific only |
| TypeScript DX | Good | Good | Excellent |
| Bundle size | ~80KB baseline | ~50KB | ~15KB |
| Deployment flexibility | Any (static export OK) | Any | Any |

Tremor gives production-ready KPI cards, area charts, bar charts, and donut charts with zero design work.

**Full dependency list:**
```
next@15
react@19
react-dom@19
@tremor/react@3
recharts@2
tailwindcss@4
date-fns@4
swr@2
```

**Recommended project layout:**

```
dashboard/
├── app/
│   ├── layout.tsx
│   ├── page.tsx                          # redirects to /overview
│   ├── overview/page.tsx
│   ├── posts/page.tsx
│   ├── posts/[id]/page.tsx
│   └── api/
│       └── collector/[...path]/route.ts  # proxy to fragola:8060
├── components/
│   ├── layout/
│   │   ├── Sidebar.tsx
│   │   ├── Topbar.tsx
│   │   └── PlatformFilter.tsx
│   ├── overview/
│   │   ├── KpiSummaryRow.tsx
│   │   ├── EngagementTrendChart.tsx
│   │   ├── PlatformBreakdownChart.tsx
│   │   ├── MediaTypeSplit.tsx
│   │   └── TopPostsTable.tsx
│   ├── posts/
│   │   ├── PostsTable.tsx
│   │   ├── PostRow.tsx
│   │   └── PostFilters.tsx
│   └── post-detail/
│       ├── MetricHistoryChart.tsx
│       └── MetricSnapshotCards.tsx
├── lib/
│   ├── api.ts
│   ├── formatters.ts
│   └── platform-config.ts
├── hooks/
│   ├── useOverview.ts
│   ├── usePosts.ts
│   └── usePostMetrics.ts
└── types/
    └── api.ts
```

---

## 3. Dashboard Views

### 3.1 View 1 — Overview (primary landing view)

Answers: "How is my content performing across all channels right now?"

```
┌──────────────────────────────────────────────────────────────────────┐
│ TOPBAR: "Goalpost"                              [Sync Now]  [Health] │
├────────┬─────────────────────────────────────────────────────────────┤
│        │  Date Range: [Last 30 days ▾]   Platform: [All ▾]          │
│  SIDE  │                                                              │
│  BAR   │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌───────┐│
│        │  │  Impressions│ │  Reach      │ │  Engagement │ │ Posts ││
│ Ovrvw  │  │  48,200     │ │  31,400     │ │  Rate 3.2%  │ │   32  ││
│ Posts  │  │  ↑12% MoM   │ │  ↑8% MoM   │ │  ↓0.4pp MoM │ │  new  ││
│        │  └─────────────┘ └─────────────┘ └─────────────┘ └───────┘│
│        │                                                              │
│        │  ┌────────────────────────────────────┐ ┌──────────────────┐│
│        │  │ Engagement Over Time (Area Chart)  │ │ By Platform      ││
│        │  │  30-day daily, one line/platform   │ │ (Horizontal Bar) ││
│        │  └────────────────────────────────────┘ │ Twitter   12,000 ││
│        │                                          │ Instagram  9,800 ││
│        │  ┌─────────────────┐ ┌──────────────────┤ Facebook   8,400 ││
│        │  │ Media Type Split│ │ Top 10 Posts     │ YouTube    7,200 ││
│        │  │ (Donut Chart)   │ │ (Sortable table) │ LinkedIn  pending││
│        │  │ Image 45%       │ │ Platform | Date  │                  ││
│        │  │ Video 30%       │ │ Imp. | Eng. Rate │                  ││
│        │  │ Text  25%       │ │ [snippet...]     │                  ││
│        │  └─────────────────┘ └──────────────────┘                  │
└────────┴─────────────────────────────────────────────────────────────┘
```

### 3.2 View 2 — Posts Table

```
│  Filters: [Platform ▾] [Media Type ▾] [Date Range ▾]  [Search]     │
├─────────────────────────────────────────────────────────────────────┤
│  Platform │ Date       │ Media │ Preview         │ Imp. │ Eng%     │
│  🐦Twitter│ Apr 5      │ text  │ "Check out..."  │ 3,400│ 4.1%     │
│  📸Insta  │ Apr 4      │ image │ "Spring..."     │ 6,200│ 5.8%     │
│  ▶YouTube │ Apr 2      │ video │ "How to..."     │12,000│ 2.9%     │
│  [← Prev]  Page 1 of 4  [Next →]                                    │
```

- Clicking a row navigates to Post Detail
- Sortable by Impressions and Engagement Rate
- Default sort: newest first

### 3.3 View 3 — Post Detail

```
│  ← Back to Posts                                                     │
│  🐦 Twitter · image · Apr 5, 2026                                   │
│  "Check out this new advisory framework for..."                      │
│                                                                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐               │
│  │Impressions│ │  Likes  │ │ Comments │ │  Shares  │               │
│  │  3,400   │ │   112   │ │    18    │ │    9     │               │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘               │
│                                                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │ Metric History (Multi-Line Chart)                             │  │
│  │  X: sync timestamps  Y-left: impressions  Y-right: engagement │  │
│  └───────────────────────────────────────────────────────────────┘  │
│  Engagement Rate: 4.09%  =  (112 + 18 + 9) / 3,400                 │
```

---

## 4. Key Metrics and KPIs

### Primary KPIs

| KPI | Formula | Notes |
|---|---|---|
| Total Impressions | Sum of latest `impressions` per post | Twitter + Facebook primary |
| Total Reach | Sum of latest `reach` per post | Instagram + Facebook only |
| Engagement Rate | (likes + comments + shares) / impressions | Per-post and aggregate |
| Total Posts | Count of posts in window | |
| Total Video Views | Sum of `video_views` | YouTube + Facebook + IG Reels |

### Engagement Rate Formula

```
engagement_rate = (likes + comments + shares) / impressions
```

- Null values treated as 0
- If `impressions` is null (Instagram), use `reach` as denominator
- Display "—" if both impressions and reach are null
- Display as percentage: `0.042 → "4.2%"`

### Platform Availability Matrix

| Metric | Twitter | Instagram | YouTube | Facebook | LinkedIn |
|---|---|---|---|---|---|
| Impressions | Yes | — | — | Yes | Pending |
| Reach | — | Yes | — | Yes | Pending |
| Likes | Yes | Yes | Yes | Yes | Pending |
| Comments | Yes | Yes | Yes | Yes | Pending |
| Shares | Yes | Yes | — | Yes | Pending |
| Saves | — | Yes | — | — | — |
| Clicks | — | — | — | Yes | Pending |
| Video Views | — | Yes (reels) | Yes | Yes | — |
| Watch Time | — | — | Yes | Yes | — |

---

## 5. Charts and Visualizations

### 5.1 Engagement Trend — Area Chart

- **Component:** `EngagementTrendChart` → Tremor `AreaChart`
- **X axis:** Date (daily buckets, last 30 days)
- **Y axis:** Total engagement actions (likes + comments + shares)
- **Series:** One line per active platform, or stacked total
- **Toggle:** "By Platform" | "Total"

### 5.2 Platform Breakdown — Horizontal Bar Chart

- **Component:** `PlatformBreakdownChart` → Tremor `BarList`
- **Data source:** `GET /analytics/summary` → `by_platform`
- **Metric toggle:** Impressions | Reach | Engagement

### 5.3 Media Type Split — Donut Chart

- **Component:** `MediaTypeSplit` → Tremor `DonutChart`
- **Segments:** image, video, text, unknown
- **Center label:** Total posts count

### 5.4 Top Posts — Sortable Table

- **Component:** `TopPostsTable`
- **Data source:** `GET /analytics/summary` → `top_posts` (top 10 by impressions)
- **Columns:** Platform icon, Date, Content preview (60 chars), Impressions, Engagement Rate
- **Sort:** Toggle between impressions and engagement rate

### 5.5 Metric History — Multi-Line Chart

- **Component:** `MetricHistoryChart` → Recharts `ComposedChart` (dual Y-axis)
- **Data source:** `GET /posts/{id}/metrics`
- **Series:** impressions/reach (left axis), likes/comments/shares (right axis)
- **Empty state:** "Only one data point — sync again later to see trends"

---

## 6. API Usage Pattern

### Proxy Architecture

All browser requests go to `/api/collector/*` (Next.js API route) which adds the Bearer token server-side. `COLLECTOR_API_KEY` never reaches the browser.

```typescript
// app/api/collector/[...path]/route.ts
export async function GET(request: Request, { params }: { params: { path: string[] } }) {
  const targetUrl = `${process.env.COLLECTOR_BASE_URL}/${params.path.join('/')}${new URL(request.url).search}`;
  return fetch(targetUrl, {
    headers: { Authorization: `Bearer ${process.env.COLLECTOR_API_KEY}` },
  });
}
```

### API Calls Per View

**Overview — on mount:**
```
GET /api/collector/analytics/summary?start_date=<30d_ago>&end_date=<now>
GET /api/collector/analytics/summary?start_date=<60d_ago>&end_date=<30d_ago>  ← MoM delta
GET /api/collector/posts?limit=200&published_after=<30d_ago>                   ← trend chart
GET /api/collector/health
```

**Posts view:**
```
GET /api/collector/posts?platform=<p>&media_type=<m>&published_after=<d>&limit=50&offset=<n>
```

**Post Detail:**
```
GET /api/collector/posts/<id>/metrics
```

**Sync:**
```
POST /api/collector/sync
→ poll GET /api/collector/sync/<sync_id> every 3s until status !== "running"
→ revalidate overview + posts data on completion
```

### SWR Refresh Strategy

- Overview data: `refreshInterval: 5 * 60 * 1000` (5 min)
- Posts table: `refreshInterval: 5 * 60 * 1000`
- Post detail: no auto-refresh (append-only data)
- Health: `refreshInterval: 60 * 1000` (60 sec)

---

## 7. TypeScript Types

```typescript
// types/api.ts

export type MetricSnapshot = {
  synced_at: string;
  impressions: number | null;
  reach: number | null;
  likes: number | null;
  comments: number | null;
  shares: number | null;
  saves: number | null;
  clicks: number | null;
  video_views: number | null;
  video_watch_time_ms: number | null;
};

export type PostResponse = {
  id: string;
  platform: string;
  platform_post_id: string;
  content_text: string | null;
  media_type: string | null;
  published_at: string | null;
  created_at: string;
  updated_at: string;
  latest_metrics: MetricSnapshot | null;
};

export type PostListResponse = {
  posts: PostResponse[];
  total: number;
  limit: number;
  offset: number;
};

export type PostMetricsResponse = {
  post: PostResponse;
  metrics: MetricSnapshot[];
};

export type PlatformTotals = {
  posts: number;
  impressions: number;
  likes: number;
  comments: number;
  shares: number;
  video_views: number;
};

export type TopPost = {
  post_id: string;
  platform: string;
  published_at: string | null;
  impressions: number;
  engagement_rate: number;
};

export type AnalyticsSummaryResponse = {
  period: { start: string; end: string };
  totals: PlatformTotals;
  by_platform: Record<string, PlatformTotals>;
  by_media_type: Record<string, PlatformTotals>;
  top_posts: TopPost[];
};

export type SyncStatusResponse = {
  sync_id: string;
  status: 'running' | 'completed' | 'failed';
  triggered_at: string;
  completed_at: string | null;
  posts_synced: number;
  posts_failed: number;
  error_summary: string | null;
  duration_ms: number | null;
};
```

---

## 8. Platform Config

```typescript
// lib/platform-config.ts
export const PLATFORMS = {
  twitter: {
    label: 'X / Twitter',
    color: '#000000',
    availableMetrics: ['impressions', 'likes', 'comments', 'shares'],
  },
  instagram: {
    label: 'Instagram',
    color: '#E1306C',
    availableMetrics: ['reach', 'likes', 'comments', 'shares', 'saves', 'video_views'],
  },
  facebook: {
    label: 'Facebook',
    color: '#1877F2',
    availableMetrics: ['impressions', 'reach', 'likes', 'comments', 'shares', 'clicks', 'video_views', 'video_watch_time_ms'],
  },
  youtube: {
    label: 'YouTube',
    color: '#FF0000',
    availableMetrics: ['video_views', 'likes', 'comments'],
  },
  linkedin: {
    label: 'LinkedIn',
    color: '#0A66C2',
    availableMetrics: [],  // pending API approval
  },
};
```

---

## 9. Key Helper Functions

```typescript
// lib/api.ts

/** Build daily-bucketed trend data from posts list for EngagementTrendChart */
export function buildTrendData(posts: PostResponse[]): TrendDataPoint[] { ... }

/** Compute engagement rate — falls back to reach if impressions is null */
export function engagementRate(m: MetricSnapshot): number | null {
  const denom = m.impressions ?? m.reach;
  if (!denom) return null;
  return ((m.likes ?? 0) + (m.comments ?? 0) + (m.shares ?? 0)) / denom;
}

/** Format large numbers: 48200 → "48.2K" */
export function fmtNumber(n: number): string { ... }

/** Format watch time in ms to "H:MM" or "MM:SS" */
export function fmtWatchTime(ms: number): string { ... }
```

---

## 10. Environment Variables

```bash
# dashboard/.env.local
COLLECTOR_BASE_URL=http://fragola:8060   # server-side only
COLLECTOR_API_KEY=changeme_collector_key  # server-side only — never in browser
```

---

## 11. Empty and Error States

| Situation | Display |
|---|---|
| No posts in date range | "No posts found. Adjust the date range or trigger a sync." |
| Provider not configured | Yellow "missing_credentials" badge in Health section |
| LinkedIn pending | Dimmed bar in Platform Breakdown labelled "LinkedIn (pending)" |
| API error | Error banner at top of main content area |
| Metrics all null | Post Detail: cards show "—" with note "No metrics collected yet" |
| First run / empty DB | Zero-state illustration + "Run your first sync to populate data" |

---

## 12. Implementation Sequence

1. **Scaffold** — `npx create-next-app@15 dashboard --typescript --tailwind --app`; install Tremor, SWR, date-fns
2. **Proxy route** — `app/api/collector/[...path]/route.ts`
3. **Types + config** — `types/api.ts`, `lib/platform-config.ts`
4. **API client + helpers** — `lib/api.ts`
5. **Layout shell** — `Sidebar`, `Topbar`, `app/layout.tsx`
6. **Overview view** — KPI cards → Platform breakdown → Media type donut → Trend chart → Top posts table
7. **Posts view** — Table + filters + pagination
8. **Post Detail view** — Snapshot cards + history chart
9. **Sync trigger** — Poll loop + toast notifications
10. **Polish** — Loading skeletons, error boundaries, responsive layout

---

## 13. Non-Goals for This Build

- Authentication / login
- Dark mode
- CSV / PDF export
- Follower growth tracking
- LinkedIn metrics (scaffold UI but show "pending" state)

---

*Design document version 1.0 — April 2026*  
*© 2026 Paul Gresham Advisory LLC*
