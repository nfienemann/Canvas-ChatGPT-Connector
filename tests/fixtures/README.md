# Synthetic complete-slide fixture

`full-slide.pptx` was generated locally with python-pptx and Pillow for renderer
verification. It contains no real course material or student records.

Slide 1 combines a navy background, a cropped raster drawing of four fictional
cells, separate CONTROL and 48 HOURS overlay labels, a title, explanatory sidebar,
footer and synthetic speaker notes. Slide 2 is hidden and has a purple background
and the text HIDDEN SECOND SLIDE. The test checks true slide numbering, text-layer
presence, distinct rendered images, composition colors and temporary-file cleanup.
