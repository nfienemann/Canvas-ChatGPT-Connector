# Linux document worker

Implementation status: verified with synthetic documents on Linux x64 and in the
restricted service image. No actual Linux student-read or public-hosting claim
is made. Windows remains the owner's verified live deployment.

The existing file reader has an OS-neutral dispatcher. Windows retains its tested
AppContainer launcher. Linux uses a fresh isolated Python process with Landlock
filesystem restrictions and a default-deny seccomp filter; unsupported kernels
fail closed before parser code reads document bytes. macOS extraction remains
unsupported. This is server infrastructure, not a new student application or login.

## Boundary

Only a copied public runtime (standard library, pypdf, defusedxml, trusted bootstrap
and parser) and the current private job directory are readable. The runtime is
read-only to the child. Job inputs are also read-only; the only writable file is
a single output precreated by the launcher. Creating additional files is denied. No host
library directory, service package, database, credential file, other job or parent
directory is granted. Standard-library native dependencies are loaded by the
trusted bootstrap before restriction; their handles remain in memory. Existing
package search paths are rebound to the copied runtime, without site initialization.

The child receives no inherited service environment or file descriptors. It must
be single-threaded when filesystem restriction is established. Subsequent socket,
network, process/thread creation, execution, signaling of other processes, ptrace,
io_uring, mounts, device operations and privilege-changing syscalls are denied by
the syscall allowlist. Landlock ABI 3 or newer is mandatory, including truncate
protection; newer optional Landlock features are not relied upon. This is no
best-effort or silently weakened sandbox.

Hard limits: 384 MiB address space, ten seconds CPU, 15 seconds wall time, 64 open
descriptors, no core dump, 2 MB total writable output, one extraction per service
process. The worker cannot overwrite input or allocate extra files.
The existing file/page/expanded-archive/text limits remain. The launcher kills and
reaps the worker after timeout; a parent-death signal also prevents an orphaned
worker. Stdout/stderr go to a null device, and errors returned to MCP are generic
or allowlisted, never parser exceptions containing document text.

Temporary input/output is deleted through the existing extraction lifecycle. As
on Windows, abrupt power loss may leave a private job folder for operator cleanup.
Public runtime caches contain no student data and are keyed by parser/bootstrap,
Python and parser-library versions. No database migration or new OAuth scope is
needed. No change is made to authorized download, cache isolation or citation rules.

## Deployment and verified scope

Run as a dedicated unprivileged user; extraction refuses effective UID zero.
Use a dedicated owner-only parser root (mode 0700) outside the repository and any
secret mount. Linux requires enabled Landlock ABI 3+ and `libseccomp.so.2`. The
service image installs Debian's libseccomp runtime dependency and prebuilds the
trusted runtime under `/opt/canvas-parser`. Its `BRIDGE_PARSER_RUNTIME_ROOT`
setting separates this read-only executable code from the private
`BRIDGE_PARSER_ROOT` job directories. Scratch storage can remain non-executable.
Continue to enable file reading explicitly using the existing operator configuration; failure to
establish isolation must not be worked around with privileged containers or an
unconfined seccomp profile. Runtime native libraries need an executable filesystem
mapping in the read-only runtime location; raw documents are never executed.

[CI run 39515513203](https://github.com/nfienemann/Canvas-ChatGPT-Connector/actions/runs/39515513203)
verified source commit `acd3fe8`: **347 tests passed, four Windows-only cases
skipped**, in 42.69 seconds, with 80% total statement coverage. All **13** Linux
sandbox cases passed, including actual PDF/TXT/Markdown/DOCX/PPTX extraction,
PDF page attribution, corrupt input cleanup, private-file/environment/descriptor
denial, network/process/runtime-write/input-write/file-creation denial and
memory/output/CPU/wall-time limits. Root execution is refused. Unsupported
kernel protections fail rather than skip on the Linux runner.

The built image independently extracted all five supported formats through
`extract_document` and verified job cleanup. It ran as its unprivileged user
with no network, all capabilities dropped, no-new-privileges, the default Docker
seccomp profile, a read-only root and 128 MiB non-executable temporary storage.
No privileged mode or unconfined profile was used. Ruff and dependency auditing
also passed (no known vulnerabilities). The separate Windows focused regression
run passed 62 tests with 12 Linux kernel skips, including actual AppContainer
PDF and Office extraction. No redundant unchanged Windows full run was required.

This does not replace an independent security review or establish resistance to
kernel vulnerabilities. Landlock does not hide all filesystem metadata; the
guarantee here concerns file contents and permitted mutations. Additional hosts
and architectures require their own compatibility proof. Fleet quotas, hosting,
managed secrets and public-distribution gates remain separate.

Primary references reviewed: [Landlock kernel documentation](https://docs.kernel.org/userspace-api/landlock.html),
[ruleset creation](https://man7.org/linux/man-pages/man2/landlock_create_ruleset.2.html),
[path rules](https://man7.org/linux/man-pages/man2/landlock_add_rule.2.html),
[seccomp initialization](https://man7.org/linux/man-pages/man3/seccomp_init.3.html),
[seccomp allowlist rules](https://man7.org/linux/man-pages/man3/seccomp_rule_add.3.html).
