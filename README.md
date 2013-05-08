git-rv
======

`git-rv` is a command line tool for syncing local git clients with code
reviews hosted on a [Rietveld][rietveld] code review server such as
[codereview.appspot.com][codereview].

## Installation

To install `git-rv`, first clone this repository:

    $ git clone https://github.com/GoogleCloudPlatform/git-rv.git

and then either copy the `git-rv` binary into a directory on your `$PATH`,
create a symlink, or add the `git-rv` directory to your `$PATH`:

    $ cp git-rv/git-rv /some/directory/on/your/path
    $ # OR
    $ ln -s git-rv/git-rv /some/directory/on/your/path/git-rv
    $ # OR
    $ PATH=${PATH}:/absolute/path/to/git-rv-directory

**NOTE:** No matter your choice, it is possible it will require `sudo` to copy
or create a symlink for directories on your path.

Once you've installed, executing `git rv {$COMMAND}` from within a `git`
repository will call `git-rv`.

## Basic Workflow

`git-rv` supports many commands (run `git-rv --help`) so see them all, but
the main ones needed for code reviews are `export`, `submit` and `sync`.
For editing and committing your code, creating branches and doing work
locally, you can use `git` as you usually would. It is only when interacting
with your code review that you'll need to use `git-rv`.

A typical review may look like the following:

1.  **Start a feature branch:**

        $ git branch
        * master
        $ git checkout -b {$BRANCH}
        $ git branch
        * {$BRANCH}
          master

1.  **Make an initial commit:**

        $ emacs ... # Do some work
        $ git add .
        $ git commit -m "Adding super cool feature X."
        ...
        $ git rv export -r reviewer@email.com
        Upload server: codereview.appspot.com (change with -s/--server)
        Loaded authentication cookies from {$HOME}/.codereview_upload_cookies
        Issue created. URL: http://codereview.appspot.com/{$ISSUE}
        Uploading base file for {$FILENAME1}
        Uploading base file for {$FILENAME2}
        ...
        Metadata update from code server succeeded.

1.  **Address comments from your code review:**

        $ emacs ... # Do some more work
        $ git add .
        $ git commit -m "Fixing the blerg typo per reviewer request."
        ...
        $ git rv export
        Upload server: codereview.appspot.com (change with -s/--server)
        Loaded authentication cookies from {$HOME}/.codereview_upload_cookies
        Issue updated. URL: http://codereview.appspot.com/{$ISSUE}
        Metadata update from code server succeeded.

1.  **Find out someone else committed to master, sync their changes in:**

        $ git rv sync
        ...
        Auto-merging {$FILENAME1}
        Auto-merging {$FILENAME2}
        ...
        Squash commit -- not updating HEAD
        [{$BRANCH} {$SYNC_COMMIT}] Syncing review {$BRANCH} at {$SYNC_COMMIT}
        2 files changed, ...
        ...
        Exporting synced changes.
        Upload server: codereview.appspot.com (change with -s/--server)
        Loaded authentication cookies from {$HOME}/.codereview_upload_cookies
        Issue updated. URL: http://codereview.appspot.com/{$ISSUE}
        Uploading base file for {$FILENAME1}
        Uploading base file for {$FILENAME2}
        ...
        Metadata update from code server succeeded.

    **NOTE:** This assumes the merge initiated by the `sync` was all peachy. If
    not, `git-rv` will do it's best to make sure you resolve the merge
    conflicts and get the review back on track.

1.  **Time to submit:**

    Trying to submit before one of your reviewers gives an LGTM (short
    for "looks good to me") will result in a failure:

        $ git rv submit
        This review has not been approved.

    Once the review has been LGTM'ed by one of your reviewers, you can submit
    your changes:

        $ git rv submit
        Checking out origin/review-{$ISSUE} at {$SYNC_COMMIT}
        Adding reviewed commits.

        Adding commit:
        Adding super cool feature X.

        Reviewed in https://codereview.appspot.com/{$ISSUE}

        Replacing review branch '{$BRANCH}' with newly committed content.

        Loaded authentication cookies from {$HOME}/.codereview_upload_cookies

        Message:

        Added in
        https://code.google.com/p/dhermes-projects/source/detail?r=7fb62f85b1209fb62d8181097bfb2529cc2fc875

        posted to code review issue.

        Issue {$ISSUE} has been closed.

## Power Users and Committers

For more details on the other commands, simply execute `git-rv --help` or
`git rv {$COMMAND} --help`.

Feel free to file new issues and feature request, comment on existing ones
and fork this repository to your heart's content.

If you are working on changes to `git-rv`, you will need to be able to run
`make_executable.py` to create a new `git-rv` binary based on your working
copy of the repository.

In order to do this you'll need to initialize the Rietveld `git` submodule.
Since Rietveld is a [Mercurial][mercurial] project, we use
[`git-remote-hg`][git-remote-hg] to include it as a `git` submodule. To
pull it, run

    $ # If you don't have git-remote-hg installed
    $ sudo pip install --upgrade git-remote-hg
    $ git submodule update --init

[rietveld]: https://code.google.com/p/rietveld/
[codereview]: https://codereview.appspot.com
[mercurial]: http://mercurial.selenic.com/
[git-remote-hg]: https://github.com/rfk/git-remote-hg
