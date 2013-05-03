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

import contextlib
import httplib
import os
import subprocess
import sys
import tempfile
import zipfile


SERVER = 'rietveld.googlecode.com'
UPLOAD_PY = '/hg/upload.py'
UPLOAD_FAIL = 'Retrieving upload.py failed with status %d.'
# TODO(dhermes): Do this in pure Python.
ADD_SHEBANG = 'echo \'#!/usr/bin/env python\' | cat - git-rv > %s'
COMPILE_ARGS = ['python', '-O', '-m', 'compileall']
MODULES = ['__main__', 'export', 'getinfo', 'git_rv', 'mv_branch', 'rm_branch',
           'submit', 'sync', 'upload', 'utils']


def get_upload_py():
    # Too bad https://code.google.com/p/rietveld/ is a mercurial project
    # and we can't just include as a git submodule
    with contextlib.closing(httplib.HTTPConnection(SERVER)) as connection:
      connection.request('GET', UPLOAD_PY)

      print 'Retrieving upload.py from %s.' % (UPLOAD_PY,)
      response = connection.getresponse()
      if response.status != 200:
          print UPLOAD_FAIL % (response.status,)
          sys.exit(1)

      payload = response.read()

    return payload


def create_zipfile():
    # Get freshest copy of upload.py from Rietveld
    upload_contents = get_upload_py()
    with open('upload.py', 'w') as fh:
        print 'Updating local upload.py contents.'
        fh.write(upload_contents)

    # Make Zip
    with zipfile.ZipFile('git-rv', 'w') as git_rv_zip:
        for module in MODULES:
            # Compile the module
            compile_args = COMPILE_ARGS + ['%s.py' % (module,)]
            subprocess.call(compile_args)
            print 'Compiling %(mod)s.py to %(mod)s.pyo.' % {'mod': module}
            print 'Writing %s.pyo to git-rv executable.' % (module,)
            git_rv_zip.write('%s.pyo' % (module,))

            # Delete the compiled .pyo file
            print 'Deleting %s.pyo.' % (module,)
            os.remove('%s.pyo' % (module,))

    tmp = tempfile.mktemp()
    os.system(ADD_SHEBANG % (tmp,))
    os.system('mv %s git-rv' % (tmp,))

    # Read and Executable for all users
    os.chmod('git-rv', 0755)


if __name__ == '__main__':
    create_zipfile()
