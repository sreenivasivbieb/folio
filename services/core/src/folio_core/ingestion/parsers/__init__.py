"""Built-in parsers, one module per file family."""

from .docx import DocxParser
from .image import ImageParser
from .media import MediaParser
from .pdf import PdfParser
from .subtitles import SubtitleParser
from .text import TextParser

BUILTIN_PARSERS = [TextParser(), DocxParser(), PdfParser(), ImageParser(), SubtitleParser(),
                   MediaParser()]

__all__ = ["BUILTIN_PARSERS"]
