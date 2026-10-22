"""Fixed LibreOffice worker; launched only in a capability-free AppContainer.

Use the document model directly: the desktop/IPC startup is unnecessary for
export and fails on some headless Windows installations. No source URLs,
commands, filters, or executable paths are accepted from document contents.
"""

import ctypes as C
import os
import sys
from pathlib import Path


def convert(work, office, slide):
    program = office / "program"
    os.environ.update(SAL_DISABLESKIA="1", SAL_DISABLE_OPENCL="1", SAL_USE_VCLPLUGIN="svp")
    # Both Python and UNO come from the same trusted LibreOffice installation.
    # -I -S excludes job-directory imports, user packages and site customization.
    sys.path.insert(0, str(program))
    handle = os.add_dll_directory(str(program))
    library = C.CDLL(str(program / "mergedlo.dll"))

    class Kit(C.Structure):
        pass

    pointer = C.POINTER(Kit)

    class KitClass(C.Structure):
        _fields_ = [("size", C.c_size_t), ("destroy", C.CFUNCTYPE(None, pointer))]

    Kit._fields_ = [("klass", C.POINTER(KitClass))]
    hook = library.libreofficekit_hook_2
    hook.argtypes, hook.restype = [C.c_char_p, C.c_char_p], pointer
    kit = hook(str(program).encode(), (work / "profile").as_uri().encode())
    if not kit:
        raise RuntimeError("Renderer initialization failed")
    document = None
    try:
        import uno
        import unohelper
        from com.sun.star.task import XInteractionHandler

        class AbortInteraction(unohelper.Base, XInteractionHandler):
            def handle(self, request):
                abort = uno.getTypeByName("com.sun.star.task.XInteractionAbort")
                for continuation in request.getContinuations():
                    candidate = continuation.queryInterface(abort)
                    if candidate:
                        candidate.select()
                        return

        def prop(name, value):
            entry = uno.createUnoStruct("com.sun.star.beans.PropertyValue")
            entry.Name, entry.Value = name, value
            return entry

        context = uno.getComponentContext()
        document = context.ServiceManager.createInstanceWithContext(
            "com.sun.star.presentation.PresentationDocument", context
        )
        document.load(
            tuple(
                prop(name, value)
                for name, value in (
                    ("URL", (work / "input.pptx").as_uri()),
                    ("FilterName", "Impress MS PowerPoint 2007 XML"),
                    ("Hidden", True),
                    ("ReadOnly", True),
                    ("Silent", True),
                    ("MacroExecutionMode", uno.Any("short", 0)),
                    ("UpdateDocMode", uno.Any("short", 0)),
                    ("InteractionHandler", AbortInteraction()),
                )
            )
        )
        if not 1 <= slide <= document.DrawPages.Count <= 200:
            raise ValueError("Invalid slide count")
        options = tuple(
            prop(name, value)
            for name, value in (
                ("PageRange", str(slide)),
                ("ExportHiddenSlides", True),
                ("ExportNotesPages", False),
                ("ExportNotes", False),
                ("UseTransitionEffects", False),
                ("UseLosslessCompression", True),
                ("ReduceImageResolution", True),
                ("MaxImageResolution", 220),
            )
        )
        document.storeToURL(
            (work / "input.pdf").as_uri(),
            (
                prop("FilterName", "impress_pdf_Export"),
                prop("FilterData", uno.Any("[]com.sun.star.beans.PropertyValue", options)),
                prop("InteractionHandler", AbortInteraction()),
            ),
        )
    finally:
        if document is not None:
            document.dispose()
        kit.contents.klass.contents.destroy(kit)
        handle.close()


if __name__ == "__main__":
    try:
        convert(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]))
    except Exception:
        # Never print UNO exceptions: they can contain document text or paths.
        sys.exit(1)
