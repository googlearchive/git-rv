"""Get info command for git-rv command line tool.

Prints the information for the current review if there is one.
"""


import utils


class GetInfoAction(object):
    """A state machine that gets and prints current branch info.

    Attributes:
        __branch: String; containing the name of the current branch.
        __pull: String; indicating whether the Rietveld data should be updated
            by pulling metadata from the code review server.
    """

    GET_INFO = 0
    PULL = 1
    PRINT_INFO = 2
    FINISHED = 3

    def __init__(self, pull=False):
        """Constructor for GetInfoAction."""
        self.__branch = utils.get_current_branch()
        self.__pull = pull
        self.state = self.GET_INFO
        self.advance()

    @classmethod
    def callback(cls, args, unused_argv):
        """A callback to begin a GetInfoAction after arguments are parsed.

        Args:
            args: An argparse.Namespace object parsed from the command line.
            unused_argv: The original command line arguments that were parsed
                to create args. These are unused.

        Returns:
            An instance of GetInfoAction. Just by instantiating the instance,
                the state machine will begin working.
        """
        return cls(pull=args.pull)

    def get_info(self):
        """Gets Rietveld info for the current branch.

        If pull is True, sets state to PULL, otherwise to PRINT_INFO.
        """
        rietveld_info = utils.RietveldInfo.from_branch(
                branch_name=self.__branch)
        if self.__pull:
            self.state = self.PULL
        else:
            self.state = self.PRINT_INFO
        self.advance(rietveld_info)

    def pull(self, rietveld_info):
        """Updates Rietveld info with metadata from code review server.

        If successful, sets state to PRINT_INFO.

        Args:
            rietveld_info: RietveldInfo object for the current branch.
        """
        success, rietveld_info = utils.update_rietveld_metadata_from_issue(
                current_branch=self.__branch, rietveld_info=rietveld_info)
        if success:
            print 'Metadata update from code server succeeded.'
        else:
            print 'Metadata update from code server failed.'

        self.state = self.PRINT_INFO
        self.advance(rietveld_info)

    def print_info(self, rietveld_info):
        """Prints Rietveld info for the current branch, if there is any.

        If successful, sets state to FINISHED.

        Args:
            rietveld_info: RietveldInfo object for the current branch.
        """
        if rietveld_info is not None:
            print utils.json.dumps(rietveld_info.to_dict(), indent=2)
        else:
            print 'No review data found in branch %r.' % (self.__branch,)
        self.state = self.FINISHED
        self.advance()

    def advance(self, *args, **kwargs):
        """Advances by calling the method corresponding to the current state.

        Args:
            *args: Arguments to be passed to the specified method based on
                the current state.
            **kwargs: Keyword arguments to be passed to the specified method
                based on the current state.

        Raises:
            GitRvException: If this method is called and the state is not one
                of the valid states.
        """
        if self.state == self.GET_INFO:
            self.get_info(*args, **kwargs)
        elif self.state == self.PULL:
            self.pull(*args, **kwargs)
        elif self.state == self.PRINT_INFO:
            self.print_info(*args, **kwargs)
        elif self.state == self.FINISHED:
            return
        else:
            raise utils.GitRvException('Unexpected state %r in GetInfoAction.' %
                                       (self.state,))
