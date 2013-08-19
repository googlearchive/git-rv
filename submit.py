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

"""Submit command for git-rv command line tool.

Allows current issue under review to be submitted.
"""


import urllib
import urllib2

from upload import GetRpcServer

import utils


BRANCH_NAME_TEMPLATE = 'review-%d'


class SubmitAction(object):
    """A state machine which submits a reviewed change to the main repository.

    Attributes:
        state: The current state of the SubmitAction state machine.
        __branch: The current branch when the action begins.
        __issue: Integer; containing the ID of the code review issue
            corresponding to the current branch.
        __subject: String; subject of the issue that was uploaded with the code
            review.
        __description: String; description of the issue that was uploaded
            with the code review.
        __server: String; the server used for review of the issue in the current
            branch.
        __rpc_server_args: A dictionary of arguments parsed from the command
            line that will be passed to GetRpcServer when using it to sign in a
            user to close and comment on an issue.
        __do_close: Boolean; Represents whether the issue should be closed
            after pushing the commit.
        __rietveld_info: RietveldInfo object associated with the current branch.
        __remote: String containing the remote the current review is being
            diffed against.
        __remote_branch: String containing the branch in the remote that the
            current review is being diffed against.
        __last_synced: String containing the commit hash in the remote branch
            that the current review was last synced with.
        __review_branch: String; the name of the dummy branch created to push
            changes. This value is set as None in the constructor and will only
            be set if a review branch is successfully created.
    """

    CHECK_ENVIRONMENT = 0
    VERIFY_APPROVAL = 1
    UPDATE_FROM_METADATA = 2
    ENTER_DETACHED_STATE = 3
    SET_HISTORY_FROM_REMOTE = 4
    CREATE_BRANCH = 5
    COMMIT = 6
    PUSHING = 7
    NOTIFY_FAILURE = 8
    CLEAN_UP_LOCAL = 9
    CLEAN_UP_REVIEW = 10
    FINISHED = 11

    def __init__(self, rpc_server_args, do_close=True):
        """Constructor for SubmitAction.

        Args:
            rpc_server_args: A list of email, host, save_cookies and
                account_type from the parsed command line arguments.
            do_close: Boolean; defaults to True. Represents whether the issue
                should be closed after pushing the commit.

        Saves some environment data on the object such as the current branch,
        and the issue, server and issue description associated with the current
        branch.
        """
        self.__branch = utils.get_current_branch()
        self.__review_branch = None

        self.__rietveld_info = utils.RietveldInfo.from_branch(
                branch_name=self.__branch)
        # TODO(dhermes): These assume rietveld_info is not None.

        # TODO(dhermes): This assumes rietveld_info.review_info is not None.
        self.__issue = self.__rietveld_info.review_info.issue

        self.__server = self.__rietveld_info.server
        self.__rpc_server_args = rpc_server_args
        # Add the server
        self.__rpc_server_args['server'] = self.__server
        self.__do_close = do_close

        # TODO(dhermes): These assume rietveld_info.remote_info is not None.
        self.__remote = self.__rietveld_info.remote_info.remote
        self.__remote_branch = self.__rietveld_info.remote_info.branch
        self.__last_synced = self.__rietveld_info.remote_info.last_synced

        self.state = self.CHECK_ENVIRONMENT
        self.advance()

    @classmethod
    def callback(cls, args, unused_argv):
        """A callback to begin a SubmitAction after arguments are parsed.

        Args:
            args: An argparse.Namespace object to extract parameters from.
            unused_argv: The original command line arguments that were parsed
                to create args. These may be used in a call to upload.py. This
                parameter is not used.

        Returns:
            An instance of SubmitAction. Just by instantiating the instance, the
                state machine will begin working.
        """
        rpc_server_args = {
            'host_override': args.host,
            'save_cookies': False,
            'account_type': args.account_type,
            'use_oauth2': True,
            'oauth2_port': args.oauth2_port,
            'open_oauth2_local_webbrowser': args.open_oauth2_local_webbrowser,
        }
        return cls(rpc_server_args=rpc_server_args, do_close=args.do_close)

    # TODO(dhermes): There is a very similar method in sync. Be sure to
    #                consolidate these when improving the state machine.
    def check_environment(self):
        """Checks that the current review branch is in a clean state.

        If not, we can't submit, so sets state to FINISHED after notifying the
        user of the issue. If it can be, sets state to VERIFY_APPROVAL. In
        either case, advances the state machine.
        """
        # Make sure branch is clean
        if not utils.in_clean_state():
            print 'Branch %r not in clean state:' % (self.__branch,)
            print utils.capture_command('git', 'diff', single_line=False)
            self.state = self.FINISHED
        else:
            self.state = self.VERIFY_APPROVAL

        self.advance()

    def verify_approval(self):
        """Verifies that the current issue has been approved in review.

        If successful, sets state to UPDATE_FROM_METADATA, otherwise sets to
        FINISHED. In either case, advances the state machine.
        """
        approved = utils.is_current_issue_approved(issue=self.__issue,
                                                   current_branch=self.__branch,
                                                   server=self.__server)
        if approved:
            self.state = self.UPDATE_FROM_METADATA
        else:
            # TODO(dhermes): Make this a constant.
            print 'This review has not been approved.'
            self.state = self.FINISHED
        self.advance()

    def update_from_metadata(self):
        """Updates Rietveld info with metadata from code review server.

        If successful, sets state to ENTER_DETACHED_STATE, otherwise sets to
        FINISHED. In either case, advances the state machine.
        """
        success, rietveld_info = utils.update_rietveld_metadata_from_issue(
                rietveld_info=self.__rietveld_info)
        if success:
            # TODO(dhermes): This assumes rietveld_info.review_info is not None.
            self.__subject = rietveld_info.review_info.subject
            self.__description = rietveld_info.review_info.description
            self.state = self.ENTER_DETACHED_STATE
        else:
            # TODO(dhermes): Make this a constant.
            print 'Metadata update from code server failed.'
            self.state = self.FINISHED
        self.advance()

    def enter_detached_state(self):
        """Enters detached HEAD state with review contents.

        Enters a detached HEAD state holding the contents of the review branch,
        but none of the history. This is so we can rewrite the history to apply
        the reviewed work to the existing history of the remote branch.

        Thanks to http://stackoverflow.com/a/4481621/1068170 for the merge
        strategy.

        If successful, sets state to SET_HISTORY_FROM_REMOTE; if not, saves the
        error message and sets state to NOTIFY_FAILURE. In either case, advances
        the state machine.
        """
        # Dictionary to pass along state to advance()
        next_state_kwargs = {}

        # Enter detached HEAD state
        print 'Entering detached HEAD state with contents from %s.' % (
                self.__branch,)
        current_branch_detached = '%s@{0}' % (self.__branch,)
        result, _, stderr = utils.capture_command(
                'git', 'checkout', current_branch_detached,
                expect_success=False)

        if result != 0:
            next_state_kwargs['error_message'] = stderr
            self.state = self.NOTIFY_FAILURE
        else:
            self.state = self.SET_HISTORY_FROM_REMOTE

        self.advance(**next_state_kwargs)

    def set_history_from_remote(self):
        """Sets history in detached HEAD to the remote history.

        Uses a soft reset to add the commit history from the last synced commit
        in the remote branch.

        Thanks to http://stackoverflow.com/a/4481621/1068170 for the merge
        strategy.

        If successful, sets state to CREATE_BRANCH; if not, saves the error
        message and sets state to NOTIFY_FAILURE. In either case, advances the
        state machine.
        """
        # Dictionary to pass along state to advance()
        next_state_kwargs = {}

        # Soft reset to add remote branch commit history
        print 'Setting head at %s.' % (self.__last_synced,)
        result, _, stderr = utils.capture_command(
                'git', 'reset', '--soft', self.__last_synced,
                expect_success=False)

        if result != 0:
            next_state_kwargs['error_message'] = stderr
            self.state = self.NOTIFY_FAILURE
        else:
            self.state = self.CREATE_BRANCH

        self.advance(**next_state_kwargs)

    def create_branch(self):
        """Creates dummy branch with contents from detached HEAD.

        - Finds a dummy name by using BRANCH_NAME_TEMPLATE and the current issue
          and then adding '_0' until it finds a branch name which doesn't
          already exist.
        - Creates and checks out (via checkout -b) the contents using the dummy
          name.

        Thanks to http://stackoverflow.com/a/4481621/1068170 for the merge
        strategy.

        If successful, sets state to COMMIT; if not, saves the error message and
        state to NOTIFY_FAILURE. In either case, advances the state machine.
        """
        # Find dummy branch name
        review_branch = BRANCH_NAME_TEMPLATE % self.__issue
        while utils.branch_exists(review_branch):
            review_branch += '_0'

        # Dictionary to pass along state to advance()
        next_state_kwargs = {}

        # Create and checkout review branch
        print 'Checking out %s at %s.' % (review_branch, self.__last_synced)
        result, _, stderr = utils.capture_command(
                'git', 'checkout', '-b', review_branch,
                expect_success=False)

        if result != 0:
            next_state_kwargs['error_message'] = stderr
            self.state = self.NOTIFY_FAILURE
        else:
            # Only set the review branch if it is created.
            self.__review_branch = review_branch
            self.state = self.COMMIT

        self.advance(**next_state_kwargs)

    def commit(self):
        """Adds reviewed changes to stable contents in dummy branch.

        Commits the current content as a single commit (extra) in this
        remote branch history (but in the local branch). Uses the issue
        description (from the review) and adds a note about the review.

        If successful, sets state to PUSHING; if not, saves the error message
        and state to NOTIFY_FAILURE. In either case, advances the state machine.
        """
        # Dictionary to pass along state to advance()
        next_state_kwargs = {}

        # Commit the current content
        description_newline = ''
        if self.__description:
            description_newline = '\n\n'
        final_commit_message = utils.SQUASH_COMMIT_TEMPLATE % {
            utils.SUBJECT: self.__subject,
            utils.DESCRIPTION_NEWLINE: description_newline,
            utils.ISSUE_DESCRIPTION: self.__description,
            utils.ISSUE: self.__issue,
            utils.SERVER: self.__server,
        }
        print 'Adding commit:'
        print final_commit_message
        result, _, stderr = utils.capture_command(
                'git', 'commit', '-m', final_commit_message,
                expect_success=False)
        if result != 0:
            next_state_kwargs['error_message'] = stderr
            self.state = self.NOTIFY_FAILURE
        else:
            self.state = self.PUSHING

        # Advance
        self.advance(**next_state_kwargs)

    def push_commit(self):
        """Pushes the squashed commit to the remote repository.

        If the push fails, saves the error message so it can be used to
        notify the user.

        If successful, sets state to CLEAN_UP_LOCAL, otherwise to
        NOTIFY_FAILURE. In either case, advances the state machine.
        """
        # Dictionary to pass along state to advance()
        next_state_kwargs = {}

        branch_mapping = '%s:%s' % (self.__review_branch, self.__remote_branch)
        result, _, stderr = utils.capture_command(
                'git', 'push', self.__remote, branch_mapping,
                expect_success=False)
        if result != 0:
            # TODO(dhermes): Should we try a sync and proceed if no failure?
            next_state_kwargs['error_message'] = stderr
            self.state = self.NOTIFY_FAILURE
        else:
            next_state_kwargs['success'] = True
            self.state = self.CLEAN_UP_LOCAL

        self.advance(**next_state_kwargs)

    def notify_failure(self, error_message):
        """Notifies the user of the script failure.

        If successful, sets state to CLEAN_UP_LOCAL.

        Args:
            error_message: String; a captured error from the "git push" command.
                This is only set if a non-0 status code occurs in push_commit.
        """
        # TODO(dhermes): Should we just always suggest 'git rv sync'?
        if utils.TIP_BEHIND_HINT in error_message:
            print utils.TIP_BEHIND_HINT
            print
            print 'Run "git rv sync".'
        else:
            print 'Unkown error occurred:'
            print error_message
        self.state = self.CLEAN_UP_LOCAL
        self.advance(success=False)

    def clean_up_local(self, success=False):
        """Cleans up the repository after a commit or failure.

        Deletes the dummy branch created and checks back out the review branch.

        If the SubmitAction was successful (success), then the branch metadata
        is removed from the git config. In addition, the review
        branch will be replaced with HEAD at the newly submitted commit.

        If the SubmitAction was not successful, all other cleanup for the
        failure case is considered to have been done before.

        If the SubmitAction was successful, sets state to CLEAN_UP_REVIEW,
        otherwise sets it to FINISHED. In either case, advances the state
        machine.

        Args:
            success: Boolean indicating whether or not the submit succeeded.
        """
        if success:
            print ('Replacing review branch %r with newly '
                   'committed content.' % (self.__branch,))
            # Remove the review branch
            utils.capture_command('git', 'branch', '-D', self.__branch,
                                  single_line=False)
            # TODO(dhermes): The git push will update the locally stored
            #                version of the remote. Is this enough to guarantee
            #                we are doing the right thing here?
            # Add back the review branch with HEAD at the new commit
            utils.capture_command(
                    'git', 'branch', '--track', self.__branch,
                    self.__rietveld_info.remote_info.remote_branch_ref,
                    single_line=False)

            # Remove Rietveld metadata associated with the review branch
            utils.RietveldInfo.remove(branch_name=self.__branch)

        # Check out the review branch. We use -f in case we failed in a detached
        # HEAD or dirty state and want to get back to our clean branch.
        utils.capture_command('git', 'checkout', '-f', self.__branch,
                              single_line=False)

        # This brings the review branch back to a stable state, which it was
        # required to be in by check_environment(). If there are no pending
        # changes left over from the checkout -f, this hard reset does nothing.
        utils.capture_command('git', 'reset', '--hard', 'HEAD',
                              single_line=False)

        # If __review_branch was set, we know we have a dummy branch created
        # by this action which must be deleted.
        if self.__review_branch is not None:
            utils.capture_command('git', 'branch', '-D', self.__review_branch,
                                  single_line=False)

        if success:
            self.state = self.CLEAN_UP_REVIEW
        else:
            self.state = self.FINISHED
        self.advance()

    def __get_xsrf_server(self):
        """Gets an authenticated RPC server and XSRF token for API calls.

        If the XSRF token exchange fails, simply notifies the user of the
        failure and moves on.

        Returns:
            Tuple rpc_server, xsrf_token where rpc_server is an authenticated
                upload.HttpRpcServer instance and xsrf_token is a string used to
                make API requests to the Rietveld server.
        """
        rpc_server = GetRpcServer(**self.__rpc_server_args)
        if not rpc_server.authenticated:
            rpc_server._Authenticate()
        try:
            xsrf_token = rpc_server.Send('/' + utils.XSRF_TOKEN,
                                         extra_headers=utils.XSRF_HEADERS)
        except urllib2.HTTPError:
            xsrf_token = None
        return rpc_server, xsrf_token

    def __add_commit_link(self, rpc_server, xsrf_token, commit_hash):
        """Adds a link to the reviewed commit on the code review issue.

        If no repository can be parsed from the remote URL, does nothing.

        If the "publish" action fails, simply notifies the user of the failure
        and moves on.

        Args:
            rpc_server: An authenticated instance of upload.HttpRpcServer.
            xsrf_token: String containing XSRF token to make API requests.
            commit_hash: String; the hash of the commit which we are trying
                to publish a link to.
        """
        repository_info = self.__rietveld_info.remote_info.repository_info
        if repository_info is None:
            return

        try:
            commit_link = repository_info.commit_link(commit_hash)
            message = 'Added in\n%s' % (commit_link,)
            publish_request_values = {
                utils.XSRF_TOKEN: xsrf_token,
                utils.MESSAGE: message,
                utils.CC: self.__rietveld_info.cc,
                utils.REVIEWERS: self.__rietveld_info.reviewers,
                utils.SUBJECT: self.__subject,
            }
            publish_request_values.update(utils.PUBLISH_ISSUE_BASE)
            publish_request_body = urllib.urlencode(publish_request_values)
            publish_issue_uri = utils.PUBLISH_ISSUE_MESSAGE_TEMPLATE % {
                  utils.ISSUE: self.__issue}
            rpc_server.Send(publish_issue_uri, payload=publish_request_body)
        except urllib2.HTTPError:
            print utils.FAILED_PUBLISH_TEMPLATE % {
                utils.ISSUE: self.__issue,
                utils.SERVER: self.__server,
                utils.MESSAGE: message,
            }
        else:
            print 'Message:\n%s\nposted to code review issue.' % (message,)

    def __close_issue(self, rpc_server, xsrf_token):
        """Closes the issue associated with the current SubmitAction.

        If the "close" action fails, simply notifies the user of the failure and
        moves on.

        Args:
            rpc_server: An authenticated instance of upload.HttpRpcServer.
            xsrf_token: String containing XSRF token to make API requests.
        """
        try:
            xsrf_request_body = urllib.urlencode({utils.XSRF_TOKEN: xsrf_token})
            close_issue_uri = utils.CLOSE_ISSUE_TEMPLATE % {
                  utils.ISSUE: self.__issue}
            rpc_server.Send(close_issue_uri, payload=xsrf_request_body)
        except urllib2.HTTPError:
            print utils.FAILED_CLOSE_TEMPLATE % {
                utils.ISSUE: self.__issue,
                utils.SERVER: self.__server
            }
        else:
            print 'Issue %d has been closed.' % (self.__issue,)

    def clean_up_review(self):
        """Cleans up the issue on the review server after successful commit.

        If possible to detect, adds message explaining where the reviewed
        changes were committed. If not explicitly asked to be left open by the
        user (via --leave_open), the issue will be closed as well.

        If successful, sets state to FINISHED and advances the state machine.
        """
        rpc_server, xsrf_token = self.__get_xsrf_server()
        # We know this will be the commit just pushed since clean_up_local has
        # just succeeded.
        commit_hash = utils.get_head_commit(current_branch=self.__branch)

        self.__add_commit_link(rpc_server, xsrf_token, commit_hash)
        if self.__do_close:
            self.__close_issue(rpc_server, xsrf_token)

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
        if self.state == self.CHECK_ENVIRONMENT:
            self.check_environment(*args, **kwargs)
        elif self.state == self.VERIFY_APPROVAL:
            self.verify_approval(*args, **kwargs)
        elif self.state == self.UPDATE_FROM_METADATA:
            self.update_from_metadata(*args, **kwargs)
        elif self.state == self.ENTER_DETACHED_STATE:
            self.enter_detached_state(*args, **kwargs)
        elif self.state == self.SET_HISTORY_FROM_REMOTE:
            self.set_history_from_remote(*args, **kwargs)
        elif self.state == self.CREATE_BRANCH:
            self.create_branch(*args, **kwargs)
        elif self.state == self.COMMIT:
            self.commit(*args, **kwargs)
        elif self.state == self.PUSHING:
            self.push_commit(*args, **kwargs)
        elif self.state == self.NOTIFY_FAILURE:
            self.notify_failure(*args, **kwargs)
        elif self.state == self.CLEAN_UP_LOCAL:
            self.clean_up_local(*args, **kwargs)
        elif self.state == self.CLEAN_UP_REVIEW:
            self.clean_up_review(*args, **kwargs)
        elif self.state == self.FINISHED:
            return
        else:
            raise utils.GitRvException('Unexpected state %r in SubmitAction.' %
                                       (self.state,))
