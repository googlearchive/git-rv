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

"""Command git and other utilities for git-rv command line tool.

The tool is distributed as an executable Python zip, so each action
is defined in it's own module, hence this is used to aid by providing
generic, re-usable methods.
"""

# TODO(dhermes): Consider a constants.py since there are so many.
# TODO(dhermes): Move utility functions to the module that uses them if only
#                used in one git-rv method.


from __future__ import with_statement

import base64
import contextlib
import httplib
try:
    import json
except ImportError:
    import simplejson as json
import os
import re
import subprocess
import urllib


# Command names
EXPORT = 'export'
GETINFO = 'getinfo'
MV_BRANCH = 'mv-branch'
RM_BRANCH = 'rm-branch'
SUBMIT = 'submit'
SYNC = 'sync'

# Constants uses in upload.py
CODE_REVIEW = 'codereview.appspot.com'
OAUTH2_ARGS = ('--oauth2', '--no_cookies')
REVISION_TEMPLATE = '--rev=%s'
SEND_MAIL_ARG = '--send_mail'
VCS_ARG = '--vcs=git'

# Metadata Keys and Constants
BRANCH = 'branch'
CC = 'cc'
COMMIT_HASH = 'commit_hash'
HOST = 'host'
ISSUE = 'issue'
ISSUE_DESCRIPTION = 'description'
LAST_COMMIT = 'last_commit'
LAST_SYNCED = 'last_synced'
PRIVATE = 'private'
REMOTE = 'remote'
REMOTE_INFO = 'remote_info'
REVIEW_INFO = 'review_info'
RIETVELD_KEY = 'rietveld-branches'
RIETVELD_KEY_TEMPLATE = RIETVELD_KEY + '.%s'
RIETVELD_KEY_REGEX = '^%s\\.' % (RIETVELD_KEY,)
REASON = 'reason'
REVIEWERS = 'reviewers'
SERVER = 'server'
STATUS = 'status'
SUBJECT = 'subject'
SYNC_HALTED = 'sync_halted'

# Issue Constants
CLOSE_ISSUE_TEMPLATE = '/%(issue)d/close'
ISSUE_ARG_TEMPLATE = '--issue=%d'
ISSUE_URI_PATH_TEMPLATE = '/api/%(issue)d?messages=true'
# TODO(dhermes): Move error messages up as templates.
ISSUE_INFO_ERROR_TEMPLATE = ('Issue %(issue)d requested from %(server)r '
                             'returned $(status)d %(reason)s.')
MESSAGE = 'message'
PUBLISH_ISSUE_MESSAGE_TEMPLATE = '/%(issue)d/publish'
PUBLISH_ISSUE_BASE = {
    'message_only': 'true',
    'no_redirect': 'true',
    'send_mail': 'on',
}

# Miscellaneous constants.
APPROVAL = 'approval'
BAD_REMOTE_ERROR_TEMPLATE = (
        'The HEAD commit in the remote %(remote)s/%(remote_branch)s is '
        '%(commit_hash)r, but this commit is not in the commit history for '
        'the current branch %(branch)r.')
BRANCH_REF_TEMPLATE = 'refs/heads/%s'
COMMIT_HASH_REGEX = re.compile('^[0-9a-f]{40}$')
DESCRIPTION_NEWLINE = 'description_newline'
FAILED_CLOSE_TEMPLATE = ('Closing issue %(issue)d failed.\nTo close the issue '
                         'manually, visit https://%(server)s/%(issue)d/ and '
                         'click the X in the top left corner.')
FAILED_PUBLISH_TEMPLATE = ('Adding link to commit for issue %(issue)d failed.\n'
                           'To add it manually, visit '
                           'https://%(server)s/%(issue)d/publish and add this '
                           'message:\n\n%(message)s')
GOOGLE_CODEHOSTING_BAD_URI_TEMPLATE = ('Project names in URIs can contain at '
                                       'most one \'.\'. Found: %s.')
GOOGLE_CODEHOSTING_HG_BAD_REMOTE_TEMPLATE = (
        'git-remote-hg repository URI not formed correctly. Expected to start '
        'with hg::. Found: %s.')
GOOGLE_CODEHOSTING_HG_NO_MAPPING_TEMPLATE = ('git commit hash %s not in commit '
                                             'mapping.')
INVALID_BRANCH_CHOICE = 'Branch choice %r is invalid.'
INVALID_MESSAGE_CHOICE = 'Message choice %r is invalid.'
INVALID_REMOTE_CHOICE = 'Remote choice %r is invalid.'
LS_REMOTE_ERROR_TEMPLATE = ('Unexpected output from "git ls-remote" '
                            'encountered:\n%s')
MESSAGES = 'messages'
MESSAGE_CHOICE_PROMPT = 'Message: '
MESSAGE_PROMPT_IN_REVIEW = ('You have made more than one commit since the last '
                            'export in this review.\nPlease choose one of the '
                            'following as your commit message:')
MESSAGE_PROMPT_PRE_REVIEW_TEMPLATE = (
    'You have made more than one commit since HEAD in %s.\n'
    'Please choose one of the following as your commit message:')
MISMATCHED_COMMIT_SUBJECT_TEMPLATE = """\
Commit message:
%r
does not begin with the subject:
%r."""
NO_BRANCHES_ERROR_TEMPLATE = 'No branches found found for remote %r.'
NO_COMMIT_TEMPLATE = ('No commits have been made since %s, can\'t '
                      'get commit message.')
NO_REMOTES_ERROR = 'No remotes found in the current repository.'
REMOTE_BRANCH = 'remote_branch'
REMOTE_URL_KEY_TEMPLATE = 'remote.%s.url'
REMOTE_PROMPT = ('You have more than one remote associated with this '
                 'repository.\nPlease choose one of the following:')
REMOTE_CHOICE_PROMPT = 'Remote: '
REMOTE_BRANCH_PROMPT = ('You have more than one branch associated with this '
                        'remote.\nPlease choose one of the following:')
REMOTE_BRANCH_CHOICE_PROMPT = 'Branch: '
SQUASH_COMMIT_TEMPLATE = ('%(subject)s\n\n%(description)s'
                          '%(description_newline)sReviewed in '
                          'https://%(server)s/%(issue)d/')
SUBJECT_TOO_LONG_TEMPLATE = 'Commit subject %r exceeds 100 characters.'
TIP_BEHIND_HINT = ('Updates were rejected because the tip of your current '
                   'branch is behind.')
XSRF_TOKEN = 'xsrf_token'
XSRF_HEADERS = {'X-Requesting-XSRF-Token': 'true'}


class GitRvException(Exception):
    """Base exception for git-rv."""


def _check_hash(value):
    """Checks that a hash value is the expected format.

    Args:
        value: String; a git commit hash.

    Raises:
        GitRvException: if the value does is not 40 hex chars.
    """
    if COMMIT_HASH_REGEX.match(value) is None:
        raise GitRvException('Hash %r is not a valid commit hash.' % (value,))


def _check_single_line(value):
    """Makes sure the value is a one-line output from the command line.

    Args:
        value: String; command line output.

    Raises:
        GitRvException: If the value is not a single line ending with a newline
            character.
    """
    if not value.endswith('\n') or value.count('\n') != 1:
        raise GitRvException('Subject %r is incorrectly formatted.' % (value,))


# TODO(dhermes): Consider making single_line default to False instead.
def capture_command(*args, **kwargs):
    """Captures the system status, stdout and stderr of a command.

    The arguments are typically passed to subprocess.Popen or subprocess.call.

    Args:
        *args: A list of strings; allowing for as many positional arguments as
            can be supplied.
        **kwargs: Keyword arguments passed in. Only the following will be used:
            expect_success: Boolean; defaults to True. Used to determine if the
                captured command should succeed.
            single_line: Boolean; defaults to True. Used to determine if the
                output should be checked if it is a single output line.

    Returns:
        If we expect success, the standard output. Otherwise, a triple
            containing the status code returned, the standard output and the
            standard error.

    Raises:
        GitRvException: If the command does not exit with status code 0 and
            expect success is True.
    """
    proc = subprocess.Popen(args, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    result = proc.wait()
    stdout = proc.stdout.read()
    stderr = proc.stderr.read()

    # TODO(dhermes): Should this be a constant?
    if not kwargs.get('expect_success', True):
        return (result, stdout, stderr)

    if result != 0:
        command = ' '.join(args)
        raise GitRvException('Command %r failed with:\n%s' % (command, stderr))

    # TODO(dhermes): Should this be a constant?
    if kwargs.get('single_line', True):
        _check_single_line(stdout)
    return stdout.rstrip()


def get_current_branch():
    """Retrieves the current active branch.

    Returns:
        String containing the current branch name, if in a branch.
    """
    return capture_command('git', 'rev-parse', '--abbrev-ref', 'HEAD')


def get_git_root():
    """Retrieves the current root of the git repository.

    Returns:
        String containing the current git root, if in a repository.
    """
    return capture_command('git', 'rev-parse', '--show-toplevel')


def get_head_commit(current_branch=None):
    """Gets the commit hash of HEAD in the given branch.

    Args:
        current_branch: String; containing the name of a branch. Defaults to
            None and in this case is replaced by a call to get_current_branch.

    Returns:
        40 hexadecimal characters containing the commit hash of HEAD in the
            given branch.
    """
    current_branch = current_branch or get_current_branch()
    result = capture_command('git', 'rev-parse', current_branch)
    _check_hash(result)
    return result


def get_current_issue(current_branch=None):
    """Get the issue associated with the current branch.

    Args:
        current_branch: String; containing the name of a branch. Defaults to
            None and in this case is replaced by a call to get_current_branch.

    Returns:
        Integer; the current issue.

    Raises:
        GitRvException: If there is no issue set in the current branch.
    """
    current_branch = current_branch or get_current_branch()

    rietveld_info = RietveldInfo.from_branch(branch_name=current_branch)
    if (rietveld_info.review_info is None or
        rietveld_info.review_info.issue is None):
        raise GitRvException('No issue set in branch %r.' % (current_branch,))

    return rietveld_info.review_info.issue


def get_commit_subject(commit_hash):
    """Gets the one-line subject of the commit.

    Args:
        commit_hash: String; the hash of the commit which has the subject we
            wish to retrieve.

    Returns:
        String containing the subject (first line) of the commit.
    """
    return capture_command('git', 'log', '-s', '-1',
                           '--pretty=%s', '-U', commit_hash)


def get_commit_message(commit_hash):
    """Gets full commit message.

    Args:
        commit_hash: String; the hash of the commit which has the subject we
            wish to retrieve.

    Returns:
        String containing the full commit message.
    """
    return capture_command('git', 'log', '-s', '-1', '--pretty=format:%B',
                           '-U', commit_hash, single_line=False)


def get_commit_message_parts(commit_hash=None, current_branch=None):
    """Gets commit message, split into subject and remaining description.

    Args:
        commit_hash: String; the hash of the commit which has the subject we
            wish to retrieve. Defaults to None.
        current_branch: String; containing the name of a branch. Defaults to
            None and in this case is replaced by a call to get_current_branch.

    Returns:
        Tuple of string containing the commit subject and remaining description
            as strings.

    Raises:
        GitRvException: If the commit subject has more than 100 characters.
        GitRvException: If the commit message does not begin with the commit
            subject.
    """
    commit_hash = commit_hash or get_head_commit(current_branch=current_branch)

    commit_subject = get_commit_subject(commit_hash)
    if len(commit_subject) > 100:
        raise GitRvException(SUBJECT_TOO_LONG_TEMPLATE % (commit_subject,))

    commit_message = get_commit_message(commit_hash)
    # This can occur if there is no newline between the subject and the
    # description. For example, if the commit is
    # """This commit does X.
    # It also does Y.
    #
    # Particularly it relates to Z."""
    # Then the subject would be
    # "This commit does X. It also does Y."
    # instead of the expected
    # "This commit does X."
    # and it would fail this test since the commit message starts with
    # "This commit does X.\nIt also does Y."
    if not commit_message.startswith(commit_subject):
        raise GitRvException(MISMATCHED_COMMIT_SUBJECT_TEMPLATE %
                             (commit_message, commit_subject))

    commit_description = commit_message.split(commit_subject, 1)[1].lstrip()
    return commit_subject, commit_description


def user_choice_from_list(choices, pre_prompt_message, input_message,
                          error_message_none, error_message_invalid):
    """Prompts a user for a choice from a list.

    If there is only one choice, does not prompt the user.

    Args:
        choices: List of strings the user can choose from.
        pre_prompt_message: String; a message to print before prompting.
        input_message: String; message to print in raw_input prompt.
        error_message_none: String; the error message to use when there are no
            choices.
        error_message_invalid: String; the error message to use when the user
            choice is invalid.

    Returns:
        Value chosen by the user. This can occur either if the user types the
            value or the index of the value in the list.

    Raises:
        GitRvException: If there are no choices.
        GitRvException: If the choice entered by the user is not valid.
    """
    if len(choices) == 0:
        raise GitRvException(error_message_none)
    elif len(choices) == 1:
        return choices[0]
    else:
        print pre_prompt_message
        options = '\n'.join(['%d: %s' % pair for pair in enumerate(choices)])
        print options
        # Accept index of choice or string value
        choice = raw_input(input_message).strip()
        if choice in choices:
          return choice
        else:
            try:
                index = int(choice)
                return choices[index]
            except (ValueError, TypeError, IndexError):
                raise GitRvException(error_message_invalid % (choice,))


def get_commits(base_commit, head_commit):
    """Gets list of commit hashes between base commit and head commit.

    Args:
        base_commit: String containing hash of the most recently used commit in
            a review.
        head_commit: String containing hash of the HEAD commit in the current
            review.

    Returns:
        List of commit hashes as strings.
    """
    rev_list_arg = '%s..%s' % (base_commit, head_commit)
    rev_list_output = capture_command(
            'git', 'rev-list', rev_list_arg, single_line=False)
    commits = rev_list_output.split('\n') if rev_list_output else []
    [_check_hash(commit_hash) for commit_hash in commits]
    return commits


def get_user_commit_message_parts(base_commit, head_commit, remote_branch=None):
    """Allows a user to choose a commit message for a patch set.

    If there have been no commits between base_commit and head_commit, then
    returns None. If there have been exactly one, returns that commit message,
    otherwise let's the user choose.

    Args:
        base_commit: String containing hash of the most recently used commit in
            a review.
        head_commit: String containing hash of the HEAD commit in the current
            review.
        remote_branch: String {remote}/{branch} where remote is the name of the
            remote and branch the name of a branch in that remote that this
            review is compared against. Defaults to None.

    Returns:
        Tuple of string containing the commit subject and remaining description
            as strings. This pair will have been chosen by the user.

    Raises:
        GitRvException: If there have been no commits since the last review.
    """
    commits = get_commits(base_commit, head_commit)
    if len(commits) == 0:
        raise GitRvException(NO_COMMIT_TEMPLATE % (base_commit,))

    commit_choices = {}
    for commit_hash in commits:
        commit_message_parts = get_commit_message_parts(commit_hash=commit_hash)
        single_value = '\n\n'.join(commit_message_parts)
        # Uniqueness is not an issue, since we only care about values.
        commit_choices[single_value] = commit_message_parts

    error_message_none = 'This error should never occur.'
    if remote_branch is None:
        pre_prompt_message = MESSAGE_PROMPT_IN_REVIEW
    else:
        pre_prompt_message = MESSAGE_PROMPT_PRE_REVIEW_TEMPLATE % remote_branch

    commit_choice = user_choice_from_list(
            commit_choices.keys(), pre_prompt_message, MESSAGE_CHOICE_PROMPT,
            error_message_none, INVALID_MESSAGE_CHOICE)
    return commit_choices[commit_choice]


def get_remote():
    """Gets the remote for a review.

    If there are multiple, prompts the user to choose.

    Returns:
        String containing the remote.
    """
    remote_output = capture_command('git', 'remote', single_line=False)
    remotes = remote_output.split('\n')
    return user_choice_from_list(remotes, REMOTE_PROMPT, REMOTE_CHOICE_PROMPT,
                                 NO_REMOTES_ERROR, INVALID_REMOTE_CHOICE)


def get_remote_branches_list(remote):
    """Gets a list of branches and hashes for a given remote.

    Args:
        remote: String containing the specific remote.

    Returns:
        Dictionary with each key as a branch name and the value for the key
            the hash (as a string) of HEAD in that branch.

    Raises:
        GitRvException: If the output of ls-remote is unexpected, such as a
            commit hash value that is 40 hex characters, a row that isn't two
            tab delimited fields, or a head that doesn't start with refs/heads/.
    """
    branches_output = capture_command('git', 'ls-remote', '--heads',
                                      remote, single_line=False)

    split_branches = [line.split('\t') for line in branches_output.split('\n')]

    branches = {}
    for split in split_branches:
        if len(split) != 2:
            bad_content = '\n'.join([
                repr('\t'.join(split)),
                '',
                'Expected two tab-delimited fields.',
            ])
            error_msg = LS_REMOTE_ERROR_TEMPLATE % (bad_content,)
            raise GitRvException(error_msg)

        commit_hash, head_ref = split
        try:
            _check_hash(commit_hash)
        except GitRvException, exc:  # Syntax for python<2.6
            bad_content = exc.message
            error_msg = LS_REMOTE_ERROR_TEMPLATE % (bad_content,)
            raise GitRvException(error_msg)

        if not head_ref.startswith('refs/heads/'):
            bad_content = ('Head reference %r does not begin with '
                           'refs/heads.' % (head_ref,))
            error_msg = LS_REMOTE_ERROR_TEMPLATE % (bad_content,)
            raise GitRvException(error_msg)

        branch = head_ref.split('refs/heads/', 1)[1]
        branches[branch] = commit_hash

    return branches


def get_remote_branch(remote):
    """Gets the remote for a review.

    If there are multiple, prompts the user to choose.

    Args:
        remote: String containing the specific remote.

    Returns:
        Tuple of string containing the branch name and the commit hash (as a
            string) of HEAD in that branch.
    """
    branches = get_remote_branches_list(remote)
    no_branches_error = NO_BRANCHES_ERROR_TEMPLATE % (remote,)
    remote_branch = user_choice_from_list(
            branches.keys(), REMOTE_BRANCH_PROMPT, REMOTE_BRANCH_CHOICE_PROMPT,
            no_branches_error, INVALID_BRANCH_CHOICE)

    commit_hash = branches[remote_branch]
    return remote_branch, commit_hash


def get_remote_url(remote):
    """Gets the URL for a remote.

    Args:
        remote: String containing the specific remote.

    Returns:
        String containing the URL of remote.
    """
    url_config_key = REMOTE_URL_KEY_TEMPLATE % (remote,)
    return capture_command('git', 'config', url_config_key)


def get_remote_info(current_branch=None):
    """Gets the remote, branch and commit for a review.

    Args:
        current_branch: String; containing the name of a branch. Defaults to
            None and is ignored if not set.

    Returns:
        Dictionary with the remote, remote branch and hash as strings.

    Raises:
        GitRvException: If current_branch isn't None and the commit hash of the
            remote is not in the current branch.
    """
    remote = get_remote()
    remote_branch, commit_hash = get_remote_branch(remote)
    url = get_remote_url(remote)
    if current_branch is not None:
        containing_output = capture_command('git', 'branch', '--contains',
                                            commit_hash, single_line=False)
        branches_containing = [branch[2:]
                               for branch in containing_output.split('\n')]
        if current_branch not in branches_containing:
            error_message = BAD_REMOTE_ERROR_TEMPLATE % {
                REMOTE: remote,
                REMOTE_BRANCH: remote_branch,
                COMMIT_HASH: commit_hash,
                BRANCH: current_branch,
            }
            raise GitRvException(error_message)

    return RemoteInfo(remote=remote, branch=remote_branch,
                      commit_hash=commit_hash, last_synced=commit_hash, url=url)


def branch_exists(branch):
    """Gets the commit hash of HEAD in the given branch.

    Args:
        branch: String; containing the name of a branch.

    Returns:
        Boolean indicating whether or not the branch exists.
    """
    # http://stackoverflow.com/questions/5167957
    ref = BRANCH_REF_TEMPLATE % branch
    status_code, _, _ = capture_command('git', 'show-ref', '--verify',
                                        '--quiet', ref, expect_success=False)
    return status_code == 0


# Rietveld Specific methods and classes
def _string_type_cast(value):
    """Makes sure a value is already a string.

    Args:
        value: String; value to be type-cast.

    Returns:
        The original value, if it's a string.

    Raises:
        GitRvException: If the value is not a string.
    """
    if not isinstance(value, basestring):
        raise GitRvException('Property must be string. Received %r.' % (value,))
    return value


def _int_type_cast(value):
    """Makes sure a value is an integer.

    Args:
        value: String or integer. Value to be type-cast.

    Returns:
        The integer version of the original value.

    Raises:
        GitRvException: If the value can't be cast to an integer.
    """
    try:
        value = int(value)
    except (ValueError, TypeError):
        raise GitRvException('Property must be integer. Received %r.'
                             % (value,))
    return value


def _hash_type_cast(value):
    """Makes sure a value is a valid commit hash.

    Args:
        value: String; value to be type-cast.

    Returns:
       The original value, if it's a commit hash.

    Raises:
        GitRvException: If the value is not a commit hash.
    """
    try:
        _string_type_cast(value)
        _check_hash(value)
    except GitRvException:
        raise GitRvException('Property must be a commit hash. Received %r.'
                             % (value,))
    return value


def simple_update_property(attr_name, can_change=False,
                           type_cast_method=_string_type_cast):
    """Creates a simple @property corresponding to an attribute.

    If can_change is True, also protects updating the value of this attribute.

    Args:
        attr_name: String; the name of a hidden attribute on the object
            corresponding to the @property.
        can_change: Boolean; indicating whether or not this attribute can change
            it's value once set. Defaults to False.
        type_cast_method: Callable which casts the value to a specific type,
            such as integer or string. Defaults to _string_type_cast.

    Returns:
        Instance of the builtin property that maps to the attribute provided by
            attr_name and enforces the rule set by can_change.
    """
    if not attr_name.startswith('_'):
        raise GitRvException('Simple property attributes must begin with an '
                             'underscore. Received %r.' % (attr_name,))
    def getter(self):
        """Simple getter for the current attribute."""
        return getattr(self, attr_name, None)

    def setter(self, value):
        """Setter for the current attribute.

        Args:
            value: Value to be set for the attribute, the type will either be a
                string or something which can be passed to type_cast_method.

        Raises:
            GitRvException: If the can_change is False and the new value differs
                from that which is already set.
        """
        value = type_cast_method(value)
        current_value = getattr(self, attr_name, None)

        if current_value is None or can_change:
            setattr(self, attr_name, value)
        elif current_value != value:
            raise GitRvException('Attribute %r can\'t be changed. Already set '
                                 'to %r.' % (attr_name, current_value))

    return property(getter, setter)


class _MetaBaseRepository(type):
    """Metaclass for base repository.

    Allows arbitrary subtypes to be registered.
    """

    def __init__(cls, name, bases, classdict):
        """Constructor for metaclass.

        Does simple type construction and then registers the current class in
        the repository type registry.
        """
        super(_MetaBaseRepository, cls).__init__(name, bases, classdict)
        cls.REPOSITORY_TYPE_REGISTRY.add(cls)


class RepositoryInfo(object):
    """Base class for specific repository info objects.

    Holds a registry of subclasses that it can use in the from_remote class
    method for doing classification.
    """

    __metaclass__ = _MetaBaseRepository

    REPOSITORY_TYPE_REGISTRY = set()

    def __init__(self, remote_url, match):
        """Constructor for RepositoryInfo.

        Args:
            remote_url: String containing a remote URL for a repository.
            match: A regex match corresponding to the match method for this
                class.
        """
        self._remote_url = remote_url
        self.populate_from_match(match)

    @classmethod
    def from_remote(cls, remote_url):
        """Class method to find the correct repository info class for a remote.

        Args:
            remote_url: String containing a remote URL for a repository.
        """
        for klass in cls.REPOSITORY_TYPE_REGISTRY:
            match = klass.match(remote_url)
            if match is not None:
                return klass(remote_url, match)

    @classmethod
    def match(cls, unused_value):
        """Dummy matcher for base class.

        Args:
            unused_value: Unused value.

        Returns:
            None.
        """
        return


class GoogleCodehostingRepositoryInfo(RepositoryInfo):
    """Repository info class for Google Code Hosting repositories.

    Matches URIs for HTTP or HTTPS protocols and also links ending in .git.
    """

    GOOGLE_CODEHOSTING_REGEX = re.compile('^(http|https)://code.google.com/p/'
                                          '(?P<project>((?!(\.git|/)).)+)'
                                          '(.git)?/?$')
    GOOGLE_CODEHOSTING_COMMIT_LINK_TEMPLATE = ('https://code.google.com/p/%s/'
                                               'source/detail?%s')

    def populate_from_match(self, match):
        """Populate instance data from a match.

        Args:
            match: A regex match corresponding to the match method for
                this class.

        Raises:
            GitRvException: If the match is None.
            GitRvException: If the project named group is not in the match.
        """
        if match is None:
            raise GitRvException('Expected match, received None.')

        try:
            project = match.group('project')
        except IndexError:
            raise GitRvException('Expected group not matched.')

        repository = None
        dot_count = project.count('.')
        if dot_count == 1:
            project, repository = project.split('.')
        elif dot_count > 1:
            raise GitRvException(
                    GOOGLE_CODEHOSTING_BAD_URI_TEMPLATE % (project,))
        self.project = project
        self.repository = repository

    def commit_link(self, commit_hash):
        """Creates a commit link for a commit in the current repository.

        Args:
            commit_hash: String; the hash of the commit we wish to link to.

        Returns:
            URI linking to the commit specific to the current project.
        """
        query_params = {'r': commit_hash}
        if self.repository is not None:
            query_params['repo'] = self.repository
        query_string = urllib.urlencode(query_params)
        return self.GOOGLE_CODEHOSTING_COMMIT_LINK_TEMPLATE % (self.project,
                                                               query_string)

    @classmethod
    def match(cls, value):
        """Matcher to check code hosting regular expressions for links.

        Args:
            value: String containing a value to be matched.

        Returns:
            An _sre.SRE_Match object if any of the regular expressions for
                Google Code Hosting repositories match, otherwise None.
        """
        return cls.GOOGLE_CODEHOSTING_REGEX.match(value)


class GoogleCodehostingHgRepositoryInfo(GoogleCodehostingRepositoryInfo):
    """Repository info class for Google Code Hosting Mercurial repositories.

    Matches URIs for HTTP or HTTPS protocols that begin with hg::, the custom
    "protocol" used for git-remote-hg.
    """

    GOOGLE_CODEHOSTING_REGEX = re.compile('^hg::(http|https)://'
                                          'code.google.com/p/'
                                          '(?P<project>((?!/).)+)'
                                          '/?$')
    def __init__(self, remote_url, match):
        """Constructor for GoogleCodehostingHgRepositoryInfo.

        Overrides the default constructor to get access to the remote URL since
        this is used to look up the git->hg commit mapping.

        Args:
            remote_url: String containing a remote URL for a repository.
            match: A regex match corresponding to the match method for this
                class.
        """
        super(GoogleCodehostingHgRepositoryInfo, self).__init__(
                remote_url, match)
        self.__add_mapfile_path(remote_url)

    def __add_mapfile_path(self, remote_url):
        """Adds mapfile path based on remote_url.

        Makes sure the git-remote-hg remote is formed correctly and sets the
        path based on the current git repository.

        Sets mapfile_path on the current instance if succeeds.

        Args:
            remote_url: String containing a remote URL for a repository.

        Raises:
            GitRvException: if the remote URL doesn't start with hg::.
        """
        if not remote_url.startswith('hg::'):
            raise GitRvException(
                    GOOGLE_CODEHOSTING_HG_BAD_REMOTE_TEMPLATE % (remote_url,))

        actual_uri = remote_url.split('hg::', 1)[1]
        hgremote_directory = urllib.quote_plus(actual_uri)
        project_root = get_git_root()
        self.mapfile_path = os.path.join(
                project_root, '.git', 'hgremotes',
                hgremote_directory, '.hg', 'git-mapfile')

    def __commit_mapping(self):
        """Dictionary mapping git commits to Mercurial commits.

        Returns:
          A dictionary mapping SHA1 git commit strings to SHA1 Mercurial commit
              strings. This mapping is created by git-remote-hg and stored in
              the file at mapfile_path.
        """
        with open(self.mapfile_path, 'rU') as fh:
            content = fh.read().rstrip()
        return dict(row.split(' ', 1) for row in content.split('\n'))

    def commit_link(self, commit_hash):
        """Creates a commit link for a commit in the current repository.

        Converts the local git commit to the corresponding hg commit, which is
        what was actually pushed.

        Args:
            commit_hash: String; the hash of the git commit we wish to link to.

        Returns:
            URI linking to the hg commit specific to the current project.

        Raises:
            GitRvException: If the commit hash is not containing in commit
                mapping.
        """
        commit_mapping = self.__commit_mapping()
        if commit_hash not in commit_mapping:
            msg = GOOGLE_CODEHOSTING_HG_NO_MAPPING_TEMPLATE % (commit_hash,)
            raise GitRvException(msg)
        hg_commit_hash = commit_mapping[commit_hash]

        return super(GoogleCodehostingHgRepositoryInfo, self).commit_link(
                hg_commit_hash)


class GithubRepositoryInfo(RepositoryInfo):
    """Repository info class for Github repositories.

    Matches URIs for SSH, HTTP, HTTPS or Git protocols and also links
    ending in .git.
    """

    # TODO(dhermes): See if there is a way to combine these so that one group
    #                can influence another conditionally.
    GITHUB_PATTERN_SUFFIX = ('(?P<organization>([^/]+))/'
                             '(?P<repository>((?!(\.git|/)).)+)'
                             '(.git)?/?$')
    SIMPLE_PROTOCOL = re.compile('^(http|https|git)://(www|)github.com/' +
                                      GITHUB_PATTERN_SUFFIX)
    SSH = re.compile('^git@github.com:' + GITHUB_PATTERN_SUFFIX)

    GITHUB_COMMIT_LINK_TEMPLATE = 'https://github.com/%s/%s/commit/%s'

    def populate_from_match(self, match):
        """Populate instance data from a match.

        Args:
            match: A regex match corresponding to the match method for
                this class.

        Raises:
            GitRvException: If the match is None.
            GitRvException: If one of the repository or organization named
                groups is not in the match.
        """
        if match is None:
            raise GitRvException('Expected match, received None.')

        try:
            self.repository = match.group('repository')
            self.organization = match.group('organization')
        except IndexError:
            raise GitRvException('Expected group not matched.')

    def commit_link(self, commit_hash):
        """Creates a commit link for a commit in the current repository.

        Args:
            commit_hash: String; the hash of the commit we wish to link to.

        Returns:
            URI linking to the commit specific to the current organization and
                repository.
        """
        return self.GITHUB_COMMIT_LINK_TEMPLATE % (self.organization,
                                                   self.repository, commit_hash)

    @classmethod
    def match(cls, value):
        """Matcher to use one or several regular expressions for links.

        Args:
            value: String containing a value to be matched.

        Returns:
            An _sre.SRE_Match object if any of the regular expressions for
                Github repositories match, otherwise None.
        """
        return cls.SIMPLE_PROTOCOL.match(value) or cls.SSH.match(value)


class _UpdateInfoBase(object):

    def __init__(self, **kwargs):
        """Constuctor for an info base class.

        All arguments must come from _properties.

        Raises:
            GitRvException: If one of the attributes being set is not among
                _properties.
        """
        for key, value in kwargs.iteritems():
            if key not in self._properties:
                raise GitRvException('Property %r not supported for %r object.'
                                     % (key, self.__class__.__name__))
            setattr(self, key, value)

    def to_dict(self):
        """Converts the current object into dictionary for serialization.

        Returns:
            Dictionary containing all properties from _properties that have
                non-null values.
        """
        result = {}
        for prop_name in self._properties:
            value = getattr(self, prop_name, None)
            if value is not None:
                result[prop_name] = value
        return result

    def update(self, other):
        """Updates using another instance of RemoteInfo.

        Raises:
            GitRvException: If the other instance tries to overwrite protected
                properties.
        """
        for prop_name in self._properties:
            other_value = getattr(other, prop_name, None)
            if other_value is not None:
                setattr(self, prop_name, other_value)


class RemoteInfo(_UpdateInfoBase):
    """Simple container class for remote info.

    Will ensure that only last_synced can be changed once set.
    """

    _properties = ('last_synced', 'commit_hash', 'remote', 'branch', 'url')

    # TODO(dhermes): Make some of these required. Since we only care about this
    #                at serialization time, could enforce it in to_dict(). It
    #                makes sense to allow __init__ to allow partial attrs, since
    #                these instances may be created just to pass to update() for
    #                a pre-existing instance.

    last_synced = simple_update_property('_last_synced', can_change=True,
                                         type_cast_method=_hash_type_cast)
    commit_hash = simple_update_property('_commit_hash', can_change=False,
                                         type_cast_method=_hash_type_cast)
    remote = simple_update_property('_remote', can_change=False)
    branch = simple_update_property('_branch', can_change=False)
    url = simple_update_property('_url', can_change=False)

    @property
    def repository_info(self):
        """Property to be used to create commits for the repository."""
        if self.url is not None:
            return RepositoryInfo.from_remote(self.url)

    @property
    def remote_branch_ref(self):
        """Property holding the full reference to the remote branch."""
        return '%s/%s' % (self.remote, self.branch)

    @property
    def head_in_remote_branch(self):
        """The SHA1 hash of the HEAD commit in the remote branch."""
        return get_head_commit(self.remote_branch_ref)


class ReviewInfo(_UpdateInfoBase):
    """Simple container class for review info.

    Will ensure that issue can't be changed once set.
    """

    _properties = ('issue', 'subject', 'description', 'last_commit')

    issue = simple_update_property('_issue', can_change=False,
                                   type_cast_method=_int_type_cast)
    subject = simple_update_property('_subject', can_change=True)
    description = simple_update_property('_description', can_change=True)
    last_commit = simple_update_property('_last_commit', can_change=True,
                                         type_cast_method=_hash_type_cast)


class RietveldInfo(object):
    """Object for holding, reading and saving Rietveld review metadata.

    Defines properties needed to act as gatekeepers, methods for saving the info
    to the local machine, and class methods for creating an instance from the
    local config.
    """
    # TODO(dhermes): Consider protecting the values of host/private.
    server = simple_update_property('_server', can_change=False)

    def __init__(self, branch_name, **kwargs):
        """Constuctor for RietveldInfo.

        Uses key for saving, all other arguments are optional. They will be set
        on the instance via setattr, which will either just add a new property
        or invoke the @property associated with the keyword from kwargs.

        Args:
            branch_name: String; containing the name of a branch.
        """
        self._branch_name = branch_name

        for key, value in kwargs.iteritems():
            setattr(self, key, value)

    @classmethod
    def from_branch(cls, branch_name=None):
        """Class method to create an object from a branch name.

        Uses branch name to create metadata key and retrieve the serialized
        data. Deserializes the data and passes to RietveldInfo constuctor.

        Args:
            branch_name: String; containing the name of a branch. Defaults to
                None and in this case is replaced by a call to
                get_current_branch.

        Returns:
            Instance of RietveldInfo created using the values stored for the key
                using the branch name in the git config. If no value is stored,
                returns None.
        """
        branch_name = branch_name or get_current_branch()
        metadata_key = RIETVELD_KEY_TEMPLATE % (branch_name,)

        proc_result, opaque_info, _ = capture_command(
                'git', 'config', metadata_key, expect_success=False)
        if proc_result != 0:
            return None

        branch_info = json.loads(base64.b64decode(opaque_info))
        return cls(branch_name, **branch_info)

    @property
    def key(self):
        """Simple getter for the Rietveld key for this object.

        There is no equivalent setter and an attempt to set this value will
        throw an exception.
        """
        return RIETVELD_KEY_TEMPLATE % (self._branch_name,)

    @property
    def remote_info(self):
        """Simple getter for remote info."""
        return getattr(self, '_remote_info', None)

    @remote_info.setter
    def remote_info(self, value):
        """Setter for remote info. Defers to the update method on RemoteInfo.

        Args:
            value: A dictionary which will be turned into a RemoteInfo object
                with values to be used on this object, or a RemoteInfo object.

        Raises:
            GitRvException: If the value is not a dictionary.
        """
        if isinstance(value, dict):
            value = RemoteInfo(**value)
        elif not isinstance(value, RemoteInfo):
            raise GitRvException('Remote info must be be constructed from a '
                                 'dictionary or RemoteInfo instance. Received '
                                 '%r for metadata key %r.' % (value, self.key))

        if getattr(self, '_remote_info', None) is None:
            self._remote_info = value
        else:
            self._remote_info.update(value)

    @property
    def review_info(self):
        """Simple getter for review info."""
        return getattr(self, '_review_info', None)

    @review_info.setter
    def review_info(self, value):
        """Setter for review info. Defers to the update method on ReviewInfo.

        Args:
            value: A dictionary which will be turned into a ReviewInfo object
                with values to be used on this object, or a ReviewInfo object.

        Raises:
            GitRvException: If the value is not a dictionary.
        """
        if isinstance(value, dict):
            value = ReviewInfo(**value)
        elif not isinstance(value, ReviewInfo):
            raise GitRvException('Review info must be be constructed from a '
                                 'dictionary or ReviewInfo instance. Received '
                                 '%r for metadata key %r.' % (value, self.key))

        if getattr(self, '_review_info', None) is None:
            self._review_info = value
        else:
            self._review_info.update(value)

    def remove_key(self, key):
        """Removes a specified key from Rietveld info.

        Intentionally doesn't allow removal of properties.

        Args:
            key: String; a key to be removed from the current Rietveld info.
        """
        if key not in self.__dict__:
            return

        del self.__dict__[key]
        self.save()

    @staticmethod
    def remove(branch_name=None):
        """Removes Rietveld metadata for the given branch name.

        Args:
            branch_name: String; containing the name of a branch. Defaults to
                None and in this case is replaced by a call to
                get_current_branch.
        """
        branch_name = branch_name or get_current_branch()
        metadata_key = RIETVELD_KEY_TEMPLATE % (branch_name,)

        capture_command('git', 'config', '--unset',
                        metadata_key, single_line=False)

        proc_result, _, _ = capture_command(
                'git', 'config', '--get-regexp',
                RIETVELD_KEY_REGEX, expect_success=False)

        if proc_result != 0:
            # Remove the section since empty
            capture_command('git', 'config', '--remove-section',
                            RIETVELD_KEY, single_line=False)

    def to_dict(self):
        """Converts the current object to a dictionary for serialization.

        Pulls non-properties from self.__dict__. Otherwise, adds the property
        directly or uses to_dict for nested/complex properties.

        Returns:
            Dictionary representing the current object.
        """
        result = {}

        # Nested {@property}s
        if self.remote_info is not None:
            result[REMOTE_INFO] = self.remote_info.to_dict()
        if self.review_info is not None:
            result[REVIEW_INFO] = self.review_info.to_dict()

        # Simple {@property}s
        if self.server is not None:
            result[SERVER] = self.server

        # Other values.
        for key, value in self.__dict__.iteritems():
            if not key.startswith('_') and value is not None:
                result[key] = value
        return result

    def save(self):
        """Writes serialized form of current object to local config.

        Returns:
            Dictionary containing the serialized form of the current object.
        """
        as_dict = self.to_dict()
        opaque_info = base64.b64encode(json.dumps(as_dict))
        result = capture_command('git', 'config', self.key,
                                 opaque_info, single_line=False)
        if result:
            raise GitRvException('Unexpected output %r from "git config".' %
                                 (result,))
        return as_dict


def in_clean_state():
    """Checks if the current branch is in a clean state.

    Returns:
        A boolean indicating whether or not the branch is in a clean state.
    """
    proc_result, _, _ = capture_command(
            'git', 'diff', '--exit-code', '--quiet', expect_success=False)
    return proc_result == 0


def in_review(current_branch=None, rietveld_info=None):
    """Determine whether a review is in progress in the current branch.

    Args:
        current_branch: String; containing the name of a branch. Defaults to
            None.
        rietveld_info: RietveldInfo object containing metadata associated with
            the current branch.

    Returns:
        Boolean corresponding to whether or not a review is in progress in
            the current branch.
    """
    if rietveld_info is None:
        rietveld_info = RietveldInfo.from_branch(branch_name=current_branch)

    if rietveld_info is None:
        return False

    return rietveld_info.review_info is not None


def get_issue_metadata(issue=None, current_branch=None, server=CODE_REVIEW):
    """Gets metadata JSON for a code review issue.

    Args:
        issue: Integer; containing an ID of a code review issue. Defaults to
            None and in this case is replaced by a call to get_current_issue.
        current_branch: String; containing the name of a branch.
            Defaults to None.
        server: String; the address of the Rietveld server hosting the code
            review. Defaults to CODE_REVIEW.

    Returns:
        Parsed dictionary from JSON payload.

    Raises:
        GitRvException: If the API request for the issue info does not return a
            200 status code.
    """
    issue = issue or get_current_issue(current_branch=current_branch)
    issue_path = ISSUE_URI_PATH_TEMPLATE % {ISSUE: issue}

    # TODO(dhermes): httplib doesn't check certs, should we use a different
    #                library not packaged in stdlib? SSL must be used because
    #                without it the API request returns a 301.
    with contextlib.closing(httplib.HTTPSConnection(server)) as connection:
      connection.request('GET', issue_path)

      response = connection.getresponse()
      if response.status != 200:
          template_values = {ISSUE: issue, SERVER: server,
                             STATUS: response.status,
                             REASON: response.reason}
          raise GitRvException(ISSUE_INFO_ERROR_TEMPLATE % template_values)

      payload = response.read()

    return json.loads(payload)


def is_current_issue_approved(issue=None, current_branch=None,
                              server=CODE_REVIEW):
    """Determines if the current issue has been approved in code review.

    Args:
        issue: Integer; containing an ID of a code review issue. Defaults to
            None and in this case is replaced by a call to get_current_issue.
        current_branch: String; containing the name of a branch.
            Defaults to None.
        server: String; the address of the Rietveld server hosting the code
            review. Defaults to CODE_REVIEW.

    Returns:
        Boolean indicating that any of the messages in the code review for the
            current issue contained LGTM.
    """
    issue_metadata = get_issue_metadata(
            issue=issue, current_branch=current_branch, server=server)
    messages = issue_metadata[MESSAGES]
    # TODO(dhermes): Consider checking for 'disapproval' as well and making sure
    #                that the most recent approval happened before the most
    #                recent disapproval.
    return any(message.get(APPROVAL, False) for message in messages)


def update_rietveld_metadata_from_issue(current_branch=None,
                                        rietveld_info=None):
    """Updates the Rietveld metadata for a branch from the issue metadata.

    Args:
        current_branch: String; containing the name of a branch. Defaults to
            None, in which case Rietveld.from_branch uses get_current_branch.
        rietveld_info: RietveldInfo object containing metadata associated with
            the current branch. Defaults to None and here will be replaced by
            info for current branch.

    Returns:
        A tuple containing a boolean indicating success or failure of the update
            and the RietveldInfo object associated with the current branch.
    """
    rietveld_info = rietveld_info or RietveldInfo.from_branch(
            branch_name=current_branch)
    if rietveld_info is None:
        return (False, None)

    server = rietveld_info.server
    review_info = rietveld_info.review_info
    if server is None or review_info is None:
        return (False, rietveld_info)

    issue = review_info.issue
    issue_metadata = get_issue_metadata(issue=issue, server=server)

    success = False
    if (REVIEWERS in issue_metadata and CC in issue_metadata and
        SUBJECT in issue_metadata):
        rietveld_info.reviewers = issue_metadata[REVIEWERS]
        rietveld_info.cc = issue_metadata[CC]
        review_info.subject = issue_metadata[SUBJECT]
        if ISSUE_DESCRIPTION in issue_metadata:
            if issue_metadata[ISSUE_DESCRIPTION] != review_info.subject:
                review_info.description = issue_metadata[ISSUE_DESCRIPTION]
            else:
                review_info.description = ''
        rietveld_info.save()
        success = True

    return (success, rietveld_info)
