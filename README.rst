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
- Automatically insert missing `typing` imports (see `--add-missing-imports` below)

Compatibility
-------------

``mypy-runner`` supports ``mypy`` 0.730 and higher.

Options
-------

::

    usage: mypyrun [-h] [--version] [--daemon] [--select SELECT [SELECT ...]] [--ignore IGNORE [IGNORE ...]] [--warn WARN [WARN ...]] [--color] [--show-ignored] [--add-missing-imports] [--options OPTIONS] [--config-file CONFIG_FILE]
                      [--files FILES [FILES ...]] [--warning-filters WARNING_FILTERS [WARNING_FILTERS ...]] [--error-filters ERROR_FILTERS [ERROR_FILTERS ...]] [--mypy-executable MYPY_EXECUTABLE]
                      [ARG [ARG ...]]

    positional arguments:
      ARG                   Regular mypy flags and files (precede with --)

    optional arguments:
      -h, --help            show this help message and exit
      --version             show program's version number and exit
      --daemon              Run mypy in daemon mode (inverse: --no-daemon)
      --select SELECT [SELECT ...], -s SELECT [SELECT ...]
                            Errors to check
      --ignore IGNORE [IGNORE ...], -i IGNORE [IGNORE ...]
                            Errors to skip
      --warn WARN [WARN ...], -w WARN [WARN ...]
                            Errors to convert into warnings
      --color               Colorize output (inverse: --no-color)
      --show-ignored, -x    Show errors that have been ignored (darker if using color)
      --add-missing-imports
                            Add missing typing imports. This will detect mypy errors related to missing classes from the typing module and automatically insert them into the file
      --options OPTIONS, -o OPTIONS
                            Override the default options to use the namedconfiguration section (e.g. pass --options=foo to use the [mypyrun-foo] section)
      --config-file CONFIG_FILE, -c CONFIG_FILE
                            Specific configuration file.
      --files FILES [FILES ...]
                            Files to isolate (triggers use of 'active'options for these files)
      --warning-filters WARNING_FILTERS [WARNING_FILTERS ...]
                            Regular expression to ignore messages flagged as warnings
      --error-filters ERROR_FILTERS [ERROR_FILTERS ...]
                            Regular expression to ignore messages flagged as errors
      --mypy-executable MYPY_EXECUTABLE
                            Path to the mypy executable

As with tools like ``flake8``, you use specific error codes to enable or disable error output.
Errors that are ignored or converted into warnings will not trigger a non-zero exit status.

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
