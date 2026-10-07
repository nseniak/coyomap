"""How a coyomap verb reads its arguments, in one place: a parser that raises instead of exiting,
and the test for an argument the shell could not decode.

`argparse` answers a bad argument by printing its own one-line usage and exiting 2. A coyomap
dispatcher answers it with the verb's OWN usage block instead (`subverb_help.usage_error`), so its
parser must hand the error back rather than exit. `coyomap state` and `coyomap findings` each grew
the same two classes for that on the same day; this is the one both import.

A byte the shell could not decode reaches Python as a lone surrogate (`caf\\udce9.py`), and no UTF-8
file can hold one. A verb that writes its arguments into a file refuses such an argument up front
(`undecodable`): written, it failed half-way, and `coyomap record` had already emptied the fragment
it was writing.

Stdlib-only (the cli.py firewall). It imports nothing from coyomap, so any verb can import it.
"""
from __future__ import annotations

import argparse
from typing import NoReturn


class ArgError(Exception):
    """An argument error, which the dispatcher reports with the verb's usage block."""


class SubverbParser(argparse.ArgumentParser):
    """An `ArgumentParser` whose `error` raises `ArgError` instead of printing and exiting."""

    def error(self, message: str) -> NoReturn:
        raise ArgError(message)


def subverb_parser(prog: str) -> SubverbParser:
    """The parser of one sub-verb, named `prog` in its messages. It has no `-h` of its own:
    `subverb_help.handle` answers `--help` before any parser runs."""
    return SubverbParser(prog=prog, add_help=False)


def undecodable(value: str) -> bool:
    """True for an argument holding a byte the shell could not decode, which UTF-8 cannot hold."""
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return True
    return False
