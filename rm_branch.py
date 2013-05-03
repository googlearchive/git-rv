# Copyright 2013 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Remove branch command for git-rv command line tool."""


import utils


class DeleteBranchAction(object):
    """A state machine that deletes a review branch.

    Attributes:
        __branch: String; containing the name of the desired branch to be
            deleted.
    """

    CHECK_BRANCH = 0
    DELETE = 1
    FINISHED = 2

    def __init__(self, branch):
        """Constructor for DeleteBranchAction.

        Sets branch on the instance, sets state to CHECK_BRANCH and advances
        state machine.

        Args:
            branch: String; containing the name of the desired branch to be
                deleted.
        """
        self.__branch = branch
        self.state = self.CHECK_BRANCH
        self.advance()

    @classmethod
    def callback(cls, args, unused_argv):
        """A callback to begin a DeleteBranchAction after arguments are parsed.

        Args:
            args: An argparse.Namespace object containing values parsed from the
                command line.
            unused_argv: The original command line arguments that were parsed
                to create args. These are unused.

        Returns:
            An instance of DeleteBranchAction. Just by instantiating the
                instance, the state machine will begin working.
        """
        return cls(args.branch)

    def check_branch(self):
        """Checks if the branch can be deleted.

        We require that the branch exists, is not the current branch and is
        actually a review branch.

        If successful, sets state to DELETE, otherwise to FINISHED.
        """
        if not utils.branch_exists(self.__branch):
            print 'Branch %r doesn\'t exist.' % (self.__branch,)
            self.state = self.FINISHED
        elif self.__branch == utils.get_current_branch():
            print 'Can\'t delete current branch.' % (self.__branch,)
            self.state = self.FINISHED
        else:
            if not utils.in_review(current_branch=self.__branch):
                print 'Branch %r has no review in progress.' % (self.__branch,)
                print 'Instead, use the git command:'
                print '\tgit branch -D %s' % (self.__branch,)
                self.state = self.FINISHED
            else:
                self.state = self.DELETE
        self.advance()

    def delete(self):
        """Deletes the branch and the Rietveld info as well.

        If successful, sets state to FINISHED.
        """
        print 'Deleting branch...'
        print utils.capture_command('git', 'branch', '-D', self.__branch,
                                    single_line=False)

        print 'Deleting review info.'
        # TODO(dhermes): Consider closing this issue as well, or adding a flag
        #                to do so.
        utils.RietveldInfo.remove(branch_name=self.__branch)

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
        if self.state == self.CHECK_BRANCH:
            self.check_branch(*args, **kwargs)
        elif self.state == self.DELETE:
            self.delete(*args, **kwargs)
        elif self.state == self.FINISHED:
            return
        else:
            raise utils.GitRvException('Unexpected state %r in '
                                       'DeleteBranchAction.' % (self.state,))
