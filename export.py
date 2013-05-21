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

"""Export command for git-rv command line tool.

Allows exporting a new issue for review and interacting with that issue
by changing reviewers, submitting new patches and doing various other
things.
"""


from upload import RealMain

import utils
from utils import GitRvException


class ExportAction(object):
    """A state machine which exports a commit to a review.

    Attributes:
        state: The current state of the ExportAction state machine.
        __branch: The current branch when the action begins.
        __current_head: The HEAD commit in the current branch.
        __rietveld_info: RietveldInfo object associated with the current branch.
        __message_overridden: Boolean indicating whether the git commit message
            for the change being exported was overridden by a command line
            argument.
        __current_message: The value passed in from the command line or inferred
            from the actual commit being exported.
        __argv: A list of strings containing the actual command line arguments.
        __no_send_mail: Boolean representing whether or not --send_mail should
            be added to the upload.py call.
    """

    STARTING = 0
    UPLOADING_ISSUE = 1
    UPDATING_ISSUE = 2
    UPDATING_METADATA = 3
    FINISHED = 4

    @property
    def rietveld_info(self):
        """Simple accessor for stored RietveldInfo on Export.

        This is intended to be used by other actions (such as sync) that might
        need to access the RietveldInfo after an ExportAction completes.
        """
        return self.__rietveld_info

    # TODO(dhermes): Make sure things can be re-wound?
    #                Final vs. in-progress in metadata.
    def __init__(self, current_branch, args, current_message=None,
                 no_send_mail=False, argv=None):
        """Constructor for ExportAction.

        Saves some environment data on the object such as the current branch and
        the metadata for the current branch.

        Args:
            current_branch: String; containing the name of a branch.
            args: An argparse.Namespace object to extract parameters from.
            current_message: The message for the given review export. Defaults
                to None, in which case the git commit message of the most recent
                commit is used.
            no_send_mail: Boolean representing whether or not --send_mail should
                be added to the upload.py call.
            argv: The original command line arguments that were parsed to create
                args. These may be used in a call to upload.py.
        """
        self.__branch = current_branch
        self.__current_head = utils.get_head_commit(
                current_branch=self.__branch)

        self.__rietveld_info = utils.RietveldInfo.from_branch(
                branch_name=self.__branch) or utils.RietveldInfo(self.__branch)
        self.__update_rietveld_info_from_args(args)

        # Add remote info if it isn't already there.
        if self.__rietveld_info.remote_info is None:
            remote_info = utils.get_remote_info(current_branch=self.__branch)
            self.__rietveld_info.remote_info = remote_info

        self.__rietveld_info.save()

        self.__message_overridden = current_message is not None
        self.__current_message = self.__get_current_message(current_message)
        self.__argv = argv
        self.__no_send_mail = no_send_mail
        self.state = self.STARTING
        self.advance()

    def __update_rietveld_info_from_args(self, args):
        """Updates the current rietveld_info with args from the command line.

        Args:
            args: An argparse.Namespace object to extract parameters from.
        """
        self.__rietveld_info.server = args.server
        self.__rietveld_info.private = args.private
        if args.cc is not None:
            self.__rietveld_info.cc = args.cc
        if args.host is not None:
            self.__rietveld_info.host = args.host
        if args.reviewers is not None:
            self.__rietveld_info.reviewers = args.reviewers

    def __get_current_message(self, current_message):
        """Gets a message for the current patch set.

        If the current message passed in is not None, uses that. Otherwise uses

        Args:
            current_message: The message for the given review export. This will
                be from the constructor, where it defaults to None.

        Returns:
            String containing the message chosen by the user. If there have been
                no commits since the last review, returns None.
        """
        if current_message is not None:
            return current_message

        if self.__rietveld_info.review_info is None:
            # RemoteInfo always populated in callback()
            remote_branch = self.__rietveld_info.remote_info.remote_branch_ref
            last_commit = self.__rietveld_info.remote_info.commit_hash
        else:
            remote_branch = None
            last_commit = self.__rietveld_info.review_info.last_commit

        return utils.get_user_commit_message(last_commit, self.__current_head,
                                             remote_branch=remote_branch)

    @classmethod
    def callback(cls, args, argv):
        """A callback to begin an ExportAction after arguments are parsed.

        If the branch is not in a clean state, won't create an ExportAction,
        will just print 'git diff' and proceed.

        Args:
            args: An argparse.Namespace object to extract parameters from.
            argv: The original command line arguments that were parsed to create
                args. These may be used in a call to upload.py.

        Returns:
            An instance of ExportAction. Just by instantiating the instance, the
                state machine will begin working.
        """
        current_branch = utils.get_current_branch()
        if not utils.in_clean_state():
            print 'Branch %r not in clean state:' % (current_branch,)
            print utils.capture_command('git', 'diff', single_line=False)
            return

        if args.no_mail and args.send_patch:
            raise GitRvException('The flags --no_mail and --send_patch are '
                                 'mutually exclusive.')
        # This is to determine whether or not --send_mail should be added to
        # the upload.py call. If --send_patch is set, we don't need to
        # send mail. Similarly if --no_mail is set, we should not send mail.
        no_send_mail = args.no_mail or args.send_patch

        current_message = args.message
        if current_message is not None:
            if len(current_message) != 1:
                raise GitRvException('Message parsing failed unexpectedly.')
            current_message = current_message[0]
        return cls(current_branch, args, current_message=current_message,
                   no_send_mail=no_send_mail, argv=argv)

    def assess_review(self):
        """Checks if the branch is in a review or starting a new one.

        If not in a review, sets state to UPLOADING_ISSUE, else to
        UPDATING_ISSUE.

        Updates the state based on whether a review is in progress or just
        beginning and advances the state machine.
        """
        if utils.in_review(rietveld_info=self.__rietveld_info):
            self.state = self.UPDATING_ISSUE
        else:
            self.state = self.UPLOADING_ISSUE
        self.advance()

    def __upload_dot_py(self, issue=None):
        """Calls upload.py with current command line args and branch metadata.

        Args:
            issue: Integer; containing an ID of a code review issue. Defaults to
                None and is ignored in that case.

        Returns:
            The string output of the call to upload.py.

        Raises:
            GitRvException: If the first command line argument isn't
                utils.EXPORT.
        """
        if self.__argv[0] != utils.EXPORT:
            raise GitRvException('upload.py called by method other than '
                                 'git-rv export.')

        # Create copy of argv to update, drop the command being executed
        command_args = self.__argv[1:]

        # TODO(dhermes): Catch failure if this lookup breaks.
        remote_commit_hash = self.__rietveld_info.remote_info.last_synced
        command_args.append(utils.REVISION_TEMPLATE % (remote_commit_hash,))

        # VCS is always git
        command_args.append(utils.VCS_ARG)

        # Auth method is always OAuth 2.0 and never use cookies
        command_args.extend(utils.OAUTH2_ARGS)

        # Send mail unless explicitly told not to
        if not self.__no_send_mail:
            command_args.append(utils.SEND_MAIL_ARG)

        # Add any issue
        if issue is not None:
            command_args.append(utils.ISSUE_ARG_TEMPLATE % (issue,))

        # Add the message if it wasn't overridden
        if not self.__message_overridden:
            command_args.extend(['-m', self.__current_message])

        # Make sure to execute upload.py
        command_args.insert(0, 'upload.py')

        # RealMain returns (issue, patchset)
        return long(RealMain(command_args)[0])

    def upload_issue(self):
        """Uploads a new issue.

        If successful, sets state to UPDATING_METADATA.
        """
        issue = self.__upload_dot_py()
        self.state = self.UPDATING_METADATA
        self.advance(issue=issue, initial_message=self.__current_message)

    def update_issue(self):
        """Updates an existing issue.

        If successful, sets state to UPDATING_METADATA.
        """
        do_upload = True
        if self.__rietveld_info.review_info.last_commit == self.__current_head:
            print 'You have made no commits since your last export.'
            print 'Exporting now will upload an empty patch, but may'
            print 'update your metadata.'
            answer = raw_input('Would like to upload to Rietveldd?(y/N) ')
            do_upload = (answer.strip() == 'y')

        # TODO(dhermes): Use different mechanism than upload if there are
        #                no changes.
        if do_upload:
            self.__upload_dot_py(issue=self.__rietveld_info.review_info.issue)
        self.state = self.UPDATING_METADATA
        self.advance()

    def update_metadata(self, issue=None, initial_message=None):
        """Updates the Rietveld metadata associated with the current branch.

        If successful, sets state to FINISHED and advances the state machine.

        Args:
            issue: Integer; containing an ID of a code review issue.
            initial_message: String; the commit message used when creating a new
                issue via upload.py.
        """
        review_info = utils.ReviewInfo(last_commit=self.__current_head)
        # TODO(dhermes): Throw exception if one of these is None while the
        #                the other isn't?
        if issue is not None and initial_message is not None:
            review_info.issue = issue
            review_info.description = initial_message
        self.__rietveld_info.review_info = review_info
        self.__rietveld_info.save()

        success, _ = utils.update_rietveld_metadata_from_issue(
                rietveld_info=self.__rietveld_info)
        if success:
            print 'Metadata update from code server succeeded.'
        else:
            print 'Metadata update from code server failed.'
            print 'To try again run:'
            print '\tgit rv getinfo --pull-metadata'

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
            self.assess_review(*args, **kwargs)
        elif self.state == self.UPLOADING_ISSUE:
            self.upload_issue(*args, **kwargs)
        elif self.state == self.UPDATING_ISSUE:
            self.update_issue(*args, **kwargs)
        elif self.state == self.UPDATING_METADATA:
            self.update_metadata(*args, **kwargs)
        elif self.state == self.FINISHED:
            return
        else:
            raise GitRvException('Unexpected state %r in ExportAction.' %
                                 (self.state,))
