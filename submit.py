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
        __description: String; description of the issue that was uploaded
            with the code review.
        __server: String; the server used for review of the issue in the current
            branch.
        __rpc_server_args: A list of server, email, host, save_cookies and
            account_type from the parsed command line arguments. This is passed
            to GetRpcServer when using it to sign in a user to close an issue.
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
            changes.
    """

    STARTING = 0
    UPDATE_FROM_METADATA = 1
    SQUASHING = 2
    CREATING_BRANCH = 3
    PUSHING = 4
    NOTIFY = 5
    CLEAN_UP_LOCAL = 6
    CLEAN_UP_REVIEW = 7
    FINISHED = 8

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

        self.__rietveld_info = utils.RietveldInfo.from_branch(
                branch_name=self.__branch)
        # TODO(dhermes): These assume rietveld_info is not None.

        # TODO(dhermes): This assumes rietveld_info.review_info is not None.
        self.__issue = self.__rietveld_info.review_info.issue

        self.__server = self.__rietveld_info.server
        rpc_server_args.insert(0, self.__server)
        self.__rpc_server_args = rpc_server_args
        self.__do_close = do_close

        # TODO(dhermes): These assume rietveld_info.remote_info is not None.
        self.__remote = self.__rietveld_info.remote_info.remote
        self.__remote_branch = self.__rietveld_info.remote_info.branch
        self.__last_synced = self.__rietveld_info.remote_info.last_synced

        self.state = self.STARTING
        self.advance()

    @classmethod
    def callback(cls, args, unused_argv):
        """A callback to begin an ExportAction after arguments are parsed.

        Args:
            args: An argparse.Namespace object to extract parameters from.
            unused_argv: The original command line arguments that were parsed
                to create args. These may be used in a call to upload.py. This
                parameter is not used.

        Returns:
            An instance of SubmitAction. Just by instantiating the instance, the
                state machine will begin working.
        """
        rpc_server_args = [args.email, args.host, args.save_cookies,
                           args.account_type]
        return cls(rpc_server_args=rpc_server_args, do_close=args.do_close)

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

        If successful, sets state to CREATING_BRANCH, otherwise sets to
        FINISHED. In either case, advances the state machine.
        """
        success, rietveld_info = utils.update_rietveld_metadata_from_issue(
                rietveld_info=self.__rietveld_info)
        if success:
            # TODO(dhermes): This assumes rietveld_info.review_info is not None.
            self.__description = rietveld_info.review_info.description
            self.state = self.CREATING_BRANCH
        else:
            # TODO(dhermes): Make this a constant.
            print 'Metadata update from code server failed.'
            self.state = self.FINISHED
        self.advance()

    def create_branch(self):
        """Creates a dummy branch to commit the reviewed changes to and push.

        If successful, sets state to SQUASHING and advances the state machine.
        """
        branch_name = BRANCH_NAME_TEMPLATE % self.__issue
        while utils.branch_exists(branch_name):
            branch_name += '_0'

        utils.capture_command('git', 'branch', '--no-track', branch_name,
                              self.__last_synced, single_line=False)
        self.__review_branch = branch_name
        self.state = self.SQUASHING
        self.advance()

    def commit(self):
        """Turns the reviewed commits into a single commit.

        Uses --squash to combine all the reviewed patches/commits into a single
        commit. Uses the issue description (from the review) and a note about
        the review.

        If successful, sets state to PUSHING and advances the state machine.
        """
        print 'Checking out %s/%s at %s.' % (self.__remote,
                                             self.__review_branch,
                                             self.__last_synced)
        utils.capture_command('git', 'checkout', self.__review_branch,
                              single_line=False)

        print 'Adding reviewed commits.'
        # http://365git.tumblr.com/post/4364212086/git-merge-squash
        utils.capture_command('git', 'merge', '--squash', self.__branch,
                              single_line=False)

        final_commit_message = utils.SQUASH_COMMIT_TEMPLATE % {
            utils.ISSUE_DESCRIPTION: self.__description,
            utils.ISSUE: self.__issue,
            utils.SERVER: self.__server,
        }
        print 'Adding commit:\n', final_commit_message
        utils.capture_command('git', 'commit', '-m', final_commit_message,
                              single_line=False)
        self.state = self.PUSHING
        self.advance()

    def push_commit(self):
        """Pushes the squashed commit to the remote repository.

        If the push fails, saves the error message so it can be used to
        notify the user.

        If successful, sets state to CLEAN_UP_LOCAL, otherwise to NOTIFY. In
        either case, advances the state machine.
        """
        branch_mapping = '%s:%s' % (self.__review_branch, self.__remote_branch)
        result, _, stderr = utils.capture_command(
                'git', 'push', self.__remote, branch_mapping,
                expect_success=False)
        next_state_kwargs = {}
        if result != 0:
            # TODO(dhermes): Should we try a sync and proceed if no failure?
            next_state_kwargs['error_message'] = stderr
            self.state = self.NOTIFY
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
            #                version of the remote. Is this enough to gaurantee
            #                we are doing the right thing here?
            # Add back the review branch with HEAD at the new commit
            branch_with_remote = '%s/%s' % (self.__remote, self.__remote_branch)
            utils.capture_command('git', 'branch', '--track', self.__branch,
                                  branch_with_remote, single_line=False)

            # Remove Rietveld metadata associated with the review branch
            utils.RietveldInfo.remove(branch_name=self.__branch)

        # Check out the review branch
        utils.capture_command('git', 'checkout', self.__branch,
                              single_line=False)
        # Delete the dummy branch created by this action
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
        rpc_server = GetRpcServer(*self.__rpc_server_args)
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
                utils.SUBJECT: self.__description,
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
        if self.state == self.STARTING:
            self.verify_approval(*args, **kwargs)
        elif self.state == self.UPDATE_FROM_METADATA:
            self.update_from_metadata(*args, **kwargs)
        elif self.state == self.CREATING_BRANCH:
            self.create_branch(*args, **kwargs)
        elif self.state == self.SQUASHING:
            self.commit(*args, **kwargs)
        elif self.state == self.PUSHING:
            self.push_commit(*args, **kwargs)
        elif self.state == self.NOTIFY:
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
