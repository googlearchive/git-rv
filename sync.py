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

"""Sync command for git-rv command line tool.

Syncs the current review branch with the most recent commit in the
remote repository.
"""


import argparse

from export import ExportAction
import utils


TOO_MANY_COMMITS_AFTER_CONTINUE = """\
You have made more than one commit to resolve the merge
conflic. Please revert back to commit %(commit)r and attempt
to run "git rv sync --continue" again.

To revert back, you could execute
\tgit reset %(commit)s"""
UNEXPORTED_CHANGES_BLOCK_SYNC = """\
You have changes which have not been exported.
Please export them before syncing."""


class SyncAction(object):
    """A state machine that syncs the current review with a remote repository.

    Attributes:
        __continue: Boolean indicating whether or not this SyncAction is
            continuing or starting fresh.
        __branch: String; containing the name of the current branch.
        __rietveld_info: RietveldInfo object associated with current branch.
        __last_commit: String containing the hash of the last commit that
            was exported.
        __sync_halted: Boolean indicating whether a previous sync was halted in
            this review branch.
        __last_synced: String containing the hash of the last remote commit
            that was synced with this review. Added by fetch_remote method.
    """

    STARTING = 0
    CHECK_NEW = 1
    CHECK_CONTINUE = 2
    FETCH_REMOTE = 3
    MERGE_REMOTE_IN = 4
    ALERT_CONFLICT = 5
    EXPORT = 6
    CLEAN_UP = 7
    FINISHED = 8

    def __init__(self, in_continue):
        """Constructor for SyncAction.

        Args:
            in_continue: Boolean indicating whether or not this SyncAction is
                continuing or starting fresh.
        """
        self.__continue = in_continue
        self.__branch = utils.get_current_branch()
        self.__rietveld_info = utils.RietveldInfo.from_branch(
                branch_name=self.__branch)
        # Make sure we have review data
        if self.__rietveld_info is None:
            print 'There is no review data for branch %r.' % (self.__branch,)
            self.state = self.FINISHED
        else:
            self.state = self.STARTING
        self.advance()

    @classmethod
    def callback(cls, args, unused_argv):
        """A callback to begin a SyncAction after arguments are parsed.

        Args:
            args: An argparse.Namespace object parsed from the command line.
            unused_argv: The original command line arguments that were parsed
                to create args. These are unused.

        Returns:
            An instance of SyncAction. Just by creating a new instance,
                the state machine will begin working.
        """
        return cls(in_continue=args.in_continue)

    def check_environment(self):
        """Checks that a sync can be performed.

        If a sync can't be performed, sets state to FINISHED. If it can be,
        sets state to CHECK_CONTINUE or CHECK_NEW, depending on whether the sync
        is a continue sync or a new sync.
        """
        # Make sure branch is clean
        if not utils.in_clean_state():
            print 'Branch %r not in clean state:' % (self.__branch,)
            print utils.capture_command('git', 'diff', single_line=False)
            self.state = self.FINISHED
        else:
            # TODO(dhermes): This assumes review_info is not None. Fix this.
            self.__last_commit = self.__rietveld_info.review_info.last_commit
            # Using getattr since SYNC_HALTED is not an explicit attribute in
            # RietveldInfo, hence accessing rietveld_info.sync_halted may result
            # in an AttributeError.
            self.__sync_halted = getattr(self.__rietveld_info,
                                         utils.SYNC_HALTED, False)
            if self.__continue:
                self.state = self.CHECK_CONTINUE
            else:
                self.state = self.CHECK_NEW
        self.advance()

    def check_continue(self):
        """Checks that a sync can be performed in the continue case.

        We know the rietveld_info is valid and the current branch is clean.

        If a sync can't be continued, sets state to FINISHED. If it can be,
        sets state to EXPORT.
        """
        if not self.__sync_halted:
            print ('Can\'t continue sync; no halted sync detected in branch '
                   '%r.' % (self.__branch,))
            self.state = self.FINISHED
        else:
            commits = utils.get_commits(self.__last_commit, 'HEAD')
            if len(commits) == 0:
                print 'Please make a commit after resolving the merge conflict.'
                self.state = FINISHED
            elif len(commits) == 1:
                self.state = EXPORT
            else:
                template_args = {'commit': commits[-1]}
                print TOO_MANY_COMMITS_AFTER_CONTINUE % template_args
                self.state = self.FINISHED
        self.advance()

    def check_new_sync(self):
        """Checks that a sync can be performed in the new case.

        We know the rietveld_info is valid and the current branch is clean.

        If a sync can't be begun, sets state to FINISHED. If it can be,
        sets state to FETCH_REMOTE.
        """
        if self.__sync_halted:
            print ('A "git rv sync" was previously halted in branch %r. Please '
                   'execute the command:\n\tgit rv sync --continue\n'
                   'instead.' % (self.__branch,))
            self.state = self.FINISHED
        else:
            head_commit = utils.get_head_commit(current_branch=self.__branch)
            if head_commit != self.__last_commit:
                print UNEXPORTED_CHANGES_BLOCK_SYNC
                self.state = self.FINISHED
            else:
                self.state = self.FETCH_REMOTE
        self.advance()

    def fetch_remote(self):
        """Fetchs the remote associated with the current review.

        If the fetched remote has no new commits, sets state to FINISHED,
        otherwise sets state to MERGE_REMOTE_IN.
        """
        # TODO(dhermes): This assumes remote_info is not None. Fix this.
        remote = self.__rietveld_info.remote_info.remote
        print utils.capture_command('git', 'fetch', remote, single_line=False)

        remote_branch = self.__rietveld_info.remote_info.branch
        remote_branch_ref = '%s/%s' % (remote, remote_branch)

        new_head_in_remote = utils.get_head_commit(remote_branch_ref)
        if new_head_in_remote == self.__rietveld_info.remote_info.last_synced:
            print 'No new changes in %s.' % (remote_branch_ref,)
            self.state = self.FINISHED
        else:
            self.state = self.MERGE_REMOTE_IN
        self.__last_synced = new_head_in_remote
        self.advance()

    def merge(self):
        """Tries to merge the new content from the remote repository.

        If there is a merge conflict, sets state to ALERT_CONFLICT, otherwise
        sets state to EXPORT.
        """
        result, stdout, _ = utils.capture_command(
                'git', 'merge', '--squash',
                self.__last_synced, expect_success=False)
        print stdout
        if result == 0:
            sync_commit_message = 'Syncing review %s at %s.' % (
                    self.__branch, self.__last_synced)
            # TODO(dhermes): Catch error here.
            print utils.capture_command('git', 'commit', '-m',
                                        sync_commit_message, single_line=False)
            self.state = self.EXPORT
        else:
            self.state = self.ALERT_CONFLICT
        self.advance()

    def alert(self):
        """Alerts the user that a merge conflict needs to be resolved.

        Also sets SYNC_HALTED boolean in Rietveld info for current branch.

        If successful, sets state to CLEAN_UP.
        """
        print 'There are merge conflicts with the remote repository.'
        print 'Please resolve these conflicts, make a commit and run:'
        print '\tgit rv sync --continue'
        self.__rietveld_info.sync_halted = True
        self.__rietveld_info.save()
        self.state = self.CLEAN_UP
        self.advance(remove_halted=False)

    def export_to_review(self):
        """Exports the synced change to the review.

        An ExportAction is constructed for this purpose, with no current
        message, since it can be implied because the sync state machine ensures
        there will be exactly one commit.

        If successful, sets state to CLEAN_UP.
        """
        # Need to update this before the ExportAction for --rev={LAST_SYNCED}
        self.__rietveld_info.remote_info.last_synced = self.__last_synced
        self.__rietveld_info.save()

        print 'Exporting synced changes.'
        # TODO(dhermes): Do something more clear cut or fix ExportAction to have
        #                better defaults.
        # We have to lie about args, argv so ExportAction doesn't get mad
        fake_namespace = argparse.Namespace(
                server=self.__rietveld_info.server,
                private=self.__rietveld_info.private,
                cc=None, host=None, reviewers=None)
        ExportAction(self.__branch, fake_namespace, argv=['export'])
        self.state = self.CLEAN_UP
        self.advance()

    # TODO(dhermes): This is only serving one of the states that feeds in here;
    #                consider just moving this into export_to_review().
    def clean_up(self, remove_halted=True):
        """Cleans up sync related info.

        If remove_halted is True, removes the SYNC_HALTED boolean from Rietveld
        info. If the sync export succeeded, updates the LAST_SYNCED value in the
        REMOTE_INFO.

        If successful, sets state to FINISHED.

        Args:
            remove_halted: Boolean inidcating whether the SYNC_HALTED key should
                be removed from Rietveld info. Defaults to True.
            last_synced: String containing commit hash of last commit synced to
                from the remote. Defaults to None.
        """
        if remove_halted:
            self.__rietveld_info.remove_key(utils.SYNC_HALTED)

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
        if self.state == self.STARTING:
            self.check_environment(*args, **kwargs)
        elif self.state == self.CHECK_NEW:
            self.check_new_sync(*args, **kwargs)
        elif self.state == self.CHECK_CONTINUE:
            self.check_continue(*args, **kwargs)
        elif self.state == self.FETCH_REMOTE:
            self.fetch_remote(*args, **kwargs)
        elif self.state == self.MERGE_REMOTE_IN:
            self.merge(*args, **kwargs)
        elif self.state == self.ALERT_CONFLICT:
            self.alert(*args, **kwargs)
        elif self.state == self.EXPORT:
            self.export_to_review(*args, **kwargs)
        elif self.state == self.CLEAN_UP:
            self.clean_up(*args, **kwargs)
        elif self.state == self.FINISHED:
            return
        else:
            raise utils.GitRvException('Unexpected state %r in SyncAction.' %
                                       (self.state,))
