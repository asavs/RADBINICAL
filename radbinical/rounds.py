"""Running rounds: each reader takes a turn, and the page is saved after every round."""
import concurrent.futures as cf
import random

from .forecast import Forecaster
from .page import labeller, models_of, render_for_reader
from .prices import complete
from .prompts import system_prompt
from .providers import open_session
from .providers.http import add_usage
from .site import render


def take_turn(page, reader, layer, visible_fn, label, note):
    d, flags, me = page.d, page.d["flags"], reader["name"]
    visible = visible_fn(me)
    system = system_prompt(d, me, label, reader.get("protocol", "tools"))
    user = f"Round {layer}. {note}\n\n" + render_for_reader(d, visible, label, me)
    made, usage, closing, err, via = 0, {}, None, None, None
    try:
        session = open_session(reader, system, user, flags)
        via = session.via
        for _ in range(flags["max_steps_per_turn"]):
            calls, text, u = session.step()
            add_usage(usage, u)
            if not calls:
                closing = text.strip() or None
                if getattr(session, "truncated", False):
                    err = f"stopped at max_tokens={reader.get('max_tokens') or flags['max_tokens']} without finishing its turn"
                break
            results = []
            for cid, args in calls:
                cap = flags["max_comments_per_turn"]
                if args is None:
                    ok, res = False, "Not recorded: the arguments were not valid JSON."
                elif cap is not None and made >= cap:
                    ok, res = False, "Not recorded: you have reached this round's comment limit."
                else:
                    ok, res = page.add(me, layer, args)
                made += ok
                results.append((cid, res))
            session.reply(results)
    except Exception as e:  # one reader failing should not sink the round
        err = f"{type(e).__name__}: {e}"[:600]
    complete(reader["model"], usage)  # priced once on the summed tokens when the provider gave no cost
    entry = {"layer": layer, "reader": me, "model": reader["model"], "via": via, "comments": made, "usage": usage}
    if closing:
        entry["closing"] = closing[:2000]
    if err:
        entry["error"] = err
    with page.lock:
        d["log"].append(entry)
    print(f"  round {layer}  {me:<22} {made} comment{'s' if made != 1 else ''}" + (f"   ERROR {err}" if err else ""), flush=True)
    return made, err


def run_layers(page, how_many, only=None):
    """Run `how_many` rounds. With `only` (a set of reader names), only those readers take turns."""
    d, flags = page.d, page.d["flags"]
    rng = random.Random(f"{flags['seed']}-{d['layers_done']}")
    label = labeller(d)
    for _ in range(how_many):
        layer = d["layers_done"] + 1
        readers = [r for r in models_of(d) if only is None or r["name"] in only]
        rng.shuffle(readers)
        live = flags["sequential"] and not (layer == 1 and flags["blind_first_layer"])
        if live:
            vis = lambda me: list(d["comments"])
            note = "Readers take turns this round; you see the page as it stands now."
        else:
            vis = lambda me, L=layer: [c for c in d["comments"] if c["layer"] < L or c["author"] == me]
            note = ("The margins are empty. Every reader is annotating independently this round; you will see each other's comments next round."
                    if layer == 1 else "Everyone annotates at the same time this round; you will see this round's comments from the others next round.")
        print(f"round {layer}: {'in turn' if live else 'in parallel'}", flush=True)
        fc = Forecaster(page, layer, label) if flags["forecast"] and layer > 1 else None

        def turn(r):
            if fc:
                fc.ask(r, vis(r["name"]), note)
            return take_turn(page, r, layer, vis, label, note)
        if live:
            results = [turn(r) for r in readers]
        else:
            with cf.ThreadPoolExecutor(len(readers)) as ex:
                results = list(ex.map(turn, readers))
        if fc:
            fc.finish()
        d["layers_done"] = layer
        page.save()
        render(page.dir)
        if all(e for _, e in results):
            print("every reader failed this round; stopping.")
            return False
        if flags["stop_when_all_pass"] and sum(m for m, _ in results) == 0:
            print("everyone passed; the page is at rest.")
            d["at_rest"] = True
            page.save()
            break
    return True
