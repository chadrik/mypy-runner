mypy-runner
===========

Ease your way into static type checking by focusing on a small set of problems at a time.

It can be quite challenging to get an existing code base to pass mypy's checks, even at its most lenient settings, and unfortunately, until you do you can't use mypy as part of your CI/CD process.

``mypy-runner`` lets you gradually introduce type checking by identifying a subset of files and errors to check:

- choose a set of files and errors to check
- get tests passing and enforce them in your CI and pre-commit hooks
- repeat

Features
--------

``mypy-runner`` adds the following features to ``mypy``:

- Display colorized output
- Convert specific errors to warnings
- Filter specific errors and warnings

Options
-------

::

    usage: mypyrun [-h] [--list] [--daemon] [--select SELECT] [--ignore IGNORE]
                   [--warn WARN] [--no-color] [--show-ignored] [--show-error-keys]
                   [--options OPTIONS]
                   [files [files ...]]

    positional arguments:
      files                 Files to isolate (triggers use of 'active'options for
                            these files)

    optional arguments:
      -h, --help            show this help message and exit
      --list                list error codes
      --daemon, -d          run in daemon mode (dmypy run)
      --select SELECT, -s SELECT
                            Errors to check (comma separated)
      --ignore IGNORE, -i IGNORE
                            Errors to skip (comma separated)
      --warn WARN, -w WARN  Errors to convert into warnings (comma separated)
      --no-color            do not colorize output
      --show-ignored, -x    Show errors that have been ignored (darker if using
                            color)
      --show-error-keys     Show error key for each line
      --options OPTIONS, -o OPTIONS
                            Override the default options to use the
                            namedconfiguration section (e.g. pass --options=foo to
                            use the [mypyrun-foo] section)

As with tools like ``flake8``, you use specific error codes to enable or disable error output.
Errors that are ignored or converted into warnings will not trigger a non-zero exit status.
To see the list of error codes and their regex pattern, run ``mypyrun --list``.

Configuration
-------------

``mypyrun`` looks for a ``[mypyrun]`` section in either ``mypy.ini`` or ``mypyrun.ini``.

Here's an example configuration file:

.. code-block:: ini

    [mypyrun]

    # run dmypy instead of mypy
    daemon = true

    # only display these errors
    select =
        not_defined,
        return_expected,
        return_not_expected,
        incompatible_subclass_attr,

    # all other errors are warnings
    warn = *

    # filter errors generated from these paths:
    exclude =
        thirdparty/*,

    # pass these paths to mypy
    paths =
        arnold/python,
        houdini/python,
        katana/python,
        mari/python,
        maya/python,
        nuke/python,
        python/packages,
