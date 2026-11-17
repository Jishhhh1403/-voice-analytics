# ILRP-app — Full Architecture & Developer Reference

> **Purpose of this document**
> This is a complete, deep technical explanation of the **LBG-Rewards-personalization (ILRP-app)** prototype. It is written so that a developer — or a team — can redevelop this system from scratch, reproduce every demo flow, and understand every moving part. It covers: system topology, every microservice, the data model, the AI orchestration pipeline, the Server-Driven UI (SDUI) renderer, the Objective Workspace wizard, the partner demo portals, the blockchain layer, how the three demos work end-to-end, and a full step-by-step rebuild guide.

---

## Table of Contents

1. [Overview & high-level architecture](#1-overview--high-level-architecture)
2. [Repository layout](#2-repository-layout)
3. [Port map & how to run](#3-port-map--how-to-run)
4. [The data layer (PostgreSQL)](#4-the-data-layer-postgresql)
5. [Intelligence Layer service (:8001)](#5-intelligence-layer-service-8001)
6. [QUEST-UI Middleware service (:8002)](#6-quest-ui-middleware-service-8002)
7. [CEAEI Objective Middleware service (:8004)](#7-ceaei-objective-middleware-service-8004)
8. [DLT / Blockchain layer (:8003)](#8-dlt--blockchain-layer-8003)
9. [Unified Rewards Backend (:8000)](#9-unified-rewards-backend-8000)
10. [Frontend portal (:5173) — structure](#10-frontend-portal-5173--structure)
11. [The SDUI component catalogue](#11-the-sdui-component-catalogue)
12. [Objective Workspace wizard](#12-objective-workspace-wizard)
13. [Partner demo portals (Alphamed :5174 & Cavendish :5175)](#13-partner-demo-portals-alphamed-5174--cavendish-5175)
14. [Demo 1 — Insurance journey (Sophie / Maya / standard personas)](#14-demo-1--insurance-journey-sophie--maya--standard-personas)
15. [Demo 2 — Persona personalization (the SDUI committee)](#15-demo-2--persona-personalization-the-sdui-committee)
16. [Demo 3 — Leo's AI-freeform Japan vacation](#16-demo-3--leos-ai-freeform-japan-vacation)
17. [Cross-app hand-off protocol](#17-cross-app-hand-off-protocol)
18. [API reference summary](#18-api-reference-summary)
19. [Explainability & audit](#19-explainability--audit)
20. [Rebuild guide — step by step](#20-rebuild-guide--step-by-step)
21. [Design principles & guardrails](#21-design-principles--guardrails)
22. [CEAEI conversational voice agent (:8005)](#22-ceaei-conversational-voice-agent-8005)

---

## 1. Overview & high-level architecture

The ILRP-app is a **banking rewards personalization prototype** that clones Lloyds Banking Group's (LBG) rewards portal and adds a server-driven, AI-personalized UI layer on top. The central idea: **the backend, not the frontend, decides which reward "cards" each customer sees and in what order**, based on a detected behavioural persona and strict governance.

The system is composed of **seven deployable parts** (six HTTP services + one blockchain node):

```
┌─────────────┐  ┌──────────────┐  ┌────────────────┐  ┌────────────────┐
│  Frontend    │  │  Alphamed    │  │  Cavendish     │  │  (any local or  │
│  Portal       │  │  Partner     │  │  Partner       │  │   nav to other  │
│  :5173 (Vite)│  │  :5174 (Vite)│  │  :5175 (Vite)  │  │   portals)      │
└──────┬───────┘  └──────┬───────┘  └──────┬─────────┘  └────────────────┘
       │                 │                │
       └────────┬──(HTTP)├────────┬───────┘
                ▼         ▼        ▼
   ┌───────────────────────────────────────────────────────────────┐
   │                    Docker Compose network                       │
   │  ┌────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────┐│
   │  │ QUEST-UI   │▶│ Intelligence  │▶│  CEAEI       │ │ Unified  ││
   │  │ Middleware │  │ Layer        │  │  Objective   │ │ Backend  ││
   │  │ :8002      │  │ :8001        │  │  Middleware  │ │ :8000    ││
   │  └─────┬──────┘  └──────────────┘  │  :8004       │ └──────────┘│
   │        │                           └──────────────┘             │
   │        └──────────────┬────────────────────────────────────────┘
   │                       ▼
   │               ┌──────────────┐   ┌──────────────────────────┐
   │               │ DLT Service  │──▶│ Besu (Hyperledger) node  │
   │               │ :8003        │   │ :8545 / :8546            │
   │               └──────┬───────┘   └──────────────────────────┘
   │                      ▼
   │               ┌──────────────┐
   │               │ PostgreSQL   │
   │               │ :5432 (ilrp) │
   │               └──────────────┘
   └───────────────────────────────────────────────────────────────┘
```

### What each piece does

| Part | Port | Role |
|---|---|---|
| **Frontend Portal** | 5173 | React + Vite + MUI mobile-styled SPA. Login, rewards dashboard, personalization renderer, and the Objective Workspace wizard. |
| **QUEST-UI Middleware** | 8002 | The heart of personalization. A LangGraph multi-agent "committee" that generates a validated **SDUI JSON** layout per customer using LLMs (Gemini → Groq failover). |
| **Intelligence Layer** | 8001 | Deterministic rule engine that classifies a customer into a behavioural **persona** and returns motives, recommendations and a component-affinity vector. |
| **CEAEI Objective Middleware** | 8004 | Standalone AI content service that powers the "Set a Goal / Personalise my LBG Coin" **Objective Workspace** wizard (summary, constraints, opportunities, strategies, evidence, execution). |
| **DLT Service** | 8003 | Bridges the app to the Hyperledger Besu blockchain for LBG Coin mint/burn/transfer, and writes `dlt_audit` rows. |
| **Besu node** | 8545/8546 | Private IBFT Ethereum-compatible blockchain running the `LBGCoin` ERC-20 contract. |
| **Unified Rewards Backend** | 8000 | Legacy auth/dashboard backend (JWT login, signup, brand/reward/wallet APIs). Mostly superseded by the middleware's customer APIs but still used for persona summaries. |
| **PostgreSQL** | 5432 | Single shared database for customers, brands, transactions, wallet ledgers, and DLT audit. |

### The two "middleware" services explained

This repository deliberately contains **two independently-running FastAPI middleware services**, which is a common source of confusion:

1. **QUEST-UI Middleware (:8002)** — the **SDUI personalization committee**. Exposes `POST /sdui/generate`. This is what builds the personalized **rewards dashboard** layout.
2. **CEAEI Objective Middleware (:8004)** — the **Objective Workspace content generator**. Exposes `POST /objective/generate`. This is what generates the AI text/video content **inside the "Set a Goal" wizard modal**. It has no database or blockchain dependency.

Here is the clean mental split: **QUEST-UI decides *what cards* go on the dashboard; CEAEI decides *what words/plans* appear in the goal wizard.**

---

## 2. Repository layout

```
ILRP-app/
├── src/                        # Frontend single-page app (:5173)
│   ├── App.tsx                 # Step machine: auth → splash → home → dashboard
│   ├── main.tsx                # React root
│   ├── pages/                  # AuthPage, BankHomePage, SplashPage,
│   │                           # RewardsDashboardPage, BookingPortal, ConvertPointsPortal
│   ├── components/
│   │   ├── auth/               # MobileStep, OtpStep, PasswordStep, SignupStep
│   │   ├── dashboard/          # LocatePointsModal, RedeemPointsModal, MetricTile, CategoryTile
│   │   ├── forms/              # BrandDropdown, OtpInputGroup
│   │   ├── objective/          # ObjectiveWorkspace (wizard), ObjectiveSDUIRenderer, registry/
│   │   ├── rewards-intelligence/  # 72 SDUI card components (+index.ts)
│   │   ├── ui/                 # BottomSheetModal
│   │   └── voice/              # VoiceOverlay, VoiceOrb, TranscriptView, ConfirmationSheet, VoiceButton
│   ├── renderer/
│   │   ├── componentRegistry.ts # span/action helpers
│   │   └── SDUIRenderer.tsx     # Renders SDUI JSON → grid of cards
│   ├── hooks/                 # useVoiceSession, useAudioCapture, useSpeechSynthesis
│   ├── services/               # rewardsApi.ts, experienceApi.ts, objectiveApi.ts, ceaeiChatApi.ts
│   ├── workspace-components/   # Wizard SDUI renderer & 27 wizard sub-components + buildStageComponents.ts
│   ├── types/                  # rewards.ts, sdui.ts, objective.ts, objective-sdui.ts, voice.ts
│   ├── theme.ts, utils/, assets/
│   ├── index.html,
├── intelligence-layer/         # FastAPI persona engine (:8001)
├── middleware/                 # QUEST-UI orchestration committee (:8002)
│   ├── agents/                 # 12 committee members
│   ├── workflow/graph.py       # LangGraph QUEST+R pipeline
│   ├── catalog/                 # 61+ SDUI component catalogue
│   ├── services/                # orchestration, intelligence_client, card_rule_engine, llm_router
│   ├── schemas/                 # state, agent_message, sdui, request/response
│   ├── validators/ transformers/ guardrails/
│   └── explainability/          # per-decision audit bundles
├── ceaei-middleware/           # Objective content generation (:8004)
├── ceaei-agent/                # CEAEI conversational voice agent (:8005)
│   ├── app/
│   │   ├── main.py             # FastAPI REST + SSE + WebSocket transport
│   │   ├── config.py           # env-driven configuration (CEAEI_ aliases supported)
│   │   ├── schemas/            # chat.py, voice.py
│   │   ├── services/           # session_store, agent_core, context_provider,
│   │   │                        # llm_router, stt, upstream, audit
│   │   ├── tools/              # registry + rewards/objective/money tools
│   │   └── prompts/            # agent_system.py
│   └── tests/                  # pytest suite for the agent
├── backend/                    # Legacy FastAPI unified rewards backend (:8000)
├── dlt/                        # DLT/Besu bridge (:8003) + LBGCoin.sol contract
├── besu/                       # Besu genesis + validator node config
├── db/
│   ├── schema.sql               # brands, customers, transactions, dlt_audit
│   └── seed.sql                 # 8 brands + 13 persona customers + sample transactions
├── Cavendish-online/           # Insurance partner portal (:5175)
├── Alphamed/                   # Healthcare partner portal (:5174)
├── docker-compose.yml          # Orchestrates all services
├── design-reference/           # Screenshot images of intended UI
├── description.txt             # Screen-by-screen wizard spec
├── REWARDS_APPLICATION_FLOW.md # Original flow narrative
├── BASE-LINE-2.md              # Large original personalization design doc
└── screens/, assets/
```

---

## 3. Port map & how to run

| Service | External port | Internal container port | Run with |
|---|---|---|---|
| Frontend Portal | 5173 | — | `npm run dev` (Native Vite) |
| Alphamed portal | 5174 | — | `npm run dev:cavendish` actually starts Cavendish; run Alphamed via `cd Alphamed && npm run dev` |
| Cavendish portal | 5175 | — | `npm run dev:cavendish` (from root: `cd Cavendish-online && npm install && npm run dev`) |
| Unified Rewards Backend | 8000 | 8000 | Docker |
| Intelligence Layer | 8001 | 8000 | Docker |
| QUEST-UI Middleware | 8002 | 8000 | Docker |
| DLT Service | 8003 | 8000 | Docker |
| CEAEI Objective Middleware | 8004 | 8000 | Docker |
| CEAEI Voice Agent | 8005 | 8000 | Docker |
| Besu (RPC / WS) | 8545 / 8546 | same | Docker |
| PostgreSQL | 5432 | 5432 | Docker |

> **Important quirk:** Every Python container exposes port **8000** internally but maps to a different **external** port. The frontend always talks to the **external** port.

### Run everything

```bash
# 1. Backend + blockchain + middleware (all in Docker)
docker compose up --build       # brings up postgres, besu, dlt, intelligence, middleware, ceaei + backend

# 2. Frontend
npm install
npm run dev                     # → http://localhost:5173

# 3. Optional partner portals
npm run dev:cavendish            # → http://localhost:5175
#       and in a second terminal:
cd Alphamed && npm install && npm run dev   # → http://localhost:5174
```

### Environment variables

| Variable | Used by | Default / meaning |
|---|---|---|
| `GEMINI_API_KEY`, `GEMINI_API_KEY_1..3` | middleware, ceaei | Gemini LLM keys (multiple for quota rotation). **Middleware requires at least `GEMINI_API_KEY_1`.** |
| `GROQ_API_KEY`, `GROQ_MODEL` | middleware, ceaei | Groq failover provider (`openai/gpt-oss-120b`). |
| `BANK_PRIVATE_KEY`, `BANK_ONCHAIN_ADDRESS` | dlt | The bank's Besu signer. |
| `INTELLIGENCE_SERVICE_URL` | middleware | `http://intelligence-layer:8000` (internal) / `localhost:8001`. |
| `DLT_SERVICE_URL` | intelligence, middleware | `http://dlt:8000` / `localhost:8003`. |
| `DATABASE_URL` | services | `postgresql://ilrp:ilrp_dev_2024@.../ilrp`. |
| `MOCK_OBJECTIVE_MODE` | ceaei | `false` → live LLM; `1/true` → local canned JSON (offline). |
| `VITE_INTELLIGENCE_API_URL` | frontend | `http://localhost:8001`. |
| `VITE_MIDDLEWARE_API_URL` | frontend | `http://localhost:8002`. |
| `VITE_CEAEI_API_URL` | frontend | `http://localhost:8004`. |
| `VITE_CEAEI_AGENT_URL` | frontend | `http://localhost:8005` — CEAEI conversational voice agent (REST). |
| `VITE_CEAEI_AGENT_WS_URL` | frontend | `ws://localhost:8005` — voice WebSocket transport. |
| `VITE_API_BASE_URL` | frontend | Backend base (`http://localhost:8000`) used by `rewardsApi`. |
| `VITE_LBG_API_BASE_URL` | Alphamed | `http://localhost:8002` (talks to middleware customer APIs). |

> The middleware reads `GEMINI_API_KEY` from `middleware/.env`; the ceaei service reads from `ceaei-middleware/.env`.

---

## 4. The data layer (PostgreSQL)

One database (`ilrp`, `POSTGRES_USER=ilrp`, `POSTGRES_PASSWORD=ilrp_dev_2024`), initialised by `db/schema.sql` then seeded by `db/seed.sql`.

### Tables (`db/schema.sql`)

- **`brands`** — loyalty programmes. Columns: `brand_key` (unique), `name`, `logo_url`, `category`, `points_per_gbp`, `reward_types` (jsonb), `is_active`. Seeded with `alphamedical`, `cavendish_online`, `coffee_house`, `travel_plus`, `fitness_first`, `nippon_air`, `sakura_holidays`, `travelperks`.
- **`customers`** — one row per persona. Columns include: `customer_id` (unique business key, e.g. `customer_001`), `name`, `email`, `points` (LBG coins), `tier`, `engagement_score`, JSON blobs `behaviors`, `signals`, `rewards_history`, `goals`, `personality_insights`, `motive_scores`, plus scalar `expiring_points`, `days_until_expiry`, `challenges_completed`, `badges`, `streak_days`, `leaderboard_rank`, `wallet_address`, `alphamed_points`, `cavendish_points`, `partner_points`.
- **`transactions`** — wallet ledger. Columns: `customer_id`, `tx_type` (`EARN`/`REDEEM`/`EXPIRE`/`TRANSFER`/`CONVERT`), `points`, `description`, `brand_key`, `reward_name`, `status`, `dlt_tx_hash`, `blockchain_metadata`, `created_at`.
- **`dlt_audit`** — blockchain operation log. Columns: UUID `id`, `customer_id`, `operation` (`MINT`/`BURN`/`TRANSFER`), `amount`, `from_address`, `to_address`, `tx_hash`, `block_number`, `block_timestamp`, `gas_used`, `gas_price_gwei`, `network` (`besu-local`), `status`, `error_message`, `metadata`, `created_at`.

A trigger (`trg_customers_updated_at`, `trg_brands_updated_at`) auto-updates `updated_at` on UPDATE.

### Seed data (`db/seed.sql`)

**13 persona customers**, each tuned to trigger a specific classification:

| customer_id | Name | LBG coins | Tier | Classifies as | Key trait |
|---|---|---|---|---|---|
| `customer_001` | Alex Rivera | 4,250 | Gold | `INSTANT_GRATIFICATION` | high immediate redemption rate |
| `customer_002` | Sarah Chen | 6,820 | Platinum | `GOAL_ORIENTED_SAVER` | high goal completion |
| `customer_003` | David Park | 28,400 | Diamond | `LONG_TERM_PLANNER` | very long redemption horizon |
| `customer_004` | Jessica Martinez | 1,850 | Silver | `CHURN_RISK` | 45 days inactive, expiring points |
| `customer_005` | Marcus Johnson | 8,750 | Gold | `GAMIFICATION_MOTIVATED` | 12 challenges, 34-day streak |
| `customer_006` | Priya Sharma | 15,400 | Platinum | `MIXED_PROFILE` | goals + gamification |
| `customer_007` | Elena Vasquez | 24,500 | Diamond | `PLANNER_AT_RISK_MIX` | long-term + at-risk |
| `customer_008` | Ryan Okafor | 3,600 | Gold | `INSTANT_AT_RISK_MIX` | instant + at-risk |
| `customer_009` | Maya Thompson | 5,600 | Gold | `VALUE_CERTAINTY_SEEKER` | needs £-value clarity |
| `customer_010` | Daniel Brooks | 7,300 | Platinum | `PAYMENT_UTILITY_FOCUSED` | statement credits |
| `customer_011` | Sophie Williams | 3,900 | Gold | `EDUCATIONAL_COMPETENCE` | education modules |
| `customer_012` | Leo Morgan | 11,200 | Platinum | `INTEROPERABILITY_SEEKER` | partner portability |
| `customer_013` | Amelia Carter | 6,450 | Gold | `PREVIEW_GUARANTEED_VALUE` | preview-only |

> `customer_012` (Leo) holds balances ONLY in three partner travel programmes (`partner_points=1,000,000`; `alphamed_points=0`, `cavendish_points=0`). His brand points are: Nippon Air 400,000 / Sakura Holidays 350,000 / TravelPerks 250,000 (defined in both `seed.sql` and the frontend `rewardsApi.ts`).

---

## 5. Intelligence Layer service (:8001)

**FastAPI** app (`intelligence-layer/app/main.py`) backed by `MockIntelligenceProvider` (`services/mock_provider.py`) — a **deterministic rule engine**, *not* an ML model.

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/intelligence/customers` | List all persona customers (DB, fallback static) — used by the login persona picker. |
| GET | `/intelligence/customer/{id}` | Classify a customer → full `IntelligenceResponse`. |
| GET | `/brands` | List loyalty brands. |
| POST | `/earn` | Increase points + create `EARN` tx + optional on-chain mint. |
| POST | `/redeem` | Decrease points + create `REDEEM` tx + optional on-chain burn. |
| GET | `/transactions/{customer_id}` | Transaction history. |
| GET | `/dlt/audit/{customer_id}` | DLT audit log. |
| GET | `/dlt/network` | Besu network info. |
| GET | `/dlt/balance/{address}` | LBG token balance. |
| GET | `/health` | DB + DLT connectivity. |

### The persona classification

`MockIntelligenceProvider._analyze_customer()` runs a **two-tier decision tree**:

1. **Card Rule Engine personas (priority)** — threshold tests on `motive_scores`:
   - `VALUE_CERTAINTY_SEEKER`: `valueCertainty ≥ .85` OR `valueConfusionRisk ≥ .75` OR `probNeedValueExplanation ≥ .85`.
   - `PAYMENT_UTILITY_FOCUSED`: `paymentUtility ≥ .85` AND `probPreferPaymentLinkedReward ≥ .80`.
   - `EDUCATIONAL_COMPETENCE`: `competenceMotivation ≥ .85` OR `probPreferEducationReward ≥ .80`.
   - `INTEROPERABILITY_SEEKER`: `portabilityPreference ≥ .85` OR `consolidatedRewardWallet ≥ .85`.
   - `PREVIEW_GUARANTEED_VALUE`: `probPreferRewardPreview ≥ .85` AND `probPreferGuaranteedValue ≥ .80`.

2. **Legacy behavioural personas (fallback)** — heuristics on `behaviors`:
   - Churn-risk mixes → `PLANNER_AT_RISK_MIX` / `INSTANT_AT_RISK_MIX` / `CHURN_RISK` / `MIXED_PROFILE`.
   - `GAMIFICATION_MOTIVATED` (challenges/streak/leaderboard), `INSTANT_GRATIFICATION` (fast redemptions), `LONG_TERM_PLANNER` (slow, high balances), `GOAL_ORIENTED_SAVER` (goal completion).

### `IntelligenceResponse` (the payload firmware)

What the middleware consumes:
```jsonc
{
  "customerId": "customer_011",
  "persona": "EDUCATIONAL_COMPETENCE",
  "confidence": 0.94,
  "motivation": "LEARNING_MASTERY",
  "priority": "HIGH",
  "signals": ["…behavioural strings…"],
  "recommendations": ["LEARNING_PATH", "QUIZ", "…"],
  "goal": { "name", "targetValue", "currentValue", "progress" },
  "goals": [ … ],
  "risk": { "level", "expiringPoints", "daysUntilExpiry" } | null,
  "motiveScores": { "valueCertainty", "…", "dltConfusionRisk" },
  "personalityInsights": { … },
  "componentAffinity": {   // 8-dimension relevance vector (0..1)
    "instant_reward", "goal_progress", "long_term_growth",
    "gamification_social", "value_clarity_education", "partner_discovery",
    "choice_control", "risk_protection"
  },
  "personalizationSignals": {
    "rewardHorizon": "IMMEDIATE|LONG_HORIZON|BALANCED",
    "topMotives": [ … ],
    "preferredTone": "PLAYFUL|EDUCATIONAL|REASSURING|CONCISE",
    "engagementDrivers": [ … ],
    "suppressionHints": [ … ]
  },
  "customerProfile": { …full row… }
}
```

The `componentAffinity` vector and `personalizationSignals` feed directly into the middleware's card-rule engine and Stage S composition directives.

### DB / blockchain clients

- `services/db_client.py` — asyncpg pool, CRUD for customers/brands/transactions/dlt_audit. In `customer_data.py` (the database first/static fallback path).
- `services/besu_client.py` — Web3 client to Besu (`BESU_RPC_URL`). ABIs: `mint`, `burn`, `transfer`, `balanceOf`, `totalSupply`, `decimals`. **In dev, when Besu is unreachable it returns simulated receipts** (`status="SIMULATED"`, SHA-256 derived fake hashes).
- `services/dlt_client.py` — HTTP client to the DLT Service (`DLT_SERVICE_URL`) for `/dlt/mint`, `/dlt/burn`, `/dlt/balance`, `/dlt/network`, `/dlt/audit`.

---

## 6. QUEST-UI Middleware service (:8002)

This is the **single most important service** in the project. It is a *governed multi-agent committee* written on **LangGraph** that composes personalized, validated **SDUI JSON** dashboards using LLMs. It is **journey-first**: the committee first constructs *which customer story and journey* to tell, then maps a narrative-sequenced component set into executable SDUI.

High-level: `POST /sdui/generate` → `OrchestrationService.generate_sdui()`:
1. Fetch intelligence for the customer (`IntelligenceClient` → :8001).
2. Run the deterministic **Card Rule Engine** (binding directive set).
3. Build `QuestUIState`.
4. Run the **QUEST+R LangGraph** (6 stages = **6 LLM calls**; up to 3 retries with exponential backoff on rate limits).
5. Deterministic **reconciliation** (structure repair, anchor enforcement, card-rule stack enforcement, narrative metadata attachment).
6. Build the validation summary.
7. Write an **explainability bundle**.
8. Cache + return the `FinalResponse` (status `PERSONALIZED` or `FALLBACK` + SDUI; the raw intelligence is also attached under `intelligence`).

### The QUEST+R pipeline

The name is the operating sequence. Each letter is a LangGraph stage/node. **Crucially, each stage is ONE committee LLM call** (gemini-3.5-flash-lite) — the whole roster of that stage's agents shares a single prompt, posts structured `AgentMessages`, and produces a JSON verdict. `STAGE_ROSTERS` in `workflow/graph.py` names the participants:

| Stage | Name | Committee roster (STAGE_ROSTERS) | Produces |
|---|---|---|---|
| **Q** | QUESTION | orchestrator, consent-guardian, journey-intent | `taskCharter` (w/ story charter: primaryCustomerOutcome, experienceMode, narrativeModes), consentCheck, journeyAnalysis |
| **U** | UNDERSTAND | context-analyst, journey-intent, reward-psychology, accessibility, consent-guardian, **customer-story-architect**, **session-continuity** | `customerContext`, `rewardInteractionProfile`, `accessibilityAnalysis`, **`storyHypotheses` (2–3, pick one)**, `continuityState` |
| **E** | EVALUATE | personalization-synth, risk-guardian, accessibility, **customer-story-architect**, **journey-composer**, **coherence-guardian** | `candidateEvaluations` (10-criterion weighted scorecard), `approvedCustomerStory`, `journeyCandidates` + pick, `coherenceAssessment`, riskAssessment |
| **S** | STRUCTURE | **journey-composer**, component-planner, **narrative-sequencer**, **session-continuity**, accessibility, constitution-guardian, **coherence-guardian** | `experienceJourneyPlan` (primary journey + 2–6 mini-journeys), exactly one candidate, `narrativeSequence`, continuityPlan, constitutionCheck, `coherenceAssessment` |
| **T** | TRANSLATE | sdui-compiler | `finalSdui` + `fallbackSdui` + `validationResults` |
| **R** | REFINE | red-team, orchestrator, **coherence-guardian**, **session-continuity** | `releaseDecision` RELEASE/HOLD (13-item checklist + deterministic post-compile coherence/continuity) |

**Every inter-stage edge is conditional** and every stage performs quality gating: if `fallback_triggered = True` (any veto, quality-gate failure, or unparseable output), control jumps to a **fallback node** that emits a minimal guaranteed screen (typically just the `POINTS_BALANCE` anchor).

### The 17 agents

All extend `BaseAgent` (`agents/base.py`) giving them `_call_llm`, tolerant JSON parsing, and `_create_message`. The `/health` endpoint lists all 17:

- **Orchestrator** (chair) — frames the Task Charter (Q), makes the final RELEASE/HOLD call (R).
- **Journey & Intent Agent** (`journey_intent.py`) — classifies journey, intent, phase with confidence.
- **Context Analyst** (`context_analyst.py`) — evidence-tiered customer context (observedFacts / declaredPreferences / inferredProperties).
- **Reward Psychology Specialist** (`reward_psychology.py`) — temporary, purpose-bound `rewardInteractionProfile` (Self-Determination Theory).
- **Consent Guardian** (`consent_guardian.py`) — validates consent/purpose, strips prohibited attributes. **VETO**.
- **Accessibility Agent** (`accessibility.py`) — `cognitiveLoadScore < 70`, `recommendedMaxComponents`, WCAG 2.1 AA.
- **Customer Story Architect** (`customer_story_architect.py`) — frames 2–3 evidence-grounded story hypotheses; recommends exactly one narrativeMode.
- **Session Continuity Agent** (`session_continuity.py`) — reads permitted prior-session data; openingTreatment, retirements, suppression; privacy-safe.
- **Personalization Synthesiser** (`personalization_synth.py`) — 10-criterion weighted scorecard.
- **Risk Guardian** (`risk_guardian.py`) — manipulation/dark-pattern/discrimination/vulnerability risk; **VETO** (`E_RISK_VETO`).
- **Journey Composer** (`journey_composer.py`) — translates the approved story into a primary journey + 2–6 mini-journeys.
- **Coherence Guardian** (`coherence_guardian.py`) — story/journey/action coherence votes; **VETO on conflict**.
- **Component Planner** (`component_planner.py`) — maps registered component types into episodes JOURNEY-FIRST.
- **Narrative Sequencer** (`narrative_sequencer.py`) — assigns narrativeRole/sequence/dependsOn; one primary action.
- **Constitution Guardian** (`constitution_guardian.py`) — bank identity, anchored components, wording, tokens. **VETO** (`S_CONSTITUTION_VETO`).
- **SDUI Compiler** (`sdui_compiler.py`) — plan → executable SDUI JSON (never rewrites approved copy).
- **Red-Team Challenger** (`red_team.py`) — 11-item adversarial release checklist (items 10–11 cover narrative coherence and continuity); HOLD → `R_REDTEAM_HOLD`.

**Core safety invariant:** a candidate failing any hard gate loses *regardless of its score*.

### Stage E scoring (10-criterion weighted scorecard)

`customerGoalRelevance 20%` · `expectedCustomerUtility 15%` · `screenLevelStoryCoherence 15%` · `journeyAndActionContinuity 10%` · `accessibilityAndCognitiveFit 10%` · `brandAndLegalConsistency 10%` · `rewardProfileAlignment 5%` · `evidenceConfidence 5%` · `usefulNovelty 5%` · `operationalFeasibility 5%`. All hard gates must pass.

### Journey-first composition (Stage S)

Composition happens **JOURNEY-FIRST**, never "pick cards, then retrofit a story":
1. **Journey skeleton** (Journey Composer) — translate the approved story into ONE primary journey of 2–6 mini-journeys, each with a customer question, entry condition, resolution type (ACTION/UNDERSTANDING/CHOICE/FEEDBACK/CONTINUATION) and transitions. Terminal mini-journey has `transitionsTo: null`.
2. **Component mapping** (Component Planner) — map ONLY registered types into episodes; every non-REFERENCE component belongs to exactly one episode.
3. **Narrative sequence** (Narrative Sequencer) — dense sequence 1..N, `narrativeRole` (ORIENTATION/MEANING/TENSION/EVIDENCE/OPTION/ACTION/FEEDBACK/PAYOFF/CELEBRATION/CONTINUATION/REFERENCE), `dependsOn` (backwards only), one `primaryActionComponentRef`; every ACTION followed by FEEDBACK/PAYOFF/CONTINUATION.
4. **Continuity treatment**, then **accessibility & constitution**, then **coherence self-check**.

After the graph returns, `_attach_narrative_metadata` folds `experienceNarrative` (storyId, primaryOutcome, primaryJourneyId, currentMiniJourneyId, entryMode, primaryActionComponentId) and per-component `narrative` (journeyId/miniJourneyId/role) into the SDUI envelope. The approved narrative sequence is the **ordering authority** (`_reconcile_compiled_order`), while card-rule insertions that were not part of the approved story get fractional positions and a `REFERENCE` role in the least disruptive episode.

### Card Rule Engine (`services/card_rule_engine.py`)

Deterministic, rules R1–R5 (value-certainty, payment-utility, educational-competence, interoperability, preview-guaranteed). Each rule contributes a **mandatory ordered component stack**, possible **banned types**, **suppression flags** (e.g. `suppress_leaderboard`, `suppress_countdowns`), a tone directive, relevance boosts, and a jargon `SANITISATION_MAP` (crypto/blockchain → plain English). These are injected into Stage S. They are **deterministically enforced again** after Stage T (`_enforce_card_rules`): banned types removed, and only genuinely-missing mandated types are deterministically synthesised from real intelligence values and inserted right after the anchor (`_synth_stack_component`).

### Stage S composition rules (binding)

1. **Richness**: **12–18** components per screen (max 20; up to 22 for customers with 4+ goals since each goal gets a card + one `ADD_GOAL_CARD`). Target aims for richness and diversity, not the minimum.
2. **Journey-first**: first non-anchored component ESTABLISHES THE ACTIVE STORY; exactly one dominant primary action; components carry narrativeRole + miniJourneyId.
3. **Anchor**: `POINTS_BALANCE` first, priority 1, `span: full`, always intact.
4. **Persona breadth**: draw from PRIMARY, SECONDARY and SUPPORTING lists — but affinity *guides, never whitelists*: any registered type is available to any persona.
5. **Category coverage (diversity)**: ≥4 of goals / insights / education / rewards / gamification / social / trust.
6. **Multi-goal**: one progress card per goal + exactly one `ADD_GOAL_CARD` after the last goal card.
7. **Real data**: every prop from the actual profile (no `"Customer Name"` placeholders).
8. **Tier-fit rewards**: items ≤ ~2× balance.
9. **Strictly ascending unique priorities** (auto-repaired if duplicated).
10. **Layout spans** (`full`/`half`, pairing two-per-row).
11. **Variety caps**: ≤1 educational, ≤1 analytics, celebration/birthday only on genuine triggers.
12. **Deferrals**: untriggered celebrations, stale actions, semantically orphaned cards, and generic mechanics not central to the story are deferred (tracked via `deferredComponents`).

### Fallback behaviour (first-class, not an error)

Triggers on: charter quality-gate failure, any guardian veto, graph exception after retries, red-team HOLD, empty/unparseable T output, or a post-compile coherence/continuity regression. Always emits a neutral guaranteed screen (typically a lone `POINTS_BALANCE`) and returns `status: "FALLBACK"` with reason codes. When Groq served the request, `GEMINI_QUOTA_GROQ_FAILOVER` is appended to the reason codes.

### Cache & debuggability

- `GET /sdui/cache/stats`, `DELETE /sdui/cache/{customer_id}`, `DELETE /sdui/cache` manage an in-memory SDUI cache keyed by customer.
- `GET /experience/customer/{id}` — convenient wrapper returning `{screen, validation, trace}`.
- `GET /health` — lists all 17 agents + cache stats.

---

## 7. CEAEI Objective Middleware service (:8004)

A **tiny, standalone** FastAPI middleware that only does AI content generation for the Objective Workspace wizard. No DB, no blockchain. Reuses the same quota-aware Gemini→Groq LLM router.

> **Note:** The identical `POST /objective/generate` route *also* exists on the QUEST-UI middleware (:8002) — it imports its own `services/objective_service.py`. The frontend calls the **:8004** copy via `VITE_CEAEI_API_URL`; the two are interchangeable. Keep them in sync when changing objective logic.

### Endpoint

`POST /objective/generate` — request (`ObjectiveGenerateRequest`):
```jsonc
{
  "customerReference": "customer_011",
  "objectiveText": "I want to pay for my insurance using LBG coins while maximizing the value",
  "stage": "summary",          // summary|constraints|opportunities|strategies|evidence|execution
  "selectedPlan": null,
  "toolRequest": null,
  "constraintValues": ["cashback 70", "conversion_rate 10:1", "no_fee"],
  "wallet": { "totalPoints", "tier", "lbgCoins", "brandsConnected", "pointsByBrand": [...] },
  "variant": "standard"         // standard | ai-freeform
}
```

Response (`ObjectiveGenerateResponse`): `status` (`PERSONALIZED`/`REJECTED`), `correlationId`, `screen` (`ObjectiveScreenPayload` — fields vary by stage), `confidence`, `reasonCodes`, optional `error`.

### The two variants

- **`variant: "standard"`** — the fixed **4-plan insurance journey** (Simplicity / Maximum Value / Monitor / No Rewards). Used by Sophie, Maya, and every non-Leo persona.
- **`variant: "ai-freeform"`** — used **only by Leo Morgan (`customer_012`)**. The LLM designs **3–4 fully personalized plans** around Leo's stated personal objective (e.g. Japan vacation), with strict guardrails (per-brand balances, no insurance references, plan diversity, short descriptions).

### Per-stage behaviour (`services/objective_service.py`)

| stage | What it returns | Notes |
|---|---|---|
| `summary` | A warm `summary` sentence restating the objective. | |
| `constraints` | `constraints[]` with `label/value/text/applied`. | Guard strips generic filler ("keep it simple"); anchors on hard facts of the objective (cashback amount, conversion rate, fees) via regex. |
| `opportunities` | `opportunities[]` + `shortlisted[]` + `rejected[]`. | **Not LLM-generated** — they come from `services/partner_offers.py`, filtered by the applied constraints into shortlisted vs rejected buckets. |
| `strategies` | `strategies[]` (`id`, `type`, `title`, `description`, `order`). | Standard → 4 fixed plans (or just `monitor` if objective is monitoring-only). Freeform → 3–4 personalized plans. |
| `evidence` | `evidence.summary` + `evidence.factors[]` (Cognitive Evidence). | Grounded in objective + chosen plan + constraints. |
| `execution` | `executionSteps[]` (`id`, `label`, `partner`, `partnerUrl`, `status`). | Standard insurance → steps hand-off to `:5174` (Alpha Medical) and `:5175` (Cavendish). Freeform → steps hand-off to the in-app portals `:5173/?portal=convert` and `:5173/?portal=booking`. |

### Offline mock mode

`MOCK_OBJECTIVE_MODE=true` short-circuits the LLM and returns deterministic canned JSON (defined in `_mock_content`), so the demo can run without any Gemini/Groq keys. The mock mirrors the exact plan/step shapes the live LLM is instructed to produce, including per-brand wallet phrasing for Leo.

### Constraint extraction helpers

`_applied_constraint_texts()` (regex) pulls numbers out of the free-text objective to drive the offer filter:
- `£70 cashback` / `70 pounds cashback` → `cashback 70`
- `10:1` → `conversion_rate 10:1`
- `no conversion fee` → `no_fee`
- mentions of `insurance`/`premium` → `insurance`

`_is_monitoring_objective()` detects "monitor / keep watching / next 2 weeks / not right now" intent → the standard flow then recommends ONLY the Monitor plan.

---

## 8. DLT / Blockchain layer (:8003 + Besu)

### Besu private network (`besu/`)

- `genesis/genesis-ibft.json` — IBFT 2.0 genesis, chain id `1337`.
- `config/config.toml` + `config/keys/validator.key` — single-validator privacy/network config bound to `BANK_PRIVATE_KEY`.

### The LBG Coin contract (`dlt/contracts/LBGCoin.sol`)

An ERC-20 (`@openzeppelin`) named **"LBG Coin" (symbol `LBGC`)**, 18 decimals. Adds `AccessControl` and `Pausable`:
- `MINTER_ROLE`, `BURNER_ROLE`, `PAUSER_ROLE`.
- `mint(to, amount)` (only MINTER, when not paused).
- `burn(from, amount)` (only BURNER).
- `transferFromAny(from, to, amount)` — operator-driven transfer.
- `pause()` / `unpause()`.

### DLT Service (`dlt/app/main.py`)

On startup it loads-or-deploys the contract (VIP: if Besu is unreachable it falls back to **simulation mode**). Endpoints:

| Method | Path | Purpose |
|---|---|---|
| POST | `/dlt/mint` | Mint `amount` wei to `to_address`; logs `dlt_audit` with operation `MINT`. |
| POST | `/dlt/burn` | Burn tokens; logs `dlt_audit` `BURN`. |
| POST | `/dlt/transfer` | Transfer between wallets; logs `dlt_audit` `TRANSFER`. |
| GET | `/dlt/balance/{address}` | Return `balance_wei` + `balance_lbg`. |
| GET | `/dlt/supply` | Total supply. |
| GET | `/dlt/network` | Network metadata. |
| GET | `/dlt/audit/{customer_id}` | Customer's audit trail. |
| GET/POST | `/dlt/audit` | Audit management. |
| GET | `/health` | DB + Besu (`connected`/`simulated`) + contract address. |

Amounts on-chain are in **wei** (18 decimals); the app multiplies integer points by `10^18`. When Besu is up, every mint/burn is both a real on-chain tx and a `dlt_audit` row; when simulated, only the audit row is written with `status="SIMULATED"`.

---

## 9. Unified Rewards Backend (:8000)

A **legacy** FastAPI + SQLAlchemy async + JWT backend (port 8000). It seeds its own copy of demo data (`13 persona customers`, `29 brands`, `wallet`), but its primary role today is **auth + dashboard summaries for the non-persona demo user** (Alex Morgan). Its endpoints run under `/api/v1`:

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/customers/login/password` | Phone+password → JWT. |
| POST | `/api/v1/customers/signup` | Register → JWT. |
| GET | `/api/v1/customers/lookup/summary?phone=` | Dashboard summary by phone. |
| GET | `/api/v1/customers/persona/{id}/summary` | Token-less summary for persona business IDs. |
| GET | `/api/v1/customers/{id}/summary` | Dashboard summary by UUID. |
| GET | `/api/v1/brands` | List brands. |
| GET | `/api/v1/rewards` | List rewards. |
| GET | `/api/v1/wallet/{id}/transactions` | Wallet ledger. |
| POST | `/api/v1/convert` | Convert reward → LBG coins. |
| GET | `/health` | Health. |

> **Gap worth knowing:** The Alphamed portal calls `POST /api/v1/customers/transfer/alphamedicol` and Cavendish calls `POST /api/v1/customers/pay/cavendish` — **these do NOT exist in the backend**; as reported, both partner frontends **fall back to local simulation** when they fail. Those two customer-management endpoints *do* exist on the **QUEST-UI middleware (:8002)** instead (see [API reference](#18-api-reference-summary)).

Separate from this, the **QUEST-UI middleware (:8002)** exposes its own customer APIs that both the main portal and partner portals actually use for live balances:
- `GET /api/v1/customers/lookup/summary?email=`
- `POST /api/v1/customers/{id}/reseed`
- `POST /api/v1/customers/transfer/alphamedicol`
- `POST /api/v1/customers/pay/cavendish`
- `GET /api/v1/customers/{id}/summary`
- `GET /api/v1/wallet/{customer_id}/transactions`

---

## 10. Frontend portal (:5173) — structure

### App flow (`src/App.tsx`)

A simple **step machine** in React state: `mobile → otp → password | signup → splash → home → dashboard`. Key behaviours:

- `?view=dashboard` auto-logs-in as `customer_demo`.
- Auth via `loginWithPassword` (calls backend, falls back to demo `Alex Morgan`).
- **Persona quick login** (`handlePersonaLogin`): picks a persona from the intelligence layer, builds the wallet summary from the persona profile, calls `reseedDemoBalance`, clears cross-app events, and lands on the splash.
- Session persistence in `localStorage` (`rewards_session_id`, `rewards_session_name`, `rewards_session_snapshot`).
- On return from a partner portal (`?ws_resume=...` or `?cross_app_events=...`), it **skips the splash** and re-opens the workspace where the user left off.
- The portal also renders in-app sub-portals via `?portal=convert` (`ConvertPointsPortal`) and `?portal=booking` (`BookingPortal`) — Leo's two in-app hand-offs.

### Dashboard (`src/pages/RewardsDashboardPage.tsx`)

The rewards home screen. Highlights:
- **Coins hero card** — LBG coin balance with tier (Silver/Gold/Platinum embossed card themes) + tier progress.
- **Three shortcuts**: *Locate Points*, *Redeem Coins*, *Set a Goal*.
- **"Personalise your LBG Coin experience"** button → opens the Objective Workspace.
- Tabs: Home / Activity / Profile. Home shows recent transactions; Activity full ledger; Profile settings.
- `handlePartnerHandoff` — builds a deep-link to a partner portal with `customerEmail`, `customerName`, `customerPhone`, `coinsToApply`, `objective`, `returnTo` (with `ws_resume`), and snapshots the dashboard to `localStorage`.
- Modals: `LocatePointsModal`, `RedeemPointsModal`, `ObjectiveWorkspace`.

### Services (`src/services/`)

- **`rewardsApi.ts`** — brand/customer/transaction API calls to the backend/middleware, with **demo fallbacks**, plus all cross-app event helpers (see §17) and Leo's constants (1000:1 partner→LBG rate, per-brand balances, `travelFocus` classifier, `leoConvertedLbgCoins`).
- **`experienceApi.ts`** — `fetchPersonaOptions()` (from intelligence layer) and `generateExperience()` (POST middleware `/sdui/generate`).
- **`objectiveApi.ts`** — `generateObjectiveStage()` → POST ceaei `/objective/generate`.

### SDUI personalization path

Authenticated *persona* users get a personalized dashboard. The flow:
1. `AuthPage` fetches personas from the intelligence layer.
2. On persona login, the dashboard calls `generateExperience(customerId, wallet)` → middleware `/sdui/generate`.
3. The middleware returns SDUI JSON: `status`, `sdui.components[]` (each with `type`, `props`, `actions`, `priority`, `span`), plus optional `narrative`.
4. `SDUIRenderer` maps each `type` to a React card and lays it out (full-width heroes, half-width pairings, narrative act headers).
5. If the middleware is unreachable, the dashboard shows the **static fallback layout** instead.

---

## 11. The SDUI component catalogue

There are **two mirrored registries** that must stay in sync:

- **Backend:** `middleware/catalog/component_catalog.py` (61 component types) *and* the `VALID_COMPONENT_TYPES` set in `middleware/validators/sdui_validator.py`.
- **Frontend:** the `REGISTRY` in `src/renderer/SDUIRenderer.tsx`, mapping type → React card in `src/components/rewards-intelligence/` (72 files).

**Every component type the middleware may emit must exist in the frontend registry**, or the renderer logs `Unknown component type ... skipped`.

### The card library (grouped)

| Group | Components |
|---|---|
| **Core/legacy SDUI (31)** | `POINTS_BALANCE` (anchored hero), `INSTANT_REWARD_POPUP`, `FLASH_REWARD_BANNER`, `QUICK_REDEEM_CARD`, `TANGIBLE_VALUE_CARD`, `REWARD_CAROUSEL`, `GOAL_PROGRESS_CARD`, `ADD_GOAL_CARD`, `GOAL_MILESTONE_CARD`, `GOAL_LINKED_REWARD`, `RECOMMENDED_ACTIONS`, `FUTURE_VALUE_CARD`, `PROJECTION_CHART`, `LONG_TERM_GOAL_CARD`, `EDUCATIONAL_INSIGHT_CARD`, `FUTURE_MILESTONE_CARD`, `EXPIRING_POINTS_ALERT`, `COUNTDOWN_CARD`, `QUICK_WIN_CARD`, `PERSONALIZED_OFFER_CARD`, `REENGAGEMENT_BANNER`, `STREAK_CARD`, `CHALLENGE_CARD`, `LEADERBOARD`, `QUIZ_CARD`, `BADGE_CARD`, `MILESTONE_CARD`, `BRAND_EXPLORER_CARD`, `SYNC_STATUS_CARD`, `REWARDS_INSIGHT_CARD`. |
| **Educational** | `LEARNING_PATH_CARD`, `DAILY_MONEY_TIP_CARD`, `POINTS_ACADEMY_BADGE_CARD`, `MYTH_OR_FACT_CARD`, `SAVINGS_CALCULATOR_CARD` (Recharts), `COACH_TIP_CARD`, `HOW_POINTS_WORK_CARD`. |
| **Goal rewards & automation** | `GOAL_TEMPLATE_GALLERY`, `MILESTONE_REWARD_LADDER`, `GOAL_STREAK_CARD`, `GOAL_MATCH_BOOST_CARD`, `SHARED_GOAL_CARD`, `GOAL_AT_RISK_CARD`, `AUTO_RULES_CARD`, `GOAL_COMPLETE_CELEBRATION`. |
| **Money-smart** | `BEST_VALUE_REDEEM_CARD`, `SAVINGS_TRANSFER_CARD`, `TRAVEL_FUND_CARD`. |
| **Analytics (Recharts)** | `EARN_BREAKDOWN_CARD` (donut), `MONTH_OVER_MONTH_CARD` (bars), `POINTS_HEALTH_SCORE` (radial gauge). |
| **Social & community** | `PEER_INSIGHT_CARD`, `COMMUNITY_CHALLENGE_CARD`. |
| **Lifecycle** | `MILESTONE_ANNIVERSARY_CARD`, `BIRTHDAY_REWARD_CARD`. |
| **Discovery** | `NEW_BRAND_SPOTLIGHT_CARD`, `LOCAL_DEALS_CARD`. |
| **Control & giving** | `PREFERENCES_CARD`, `GIFT_DONATE_CARD`, `REFERRAL_CARD`. |
| **Value-certainty / transparency** | `REWARD_CHOICE_PANEL`, `PARTNER_VALUE_COMPARISON`, `WHY_THIS_UI_CARD`. |
| **Payment utility** | `PAYMENT_REWARD_CARD`, `REWARD_ALLOCATION_CONTROL`, `PAYMENT_REWARD_CONFIRMATION`. |
| **Educational competence** | `LEARNING_MISSION_CARD`, `COMPREHENSION_FEEDBACK_CARD`, `CONFIDENCE_PROGRESS_CARD`. |
| **Interoperability / portability** | `CONSOLIDATED_REWARD_WALLET`, `PARTNER_TRANSFER_CARD`, `REWARD_PROVENANCE_CARD`, `PROGRAMME_CONNECTION_CARD`. |

### Renderer layout rules (`SDUIRenderer.tsx`)

- `span:"full"` → occupies an entire row.
- `span:"half"` → pairs two-per-row in a 2-column grid; a lone half expands to full-width.
- `POINTS_BALANCE` and `HEADER` are **anchored** (rendered by the app header, never in the stream).
- Narrative `acts[]` split the stream into story sections with act headers.
- Card **actions** map to real modals: `actionTarget(type)` in `componentRegistry.ts` routes arrow actions like `OPEN_LOCATE_MODAL`→Locate, `OPEN_REDEEM_MODAL`→Redeem, `REDEEM_REWARD`→Redeem, etc.

---

## 12. Objective Workspace wizard

This is the "Set a Goal / Personalise your LBG Coin experience" feature — the mobile-first wizard inside a modal. It is driven by **`src/components/objective/ObjectiveWorkspace.tsx`**, rendered via the **workspace SDUI renderer** (`src/workspace-components/`).

### The 12-screen skeleton

Screen IDs `1a` → `4c` (from `description.txt`):

| Phase | Screens | What happens |
|---|---|---|
| **Understand** | `1a` (Capture), `1b` (Summary+Constraints), `1c` (Confirmed objective) | User types objective (or uses quick-start). CEAEI generates a summary + extracts hard-fact constraints. 3-bar progress, segment 1 active. |
| **Explore & decide** | `2a` (Reward opportunities), `2b` (Strategy cards + Coplan tools), `2c` (Cognitive evidence), `2d` (Monitor confirmation), `2e` (No-reward direct pay) | CEAEI lists filtered opportunities, then 4 strategy cards (or 3–4 personalized for Leo). Coplan tools: *Explain / Combine / Edit constraints / Compare*. User picks a plan; evidence is generated. 3-bar progress, segment 2 active. |
| **Execute** | `3a`/`4a` (Execution steps), `3b`/`4b` (Redirect prompt), `3c`/`4c` (Success/failure) | Deterministic, plan-driven flow. `3x` = Plan A / Simplicity track; `4x` = Plan B / Maximum Value track. 3-bar progress, segment 3 active. |

**Key logic in `ObjectiveWorkspace.tsx`**:
- `isFreeform = customerId === 'customer_012'` → Leo runs the `ai-freeform` variant; everyone else runs `standard`.
- `handleNext` advances by calling `generateStage` / `generateSummaryAndConstraints` (which call CEAEI) and caching the result per screen (`stageCacheRef`) so **back navigation restores exact AI content without re-calling**.
- `buildStageComponents.ts` turns CEAEI's structured `ObjectiveScreenPayload` into the SDUI component stream the renderer consumes.
- Plan routing: `monitor` → `2d`; `no-redeem` → `2e`; `simplicity` → `3a`/`3c`; `max-redeem`/`hybrid` → `4a`/`4c`.
- Execution steps:
  - *Simplicity*: use LBG balance → review plan → authorize card → payment complete (Cavendish `:5175`).
  - *Maximum Value*: **Alpha Medical convert (`:5174`)** → use bigger balance → review → authorize → complete.
  - *Hybrid*: automatic conversion + one-step payment.
  - *Monitor*: watch only.
  - *No Rewards*: direct cash pay at Cavendish.
  - *Leo (freeform)*: Convert partner points (`?portal=convert`) → review balance → book Japan (`?portal=booking`).
- **Resume path**: returning from a partner portal re-opens at the exact step via `applyResume`.

### Workspace SDUI sub-components (`src/workspace-components/`)

27 files compose wizard screens: `WorkspaceAnchor`, `WorkspaceHero`, `WorkspaceTextbox`, `QuickObjective`, `StateObjective`, `SummaryCaptured`, `ExtractedConstraints`, `ConstraintList`, `ObjectiveHero`, `RewardOpportunity`, `StrategyCard`, `CoplanTools`, `CognitiveEvidence`, `PlanHero`, `ExecutionStepsCard`, `RedirectPrompt`, `ExecutionSuccess`, `ExecutionFailure`, `RecoveryOptions`, `ModifyObjective`, `WorkshopNav`, `WorkshopTextbox`, `UnderstoodAnchor`, `WorkspaceBackground`, `WorkspaceSDUIRenderer`, plus `buildStageComponents.ts` and `types.ts`.

---

## 13. Partner demo portals (Alphamed :5174 & Cavendish :5175)

These two separate React/Vite apps are the "partner portals" the workspace deep-links to.

### Alphamed (:5174) — points → LBG coins

Mobile healthcare portal. Converts **AlphaMedicol points → LBG coins at 1:5** (1 point = 5 coins).
- Routes: `/` (entry, reads `?customerName=&customerEmail=`), `/login`, `/dashboard`, `/lbg-rewards/convert`, `/lbg-rewards/success`.
- **Convert flow** (`LbgRewardsConvertPage`): slider for how many points to convert → `transferAlphaMedicolPointsToLbg` → POST middleware `/api/v1/customers/transfer/alphamedicol` → on success redirects to the LBG workspace (via `?returnTo`).
- Calls middleware customer APIs with graceful simulation fallback.

### Cavendish (:5175) — LBG coins → insurance payment

Insurance partner portal. Redeems LBG coins to pay a **£100 annual insurance premium. 100 coins = £1**.
- Hash routing: `#/policy` (policy page), `#/checkout` (checkout), `#/success` (confirmation).
- **Checkout** (`CheckoutPage`): reads `coinsToApply` from URL, auto-applies up to 100% premium as coin discount, offers card/bank/DD/Apple Pay, validates card with Luhn, processes with animation, can fail → failure modal.
- Each £1 paid earns `round(amountPayable * 5)` coins back (reward).
- Calls `payCavendish` → POST middleware `/api/v1/customers/pay/cavendish`; on success writes a **`cross_app_events` REDEEM** (negative coins) into the return URL so the main dashboard balance updates immediately.

---

## 14. Demo 1 — Insurance journey (Sophie / Maya / standard personas)

**Goal:** show a governed, AI-assisted "pay my insurance with LBG coins" journey with a fixed set of redemption plans.

1. Login via a persona (e.g. **Sophie Williams / customer_011**, `EDUCATIONAL_COMPETENCE`) — or the generic demo user.
2. On the dashboard tap **"Set a Goal"** (or "Personalise your LBG Coin experience").
3. Workspace `1a`: enter objective — e.g. *"I want to pay my insurance using LBG coins while maximizing the value"* (or the provided quick-start). Non-Leo → `variant: standard`.
4. `1b`: CEAEI generates a **summary** + extracts **constraints** (e.g. *£70 cashback*, *10:1 conversion rate*, *no conversion fee* — regex-parsed from the text). Shown as "What I understood + Constraints extracted".
5. `2a`: **Reward opportunities** — filtered from the partner-offers store against the constraints, partitioned into shortlisted vs rejected.
6. `2b`: **Strategy cards** — the 4 fixed plans (Simplicity / Maximum Value / Monitor / No Rewards). The Coplan tools let the user *explain*, *combine*, *edit constraints*, or *compare* and regenerate the plans (re-calls CEAEI with a `toolRequest`).
7. `2c`: **Cognitive evidence** for the chosen plan (grounded in objective + plan + constraints).
8. Execute:
   - **Simplicity** → execution chart → deep-link to **Cavendish** (`:5175/#/checkout`) with coins applied → pay → `cross_app_events` REDEEM → return → `3c` success.
   - **Maximum Value** → first deep-link to **Alphamed** (`:5174/lbg-rewards/convert`) to convert points → back → then Cavendish → `4c` success.
   - **Monitor** → `2d` (we'll watch — no action).
   - **No Rewards** → `2e` direct cash pay at Cavendish.

This is the "Sophie / Maya" or **any non-Leo** standard journey.

---

## 15. Demo 2 — Persona personalization (the SDUI committee)

**Goal:** show that the **dashboard itself** changes per behavioural persona, driven by the QUEST-UI committee.

1. On the login screen, the **persona picker** lists all 13 customers (fetched from `GET :8001/intelligence/customers`).
2. Pick any persona; the app signs in, calls reseed, and renders the dashboard.
3. The dashboard calls **`POST :8002/sdui/generate`** with the persona's `customerReference` + a live `wallet` snapshot.
4. The middleware: fetches intelligence from `:8001`, runs the Card Rule Engine, then the **6-stage company committee** over **Gemini/Groq**, writes an explainability bundle, and returns SDUI JSON.
5. `SDUIRenderer` renders the 12–17 component cards (e.g. `POINTS_BALANCE` hero + persona-targeted cards).

**Expected compositions per persona** (from `README.md`):

| Customer | Persona | Typical composition |
|---|---|---|
| `customer_003` (David) | `LONG_TERM_PLANNER` | goal cards ×3 + `ADD_GOAL_CARD`, `FUTURE_VALUE_CARD`, `PROJECTION_CHART` |
| `customer_005` (Marcus) | `GAMIFICATION_MOTIVATED` | `STREAK_CARD`, `CHALLENGE_CARD`, `LEADERBOARD`, `BADGE_CARD` |
| `customer_004` (Jessica) | `CHURN_RISK` | `EXPIRING_POINTS_ALERT`, `REENGAGEMENT_BANNER`, `QUICK_WIN_CARD` |
| `customer_011` (Sophie) | `EDUCATIONAL_COMPETENCE` | `POINTS_BALANCE`, `GOAL_PROGRESS_CARD`, `LEARNING_MISSION_CARD`, `TANGIBLE_VALUE_CARD`, `ADD_GOAL_CARD`, `STREAK_CARD`, `REWARDS_INSIGHT_CARD` (see EXPLANATION.md) |

**Guardrail:** at most one educational + one analytics component per screen; celebration/birthday/anniversary cards only when the profile genuinely supports them.

If the middleware is unreachable, the UI **falls back to the static layout** with the header anchored — the demo still works.

---

## 16. Demo 3 — Leo's AI-freeform Japan vacation

**Goal:** show a fully freeform, AI-personalized (non-insurance) journey. **`customer_012` Leo Morgan** is the only persona on this track.

Key Leo facts:
- Partner points: Nippon Air 400,000 / Sakura Holidays 350,000 / TravelPerks 250,000 (total 1,000,000). **Conversion rate 1,000 partner points → 1 LBG coin** (`PARTNER_TO_LBG_RATE = 1000`). So converting all = **1,000 LBG coins = £10**.
- Workspace uses `variant: "ai-freeform"`.

Flow:
1. Sign in as **Leo (customer_012)**.
2. Open "Set a Goal". Quick-start objective: *"I want to get £50 discount cashback with no fee on flights for my Japan vacation"*. Leo can also type a hotel objective (*"I want to save money on my hotel booking in Japan, min £30 cashback"*).
3. `2b`: CEAEI (via `strategies_freeform`) designs **3–4 personalized plans** with strict guardrails:
   - **Exactly one** consolidation plan (order 1) that names per-brand balances.
   - The others are brand-agnostic: cashback deal, LBG-direct, early-booking, split-pay — **no partner conversions**.
   - Must stay in the objective's category (flights vs hotels) and **never mention insurance**.
4. `2c`: freeform cognitive evidence.
5. Execution (`freeform_execution_steps`) — hands off to **in-app portals** (not external):
   - Step 1 → `?portal=convert` (`ConvertPointsPortal`): Leo converts his partner points to LBG coins; a **CONVERT cross-app event** is recorded.
   - Step 2 → review the refreshed balance in place.
   - Step 3 → `?portal=booking` (`BookingPortal`): book Japan flights/stays and pay the MRP difference; a **REDEEM cross-app event** is recorded.
6. Each portal returns to the workspace via `ws_resume`; the dashboard coin balance updates from the cross-app events.

The `travelFocus(objective)` classifier (flights/stays/generic) decides whether the booking portal shows the Flights or Stays tab, and whether step wording says "flight tickets" vs "hotel stay".

---

## 17. Cross-app hand-off protocol

Because the main portal and the partner portals are separate SPA origins, state is passed via **URL query params + `localStorage` cross-app events**.

### Outbound hand-off (`RewardsDashboardPage.handlePartnerHandoff`)

Builds a partner URL with:
- `customerEmail`, `customerName`, `customerPhone`
- `coinsToApply` (only for Cavendish / Travel Booking) — how many LBG coins to auto-apply
- `objective` (only for Travel Booking) — for Leo's booking portal tab filtering
- `returnTo` = the main app URL carrying `?ws_resume=<JSON>`

Before navigating it snapshots the dashboard to `localStorage['rewards_session_snapshot']` (customer, pointsByBrand, un-adjustment `baseLbgCoins`).

### Cross-app events (`src/services/rewardsApi.ts`)

Events are written to `localStorage['rewards_cross_app_events']` and carried between origins through a `cross_app_events` JSON query param. Event shape:

```jsonc
{ "id", "type": "EARN|CONVERT|REDEEM|TRANSFER|EXPIRE",
  "description": "...", "amount": <signed int>,
  "currency": "LBG_COIN|BRAND_POINT", "createdAt": "...", "source": "..." }
```

- `consumeCrossAppEventsFromUrl()` ingests events from the URL and persists them.
- `computeAdjustedLbgBalance(base)` = `max(base + Σ LBG_COIN event amounts, 0)` — the dashboard's coin hero reflects converted/earned coins added and redeemed/expired coins subtracted.
- `applyLeoPartnerPointsConversion()` records Leo's CONVERT event.
- `leoConversionApplied()` guards against double-converting on repeat visits.

### Return path (`App.tsx`)

On `?ws_resume` or `?cross_app_events`:
1. Skip the splash; land straight on the dashboard.
2. Restore from snapshot + re-apply cross-app event deltas to the LBG balance.
3. Re-open the workspace at the resumed screen (`ws_resume`), so the user continues exactly where they left off.

---

## 18. API reference summary

### Intelligence Layer (:8001)
`GET /intelligence/customers` · `GET /intelligence/customer/{id}` · `GET /brands` · `POST /earn` · `POST /redeem` · `GET /transactions/{id}` · `GET /dlt/audit/{id}` · `GET /dlt/network` · `GET /dlt/balance/{address}` · `GET /health`

### QUEST-UI Middleware (:8002)
`POST /sdui/generate` · `POST /objective/generate` (mirrored from CEAEI) · `GET /experience/customer/{id}` · `GET /health`
**Customer/partner APIs:** `GET /api/v1/customers/lookup/summary?email=` · `POST /api/v1/customers/{id}/reseed` · `POST /api/v1/customers/transfer/alphamedicol` · `POST /api/v1/customers/pay/cavendish` · `GET /api/v1/customers/{id}/summary` · `GET /api/v1/wallet/{id}/transactions`
**Cache:** `GET /sdui/cache/stats` · `DELETE /sdui/cache/{id}` · `DELETE /sdui/cache`

> SDUI results are cached **in-memory for 1 hour** per customer (`SDUICache(ttl_seconds=3600)`). `GET /health` returns all 17 agents + cache stats.

### CEAEI Objective Middleware (:8004)
`POST /objective/generate` · `GET /health`

### DLT Service (:8003)
`POST /dlt/mint` · `POST /dlt/burn` · `POST /dlt/transfer` · `GET /dlt/balance/{address}` · `GET /dlt/supply` · `GET /dlt/network` · `GET|POST /dlt/audit` · `GET /health`

### Unified Backend (:8000)
`POST /api/v1/customers/login/password` · `POST /api/v1/customers/signup` · `GET /api/v1/customers/lookup/summary?phone=` · `GET /api/v1/customers/persona/{id}/summary` · `GET /api/v1/customers/{id}/summary` · `GET /api/v1/brands` · `GET /api/v1/rewards` · `GET /api/v1/wallet/{id}/transactions` · `POST /api/v1/convert` · `GET /health`

---

## 19. Explainability & audit

Every QUEST-UI decision (and DLT transaction) is auditable:

- **SDUI decisions** (`middleware/explainability/YYYY/MM/DD/<correlationId>/`): the middleware writes a full bundle including `manifest.json`, `request-snapshot.json`, `permitted-evidence.json`, `policy-decisions.json`, `candidate-evaluations.json`, `ui-decision-plan.json`, `final-sdui.json`, `fallback-sdui.json`, `validation-results.json`, `agent-conversation.json`, `agent-ai-conversation.json` (structured AgentMessages + raw LLM transcripts), and `audit-summary.json`. The response's `explainabilityRecordRef` points at the bundle — so *"why did this customer see this screen?"* can always be answered.
- **Blockchain ops**: every mint/burn/transfer is written to the `dlt_audit` table (via the DLT service and/or the intelligence layer).

---

## 20. Rebuild guide — step by step

To rebuild this system from scratch, follow this order (dependencies downward):

### Phase A — Infrastructure
1. **PostgreSQL** — schema + seed (`db/schema.sql`, `db/seed.sql`). Create `ilrp` DB, user `ilrp` / password `ilrp_dev_2024`.
2. **Besu node** — IBFT genesis (chain id 1337) + validator key. Expose RPC 8545, WS 8546, p2p 30303.
3. **LBGCoin contract** — compile `LBGCoin.sol` (OpenZeppelin ERC20 + AccessControl + Pausable). Grant the bank signer `MINTER_ROLE`/`BURNER_ROLE`.

### Phase B — Services (python)
4. **DLT Service (:8003)** — FastAPI wrapping Besu via Web3. `load_or_deploy_contract()`; endpoints mint/burn/transfer/balance/supply/network/audit; simulation fallback. Write `dlt_audit`.
5. **Intelligence Layer (:8001)** — FastAPI. Static persona profiles + two-tier classifier → `IntelligenceResponse` (persona, componentAffinity, personalizationSignals). DB client + Besu/DLT clients. Endpoints `/intelligence/...`, `/earn`, `/redeem`, `/dlt/...`.
6. **QUEST-UI Middleware (:8002)** — FastAPI + LangGraph. Implement `QuestUIState`, `BaseAgent` + 12 agents, the QUEST+R graph, `CardRuleEngine` (R1–R5), `OrchestrationService`, LLM router (Gemini→Groq), SDUI catalogue, validator, transformer, explainability writer. Expose `/sdui/generate` + customer/partner APIs.
7. **CEAEI Objective Middleware (:8004)** — FastAPI. LLM per-stage generation for the wizard (summary/constraints/opportunities/strategies/evidence/execution), `partner_offers.py` filter, optional `MOCK_OBJECTIVE_MODE`. Expose `/objective/generate`.
8. **(Optional) Unified Backend (:8000)** — FastAPI + SQLAlchemy + JWT for legacy auth/dashboard.

### Phase C — Frontends
9. **Main Portal (:5173)** — Vite + React + MUI + Tailwind + Recharts + framer-motion.
   - Auth flow + persona picker.
   - `RewardsDashboardPage` with hero, shortcuts, modals.
   - `SDUIRenderer` + `REGISTRY` of 70+ card components in `src/components/rewards-intelligence/`.
   - `ObjectiveWorkspace` + `src/workspace-components/` wizard renderer.
   - Cross-app event + snapshot persistence.
10. **Alphamed (:5174)** & **Cavendish (:5175)** — independent React/Vite portals implementing the conversion and insurance-payment flows, reading/writing the hand-off params and cross-app events.
11. `docker-compose.yml` wiring DB → besu → dlt → intelligence → middleware → ceaei (+ backend), plus CORS for all frontend origins.

### Phase D — Data
12. Ensure the **frontend registry** and the **backend `VALID_COMPONENT_TYPES`** stay in sync whenever you add a card.

### Key caveats when rebuilding
- Keep the two middleware services **separate** (QUEST-UI for SDUI, CEAEI for objective content).
- Keep `POINTS_BALANCE` as the anchored hero (priority 1, `span: full`).
- Mirror every card in both the Python catalogue and the TS registry.
- All partner portals must **gracefully simulate** when the backend is down, so the demo never hard-fails.
- Use **cross-app events** + `ws_resume` + snapshots for the multi-origin hand-offs; never assume in-memory state survives navigation.

---

## 21. Design principles & guardrails

These are enforced across the whole personalization stack (restated in every agent prompt and the card-rule engine):

1. Agents may select/configure **approved components only** — never invent types, props, tokens, or content refs.
2. Never create/modify/replace official **bank logos** or **reward-coin logos**.
3. Never rewrite **regulated, legal, security or mandatory bank text**.
4. Never remove or demote **anchored components** (`POINTS_BALANCE` stays first).
5. Use only customer data allowed by **Consent and Purpose Policy**.
6. Never infer/use **protected or sensitive attributes** (race, religion, health, biometrics, pregnancy, precise age…).
7. No **manipulative urgency, dark patterns, artificial scarcity, coercive mechanisms** — countdowns must reflect genuine expiry data.
8. Treat the `rewardInteractionProfile` as **temporary and purpose-bound**, never a permanent psychological label.
9. **Declared preferences beat inferred signals** when they conflict.
10. **A candidate failing any hard governance gate must be rejected regardless of its personalization score.**

These guardrails are the difference between this prototype and a naive recommend-anything system — they are intentionally the load-bearing safety invariants of the architecture.
---

## 22. CEAEI conversational voice agent (:8005)

`ceaei-agent/` is a new FastAPI service that turns the rewards app into a spoken
conversation. It **orchestrates over** the existing services (intelligence-layer,
middleware, ceaei-middleware) — it never duplicates their logic.

### 22.1 Topology

```
Browser (VoiceOverlay)
   │  REST  /chat/session /chat/message /chat/confirm /audio/transcribe
   │  WS    /ws/session/{id}   (binary audio in, JSON events out)
   ▼
ceaei-agent (:8005)
   ├── intelligence-layer (:8001)  → persona + customer summary
   ├── middleware (:8002)          → balances, transactions, SDUI, money endpoints
   └── ceaei-middleware (:8004)    → objective generation
```

### 22.2 Turn lifecycle

1. `POST /chat/session` binds the **customer id + email to the session** — the model
   never supplies its own identity.
2. The context provider pulls a compact, authorised bundle (summary, persona, the
   five most recent transactions) and injects it into the system prompt.
3. The LLM router answers with a plain reply or a `TOOL_CALL {...}` directive.
4. The registry validates the call against the allowlist, runs it (read tools) or
   builds a preview (consequential tools).
5. The reply is streamed back; the browser speaks it and can interrupt it.

### 22.3 Tool classes

| Class | Tools | Behaviour |
|---|---|---|
| `read` | `get_wallet_summary`, `get_recent_transactions`, `get_brand_points`, `get_persona_profile`, `generate_objective`, `refresh_dashboard_cards` | Executed immediately, result fed back to the model. |
| `consequential` | `convert_points_to_coins`, `pay_cavendish_premium` | **Never executed without approval.** The customer sees a preview and must approve explicitly. |
| `navigation` | `open_goal_wizard` | Emits a `navigation` event; the dashboard opens the objective wizard. |

### 22.4 The money gate

- Approval is **one-shot**: the confirmation is consumed on read and replay returns `409`.
- The preview is bound to an `argsHash` (`sha256` of tool + args) — a tampered amount is rejected.
- Confirmations expire after `CONFIRMATION_TTL_SECONDS` (120s).
- The customer email is injected from the session; it is stripped from every tool schema
  and never enters the model context. Persona customers without an email are refused.

### 22.5 Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/chat/session` | Create a session, returns the greeting. |
| `GET` | `/chat/session/{id}` | Session state, pending confirmation and the tool audit log. |
| `DELETE` | `/chat/session/{id}` | Close the session. |
| `POST` | `/chat/message` | One turn. `stream:true` returns server-sent events. |
| `POST` | `/chat/confirm` | Approve or decline a pending money action. |
| `POST` | `/audio/transcribe` | Stateless speech-to-text (Groq Whisper). |
| `WS` | `/ws/session/{id}` | Live channel: audio in, transcript/tool/message events out. |
| `GET` | `/health` | Provider status and the registered tool names. |

### 22.6 Frontend

| File | Responsibility |
|---|---|
| `src/types/voice.ts` | Shared types for sessions, messages, tools, confirmations and server events. |
| `src/services/ceaeiChatApi.ts` | REST client, SSE frame parser and the WebSocket wrapper. |
| `src/hooks/useVoiceSession.ts` | Pure `voiceReducer` plus session/socket wiring and a REST fallback. |
| `src/hooks/useAudioCapture.ts` | `getUserMedia` + `MediaRecorder` + RMS metering with energy-based VAD. |
| `src/hooks/useSpeechSynthesis.ts` | Speech queue with instant cancel (barge-in). |
| `src/components/voice/*` | Overlay, orb, transcript, confirmation sheet, launcher button. |

### 22.7 Running it

```bash
# with the whole stack
docker compose up --build ceaei-agent

# standalone (mock replies, no LLM calls)
cd ceaei-agent
MOCK_AGENT_MODE=true uvicorn app.main:app --port 8005

curl http://localhost:8005/health
```
