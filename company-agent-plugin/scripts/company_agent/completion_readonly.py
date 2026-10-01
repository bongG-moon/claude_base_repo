"""Small literal Bash inspection grammar, for completion accounting only.

This neither grants execution permission nor proves an executable trustworthy.
Unknown syntax keeps existing conservative accounting. Do not turn this into a
general shell parser: Read/Glob/Grep remain preferable for ordinary inspection.
"""
from __future__ import annotations

import re
import shlex


_TOKEN = re.compile(
    r'''[ \t]*(?:(?P<null>2>/dev/null)(?=$|[ \t;&|])|'''
    r'''(?P<operator>&&|\|\||[;|])|'''
    r'''(?P<word>(?:'[^']*'|"(?:[^"\\]|\\.)*"|\\[^\r\n]|[^ \t'"\\;&|<>])+))'''
)
_NUMBER = re.compile(r"[0-9]{1,6}")


def _has_unquoted_glob(word: str) -> bool:
    """Keep expansion evidence until the segment's executable is known."""
    quote = ""
    escaped = False
    for char in word:
        if escaped:
            escaped = False
        elif char == "\\" and quote != "'":
            escaped = True
        elif quote:
            if char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
        elif char in "*?[":
            return True
    return False


def _simple_options(values: list[str], options: str) -> bool:
    for value in values:
        if value == "--":
            return True  # All following values are literal input paths.
        if value.startswith("-") and not re.fullmatch(options, value):
            return False
    return True


def _grep(values: list[str]) -> bool:
    pattern = False
    index = 0
    while index < len(values):
        value = values[index]
        if value == "--":
            return pattern or index + 1 < len(values)
        if value == "-e":
            if index + 1 >= len(values) or pattern:
                return False
            pattern = True
            index += 2
            continue
        if value in {"-m", "-A", "-B", "-C"}:
            if index + 1 >= len(values) or not _NUMBER.fullmatch(values[index + 1]):
                return False
            index += 2
            continue
        if value.startswith("-"):
            if not re.fullmatch(r"-[EFivnHhowsclqx]+|-[mABC][0-9]{1,6}|--color=never", value):
                return False
        elif not pattern:
            pattern = True
        index += 1
    return pattern


def _inspection(arguments: list[str]) -> bool:
    name, values = arguments[0], arguments[1:]
    if name == "pwd":
        return not values
    if name == "ls":
        return _simple_options(values, r"-[laAdhF]+")
    if name == "cat":
        return _simple_options(values, r"-[AbEnsTv]+")
    if name == "head":
        if values[:1] == ["-n"]:
            if len(values) < 2 or not _NUMBER.fullmatch(values[1]):
                return False
            values = values[2:]
        return _simple_options(values, r"-[0-9]{1,6}")
    if name == "cd":
        if values[:1] == ["--"]:
            values = values[1:]
        return len(values) == 1 and bool(values[0]) and not values[0].startswith("-")
    if name == "sed":
        # Only bounded line printing. In-place edits, w/e commands, -f files,
        # substitutions and all other sed programs deliberately stay unknown.
        return (len(values) >= 2 and values[0] == "-n"
                and re.fullmatch(r"[1-9][0-9]{0,5}(?:,[1-9][0-9]{0,5})?p", values[1]) is not None
                and all(value and not value.startswith("-") for value in values[2:]))
    if name == "tr":
        flags = ""
        if values and values[0].startswith("-"):
            flags, values = values[0], values[1:]
            if not re.fullmatch(r"-[dscC]+", flags):
                return False
        expected = {1, 2} if "s" in flags else ({1} if "d" in flags else {2})
        return len(values) in expected and all(value and not value.startswith("-") for value in values)
    if name == "grep":
        return _grep(values)
    return False


def is_read_only_observation(command: str, tool_name: str) -> bool:
    """Recognize a bounded chain of literal queries without running anything."""
    if (tool_name.casefold() != "bash" or not command or len(command) > 4096
            or any(char in command for char in '\r\n\0$`(){}')
            or any(ord(char) < 32 and char != '\t' for char in command)):
        return False
    segments: list[list[str]] = [[]]
    segment_globs = [False]
    cursor = 0
    count = 0
    while cursor < len(command):
        if not command[cursor:].strip(" \t"):
            break
        token = _TOKEN.match(command, cursor)
        count += 1
        if token is None or count > 128:
            return False
        cursor = token.end()
        if token.lastgroup == "operator":
            if not segments[-1] or len(segments) >= 16:
                return False
            segments.append([])
            segment_globs.append(False)
        elif token.lastgroup == "null":
            if not segments[-1]:
                return False
        else:
            raw_word = token.group("word")
            segment_globs[-1] = segment_globs[-1] or _has_unquoted_glob(raw_word)
            try:
                words = shlex.split(raw_word, posix=True)
            except ValueError:
                return False
            if len(words) != 1:
                return False
            segments[-1].append(words[0])
    # sed options can write or execute. Expanded filenames could supply -i or
    # --expression, so no glob-bearing sed segment gets the query exemption.
    # Keep existing cat/ls/head and other read-only utilities' glob inspections:
    # their options do not execute programs or write named output files.
    return all(arguments and not (arguments[0] == "sed" and has_glob)
               and _inspection(arguments)
               for arguments, has_glob in zip(segments, segment_globs))
