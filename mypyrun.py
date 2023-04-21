from __future__ import absolute_import, print_function

import argparse
import subprocess
import os
import os.path
import sys
import re
import fnmatch
import json
from collections import defaultdict

try:
    import configparser
except ImportError:
    from backports import configparser  # type: ignore[no-redef]

if False:
    from typing import *
    from typing import Pattern
    multi_options = Union[Sequence[str], str]

__version__ = "0.3.1"

if sys.version_info[0] < 3:
    string_types = (str, unicode)
else:
    string_types = str

# adapted from mypy:
CONFIG_FILE = 'mypyrun.ini'
SHARED_CONFIG_FILES = ('mypy.ini', 'setup.cfg')
USER_CONFIG_FILES = ('~/.mypy.ini',)
CONFIG_FILES = (CONFIG_FILE,) + SHARED_CONFIG_FILES + USER_CONFIG_FILES

ALL = None

# choose an exit that does not conflict with mypy's
PARSING_FAIL = 100
ERROR_CODE = re.compile(r'\[([a-z0-9\-_]+)\]\n$')
IMPORT_SUGGESTION = re.compile(r'from typing import ([a-zA-Z_][a-zA-Z0-9_]*)')
NAMED_DEFINED = re.compile(r'Name "([a-zA-Z_][a-zA-Z0-9_]*)" is not defined')

REVEALED_TYPE = 'Revealed type is'

COLORS = {
    'error': 'red',
    'warning': 'yellow',
    'note': None,
}

GLOBAL_ONLY_OPTIONS = [
    'color',
    'show_ignored',
    'daemon',
    'exclude',
    'mypy_executable',
    'add_missing_imports',
]

TERM_ATTRIBUTES = {
    'bold': 1,
    'dark': 2,
    'underline': 4,
    'blink': 5,
    'reverse': 7,
    'concealed': 8,
}

TERM_COLORS = {
    'grey': 30,
    'red': 31,
    'green': 32,
    'yellow': 33,
    'blue': 34,
    'magenta': 35,
    'cyan': 36,
    'white': 37,
}

TERM_RESET = '\033[0m'

EXTRA_TYPING_TYPES = set(['NamedTuple', 'Pattern', 'Match', 'Literal', 'TypedDict', 'Type'])

try:
    import typing
except ImportError:
    pass
else:
    EXTRA_TYPING_TYPES.update(x for x in typing.__all__ if x[0].isupper())

try:
    import typing_extensions
except ImportError:
    pass
else:
    EXTRA_TYPING_TYPES.update(x for x in typing_extensions.__all__ if x[0].isupper())


def colored(text, color=None, attrs=None):
    esc = '\033[%dm%s'
    if color is not None:
        text = esc % (TERM_COLORS[color], text)

    if attrs is not None:
        for attr in attrs:
            text = esc % (TERM_ATTRIBUTES[attr], text)

    text += TERM_RESET
    return text


def match(regex_list, s):
    # type: (List[Pattern], str) -> bool
    for regex in regex_list:
        if regex.search(s):
            return True
    return False


class Options(object):
    """
    Options common to both the config file and the cli.
    """
    PER_MODULE_OPTIONS = [
        'select',
        'ignore',
        'warn',
        'include',
        'error_filters',
        'warning_filters',
    ]
    # error codes:
    select = None  # type: Optional[Set[str]]
    ignore = None  # type: Optional[Set[str]]
    warn = None  # type: Optional[Set[str]]
    # paths:
    include = None  # type: List[Pattern]
    exclude = None  # type: List[Pattern]
    # messages:
    error_filters = None  # type: List[Pattern]
    warning_filters = None  # type: List[Pattern]

    # global-only options:
    args = None  # type: List[str]
    color = True
    show_ignored = False
    daemon = False
    mypy_executable = ''  # type: Optional[str]
    add_missing_imports = False

    def __init__(self):
        self.select = ALL
        self.ignore = set()
        self.warn = set()
        self.include = []
        self.exclude = []
        self.error_filters = []
        self.warning_filters = []
        self.args = []

    def is_excluded_path(self, path):
        # type: (str) -> bool
        return match(self.exclude, path)

    def is_included_path(self, path):
        # type: (str) -> bool
        return match(self.include, path)

    def get_status(self, error_code, msg):
        # type: (str, str) -> Optional[str]
        """
        Determine whether an error code is an error, warning, or ignored

        Parameters
        ----------
        error_code: str
        msg : str

        Returns
        -------
        Optional[str]
            Returns the new status, or None if it should be filtered
        """
        # We have specified something to check for
        if self.select is not ALL and error_code in self.select:
            return 'error' if not match(self.error_filters, msg) else None

        # We have specified something to ignore (specific selects override this)
        if self.ignore is ALL or error_code in self.ignore:
            return None

        # We have specified something to warn (ignore overrides this)
        if self.warn is ALL or error_code in self.warn:
            return 'warning' if not match(self.warning_filters, msg) else None

        # We're checking everything!
        if self.select is ALL:
            return 'error' if not match(self.error_filters, msg) else None

        return None


def _read_python_source(filename):
    """
    Do our best to decode a Python source file correctly.
    """
    import io
    from lib2to3.pgen2 import tokenize

    try:
        f = open(filename, "rb")
    except OSError as err:
        print("Can't open %s: %s" % (filename, err), file=sys.stderr)
        return None, None
    try:
        encoding = tokenize.detect_encoding(f.readline)[0]
    finally:
        f.close()
    with io.open(filename, "r", encoding=encoding, newline='') as f:
        return f.read(), encoding


def write_file(new_text, filename, encoding=None):
    """Writes a string to a file.
    """
    import io

    try:
        fp = io.open(filename, "w", encoding=encoding, newline='')
    except OSError as err:
        print("Can't create %s: %s" % (filename, err), file=sys.stderr)
        return

    with fp:
        try:
            fp.write(new_text)
        except OSError as err:
            print("Can't write %s: %s" % (filename, err), file=sys.stderr)
    print("Fixed imports for %s" % filename)


def add_typing_imports(filename, imports):
    # type: (str, Iterable[str]) -> bool
    import lib2to3.pgen2.driver
    from lib2to3 import pytree, pygram
    from lib2to3.fixer_util import touch_import

    data, encoding = _read_python_source(filename)
    if data is None:
        # Reading the file failed.
        return False
    data += "\n"  # Silence certain parse errors

    grammar = pygram.python_grammar_no_print_statement
    driver = lib2to3.pgen2.driver.Driver(
        grammar, convert=pytree.convert)
    tree = driver.parse_string(data)
    for name in imports:
        touch_import('typing', name, tree)

    if tree and tree.was_changed:
        # The [:-1] is to take off the \n we added earlier
        write_file(str(tree)[:-1], filename, encoding=encoding)
        return True
    return False


def get_error_code(msg):
    # type: (str) -> str
    """
    Lookup the error constant from a parsed message literal.

    Parameters
    ----------
    msg : str

    Returns
    -------
    str
    """
    m = ERROR_CODE.search(msg)
    if m:
        return m.group(1)
    return 'Unknown'


_cached_options = {}  # type: Dict[str, Options]


def get_options(filename, global_options, module_options):
    # type: (str, Options, List[Tuple[str, Options]]) -> Options
    try:
        return _cached_options[filename]
    except KeyError:
        pass

    for key, options in module_options:
        if options.is_included_path(filename):
            _cached_options[filename] = options
            return options
    _cached_options[filename] = global_options
    return global_options


def report(options, filename, lineno, status, msg,
           is_filtered, error_key=None):
    # type: (Options, str, str, str, str, bool, Optional[str]) -> None
    """
    Report an error to stdout.

    Parameters
    ----------
    options : Options
    filename : str
    lineno : str
    status : str
    msg : str
    is_filtered : bool
    error_key : Optional[str]
    """
    if not options.color:
        msg = '%s: %s' % (status, msg)
        outline = 'IGNORED ' if options.show_ignored and is_filtered else ''
        outline += '%s:%s: %s' % (filename, lineno, msg)

    else:
        display_attrs = ['dark'] if options.show_ignored and is_filtered else None

        filename = colored(filename, 'cyan', attrs=display_attrs)
        lineno = colored(':%s: ' % lineno, attrs=display_attrs)
        color = COLORS[status]
        status = colored(status + ': ', color, attrs=display_attrs)
        msg = colored(msg, color, attrs=display_attrs)
        outline = filename + lineno + status + msg

    print(outline)


def run(active_files, global_options, module_options):
    # type: (Optional[List[str]], Options, List[Tuple[str, Options]]) -> int
    """
    Parameters
    ----------
    active_files : Optional[List[str]]
    global_options : Options
    module_options : List[Tuple[str, Options]]

    Returns
    -------
    int
        exit status
    """
    if global_options.daemon:
        executable = 'dmypy'
        if global_options.mypy_executable:
            basedir = os.path.dirname(global_options.mypy_executable)
            executable = os.path.join(basedir, executable)
        args = ['run', '--']
    else:
        executable = 'mypy'
        args = []

    if global_options.mypy_executable:
        basedir = os.path.dirname(global_options.mypy_executable)
        executable = os.path.join(basedir, executable)

    args.append('--show-error-codes')

    if global_options.args:
        args.extend(global_options.args)

    proc = subprocess.Popen([executable] + args, stdout=subprocess.PIPE)

    active_options = dict(module_options).get('active')
    if active_options and active_files:
        # force the `active` options to be found by `get_options()` for all
        # files passed on the command-line
        # FIXME: reorder module_options so this is first?
        active_options.include = [_glob_to_regex(x) for x in active_files]

    # used to know when to error a note related to an error
    matched_error = None  # type: Optional[Tuple[Optional[str], str]]
    errors_by_type = defaultdict(int)  # type: DefaultDict[str, int]
    errors = defaultdict(int)  # type: DefaultDict[str, int]
    warnings = defaultdict(int)  # type: DefaultDict[str, int]
    filtered = defaultdict(int)  # type: DefaultDict[str, int]
    missing_imports = defaultdict(set)  # type: DefaultDict[str, Set[str]]
    last_error = None  # type: Optional[Tuple[Options, Any, Any, Any, str]]

    output = proc.stdout or []  # type: Iterable[bytes]
    for raw_line in output:
        line = raw_line.decode()

        try:
            filename, lineno, status, msg = line.split(':', 3)
        except ValueError:
            lineno = ''
            try:
                filename, status, msg = line.split(':', 2)
            except ValueError:
                print(line, end='')
                continue

        if global_options.is_excluded_path(filename):
            filtered[filename] += 1
            continue

        options = get_options(filename, global_options, module_options)

        error_code = get_error_code(msg)
        status = status.strip()
        msg = msg.strip()

        last_error = global_options, filename, lineno, msg, error_code

        if status == 'error':
            # print(error_code, repr(msg), options.select)
            new_status = options.get_status(error_code, msg)
            if new_status == 'error':
                errors[filename] += 1
                errors_by_type[error_code] += 1
            elif new_status == 'warning':
                warnings[filename] += 1
            elif new_status is None:
                filtered[filename] += 1

            if global_options.show_ignored or new_status:
                report(global_options, filename, lineno, new_status or 'error',
                       msg, is_filtered=not new_status, error_key=error_code)
                matched_error = new_status, error_code
            else:
                matched_error = None

            if error_code == 'name-defined':
                match = NAMED_DEFINED.search(msg)
                if match:
                    obj = match.group(1)
                    if obj in EXTRA_TYPING_TYPES:
                        missing_imports[filename].add(obj)

        elif status == 'note' and matched_error is not None:
            match = IMPORT_SUGGESTION.search(msg)
            if match:
                missing_imports[filename].add(match.group(1))
            report(global_options, filename, lineno, status, msg,
                   is_filtered=not matched_error[0], error_key=matched_error[1])
        elif status == 'note' and msg.startswith(REVEALED_TYPE):
            report(global_options, filename, lineno, status, msg,
                   is_filtered=False)

    def print_stat(key, value):
        print("{:.<50}{:.>8}".format(key, value))

    error_files = set(errors.keys())
    warning_files = set(warnings.keys())
    filtered_files = set(filtered.keys())

    print()
    print_stat("Errors", sum(errors.values()))
    print_stat("Warnings", sum(warnings.values()))
    print_stat("Filtered", sum(filtered.values()))
    print()
    for (code, count) in sorted(errors_by_type.items(), key=lambda v: v[1],
                                reverse=True):
        print_stat(code, count)
    print()
    print_stat("Files with errors or warnings (excluding filtered)",
               len(error_files | warning_files))
    print_stat("Files with errors or warnings (including filtered)",
               len(error_files | warning_files | filtered_files))

    if active_files:
        clean_files = set(active_files).difference(error_files | warning_files)
        print_stat("Clean files", len(clean_files))
        # for x in sorted(clean_files):
        #     print(x)

    if global_options.add_missing_imports and missing_imports:
        print()
        for filename, imports in missing_imports.items():
            add_typing_imports(filename, imports)

    returncode = proc.wait()
    if returncode > 1:
        # severe error: print everything that wasn't formatted as a standard
        # error
        msg = "Warning: A severe error occurred"
        if global_options.color:
            msg = colored(msg, "red")
        print(msg)
        if last_error:
            global_options, filename, lineno, msg, error_code = last_error
            report(global_options, filename, lineno, 'error', msg, False)
        return returncode
    else:
        return returncode if errors else 0


def main(argv=None):
    # type: (Optional[List[str]]) -> None

    if argv is None:
        argv = sys.argv[1:]

    options = Options()
    module_options = []  # type: List[Tuple[str, Options]]

    parser = get_parser()

    dummy = argparse.Namespace()
    parser.parse_args(argv, dummy)

    parsers = [
        ConfigFileOptionsParser(dummy.config_file),
        JsonEnvVarOptionsParser(),
        ArgparseOptionsParser(parser, argv)
    ]

    for p in parsers:
        p.apply(options, module_options)

    if dummy.options:
        override_options = dict(module_options).get(dummy.options)
        if override_options is None:
            print('Configuration section does not exist: [mypyrun-%s]' %
                  dummy.options)
            sys.exit(PARSING_FAIL)
        for key in Options.PER_MODULE_OPTIONS:
            setattr(options, key, getattr(override_options, key))

    # if options.select:
    #     options.select.add('invalid_syntax')

    if options.select and options.ignore:
        overlap = options.select.intersection(options.ignore)
        if overlap:
            print('The same option must not be both selected and '
                  'ignored: %s' % ', '.join(overlap), file=sys.stderr)
            sys.exit(PARSING_FAIL)

    sys.exit(run(dummy.files, options, module_options))


# Options Handling

def _parse_multi_options(options, split_token=','):
    # type: (multi_options, str) -> List[str]
    r"""
    Split and strip and discard empties.

    Turns the following:

    >>> _parse_multi_options("    A,\n    B,\n")
    ["A", "B"]
    >>> _parse_multi_options(["A   ", "  B  "])
    ["A", "B"]


    Parameters
    ----------
    options : str or sequence
    split_token : str

    Returns
    -------
    List[str]
    """
    if isinstance(options, string_types):
        options = options.split(split_token)
    return [o.strip() for o in options if o.strip()]


def _glob_to_regex(s):
    return re.compile(fnmatch.translate(s))


def _glob_list(s):
    # type: (multi_options) -> List[Pattern]
    return [_glob_to_regex(x) for x in _parse_multi_options(s)]


def _regex_list(s):
    # type: (multi_options) -> List[Pattern]
    return [re.compile(x) for x in _parse_multi_options(s)]


def _error_set(s):
    # type: (multi_options) -> Optional[Set[str]]
    result = set()
    for res in _parse_multi_options(s):
        if res == '*':
            return None
        else:
            result.add(res)
    return result


config_types = {
    'select': _error_set,
    'ignore': _error_set,
    'warn': _error_set,
    'args':  _parse_multi_options,
    'include': _glob_list,
    'exclude': _glob_list,
    'error_filters': _regex_list,
    'warning_filters': _regex_list,
}  # type: Dict[str, Callable[[Any], Any]]


class BaseOptionsParser(object):
    def extract_updates(self, options):
        # type: (Options) -> Iterator[Tuple[Dict[str, object], Optional[str]]]
        raise NotImplementedError

    def apply(self, options, module_options):
        # type: (Options, List[Tuple[str, Options]]) -> None
        for updates, key in self.extract_updates(options):
            if updates:
                if key is None:
                    opt = options
                else:
                    opt = Options()
                    module_options.append((key, opt))
                for k, v in updates.items():
                    setattr(opt, k, v)


class ConfigFileOptionsParser(BaseOptionsParser):
    def __init__(self, filename=None):
        self.filename = filename

    def _parse_section(self, prefix, template, section):
        # type: (str, Options, configparser.SectionProxy) -> Dict[str, object]
        """
        Parameters
        ----------
        prefix : str
        template : Options
        section : configparser.SectionProxy

        Returns
        -------
        Dict[str, object]
        """
        results = {}  # type: Dict[str, object]
        for key in section:
            if key in config_types:
                ct = config_types[key]
            else:
                dv = getattr(template, key, None)
                if dv is None:
                    print("%s: Unrecognized option: %s = %s" %
                          (prefix, key, section[key]),
                          file=sys.stderr)
                    continue
                ct = type(dv)
            v = None  # type: Any
            try:
                if ct is bool:
                    v = section.getboolean(key)  # type: ignore  # Until better stub
                elif callable(ct):
                    try:
                        v = ct(section.get(key))
                    except argparse.ArgumentTypeError as err:
                        print("%s: %s: %s" % (prefix, key, err),
                              file=sys.stderr)
                        continue
                else:
                    print("%s: Don't know what type %s should have" %
                          (prefix, key), file=sys.stderr)
                    continue
            except ValueError as err:
                print("%s: %s: %s" % (prefix, key, err), file=sys.stderr)
                continue
            results[key] = v
        return results

    def extract_updates(self, options):
        # type: (Options) -> Iterator[Tuple[Dict[str, object], Optional[str]]]
        if self.filename is not None:
            config_files = (self.filename,)  # type: Tuple[str, ...]
        else:
            config_files = tuple(map(os.path.expanduser, CONFIG_FILES))

        parser = configparser.RawConfigParser()

        for config_file in config_files:
            if not os.path.exists(config_file):
                continue
            try:
                parser.read(config_file)
            except configparser.Error as err:
                print("%s: %s" % (config_file, err), file=sys.stderr)
            else:
                file_read = config_file
                # options.config_file = file_read
                break
        else:
            print("No config files found")
            return

        if 'mypyrun' not in parser:
            if self.filename or file_read not in SHARED_CONFIG_FILES:
                print("%s: No [mypyrun] section in config file" % file_read,
                      file=sys.stderr)
        else:
            section = parser['mypyrun']

            prefix = '%s: [%s]' % (file_read, 'mypy')
            yield self._parse_section(prefix, options, section), None

        for name, section in parser.items():
            if name.startswith('mypyrun-'):
                prefix = '%s: [%s]' % (file_read, name)
                updates = self._parse_section(prefix, options, section)

                if set(updates).intersection(GLOBAL_ONLY_OPTIONS):
                    print("%s: Per-module sections should only specify "
                          "per-module flags (%s)" %
                          (prefix, ', '.join(sorted(set(updates).intersection(GLOBAL_ONLY_OPTIONS)))),
                          file=sys.stderr)
                    updates = {k: v for k, v in updates.items() if k in Options.PER_MODULE_OPTIONS}
                globs = name[8:]
                for glob in globs.split(','):
                    yield updates, glob


class SplitNamespace(argparse.Namespace):
    def __init__(self, standard_namespace, alt_namespace):
        self.__dict__['_standard_namespace'] = standard_namespace
        self.__dict__['_alt_namespace'] = alt_namespace

    def _get(self):
        return (self._standard_namespace, self._alt_namespace)

    def __setattr__(self, name, value):
        if hasattr(self._standard_namespace, name):
            if name in config_types:
                ct = config_types[name]
                value = ct(value)
            setattr(self._standard_namespace, name, value)
        else:
            setattr(self._alt_namespace, name, value)

    def __getattr__(self, name):
        if hasattr(self._standard_namespace, name):
            return getattr(self._standard_namespace, name)
        else:
            return getattr(self._alt_namespace, name)


class ArgparseOptionsParser(BaseOptionsParser):
    def __init__(self, parser, argv=None):
        # type: (argparse.ArgumentParser, Optional[List[str]]) -> None
        self.parser = parser
        self.argv = argv

    def apply(self, options, module_options):
        # type: (Options, List[Tuple[str, Options]]) -> None
        other_args = argparse.Namespace()
        self.parser.parse_args(self.argv, SplitNamespace(options, other_args))


class JsonOptionsParser(BaseOptionsParser):

    def __init__(self, json_data):
        self.json_data = json_data

    def extract_updates(self, options):
        # type: (Options) -> Iterator[Tuple[Dict[str, object], Optional[str]]]

        if self.json_data:
            results = {}  # type: Dict[str, object]
            for key, v in self.json_data.items():
                if key in config_types:
                    ct = config_types[key]
                    v = ct(v)  # type: ignore[operator]
                else:
                    dv = getattr(options, key, None)
                    if dv is None:
                        print("Unrecognized option: %s = %s" % (key, v),
                              file=sys.stderr)
                        continue
                results[key] = v
            yield results, None


class JsonEnvVarOptionsParser(JsonOptionsParser):
    def __init__(self):
        opts = os.environ.get('MYPYRUN_OPTIONS')
        json_data = json.loads(opts) if opts else None
        super(JsonEnvVarOptionsParser, self).__init__(json_data)


def get_parser():
    # type: () -> argparse.ArgumentParser

    parser = argparse.ArgumentParser(prog='mypyrun')

    def add_invertible_flag(flag, help, inverse=None):
        if inverse is None:
            inverse = '--no-{}'.format(flag[2:])

        help += " (inverse: {})".format(inverse)

        arg = parser.add_argument(
            flag, action='store_true',
            help=help)

        dest = arg.dest
        arg = parser.add_argument(
            inverse, action='store_false',
            dest=dest, help=argparse.SUPPRESS)

    parser.add_argument('--version', action='version',
                        version='%(prog)s {version}'.format(version=__version__))
    add_invertible_flag("--daemon",
                        help="Run mypy in daemon mode")
    parser.add_argument("--select", "-s", nargs="+", type=str,
                        help="Errors to check")
    parser.add_argument("--ignore",  "-i", nargs="+", type=str,
                        help="Errors to skip")
    parser.add_argument("--warn",  "-w", nargs="+", type=str,
                        help="Errors to convert into warnings")
    add_invertible_flag("--color",
                        help="Colorize output")
    parser.add_argument("--show-ignored", "-x",
                        help="Show errors that have been ignored (darker"
                             " if using color)",
                        action="store_true")
    parser.add_argument("--add-missing-imports",
                        help="Add missing typing imports. This will detect mypy errors "
                             "related to missing classes from the typing module and "
                             "automatically insert them into the file",
                        action="store_true")
    parser.add_argument("--options",  "-o",
                        help="Override the default options to use the named"
                             "configuration section (e.g. pass "
                             "--options=foo to use the [mypyrun-foo] "
                             "section)")
    parser.add_argument("--config-file", "-c",
                        help="Specific configuration file.")
    parser.add_argument('--files', nargs="+", type=str,
                        help="Files to isolate (triggers use of 'active'"
                             "options for these files)")
    parser.add_argument('--warning-filters', nargs="+", type=re.compile,  # type: ignore[arg-type]
                        default=argparse.SUPPRESS,
                        help="Regular expression to ignore messages flagged as"
                             " warnings")
    parser.add_argument('--error-filters', nargs="+", type=re.compile,  # type: ignore[arg-type]
                        default=argparse.SUPPRESS,
                        help="Regular expression to ignore messages flagged as"
                             " errors")
    parser.add_argument("--mypy-executable", type=str,
                        help="Path to the mypy executable")
    parser.add_argument('args', metavar='ARG', nargs='*', type=str,
                        default=argparse.SUPPRESS,
                        help="Regular mypy flags and files (precede with --)")

    return parser


if __name__ == '__main__':
    main()
