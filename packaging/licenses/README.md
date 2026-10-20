# Runtime notices

`PYTHON-LICENSE.txt` is the license shipped with the local CPython 3.14.5
distribution; it is a fallback when a platform does not put its own copy at
`sys.base_prefix/LICENSE.txt`. The build prefers the runtime's installed copy.
Python source: https://github.com/python/cpython/blob/3.14/LICENSE

`TCL-LICENSE.txt` is the unmodified Tcl 8.6.15 notice from
https://github.com/tcltk/tcl/blob/core-8-6-15/license.terms.
The Tk distribution's own `license.terms` is also included by its bundling hook.
Installed package notices preserve their individual paths, including notices
for vendored dependencies. These files do not choose a license for Canvas Bridge.
