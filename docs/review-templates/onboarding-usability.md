# Nontechnical onboarding usability study

Status: protocol only. Participants tested: **0**. Automated wizard tests are not
human usability evidence. No completion rate, time-to-task result or privacy
comprehension claim is available yet.

## Study design

Recruit 8–12 consenting adult participants with no development experience for an
initial formative Windows study. Use clean Windows 10/11 x64 standard-user accounts
on independently configured machines, with normal security controls. Use only
fictional course records and the supplied fictional TXT example. Do not collect
real coursework, credentials, recordings of personal desktops, or health or other
protected-characteristic inferences. Assign random participant codes.

Start timing when the verified installer is opened. Ask the participant to choose
the offline edition, explain its data use in their own words, finish setup and
identify the fictional grade result. Stop task timing only at verified academic
completion. Then try synthetic setup, recover from an occupied folder and a failed
check, interpret missing-converter guidance, reject an unsigned/expired update,
inspect a prepared signed release's notes, and uninstall with a deliberate keep or
remove choice. Do not weaken Windows security or create a real institution login.
A facilitator may intervene after the participant requests help; count each step.

Test understanding using concrete questions: Is a university connected? Is ChatGPT
connected? Does extracting text prove image interpretation? What does deleting local
data leave elsewhere? Does an expired approval permit an API-token workaround?
An incorrect permission decision is any attempt to use another person's record,
bypass missing approval, weaken verification or enable sharing without the required
permission. Record UI prevention separately from participant understanding.

Use operator-prepared, trusted signed fixtures for actual installer update/rollback
trials; cryptographic unit-test keys are not release identities. Until those fixtures
exist, mark signed installation tasks unavailable, never completed.

## Per-participant record

| Field | Entry |
|---|---|
| Participant code / consent | |
| OS build / DPI / app version / installer SHA-256 | |
| First-task outcome: completed / failed / unavailable | |
| Elapsed seconds to verified fictional result | |
| Setup errors and diagnostic codes | |
| Assistance steps and whether outcome required them | |
| Incorrect permission decisions / UI blocked them | |
| Privacy questions correct / total | |
| Recovery outcomes for each named failure | |
| Uninstall selection and independently verified local outcome | |
| Remaining confusion and participant's own wording | |

Store study notes outside source control under an approved retention plan. Publish
only deidentified aggregates with denominator, missing/unavailable tasks, assisted
versus unassisted outcomes and median/range. Report a Wilson interval for completion
only if its sample and recruitment design justify inference; small convenience
samples are formative, not population estimates. Never combine privacy mistakes
with speed into a single score. Compare versions using the same tasks and matched
conditions; document order effects.

## Release decision

Do not declare zero-friction onboarding complete from automated checks. Require
observed unassisted completion on supported Windows setups, correct disclosure
understanding, recoverable failures, an actual trusted signing chain, and separate
acceptance records for each advertised AI client. Record failures individually and
turn verified software regressions into synthetic tests. Human difficulties need
UI changes and a fresh task-specific trial. Review accessibility with keyboard,
screen reader, scaling and long paths on an unlocked desktop.
