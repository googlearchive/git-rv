import sys

from git_rv import get_parser


def main(argv):
    """Runs main program.

    Args:
        argv: The list of command line arguments.

    Returns:
        The status code of the script.
    """
    first = argv[0]
    remaining = argv[1:]
    if not first.endswith('git-rv'):
        print 'ERROR: git-rv invoked through non-standard path'
        return 1

    parser = get_parser()
    args = parser.parse_args(remaining)
    args.callback(args, remaining)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
