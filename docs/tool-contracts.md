# Tool contracts

All tools require `academic:read`; local writes additionally require
`preferences:write`. Identity comes from the verified request, never a tool
argument. Inputs have bounded typed schemas; no arbitrary URL, student identity,
HTTP method, SQL or command parameter exists.

Responses use `Result` schema 1.0: status, readable summary, data, sources and
metadata (snapshot, retrieval time, timezone, freshness, coverage, continuation).
Missing upstream data is not success with an empty list. Maximum serialized
response size is 250 KB; callers must narrow excessive requests.

| Tool | Result boundary |
|---|---|
| get_connection_status | Owned identity/scope/capability state; fictional profile visibly labeled |
| list_courses | Active student courses; staff/mixed roles excluded; does not select courses |
| get_workload | Explicit <=31-day window; max 100 items/page; course coverage and encrypted bound cursor |
| get_assignment_details | Fresh accessible requirements/rubric; no locked material |
| get_changes | Complete matching-scope baselines only; first observed is not newly published |
| get_gradebook | Own visible Canvas fields; no unposted fields or exact-policy assumptions |
| get_course_outline | Bounded modules/items/pages/files with one overall time budget; course-bound material references join visible module items; listing never proves a reading was accessed |
| fetch_course_material | Backward-compatible page or file text; fresh access checks, content-hash-bound continuation; files require enabled OS isolation |
| list_course_files | Selected-course metadata with module associations, opaque file IDs, stable Canvas links and indexed state; resolves visible module files even when the Files collection is denied |
| read_course_file | PDF/TXT/Markdown text windows, PDF page ranges/locators, metadata, hashes and explicit extraction limits; max 16,000 characters per window |
| search_course_files | Previously extracted authorized file text only; page passages, indexed count, unindexed documents and incomplete-coverage flags |
| get_file_extraction_status | Fresh authorization without downloading; available/downloaded/parsed/partially_parsed/unsupported/failed/inaccessible state and reason |
| search_course_materials | Previously fetched page index only; fresh access recheck before returned hits |
| propose_study_plan | Stateless priorities/allocation; no calendar access or saved side effect |
| get_saved_study_state | Local record versions for explicit later changes |
| update_study_preferences | Persistent scoped preference write with expected version |
| record_personal_progress | Persistent personal status/effort; never Canvas submission evidence |
| save_study_plan | Fresh proposal validation and local version receipt; not a calendar action |

Timed filters use half-open instants. Date-only items stay dates and are included
when their local calendar date intersects the requested window; an exactly
midnight end excludes that end date. No 11:59 PM time is manufactured.

Effort is not inferred from points. Unknown effort produces a bounded requirements
review. Plans use upper effort bounds, reserve breaks/buffer and report unmet
minutes. Unknown prerequisites keep otherwise fitting plans provisional.
Replanning accepts explicit busy intervals and pinned study blocks. Pins are
preserved; conflicts with busy time, source deadlines or availability require a
correction. Dependency completion must precede dependent sessions. Supplied
calendar constraints are conversation input, not verified Calendar access.

Saved preference values are returned for conversation reuse. Callers should pass
the student's saved preferences into explicit plan constraints; a read never
silently saves a correction.

No calendar/action/notification or generic standard `search`/`fetch` compatibility
tool is advertised. Standard research-surface adapters require separate actual
client verification before being added.

The file inventory requires explicit current-user visibility and excludes hidden
or locked files. A module label can remain visible without a usable material
reference when its resource is absent from the accessible bounded inventory.
Module inclusion does not establish whether a reading is assigned or optional.
Only previously extracted file bodies are searched by `search_course_files`;
`search_course_materials` retains its page-only behavior. Signed download URLs
are never returned or persisted as sources. See [file reading](file-reading.md).
