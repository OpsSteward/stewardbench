# Framework decision inputs

Status: Input to a separate architecture phase; no framework is selected here.

## Decision goal

Choose the simplest maintainable implementation approach that satisfies the
documented StewardBench v1 workflow and preserves clean paths to later APIs,
CLI access, and Kubernetes deployment. The choice should optimize for a small
technical team, not for speculative scale or fashionable separation.

## Required capabilities

The later framework evaluation must demonstrate:

| Area | Requirement |
| --- | --- |
| Ecosystem | Python is preferred unless evidence strongly supports another choice. |
| Persistence | First-class PostgreSQL support, relational modeling, constraints, transactions, JSONB, and version-controlled migrations. |
| Application shape | CRUD-heavy authenticated operations application with substantial domain workflows. |
| Authentication | Secure local passwords, sessions (or comparably appropriate mechanism), first-admin bootstrap, and replaceable authentication boundary. |
| Authorization | Server-side enforcement of exactly ADMIN and read-only OPERATOR behavior. |
| UI | Dense desktop-first tables, forms, filters, pagination, detail pages, review navigation, and charts. |
| Background work | Durable run dispatch independent of a browser request; bounded sequential/parallel work; restart recovery; timeouts; progress observation. |
| API integration | Versioned target adapters with safe HTTP handling and untrusted response rendering. |
| Evidence | Efficient storage/retrieval of text and structured raw evidence without forcing the entire model into JSON. |
| Operations | Docker-based laptop and DGX deployment with external configuration/secrets and straightforward diagnostics. |
| Extensibility | Reusable application services callable later by REST endpoints, a user CLI, CI, and other adapters. |
| Maintenance | Clear conventions, strong testing support, manageable dependency surface, and accessible staffing/documentation. |

## Architecture questions candidates must answer

1. Can one cohesive application serve UI and application services without
   embedding domain logic in presentation handlers?
2. What is the smallest durable background-execution design, and what happens
   when web or worker processes restart mid-run?
3. Can background execution use PostgreSQL safely before adding a separate
   broker, and what evidence would justify another component?
4. How are database transactions, worker claims/leases, idempotency, and
   terminal observation immutability enforced?
5. How are URL-addressable filters, bulk selection, and the sequential review
   workstation implemented without unnecessary frontend complexity?
6. How are authentication and CSRF/session concerns handled securely?
7. How are future read APIs and CLI callers routed through the same service
   layer as the web UI?
8. How does the approach run in Docker Compose now and split into Kubernetes
   workloads later without redesign?

## Candidates for later comparison

Django-based, FastAPI-based, and other justified Python approaches may be
compared. Their names here are candidates, not endorsements. The exercise must
not assume either a single server-rendered UI or a separate SPA/API pair before
evaluating complexity against StewardBench's actual workflows.

## Required decision evidence

The separate selection phase should produce:

- a small set of end-to-end architecture sketches for the credible candidates;
- explicit component/dependency counts;
- a background-run and restart-recovery walkthrough;
- a representative authenticated CRUD/filter/review-flow walkthrough;
- migration, testing, deployment, and operations implications;
- security implications;
- tradeoffs against v1 scope and small-team maintainability; and
- a selected approach recorded in a new ADR.

No implementation should begin until the product owner reviews this foundation
and the separate framework decision is accepted.
