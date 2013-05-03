"""Rename (mv) branch command for git-rv command line tool."""


import utils


class RenameBranchAction(object):
    """A state machine that renames a review branch.

    Attributes:
        __source_branch: String; containing the name of the desired branch
            to be renamed.
        __target_branch: String; containing the name of the desired new name
            for the branch.
    """

    CHECK_BRANCHES = 0
    RENAME = 1
    FINISHED = 2

    def __init__(self, source_branch, target_branch):
        """Constructor for RenameBranchAction.

        Sets branches on the instance, sets state to CHECK_BRANCHES and advances
        state machine.

        Args:
            source_branch: String; containing the name of the desired branch to
                be renamed.
            target_branch: String; containing the name of the desired new name
                for the branch.
        """
        self.__source_branch = source_branch
        self.__target_branch = target_branch
        self.state = self.CHECK_BRANCHES
        self.advance()

    @classmethod
    def callback(cls, args, unused_argv):
        """A callback to begin a RenameBranchAction after arguments are parsed.

        Args:
            args: An argparse.Namespace object containing values parsed from the
                command line.
            unused_argv: The original command line arguments that were parsed
                to create args. These are unused.

        Returns:
            An instance of RenameBranchAction. Just by instantiating the
                instance, the state machine will begin working.
        """
        return cls(*args.branches)

    def check_branches(self):
        """Checks if the branch can be renamed.

        We require that the source branch exists, is not the current branch and
        is actually a review branch. We also require that the target branch does
        not exist.

        If successful, sets state to RENAME, otherwise to FINISHED.
        """
        rietveld_info = None
        if utils.branch_exists(self.__target_branch):
            print 'Target branch %r already exists.' % (self.__target_branch,)
            self.state = self.FINISHED
        elif not utils.branch_exists(self.__source_branch):
            print 'Branch %r doesn\'t exist.' % (self.__source_branch,)
            self.state = self.FINISHED
        elif self.__source_branch == utils.get_current_branch():
            print 'Can\'t rename branch you\'re currently in.'
            self.state = self.FINISHED
        else:
            rietveld_info = utils.RietveldInfo.from_branch(
                    branch_name=self.__source_branch)
            if rietveld_info is None:
                print ('Branch %r has no review in progress.' %
                       (self.__source_branch,))
                print 'Instead, use the git command:'
                print '\tgit branch -m %s %s' % (self.__source_branch,
                                                 self.__target_branch)
                self.state = self.FINISHED
            else:
                self.state = self.RENAME
        self.advance(rietveld_info)

    def rename(self, rietveld_info):
        """Renames the source branch and moves the Rietveld info as well.

        If successful, sets state to FINISHED.

        Args:
            rietveld_info: RietveldInfo object for the branch. Is copied over
                to the new branch.

        Raises:
            GitRvException: If rietveld_info is None.
        """
        if rietveld_info is None:
            raise utils.GitRvException('Rename command received unexpected '
                                       'branch info.')

        print 'Renaming branch...'
        print utils.capture_command('git', 'branch', '-m', self.__source_branch,
                                    self.__target_branch, single_line=False)

        print 'Moving review info.'
        rietveld_info._branch_name = self.__target_branch
        rietveld_info.save()
        utils.RietveldInfo.remove(branch_name=self.__source_branch)

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
        if self.state == self.CHECK_BRANCHES:
            self.check_branches(*args, **kwargs)
        elif self.state == self.RENAME:
            self.rename(*args, **kwargs)
        elif self.state == self.FINISHED:
            return
        else:
            raise utils.GitRvException('Unexpected state %r in '
                                       'RenameBranchAction.' % (self.state,))
