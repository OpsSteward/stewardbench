# Framework decision inputs

Status: Decision input evaluated on 2026-09-03. The result is in
[Framework selection](framework-selection.md) and
[ADR 0007](adr/0007-django-monolith-and-postgresql-worker.md).

## Decision goal

Choose the simplest maintainable implementation approach that satisfies the
documented StewardBench v1 workflow and preserves clean paths to later APIs,
CLI access, and Kubernetes deployment. The choice should optimize for a small
technical team, not for speculative scale or fashionable separation.

## Required capabilities

The completed framework evaluation was required to demonstrate:

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

## Candidates evaluated

Django-based, FastAPI-based, and other justified Python approaches were eligible
for comparison. Their names here were candidates, not endorsements. The
completed exercise compared a Django server-rendered monolith, FastAPI with
server-rendered templates, and FastAPI with a SPA against StewardBench's actual
workflows.

## Required decision evidence

The selection phase was required to produce:

- a small set of end-to-end architecture sketches for the credible candidates;
- explicit component/dependency counts;
- a background-run and restart-recovery walkthrough;
- a representative authenticated CRUD/filter/review-flow walkthrough;
- migration, testing, deployment, and operations implications;
- security implications;
- tradeoffs against v1 scope and small-team maintainability; and
- a selected approach recorded in a new ADR.

The evidence is recorded in [Framework selection](framework-selection.md). No
implementation should begin until the product owner reviews this foundation and
the framework decision, followed by the separately planned development skill,
independent QA skill, acceptance harness, and milestone plan.
