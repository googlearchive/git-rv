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

"""Command line tool for using git with Rietveld.

Allows feature branches to be used and keeps each branch up to date with
a synced review on codereview.appspot.com.
"""


import argparse
from optparse import NO_DEFAULT
import sys

from upload import parser as UPLOAD_PARSER

from export import ExportAction
from getinfo import GetInfoAction
from mv_branch import RenameBranchAction
from rm_branch import DeleteBranchAction
from submit import SubmitAction
from sync import SyncAction
import utils


# optparse->argparse conversion constants
EMAIL_OPTION = '-e'
DISCARDED_UPLOAD_OPTIONS = ['file', 'email', 'help', utils.ISSUE, 'revision',
                            'save_cookies', 'send_mail', 'use_oauth2', 'vcs']
REVIEW_SERVER_IGNORED_OPTIONS = [utils.SERVER, 'email',
                                 'save_cookies', 'use_oauth2']
STRING_TO_TYPE_MAP = {
    'string': str,
    'int': int,
    'long': long,
    'float': float,
    'complex': complex,
    'choice': str,
    None: None,
}
REVIEW_SERVER_OPTIONS = 'Review server options'


# Helper methods for copying some options from the optparse parser from
# upload.py into an argparse parser/subparser
def _get_add_argument_keyword_arguments(option):
    """Converts an optparse into keyword arguments for add_argument in argparse.

    Args:
        option: optparse.Option; An option to be copied onto the target.

    Result:
        A dictionary containing the keyword arguments to be passed to
            add_argument.
    """
    result = {'dest': option.dest}

    if option.choices is not None:
        result['choices'] = option.choices

    if option.metavar is not None:
        result['metavar'] = option.metavar

    if option.action == 'callback':
        raise ValueError('Callback is not a supported action in argparse.')
    result['action'] = option.action

    # const can only be used if nargs is '?'
    nargs = option.nargs
    if option.const is not None:
        if nargs not in (None, '?'):
            raise ValueError('')
        nargs = '?'

        result['const'] = option.const
        if option.action != 'store_const':
            result['nargs'] = nargs

    # argparse has no concept of default None vs. no default provided
    default = option.default
    if default == NO_DEFAULT:
        default = None
    result['default'] = default

    # The string %(prog) could also be used, but is not by upload
    result['help'] = option.help.replace('%default', '%(default)s')

    # optparse uses strings for type while argparse uses the actual types
    try:
        type_arg = STRING_TO_TYPE_MAP[option.type]
    except KeyError:
        print 'Unexpected parser argument type: %s.' % (option.type,)
        sys.exit(1)

    if type_arg is not None:
        result['type'] = type_arg

    return result


def _copy_optparse_option(option, target, ignored_destinations=None):
    """Copies an optparse option to an argparse parser OR subparser.

    Args:
        option: optparse.Option; An option to be copied onto the target.
        target: argparse.ArgumentParser; a parser or subparser which will have
            the option copied to it.
        ignored_destinations: List of strings; list of destinations which can be
            ignored. Defaults to None and won't be used if None.
    """
    if ignored_destinations is not None and option.dest in ignored_destinations:
        return

    positional_arguments = option._short_opts + option._long_opts
    keyword_arguments = _get_add_argument_keyword_arguments(option)
    target.add_argument(*positional_arguments, **keyword_arguments)


def _copy_optparse_option_group(option_group, target,
                                ignored_destinations=None):
    """Copies an optparse option group to an argparse parser OR subparser.

    Args:
        option: optparse.OptionGroup; An option group to be copied onto the
            target.
        target: argparse.ArgumentParser; a parser or subparser which will have
            the option group copied to it.
        ignored_destinations: List of strings; list of destinations which can be
            ignored when adding options. Defaults to None and won't be used
            if None.
    """
    group = target.add_argument_group(option_group.title)
    for option in option_group.option_list:
        _copy_optparse_option(option, group,
                              ignored_destinations=ignored_destinations)


def get_parser():
    """Argument parser for git-rv.

    Registers the commands:
        export: For committing changes locally and sending them off for review.
        submit: For pushing a change to the reposity after completing a review.

    Returns:
        An argparse.ArgumentParser that can parse the passed in arguments.
    """
    parser = argparse.ArgumentParser(
            prog='git-rv', description='git-rv Rietveld interface')
    subparsers = parser.add_subparsers(help='git-rv commands')

    # Export
    parser_export = subparsers.add_parser(utils.EXPORT, help='Export changes.')
    parser_export.set_defaults(callback=ExportAction.callback)

    # Add main options from upload.py
    for option in UPLOAD_PARSER.option_list:
        _copy_optparse_option(option, parser_export,
                              ignored_destinations=DISCARDED_UPLOAD_OPTIONS)

    # Add option subgroups from upload.py
    for option_group in UPLOAD_PARSER.option_groups:
        _copy_optparse_option_group(
                option_group, parser_export,
                ignored_destinations=DISCARDED_UPLOAD_OPTIONS)

    # Add argument(s) unique to export
    parser_export.add_argument('--no_mail', action='store_true', dest='no_mail',
                               help='Don\'t send e-mail for this export.')

    # Get Info
    parser_getinfo = subparsers.add_parser(
            utils.GETINFO, help='Get info about the current review.')
    parser_getinfo.set_defaults(callback=GetInfoAction.callback)

    parser_getinfo.add_argument(
            '-p', '--pull-metadata', action='store_true', dest='pull',
            help='Pull metadata updates from code review server.')

    # Rename Branch
    parser_mv_branch = subparsers.add_parser(
            utils.MV_BRANCH, help='Rename a Rietveld review branch.')
    parser_mv_branch.set_defaults(callback=RenameBranchAction.callback)

    # TODO(dhermes): Write this differently so we have old-name, new-name
    #                as separate arguments which must come in order.
    parser_mv_branch.add_argument(
            'branches', nargs=2,
            help='Current branch name and desired new name.')

    # Delete Branch
    parser_rm_branch = subparsers.add_parser(
            utils.RM_BRANCH, help='Remove a Rietveld review branch.')
    parser_rm_branch.set_defaults(callback=DeleteBranchAction.callback)

    parser_rm_branch.add_argument('branch',
                                  help='Name of branch to delete.')

    # Review server option group for submit and sync
    review_server_option_group = UPLOAD_PARSER.get_option_group(EMAIL_OPTION)
    if review_server_option_group.title != REVIEW_SERVER_OPTIONS:
        raise GitRvException('Unexpected option group for parser. Email option '
                             'contained in %r group, expected to be in %r '
                             'group.' % (review_server_option_group.title,
                                         REVIEW_SERVER_OPTIONS))

    # Submit
    parser_submit = subparsers.add_parser(
            utils.SUBMIT, help='Submit reviewed changes to remote repository.')
    parser_submit.set_defaults(callback=SubmitAction.callback)

    # Add review server option subgroup for closing issues
    _copy_optparse_option_group(
            review_server_option_group, parser_submit,
            ignored_destinations=REVIEW_SERVER_IGNORED_OPTIONS)

    # Add argument(s) unique to submit
    parser_submit.add_argument('--leave_open', action='store_false',
                               dest='do_close',
                               help='Don\'t close the issue when submitting.')

    # TODO(dhermes): Add --no_squash flag and use it correctly.

    # Sync
    sync_help = ('Pull changes from the remote repository '
                 'into the current review.')
    parser_sync = subparsers.add_parser(utils.SYNC, help=sync_help)
    parser_sync.set_defaults(callback=SyncAction.callback)

    # Add review server option subgroup for sync
    _copy_optparse_option_group(
            review_server_option_group, parser_sync,
            ignored_destinations=REVIEW_SERVER_IGNORED_OPTIONS)

    # Add argument(s) unique to sync
    parser_sync.add_argument('--continue', action='store_true',
                             dest='in_continue',
                             help='Continue sync after resolving conflicts.')
    parser_sync.add_argument('--no_mail', action='store_true', dest='no_mail',
                             help='Don\'t send e-mail for this sync.')

    return parser
