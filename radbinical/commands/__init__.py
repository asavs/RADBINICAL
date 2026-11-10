"""One module per command. Each defines `register(sub)`; cli.py finds them all.

    def register(sub):
        p = sub.add_parser("name", help="one line for the command list", description=__doc__)
        p.add_argument(...)
        p.set_defaults(f=main)      # main(args) does the work
"""
