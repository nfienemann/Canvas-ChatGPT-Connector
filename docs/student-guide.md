# Student guide

The owner's private Windows connection now supports PDF, Word, PowerPoint, text and Markdown
reading directly in ChatGPT. Ask “Summarize Bundle 2 Paper 3” or “Compare Papers
1, 2 and 3 from Bundle 2.” ChatGPT can locate the files without asking for IDs.
Search covers documents already read; unread documents are labeled unindexed.
Scanned pages and figures cannot yet be visually interpreted. See
[file-reading limits](file-reading.md). The private service must remain running.
The public installer previews described below still use fictional courses.

“Not submitted” describes the online Canvas record only. An assessment may have
been completed in class or outside Canvas. Records without a Canvas due date
are listed as undated with unknown scheduling; they are not automatically called
upcoming. An empty assignment description is labeled explicitly and does not
mean the instructor has provided no requirements elsewhere. Change tracking
starts with complete observed snapshots and cannot reconstruct older history.

The downloadable preview is a fictional local demonstration; general student
onboarding is not available. A student should not install a server or paste a
Canvas token to use a future hosted release.

To try fictional data now, choose your computer's package on the
[download page](https://github.com/nfienemann/Canvas-ChatGPT-Connector/releases),
open **Canvas Bridge Demo**, and follow its short setup wizard. You do not need
Python or terminal commands. The **Check study tools** button verifies the local
demo. These unsigned previews may be blocked by your operating system; trusted
publisher signing remains unfinished. They do not connect to ChatGPT or Canvas.

For an operator-provided supported release, the intended journey is:

1. Add the approved connector using the connection method documented for your
   actual ChatGPT plan/workspace. Sign in through its configured identity provider.
2. Open connection settings, choose a supported institution, and approve its
   Canvas OAuth disclosure on the institution's genuine login page.
3. Select your courses and IANA display timezone. Return to ChatGPT.
4. Ask “What is due this week?” or “I have 45 minutes; what should I work on first?”
5. Read coverage and freshness with the answer. An unavailable course is not an
   empty workload. An unknown due date is not proof that there is no deadline.

This sequence still requires real-client and institution validation. Unsupported
schools need an administrator-approved access path; a shared or personal token
from another student is not a workaround.

For study planning, provide usable free-time windows without private meeting
titles, and remaining-effort ranges when known. The connector does not know your
calendar unless availability is supplied through the conversation. A proposed
plan has not created events. Ask ChatGPT to use your existing Google Calendar
connection to check availability and propose deadline events. It must show the
specific events and get your confirmation before creating or updating them.
Automatic notifications remain disabled.

You can also ask “Compare my syllabus deadlines with Canvas,” “Check this
assignment against its rubric,” “Prepare me for my next quiz,” or “Check my
course for inconsistencies.” Unknown coverage or unsupported rules will be
reported rather than turned into a confident answer. Word citations refer to
text sections; PowerPoint citations refer to slides.

Ask to remember a preference or progress correction only when you want it saved.
Personal “done” does not prove a Canvas submission. Saved plans can be incomplete
or provisional; their limitations remain visible.

Use settings to change course scope/timezone, export retained normalized records,
or disconnect. Disconnect disables local access immediately and deletes active
connection records. The response distinguishes remote token revocation from local
removal. Prior ChatGPT conversations and independent downloads require their own
deletion controls.

To remove all linked institutions at once, use **Delete all local account data**
in settings and select its confirmation checkbox. This also cancels pending
Canvas linking, deletes saved plans and signs you out. Remote revocation failures
are reported separately; revoke the app in your institution's Canvas account
settings if necessary. Signing in and explicitly linking again starts a new
connection. Minimal deletion fences remain to prevent old backups restoring data.

Use fetched sources for quotes. Text extraction does not establish what a figure
shows. Locked or unfetched readings remain unresolved. Visible grades and
hypothetical calculations are different.

You can ask “Is my Canvas grade accurate according to the syllabus?” or “What
would I need on the final?” The connector preserves Canvas's reported value and
shows any independent calculation separately. It first checks visible scores and
grading settings, then retrieves available syllabus text. It may ask you to review
specific source passages and confirm whether amendments or other rules are missing.
An ungraded assessment is not a zero. If a policy, grade or course category is
uncertain, a precise estimate may be unavailable; this is not an accusation that
the instructor or Canvas is wrong. Projections use your explicit hypothetical
scores, remain conditional on visible work, and never change Canvas.

Report issues to the repository owner using synthetic examples. Never include
tokens, private grades or other students' data in a public issue.
