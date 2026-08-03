# Hidden production-brief P1 rubric

This rubric is fixed before either treatment begins. Agents must not read it.

## Mandatory gates

- Existing unit/component tests pass.
- Integration tests pass.
- Typecheck passes.
- Production build passes.
- No test is weakened or deleted.
- No critical privacy failure: supporter access must remain consent-controlled, aggregate-only and non-monitoring; supporter suggestions must not directly mutate a learner plan.

## Outcome score (100)

### Learner workflow — 35

- Weekly goals capture subject, target quantity, deadline and importance: 7.
- Goal decomposition produces proposed schedule tasks and requires learner confirmation before persistence: 8.
- Overload guidance combines today's energy with recent actual duration evidence: 7.
- Weekly review shows planned time, actual focus time, completion and deferral: 7.
- Moving unfinished work to next week is an explicit preview/confirm action, never an automatic mutation: 6.

### Supporter workflow — 30

- Authorized aggregate weekly-goal progress without private task details or live monitoring: 8.
- Suggestions cover reducing load, delaying a date and splitting work; they remain learner-controlled: 8.
- Fixed gentle responses include “收到，我陪你” and “今天先休息”: 6.
- A completed stage can receive one lightweight supporter reaction: 4.
- Existing pairing revocation and sharing preferences still gate access: 4.

### Cross-layer engineering — 25

- Reuses existing planning/support/suggestion contracts rather than creating an isolated duplicate feature: 5.
- Local backend persists and exercises the workflow: 6.
- Supabase contract/migration/types are updated, or the implementation explicitly preserves a bounded backend-compatible contract without claiming cloud completion: 5.
- New behavior has meaningful tests across domain/backend/UI as applicable: 6.
- Existing public API and privacy regression tests remain intact: 3.

### Product quality — 10

- User-visible copy is non-judgmental and confirmation states are clear: 4.
- Empty/error/busy states are handled for added interactions: 3.
- Diff remains scoped and understandable: 3.

## Interpretation

- 85–100: production-shaped complete result.
- 75–84: useful complete slice with documented boundary.
- 60–74: partial product slice.
- Below 60 or any mandatory/critical privacy failure: unsuccessful.

The final evaluator must cite physical source/test evidence for every awarded item. Static keyword signals are discovery aids only and never award points by themselves.
