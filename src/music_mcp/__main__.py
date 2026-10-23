"""CLI: `music-mcp` serves over stdio; `music-mcp auth` links a Spotify account once."""

import argparse
import logging

from . import __version__


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="music-mcp", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="run the MCP server over stdio (default)")
    sub.add_parser("auth", help="log in to Spotify (Authorization Code + PKCE)")
    args = parser.parse_args(argv)

    # stdout is the MCP wire; logs must go to stderr.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.command == "auth":
        from .auth import login
        from .config import Settings

        login(Settings.from_env())
        return

    from .server import mcp

    mcp.run("stdio")


if __name__ == "__main__":
    main()
