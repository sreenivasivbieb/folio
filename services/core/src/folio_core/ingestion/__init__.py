"""Turning files into indexed, locatable chunks.

    base.py        Parser plugin contract (ParsedUnit + locator)
    parsers/       one parser per file family (pdf, image, docx, text/md, vtt/srt, audio/video)
    registry.py    extension -> parser, plus third-party plugins via entry points
    sandbox.py     runs untrusted parsing in a resource-limited subprocess
    chunker.py     merges units into chunks without losing locators
    service.py     roots, scanning, hashing, indexing, "forget this file"
    watcher.py     debounced folder watching
"""
