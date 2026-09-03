# ADR 0006: Local authentication and two-role RBAC

- Status: Accepted
- Date: 2026-09-03

## Context

StewardBench requires authenticated operational access and clear authority for
launching runs and changing accepted evaluation state. v1 is expected behind a
firewall. External identity integration and granular roles would expand scope
without helping the immediate evaluation loop.

## Decision

v1 uses local username/password authentication. A deployment/administrative
command bootstraps the first ADMIN; subsequent users are managed through the UI.
There are exactly two roles:

- ADMIN has all administrative capabilities; and
- OPERATOR has authenticated read-only access to all normal evaluation evidence,
  reviews, comments, baselines, comparisons, and trends.

All admins are equivalent. Authorization is enforced server-side in application
services. Authentication mechanics are isolated behind a boundary suitable for
future replacement. Passwords use secure hashing; sessions and CSRF are handled
according to the later selected framework.

## Consequences

- Only ADMIN can launch/retry/rerun, review GOOD/BAD, comment, invalidate,
  manage questions/targets/users, or manage baselines/evaluator configuration.
- There is no anonymous access, super-admin, granular permission system,
  approval queue, voting, or project-owner role.
- OIDC, Authentik, LDAP, SAML, MFA, and external role mapping are not v1.
- A future authentication integration must preserve the two-role domain policy
  unless a separate product decision changes it.

See [Product definition](../product-definition.md),
[Architecture](../architecture.md), and [UI/UX](../ui-ux.md).
