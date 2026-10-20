# Capability, route and scope inventory

Reviewed against the linked Canvas API documentation on 2026-10-20. These are
proposed developer-key scopes, not evidence that any institution approved them.
Configure only the enabled capabilities. The registry contains no live grant.

| Capability | GET route used | Developer-key scope | Application restriction |
|---|---|---|---|
| Link verification | `/api/v1/users/self/profile` | `url:GET\|/api/v1/users/:user_id/profile` | Keep only the verified account ID; discard profile/contact/feed fields |
| Course access | `/api/v1/courses` | `url:GET\|/api/v1/courses` | Active student enrollments only; mixed staff roles excluded |
| Workload | `/api/v1/courses/{course}/assignments` | `url:GET\|/api/v1/courses/:course_id/assignments` | Selected authorized course; own submission only |
| Requirements/rubric | `/api/v1/courses/{course}/assignments/{assignment}` | `url:GET\|/api/v1/courses/:course_id/assignments/:id` | Opaque work reference resolved server-side; locked/unpublished content denied |
| Reported grades | `/api/v1/users/self/enrollments` | `url:GET\|/api/v1/users/:user_id/enrollments` | Own student enrollment; visible grade fields/current points and separately preserved overrides; no unposted fields |
| Grading configuration/syllabus | `/api/v1/courses/{course}` | `url:GET\|/api/v1/courses/:id` | Selected student course; syllabus and grading-period includes; no instructor history |
| Grading categories | `/api/v1/courses/{course}/assignment_groups` | `url:GET\|/api/v1/courses/:course_id/assignment_groups` | Weights/drop rules; assignment scores obtained through existing own-submission paths |
| Course file metadata | `/api/v1/courses/{course}/files/{file}` and `/api/v1/courses/{course}/files` | `url:GET\|/api/v1/courses/:course_id/files/:id` and `url:GET\|/api/v1/courses/:course_id/files` | Selected course, current visibility, approved bounded download path |
| Outline | `/api/v1/courses/{course}/modules` | `url:GET\|/api/v1/courses/:course_id/modules` | Selected course; bounded pagination |
| Outline items | `/api/v1/courses/{course}/modules/{module}/items` | `url:GET\|/api/v1/courses/:course_id/modules/:module_id/items` | Module obtained from selected course; metadata only |
| Page discovery | `/api/v1/courses/{course}/pages` | `url:GET\|/api/v1/courses/:course_id/pages` | Selected course; no revision history or group-wide reads |
| Current page text | `/api/v1/courses/{course}/pages/page_id:{page}` | `url:GET\|/api/v1/courses/:course_id/pages/:url_or_id` | Numeric page ID; fresh access check; content is untrusted data |

Sources: [users](https://developerdocs.instructure.com/services/canvas/resources/users),
[courses](https://developerdocs.instructure.com/services/canvas/resources/courses),
[assignments](https://developerdocs.instructure.com/services/canvas/resources/assignments),
[enrollments](https://developerdocs.instructure.com/services/canvas/resources/enrollments),
[modules](https://developerdocs.instructure.com/services/canvas/resources/modules),
[pages](https://developerdocs.instructure.com/services/canvas/resources/pages).

All IDs and URLs are resolved internally. Tools cannot submit a method, route,
token, institution origin, user ID or arbitrary URL. The adapter validates
pagination against the original route/query and checks public network addresses.
Credentials never move to another origin. Broader upstream privileges do not
expand this product's student-only allowlist.

OAuth authorization-code exchange, refresh and token revocation are the separate
credential lifecycle operations. They do not authorize academic mutations.
See [Canvas OAuth](https://developerdocs.instructure.com/services/canvas/oauth2/file.oauth)
and [developer keys](https://developerdocs.instructure.com/services/canvas/oauth2/file.developer_keys).

`SUBMISSION` and `ANNOUNCEMENTS` enum entries are reserved and
have no current public tool path. Do not grant their additional scopes simply
because the constants exist. Discussion replies, rosters, submissions, grades,
module completion and other academic writes are outside the application.
PDF/TXT/Markdown file text is opt-in on the verified Windows worker. Office/OCR,
visual interpretation, Calendar and notifications remain disabled.

MCP uses separate service scopes: `academic:read`, `preferences:write` and
`settings:write`. They are not Canvas OAuth scopes. The identity provider must
issue tokens for the exact configured resource audience.
