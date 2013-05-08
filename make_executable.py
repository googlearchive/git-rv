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

"""Script to create git-rv binary from required modules."""

import os
import subprocess
import sys
import tempfile
import zipfile


UPLOAD_PY_PATH = ('rietveld', 'upload')
UPLOAD_FAIL = """\
The upload.py file was not in it's expected place.

Please install git-remote-hg, then run

    git submodule update --init

and try again.
"""
# TODO(dhermes): Do this in pure Python.
ADD_SHEBANG = 'echo \'#!/usr/bin/env python\' | cat - git-rv > %s'
COMPILE_ARGS = ['python', '-O', '-m', 'compileall']
MODULE_MAPPING = {
    '__main__': '__main__',
    'export': 'export',
    'getinfo': 'getinfo',
    'git_rv': 'git_rv',
    'mv_branch': 'mv_branch',
    'rm_branch': 'rm_branch',
    'submit': 'submit',
    'sync': 'sync',
    'utils': 'utils',
    UPLOAD_PY_PATH: 'upload',
}


def get_project_root():
    return subprocess.check_output(
        ['git', 'rev-parse', '--show-toplevel']).strip()


def get_full_path(module, project_root=None):
    if isinstance(module, tuple):
        module = os.path.join(*module)
    if project_root is not None:
        module = os.path.join(project_root, module)
    return module + '.py'


def check_upload_py_exists(project_root):
    full_path = get_full_path(UPLOAD_PY_PATH, project_root)
    if not os.path.isfile(full_path):
        print UPLOAD_FAIL
        sys.exit(1)


def create_zipfile():
    project_root = get_project_root()

    # Make Zip
    with zipfile.ZipFile('git-rv', 'w') as git_rv_zip:
        # First make sure the submodule is loaded
        check_upload_py_exists(project_root)

        for source_module, target_module in MODULE_MAPPING.iteritems():
            source_path = get_full_path(source_module, project_root)
            # .pyo instead of .py, also, don't use project_root since
            # will be relative paths in git-rv zipfile
            target_path = get_full_path(target_module) + 'o'

            # Compile the module
            compile_args = COMPILE_ARGS + [source_path]
            subprocess.call(compile_args)
            print 'Writing %s to git-rv executable.' % (target_path,)
            compiled_source_path = source_path + 'o'
            git_rv_zip.write(compiled_source_path, arcname=target_path)

            print 'Deleting %s.' % (compiled_source_path,)
            os.remove(compiled_source_path)

    tmp = tempfile.mktemp()
    os.system(ADD_SHEBANG % (tmp,))
    os.system('mv %s git-rv' % (tmp,))

    # Read and Executable for all users
    os.chmod('git-rv', 0755)


if __name__ == '__main__':
    create_zipfile()
