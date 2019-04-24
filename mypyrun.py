from __future__ import absolute_import, print_function

import argparse
import subprocess
import os
import sys
import re
import fnmatch
import json
from collections import defaultdict

if sys.version_info[0] == 3:
    import configparser
else:
    import ConfigParser as configparser

if False:
    from typing import *

# adapted from mypy:
CONFIG_FILE = 'mypyrun.ini'
SHARED_CONFIG_FILES = ('mypy.ini', 'setup.cfg')
USER_CONFIG_FILES = ('~/.mypy.ini',)
CONFIG_FILES = (CONFIG_FILE,) + SHARED_CONFIG_FILES + USER_CONFIG_FILES

ALL = None

# choose an exit that does not conflict with mypy's
PARSING_FAIL = 100

_FILTERS = [
    ('revealed_type', 'Revealed type is'),
    # DEFINITION ERRORS --
    # Type annotation errors:
    ('invalid_syntax', 'syntax error in type comment'),
    ('wrong_number_of_args', 'Type signature has '),
    ('misplaced_annotation', 'misplaced type annotation'),
    ('not_defined', ' is not defined'),  # in seminal
    ('invalid_type_arguments', '(".*" expects .* type argument)'  # in typeanal
                               '(Optional.* must have exactly one type argument)'
                               '(is not subscriptable)'),
    ('generator_expected', 'The return type of a generator function should be '),  # in messages
    # Advanced signature errors:
    ('orphaned_overload', 'Overloaded .* will never be matched'),  # in messages
    ('already_defined', 'already defined'),  # in seminal
    # Signature incompatible with function internals:
    ('return_expected', 'Return value expected'),
    ('return_not_expected', 'No return value expected'),
    ('incompatible_return', 'Incompatible return value type'),
    ('incompatible_yield', 'Incompatible types in "yield"'),
    ('incompatible_arg', 'Argument .* has incompatible type'),
    ('incompatible_default_arg', 'Incompatible default for argument'),
    # Signature/class incompatible with super class:
    ('incompatible_subclass_signature', 'Signature .* incompatible with supertype'),
    ('incompatible_subclass_return', 'Return type .* incompatible with supertype'),
    ('incompatible_subclass_arg', 'Argument .* incompatible with supertype'),
    ('incompatible_subclass_attr', 'Incompatible types in assignment '
                                   '\(expression has type ".*", base class '
                                   '".*" defined the type as ".*"\)'),

    # MISC --
    ('need_annotation', 'Need type annotation'),
    ('missing_module', 'Cannot find module '),

    # USAGE ERRORS --
    # Special case Optional/None issues:
    ('no_attr_none_case', 'Item "None" of ".*" has no attribute'),
    ('incompatible_subclass_attr_none_case',
     'Incompatible types in assignment \(expression has type ".*", base class '
     '".*" defined the type as "None"\)'),
    # Other:
    ('incompatible_list_comprehension', 'List comprehension has incompatible type'),
    ('cannot_assign_to_method', 'Cannot assign to a method'),
    ('not_enough_arguments', 'Too few arguments'),
    ('not_callable', ' not callable'),
    ('no_attr', '.* has no attribute'),
    ('not_indexable', ' not indexable'),
    ('invalid_index', 'Invalid index type'),
    ('not_iterable', ' not iterable'),
    ('not_assignable_by_index', 'Unsupported target for indexed assignment'),
    ('no_matching_overload', 'No overload variant of .* matches argument type'),
    ('incompatible_assignment', 'Incompatible types in assignment'),
    ('invalid_return_assignment', 'does not return a value'),
    ('unsupported_operand', 'Unsupported .*operand '),
    ('abc_with_abstract_attr', "Cannot instantiate abstract class .* with abstract attribute"),
]

FILTERS = [(n, re.compile(s)) for n, s in _FILTERS]
FILTERS_SET = frozenset(n for n, s in FILTERS)

COLORS = {
    'error': 'red',
    'warning': 'yellow',
    'note': None,
}

GLOBAL_ONLY_OPTIONS = [
    'color',
    'show_ignored',
    'show_error_keys',
    'daemon',
    'exclude',
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


def colored(text, color=None, attrs=None):
    esc = '\033[%dm%s'
    if color is not None:
        text = esc % (TERM_COLORS[color], text)

    if attrs is not None:
        for attr in attrs:
            text = esc % (TERM_ATTRIBUTES[attr], text)

    text += TERM_RESET
    return text


class Options:
    """
    Options common to both the config file and the cli.

    Options like paths and mypy-options, which can be set via mypy are
    not recorded here.
    """
    PER_MODULE_OPTIONS = [
        'select',
        'ignore',
        'warn',
        'include',
    ]

    select = None  # type: Optional[Set[str]]
    ignore = None  # type: Optional[Set[str]]
    warn = None  # type: Optional[Set[str]]
    include = None  # type: List[Pattern]
    exclude = None  # type: List[Pattern]

    # global-only options:
    paths = None  # type: List[str]
    color = True
    show_ignored = False
    show_error_keys = False
    daemon = False

    def __init__(self):
        self.select = ALL
        self.ignore = set()
        self.warn = set()
        self.include = []
        self.exclude = []
        self.paths = []


def get_error_code(msg):
    # type: (str) -> Optional[str]
    """
    Lookup the error constant from a parsed message literal.

    Parameters
    ----------
    msg : str

    Returns
    -------
    Optional[str]
    """
    for code, regex in FILTERS:
        if regex.search(msg):
            return code
    return None


def is_excluded_path(path, options):
    for regex in options.exclude:
        if regex.search(path):
            return True
    return False


def get_options(filename, global_options, module_options):
    # type: (str, Options, List[Tuple[str, Options]]) -> Options
    for key, options in module_options:
        for include in options.include:
            if include.search(filename):
                return options
    return global_options


def get_status(options, error_code):
    # type: (Options, str) -> Optional[str]
    """
    Determine whether an error code is an error, warning, or ignored

    Parameters
    ----------
    options: Options
    error_code: str

    Returns
    -------
    Optional[str]
    """
    if options.select is ALL or error_code in options.select:
        return 'error'

    if options.ignore is ALL or error_code in options.ignore:
        return None

    if options.warn is ALL or error_code in options.warn:
        return 'warning'

    if options.ignore or (options.select is not ALL and not options.select):
        return 'error'

    return None


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
        if options.show_error_keys and error_key:
            msg = '%s: %s: %s' % (error_key, status, msg)
        else:
            msg = '%s: %s' % (status, msg)

        outline = 'IGNORED ' if options.show_ignored and is_filtered else ''
        outline += '%s:%s: %s' % (filename, lineno, msg)

    else:
        display_attrs = ['dark'] if options.show_ignored and is_filtered else None

        filename = colored(filename, 'cyan', attrs=display_attrs)
        lineno = colored(':%s: ' % lineno, attrs=display_attrs)
        color = COLORS[status]
        status = colored(status + ': ', color, attrs=display_attrs)
        if options.show_error_keys and error_key:
            status = colored(error_key + ': ', 'magenta',
                             attrs=display_attrs) + status
        msg = colored(msg, color, attrs=display_attrs)
        outline = filename + lineno + status + msg

    print(outline)


def run(active_files, global_options, module_options, daemon_mode=False):
    # type: (Optional[List[str]], Options, List[Tuple[str, Options]], bool) -> int
    """
    Parameters
    ----------
    mypy_options : Optional[List[str]]
    global_options : Options
    module_options : List[Tuple[str, Options]]
    daemon_mode : bool
        run `dmypy` instead of `mypy`

    Returns
    -------
    int
        exit status
    """
    if daemon_mode:
        args = ['dmypy', 'run', '--']
    else:
        args = ['mypy']

    # if mypy_options:
    #     args.extend(mypy_options)

    active_options = dict(module_options).get('active')
    if active_options and active_files:
        # force the `active` options to be found by `get_options()` for all
        # files passed on the command-line
        # FIXME: reorder module_options so this is first?
        active_options.include = [_glob_to_regex(x) for x in active_files]

    env = os.environ.copy()

    if global_options.paths:
        args.extend(global_options.paths)

    proc = subprocess.Popen(args, stdout=subprocess.PIPE, env=env)

    # used to know when to error a note related to an error
    matched_error = None
    errors = defaultdict(int)  # type: DefaultDict[str]
    warnings = defaultdict(int)  # type: DefaultDict[str]
    last_error = None  # type: Optional[Tuple[Options, Any, Any, Any, Optional[str]]]

    for line in proc.stdout:
        line = line.decode()
        try:
            filename, lineno, status, msg = line.split(':', 3)
        except ValueError:
            lineno = ''
            try:
                filename, status, msg = line.split(':', 2)
            except ValueError:
                print(line, end='')
                continue

        if is_excluded_path(filename, global_options):
            continue

        options = get_options(filename, global_options, module_options)

        error_code = get_error_code(msg)
        status = status.strip()
        msg = msg.strip()

        last_error = global_options, filename, lineno, msg, error_code

        if error_code and status == 'error':
            new_status = get_status(options, error_code)
            if new_status == 'error':
                errors[filename] += 1
            elif new_status == 'warning':
                warnings[filename] += 1
            if global_options.show_ignored or new_status:
                report(global_options, filename, lineno, new_status or 'error',
                       msg, not new_status, error_code)
                matched_error = new_status, error_code
            else:
                matched_error = None
        elif status == 'note' and matched_error is not None:
            report(global_options, filename, lineno, status, msg,
                   not matched_error[0], matched_error[1])

    def print_stat(key, value):
        print("{:.<12}{:.>20}".format(key, value))

    print()
    print_stat("Errors", sum(errors.values()))
    print_stat("Warnings", sum(warnings.values()))
    if active_files:
        error_files = set(errors.keys())
        warning_files = set(warnings.keys())
        clean_files = set(active_files).difference(error_files | warning_files)
        print_stat("Clean files", len(clean_files))
        # for x in sorted(clean_files):
        #     print(x)

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


def main():
    options = Options()
    module_options = []

    parser = get_parser()

    error_codes = get_error_codes()

    args = parser.parse_args()
    if args.list:
        for name, pattern in sorted(_FILTERS):
            print('  %s: %r' % (name, pattern))
        sys.exit(0)

    parsers = [
        ConfigFileOptionsParser(),
        JsonEnvVarOptionsParser(),
        ArgparseOptionsParser(parser, args)
    ]

    for p in parsers:
        p.apply(options, module_options)

    if args.options:
        override_options = dict(module_options).get(args.options)
        if override_options is None:
            print('Configuration section does not exist: [mypyrun-%s]' %
                  args.options)
            sys.exit(PARSING_FAIL)
        for key in Options.PER_MODULE_OPTIONS:
            setattr(options, key, getattr(override_options, key))

    # if options.select:
    #     options.select.add('invalid_syntax')

    if options.select:
        overlap = options.select.intersection(options.ignore)
        if overlap:
            print('The same option must not be both selected and '
                  'ignored: %s' % ', '.join(overlap), file=sys.stderr)
            sys.exit(PARSING_FAIL)

    # _validate(options.select, error_codes)
    # _validate(options.ignore, error_codes)
    # _validate(options.warn, error_codes)
    #
    # unused = set(error_codes).difference(options.ignore)
    # unused = unused.difference(options.select)
    # _validate(unused, error_codes)

    sys.exit(run(args.files, options, module_options, options.daemon))


# Options Handling

def _parse_multi_options(options, split_token=','):
    # type: (str, str) -> List[str]
    r"""
    Split and strip and discard empties.

    Turns the following:

    >>> _parse_multi_options("    A,\n    B,\n")
    ["A", "B"]

    Parameters
    ----------
    options : str
    split_token : str

    Returns
    -------
    List[str]
    """
    if options:
        return [o.strip() for o in options.split(split_token) if o.strip()]
    else:
        return []


def _validate(filters, error_codes):
    # type: (Set[str], Set[str]) -> None
    """
    Parameters
    ----------
    filters : Set[str]
    error_codes : Set[str]
    """
    invalid = sorted(filters.difference(error_codes))
    if invalid:
        print('Invalid filter(s): %s\n' % ', '.join(invalid), file=sys.stderr)
        sys.exit(PARSING_FAIL)


def _glob_to_regex(s):
    return re.compile(fnmatch.translate(s))


def _glob_list(s):
    # type: (str) -> List[Pattern]
    return [_glob_to_regex(x) for x in _parse_multi_options(s)]


def _error_set(s):
    # type: (str) -> Optional[Set[str]]
    result = set(_parse_multi_options(s))
    if '*' in result:
        return None
    return result


config_types = {
    'select': _error_set,
    'ignore': _error_set,
    'warn': _error_set,
    'paths':  _parse_multi_options,
    'include': _glob_list,
    'exclude': _glob_list,
}


class BaseOptionsParser:
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
                    print("%s: Unrecognized option: %s = %s" % (prefix, key, section[key]),
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
                        print("%s: %s: %s" % (prefix, key, err), file=sys.stderr)
                        continue
                else:
                    print("%s: Don't know what type %s should have" % (prefix, key), file=sys.stderr)
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
                    print("%s: Per-module sections should only specify per-module flags (%s)" %
                          (prefix, ', '.join(sorted(set(updates).intersection(GLOBAL_ONLY_OPTIONS)))),
                          file=sys.stderr)
                    updates = {k: v for k, v in updates.items() if k in Options.PER_MODULE_OPTIONS}
                globs = name[8:]
                for glob in globs.split(','):
                    yield updates, glob


class ArgparseOptionsParser(BaseOptionsParser):
    def __init__(self, parser, parsed):
        # type: (argparse.ArgumentParser, Any) -> None
        self.parser = parser
        self.parsed = parsed

    def _get_specified(self):
        # type: () -> Dict[str, object]
        parsed_kwargs = dict(self.parsed._get_kwargs())
        specified = {}  # type: Dict[str, object]
        for action in self.parser._get_optional_actions():
            if action.dest in parsed_kwargs:
                if parsed_kwargs[action.dest] != action.default:
                    specified[action.dest] = parsed_kwargs[action.dest]
        return specified

    def extract_updates(self, options):
        # type: (Options) -> Iterator[Tuple[Dict[str, object], Optional[str]]]
        results = {}  # type: Dict[str, object]
        for key, v in self._get_specified().items():
            if key in config_types:
                ct = config_types[key]
                v = ct(v)
            else:
                dv = getattr(options, key, None)
                if dv is None:
                    continue
            results[key] = v
        yield results, None


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
                    v = ct(v)
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


def get_error_codes():
    # type: () -> FrozenSet[str]
    """
    Returns
    -------
    FrozenSet[str]
    """
    return FILTERS_SET


def get_parser():
    # type: () -> argparse.ArgumentParser
    parser = argparse.ArgumentParser()
    parser.add_argument("--list",
                        help="list error codes",
                        action="store_true")
    parser.add_argument("--daemon", "-d",
                        help="run in daemon mode (dmypy run)",
                        action="store_true")
    parser.add_argument("--select", "-s",
                        help="Errors to check (comma separated)")
    parser.add_argument("--ignore",  "-i",
                        help="Errors to skip (comma separated)")
    parser.add_argument("--warn",  "-w",
                        help="Errors to convert into warnings (comma separated)")
    parser.add_argument("--no-color", dest="color",
                        default=True,
                        help="do not colorize output",
                        action="store_false")
    parser.add_argument("--show-ignored", "-x",
                        help="Show errors that have been ignored (darker"
                             " if using color)",
                        action="store_true")
    parser.add_argument("--show-error-keys",
                        help="Show error key for each line",
                        action="store_true")
    parser.add_argument("--options",  "-o",
                        help="Override the default options to use the named"
                             "configuration section (e.g. pass "
                             "--options=foo to use the [mypyrun-foo] "
                             "section)")
    parser.add_argument('files', nargs='*', type=str,
                        help="Files to isolate (triggers use of 'active'"
                             "options for these files)")
    return parser


if __name__ == '__main__':
    main()
