"""Serve the library and its pages, so they can be written on from a browser.

    python -m radbinical serve                          # http://127.0.0.1:8000, for this machine
    python -m radbinical serve --env-keys               # readers may use the keys in .env
    python -m radbinical serve --host 0.0.0.0 --port 80 # for other machines to reach

Pick a passage, and a bare page opens on it. Ask models for a round, or select some words and
either write a comment on them or ask models for one. Pages are kept in pages/ (--pages), each
under a long random id that is its only address.

Readers bring their own provider keys, kept in their browser and sent with each request; the
server uses them for that request's calls and stores nothing. Without --env-keys the keys in this
machine's .env are never used, so a server others can reach cannot spend them. Put a public
server behind HTTPS, since keys travel to it.
"""
import argparse

from ..serve import make_server


def main(a):
    server = make_server(a.host, a.port, a.pages, a.env_keys)
    print(f"http://{a.host}:{a.port}/" + ("   (using this machine's keys)" if a.env_keys else ""), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


def register(sub):
    p = sub.add_parser("serve", help="serve pages that can be written on", description=__doc__,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--pages", help="folder the pages are kept in (default pages/)")
    p.add_argument("--env-keys", action="store_true", help="let readers use the keys in this machine's environment")
    p.set_defaults(f=main)
