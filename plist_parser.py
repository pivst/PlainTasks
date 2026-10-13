"""Read XML or binary property lists using Python's standard library."""

from io import BytesIO
from os import PathLike
import plistlib
from typing import BinaryIO, TextIO
from xml.parsers.expat import ExpatError


class PropertyListParseError(ValueError):
    """Raised when a property list cannot be decoded."""


class XmlPropertyListParser:
    """Compatibility wrapper for the original parser's public entry point."""

    def parse(self, xml_input: str | bytes | BinaryIO | TextIO):
        return parse_string(xml_input)


def parse_string(source: str | bytes | BinaryIO | TextIO):
    """Parse plist contents or a readable stream, preserving Unicode strings."""
    if hasattr(source, "read"):
        source = source.read()
    if isinstance(source, str):
        source = source.encode("utf-8")
    try:
        return plistlib.load(BytesIO(source))
    except (plistlib.InvalidFileException, ExpatError, ValueError, OverflowError) as error:
        raise PropertyListParseError(str(error)) from error


def parse_file(file_path: str | PathLike[str]):
    """Read a property list without relying on the platform text encoding."""
    with open(file_path, "rb") as stream:
        return parse_string(stream)
