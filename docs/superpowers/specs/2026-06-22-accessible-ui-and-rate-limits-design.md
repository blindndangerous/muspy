# Accessible UI and Rate Limits Design

Date: 2026-06-22

## Status

Approved design direction from brainstorming. Implementation plan has not started.

## Goal

Build a simple server-rendered UI for public release browsing and authenticated user workflows, with WCAG 2.2 AA as the accessibility target and rate limiting included in this phase.

## Non-Goals

- Do not build a single-page app.
- Do not add a frontend framework.
- Do not add public write actions.
- Do not expose user follows, imports, notifications, emails, feed tokens, or account data on public pages.
- Do not add RSS/iCal token management in this phase.
- Do not add email sending UI in this phase.

## Standards and Sources

- WCAG target: WCAG 2.2 AA.
- W3C WCAG 2.2: `https://www.w3.org/TR/WCAG22/`
- W3C WCAG overview: `https://www.w3.org/WAI/standards-guidelines/wcag/`
- Django 6 Redis cache docs: `https://docs.djangoproject.com/en/6.0/topics/cache/`

WCAG 3.0 is draft work, not the conformance target for this project. WCAG 2.2 AA is the current stable target for implementation and testing.

## Approach

Use the original Muspy-style simplicity as the product direction: list pages, clear forms, plain navigation, and direct actions. The new implementation should be more accessible, more secure, and easier to test than the original, but not visually complex.

The UI will be server-rendered Django templates with a small first-party CSS file. JavaScript is not required for MVP workflows. If JavaScript is added later, every workflow must continue to work without it.

## Page Map

### Public Pages

- `/`: public release overview with recent and upcoming visible releases.
- `/artists/<id>/`: public artist detail with visible release groups and events.
- `/releases/`: public release list with simple filters.
- `/releases/<id>/`: public release event detail.

Public pages show only release and artist metadata already stored in the local database.

### Authenticated Pages

- `/dashboard/`: followed artists, latest visible release events for followed artists, import status summary.
- `/artists/search/`: MusicBrainz artist search and follow confirmation.
- `/follows/`: manage followed artists and ignored artists.
- `/imports/`: import runs and review candidates.
- `/settings/notifications/`: cadence, email enabled, and future-release preference.

All authenticated pages require login and must filter user-owned data by `request.user`.

## Access Model

- Public pages query only `ReleaseEvent.visible=True`.
- Public pages do not show follow state.
- Public pages do not show user-specific notification status.
- Authenticated pages use `login_required`.
- Mutating actions use POST and CSRF.
- Mutating actions redirect after success or failure.
- Every user-owned query filters by `request.user`.
- Cross-user access attempts return 404 to avoid confirming private object existence.

## Navigation and Layout

Base template:

- skip link to main content
- site header
- primary navigation
- main landmark
- footer
- message region with `aria-live="polite"`

Navigation:

- Public links: Home, Releases.
- Logged-in links: Dashboard, Search Artists, Follows, Imports, Notification Settings.
- Admin remains at `/admin/`.
- Health remains at `/health/`.

Layout should be calm and utilitarian:

- readable text
- narrow line length for forms
- plain lists and tables
- no decorative hero
- no nested cards
- no hover-only controls

## Core Components

### Search Form

- Explicit label for query input.
- Help text explains artist name or MusicBrainz ID.
- Submit button named "Search artists".
- Results include artist name, disambiguation, type, country, and follow action.
- Follow buttons include object names, such as "Follow Fugazi".

### Public Release Lists

- Release list uses a table when tabular.
- Table includes caption and scoped headers.
- Date precision is shown explicitly:
  - `2026`
  - `June 2026`
  - `June 22, 2026`
- Country, media format, and status are text, not color-only indicators.

### Import Review

- Each candidate shows source name, matched artist if any, and review state.
- Candidate controls are Accept, Ignore, and Reject.
- POST action includes candidate ID and desired action.
- Accepted candidate creates or reuses follow.
- Ignored candidate remains ignored across repeated imports.

### Notification Settings

- Cadence is a radio group:
  - off
  - daily
  - weekly
  - instant
- Email enabled is a checkbox.
- Include future releases is a checkbox.
- Save action uses POST and CSRF.

## Accessibility Requirements

Target WCAG 2.2 AA.

Required patterns:

- Valid page language.
- One `h1` per page.
- Logical heading order.
- Skip link visible on focus.
- Main content landmark.
- Native form controls.
- Programmatically associated labels.
- Error summary at top of invalid forms.
- Field-level errors linked with `aria-describedby`.
- Status messages announced with `aria-live="polite"` or equivalent.
- Visible focus indicator on every interactive element.
- Focused elements must not be fully hidden by sticky or fixed content.
- Interactive targets at least 24 by 24 CSS pixels.
- Primary action targets should be closer to 44 by 44 CSS pixels.
- No color-only status.
- No drag-only actions.
- No hover-only content.
- No timed interactions in this phase.

Screen reader behavior:

- Page title identifies current page.
- Form errors are discoverable from the top and each field.
- Repeated action buttons and links include object context, such as "Follow Fugazi" instead of only "Follow".
- Tables have captions and scoped headers.

## Rate Limiting

Rate limiting is in scope for this UI phase.

### Design Choice

Use an internal Django-cache-backed rate limiter instead of adding a third-party package in this phase.

Reasons:

- Django 6 includes Redis cache support.
- Project already has Redis in bare-metal and container runtime.
- A small internal wrapper avoids dependency compatibility risk with Django 6.
- Tests can exercise exact behavior.
- Implementation can later swap to a third-party limiter behind the same helper if needed.

### Cache Backend

Production and container runtime should use Django `RedisCache` via `REDIS_URL`.

Tests may override the cache backend with locmem where deterministic behavior is sufficient, but production docs must state that rate limits need a shared Redis cache across web workers.

### Rate Limit Helper

Create a small `releasewatch.rate_limits` module during implementation.

Expected responsibilities:

- build stable rate keys
- support user, IP, and user-or-IP identities
- support fixed windows such as minute and hour
- expose a decorator or guard helper for views
- return a clear 429 response for exceeded limits
- return a clear 503 response if the shared cache is unavailable on protected endpoints
- avoid storing raw emails, passwords, tokens, or search strings in cache keys

Keys must hash sensitive or user-entered key parts before storage.

### Initial Limits

These values are starting defaults and should be settings, not hard-coded literals:

- Artist search:
  - authenticated: 60 per minute per user
  - anonymous if public search is added later: 30 per minute per IP
- Follow, unfollow, ignore:
  - 60 per minute per user
- Import creation:
  - 10 per hour per user
- Import candidate review:
  - 120 per minute per user
- Notification settings save:
  - 30 per minute per user
- Login:
  - 5 per minute per username and IP hash
  - 20 per hour per IP
- Password reset:
  - 5 per hour per email hash
  - 20 per hour per IP

If a route is not implemented in this UI phase, its limit can be added with the route that uses it.

### Rate Limit User Experience

For 429 responses:

- show page title "Too many requests"
- explain when to retry in plain language
- include a link back to safe navigation
- do not reveal whether a username or email exists

For 503 rate-limit backend failures:

- show page title "Service temporarily unavailable"
- explain that the action cannot be processed right now
- do not perform the protected action

## Data Flow

### Public Release Browsing

1. User opens public release page.
2. View queries visible release events.
3. Template renders release group, artist, release date, country, and status.
4. No user-specific data is loaded.

### Artist Search and Follow

1. Logged-in user opens artist search.
2. Rate limit guard checks request.
3. View calls MusicBrainz through existing client.
4. Results render as confirmable choices.
5. User submits POST to follow.
6. Rate limit guard checks mutation.
7. View creates or reuses artist and follow.
8. View enqueues release sync for artist.
9. User receives status message.

### Import Review

1. Logged-in user opens import run.
2. View queries only import runs owned by user.
3. User selects Accept, Ignore, or Reject for candidate.
4. Rate limit guard checks mutation.
5. View updates candidate state.
6. Accept creates or reuses follow.
7. User receives status message.

### Notification Settings

1. Logged-in user opens settings page.
2. View loads or creates notification preference.
3. User submits form.
4. Rate limit guard checks mutation.
5. View validates and saves settings.
6. User receives status message.

## Error Handling

Forms:

- invalid forms render with status 200
- top error summary links to fields
- fields use `aria-invalid="true"` when invalid
- field errors use `aria-describedby`

Missing objects:

- missing public release or artist: 404
- missing user-owned object or cross-user access: 404 or 403

Upstream failures:

- MusicBrainz unavailable returns search page with a non-field error
- rate-limited upstream calls show a retry message
- upstream error details are not shown raw to users

## Security

- CSRF on every mutating form.
- POST required for mutations.
- No GET mutation endpoints.
- No user data on public pages.
- No private object lookup by unscoped ID.
- No raw upstream payloads in templates.
- No secrets in templates or logs.
- Rate limit keys hash sensitive values.
- Public release pages are safe for anonymous cache/CDN use later because they do not vary by user.

## Testing Requirements

Use TDD for implementation.

Required test groups:

- public page access without login
- authenticated page redirects without login
- authenticated page access with login
- public pages show only visible release events
- cross-user follows/imports/settings are blocked
- POST required for mutations
- CSRF behavior covered with Django test client `enforce_csrf_checks=True` for at least one mutating UI endpoint
- artist search uses mocked MusicBrainz client
- follow action creates or reuses follow and enqueues sync
- import review updates candidate state and creates follows for accepted candidates
- notification settings save valid values and reject invalid values
- rate limits return 429 when exceeded
- rate limit backend failure returns 503 on protected actions
- rate limit keys do not include raw email, username, query, or token values
- templates include skip link, main landmark, labels, error summary, and accessible button/link names
- coverage floor remains at least 97

Accessibility tests:

- template smoke tests for landmarks, headings, labels, table captions, and skip link
- CSS smoke test for focus-visible rules
- manual screen reader pass before public launch, documented separately

## Implementation Phases

1. Rate limit helper, Redis cache setting, and error pages.
2. Base template, CSS, navigation, and message region.
3. Public release pages.
4. Authenticated dashboard and follows.
5. Artist search and follow workflow.
6. Import review workflow.
7. Notification settings page.
8. Accessibility, security, docs, Podman smoke, and checkpoint tag.

## Checkpoints

- Commit design spec before implementation plan.
- Commit implementation plan before code.
- Commit after each verified implementation phase.
- Create tag `checkpoint/accessible-ui-rate-limits` after full verification.

## Context Compact Recovery

After context compact, read:

1. `docs/agent-handoff.md`
2. `docs/superpowers/specs/2026-06-22-accessible-ui-and-rate-limits-design.md`
3. implementation plan once written
4. `git status`

Continue from the first unchecked plan task.
