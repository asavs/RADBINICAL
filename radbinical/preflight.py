"""Asking each reader for one word before a run spends anything.

A reader whose provider is out of credit, has no quota for the model, or no longer serves it
fails every turn of a run, and the page that comes out is missing a voice. `preflight` sends each
model reader one small request, with the output limit the run will use (a shared provider refuses
a request whose limit the account cannot afford), and reports who answered.
"""
import concurrent.futures as cf

from .providers import http, open_session, split_model

SYSTEM = "This is a connection check before a longer task."
USER = "Reply with the single word: ready"


def probe(reader, flags):
    """(provider the reader went through or None, why it failed or None), from one small request."""
    try:
        session = open_session(reader, SYSTEM, USER, flags)
        session.step()
        return session.via, None
    except Exception as e:
        return None, " ".join(f"{type(e).__name__}: {e}".split())[:300]


def preflight(readers, flags):
    """Probe every model reader at once. Returns [(reader, via, error)] in the order given. Mock
    readers are not called. A refusal is not waited out: the retries a run makes are switched off."""
    live = [r for r in readers if split_model(r["model"])[0] != "mock"]
    if not live:
        return [(r, "mock", None) for r in readers]
    attempts, http.ATTEMPTS = http.ATTEMPTS, 1
    try:
        with cf.ThreadPoolExecutor(len(live)) as ex:
            got = dict(zip((r["name"] for r in live), ex.map(lambda r: probe(r, flags), live)))
    finally:
        http.ATTEMPTS = attempts
    return [(r, *got.get(r["name"], ("mock", None))) for r in readers]


def report(results):
    """Print one line per reader; return the names of those that could not be reached."""
    for r, via, err in results:
        print(f"  {r['name']:<22} {('via ' + via) if not err else 'UNREACHABLE'}" + (f"   {err}" if err else ""), flush=True)
    return [r["name"] for r, _, err in results if err]


def require(readers, flags):
    """Exit, naming who could not be reached, unless every reader answers."""
    print("checking that every reader can be reached", flush=True)
    down = report(preflight(readers, flags))
    if down:
        raise SystemExit(f"not started: {', '.join(down)} could not be reached. Fix the account or the model id, "
                         "leave the reader out, or pass --no-check to run without them answering.")
