"""Command line. Every module in radbinical/commands/ is one command.

    python -m radbinical <command> -h      # what a command takes
"""
import argparse
import importlib
import pkgutil

from . import commands
from .config import load_dotenv


def parser():
    """The argument parser, with one subcommand per module in radbinical.commands.

    Each module defines `register(sub)`, where `sub` is the argparse subparsers object; it adds
    its parser and sets `f`, the function called with the parsed arguments.
    """
    ap = argparse.ArgumentParser(prog="radbinical", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="<command>")
    for m in pkgutil.iter_modules(commands.__path__):
        importlib.import_module(f"{commands.__name__}.{m.name}").register(sub)
    return ap


def main(argv=None):
    load_dotenv()
    a = parser().parse_args(argv)
    a.f(a)
