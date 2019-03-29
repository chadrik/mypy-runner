from __future__ import absolute_import, print_function

import argparse
import subprocess
import os
import sys
import re

try:
    import configparser
except ImportError:
    import ConfigParser as configparser
from termcolor import colored

from typing import *

# adapted from mypy:
CONFIG_FILE = 'mypyrun.ini'
SHARED_CONFIG_FILES = ('mypy.ini', 'setup.cfg')
USER_CONFIG_FILES = ('~/.mypy.ini',)
CONFIG_FILES = (CONFIG_FILE,) + SHARED_CONFIG_FILES + USER_CONFIG_FILES

# choose an exit that does not conflict with mypy's
PARSING_FAIL = 100

# _FILTERS = [
#     # DEFINITION ERRORS --
#     # Type annotation errors:
#     ('invalid_syntax', 'syntax error in type comment'),
#     ('not_defined', ' is not defined'),  # in seminal
#     ('invalid_type_arguments', '(".*" expects .* type argument)'  # in typeanal
#                                '(Optional.* must have exactly one type argument)'
#                                '(is not subscriptable)'),
#     ('generator_expected', 'The return type of a generator function should be '),  # in messages
#     # Advanced signature errors:
#     ('orphaned_overload', 'Overloaded .* will never be matched'),  # in messages
#     ('already_defined', 'already defined'),  # in seminal
#     # Signature incompatible with function internals:
#     ('return_expected', 'Return value expected'),
#     ('return_not_expected', 'No return value expected'),
#     ('incompatible_return', 'Incompatible return value type'),
#     ('incompatible_yield', 'Incompatible types in "yield"'),
#     ('incompatible_arg', 'Argument .* has incompatible type'),
#     ('incompatible_default_arg', 'Incompatible default for argument'),
#     # Signature/class incompatible with super class:
#     ('incompatible_subclass_signature', 'Signature .* incompatible with supertype'),
#     ('incompatible_subclass_return', 'Return type .* incompatible with supertype'),
#     ('incompatible_subclass_arg', 'Argument .* incompatible with supertype'),
#     ('incompatible_subclass_attr', 'Incompatible types in assignment '
#                                    '\(expression has type ".*", base class '
#                                    '".*" defined the type as ".*"\)'),
#
#     # MISC --
#     ('need_annotation', 'Need type annotation'),
#     ('missing_module', 'Cannot find module '),
#
#     # USAGE ERRORS --
#     # Special case Optional/None issues:
#     ('no_attr_none_case', 'Item "None" of ".*" has no attribute'),
#     ('incompatible_subclass_attr_none_case',
#      'Incompatible types in assignment \(expression has type ".*", base class '
#      '".*" defined the type as "None"\)'),
#     # Other:
#     ('incompatible_list_comprehension', 'List comprehension has incompatible type'),
#     ('cannot_assign_to_method', 'Cannot assign to a method'),
#     ('not_enough_arguments', 'Too few arguments'),
#     ('not_callable', ' not callable'),
#     ('no_attr', '.* has no attribute'),
#     ('not_indexable', ' not indexable'),
#     ('invalid_index', 'Invalid index type'),
#     ('not_iterable', ' not iterable'),
#     ('not_assignable_by_index', 'Unsupported target for indexed assignment'),
#     ('no_matching_overload', 'No overload variant of .* matches argument type'),
#     ('incompatible_assignment', 'Incompatible types in assignment'),
#     ('invalid_return_assignment', 'does not return a value'),
#     ('unsupported_operand', 'Unsupported .*operand '),
#     ('abc_with_abstract_attr', "Cannot instantiate abstract class .* with abstract attribute"),
# ]
#
# FILTERS = [(n, re.compile(s)) for n, s in _FILTERS]
# FILTERS_SET = frozenset(n for n, s in FILTERS)

COLORS = {
    'error': 'red',
    'note': 'yellow',
}

GLOBAL_ONLY_OPTIONS = ['color', 'show_ignored', 'show_error_keys']


class Options:
    """
    Options common to both the config file and the cli.

    Options like paths and mypy-options, which can be set via mypy are
    not recorded here.
    """
    select = frozenset()
    ignore = frozenset()
    color = True
    show_ignored = False
    show_error_keys = False


def is_error(options: Options, error_code: str) -> bool:
    if options.select:
        if error_code in options.select:
            return True

    if options.ignore:
        if error_code in options.ignore:
            return False

    return options.ignore or not options.select


def report(options: Options, filename: str, lineno: str, status: str, msg: str, is_filtered: bool, error_key=None):
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
            status = colored(error_key + ': ', 'magenta', attrs=display_attrs) + status
        msg = colored(msg, color, attrs=display_attrs)
        outline = filename + lineno + status + msg

    print(outline)


def main(paths, mypy_options: Optional[List[str]], options: Options):
    args = ['mypy', '--show-error-codes']
    if mypy_options:
        args.append(mypy_options)
    args.extend(paths)
    proc = subprocess.Popen(args, stdout=subprocess.PIPE)

    # used to know when to error a note related to an error
    matched_error = None
    errors = 0
    text = ''
    for line in proc.stdout:
        line = line.decode()
        try:
            filename, lineno, error_code, status, msg = line.split(':', 4)
        except ValueError:
            text += line
        else:
            status = status.strip()
            msg = msg.strip()
            if status == 'error':
                error = is_error(options, error_code)
                if error:
                    errors += 1
                if options.show_ignored or error:
                    report(options, filename, lineno, status, msg, not error, error_code)
                    matched_error = error, error_code
                else:
                    matched_error = None
            elif status == 'note' and matched_error is not None:
                report(options, filename, lineno, status, msg,
                       not matched_error[0], matched_error[1])

    returncode = proc.wait()
    if returncode != 1:
        sys.stdout.write(text)
    return returncode if errors else 0


# Options Handling


def get_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", metavar='PATH', nargs='*')
    parser.add_argument("--select", "-s",
                        help="Errors to check (comma separated)")
    parser.add_argument("--ignore",  "-i",
                        help="Errors to skip (comma separated)")
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
    parser.add_argument("--list",
                        help="list error codes",
                        action="store_true")
    parser.add_argument("--mypy-options",
                        help="Options to pass to mypy (Note: to avoid parse "
                             "errors specify with equal. e.g. "
                             "--mypy-options=\"--py2\"")
    parser.add_argument("--select-all",
                        help="Enable all selections (for debugging missing choices)",
                        action="store_true")
    return parser


def _parse_multi_options(options, split_token: str = ',') -> List[str]:
    r"""Split and strip and discard empties.

    Turns the following:

    A,
    B,

    into ["A", "B"]
    """
    if options:
        return [o.strip() for o in options.split(split_token) if o.strip()]
    else:
        return []


def _validate(filters: Set[str], error_codes: Set[str]):
    invalid = sorted(filters.difference(error_codes))
    if invalid:
        print('Invalid filter(s): %s\n' % ', '.join(invalid), file=sys.stderr)
        sys.exit(PARSING_FAIL)


config_types = {
    'select': lambda x: set(_parse_multi_options(x)),
    'ignore': lambda x: set(_parse_multi_options(x)),
}


class BaseOptionsParser:
    def extract_updates(self, options):
        raise NotImplementedError

    def apply(self, options):
        for updates, fpath in self.extract_updates(options):
            if updates:
                for k, v in updates.items():
                    setattr(options, k, v)


class ConfigFileOptionsParser(BaseOptionsParser):
    def __init__(self, filename=None):
        self.filename = filename

    def _parse_section(self, prefix, template, section):
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
        if self.filename is not None:
            config_files = (self.filename,)  # type: Tuple[str, ...]
        else:
            config_files = tuple(map(os.path.expanduser, CONFIG_FILES))

        parser = configparser.RawConfigParser()

        for config_file in config_files:
            print(config_file)
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
                globs = name[5:]
                for glob in globs.split(','):
                    yield updates, glob


class ArgparseOptionsParser(BaseOptionsParser):
    def __init__(self, parser, parsed):
        self.parser = parser
        self.parsed = parsed

    def _get_specified(self):
        parsed_kwargs = dict(self.parsed._get_kwargs())
        specified = {}
        for action in self.parser._get_optional_actions():
            if action.dest in parsed_kwargs:
                if parsed_kwargs[action.dest] != action.default:
                    specified[action.dest] = parsed_kwargs[action.dest]
        return specified

    def extract_updates(self, options):

        results = {}  # type: Dict[str, object]
        for key, v in self._get_specified().items():
            if key in config_types:
                ct = config_types[key]
                try:
                    v = ct(v)
                except argparse.ArgumentTypeError as err:
                    print("%s: %s" % (key, err), file=sys.stderr)
                    continue
            else:
                dv = getattr(options, key, None)
                if dv is None:
                    continue
            results[key] = v
        yield results, None


def get_error_codes() -> Set[str]:
    import mypy.messages
    return mypy.messages.MessageBuilder.get_message_ids()

    # import inspect
    #
    # constant = re.compile("[A-Z][A-Z09_]+$")
    #
    # messages = {
    #     name.lower(): obj.replace('{}', '.*')
    #     for name, obj in inspect.getmembers(mypy.messages)
    #     if isinstance(obj, str) and constant.match(name)
    # }
    # return messages
    #
    # class Errors:
    #     def report(self, line, column, message, *kwargs):
    #         print(message)

    # print()
    #
    # errors = Errors()
    # messages = mypy.messages.MessageBuilder(errors, {})
    # for name, obj in inspect.getmembers(messages):
    #     if not name.startswith('_') and inspect.ismethod(obj):
    #         signature = inspect.signature(obj)
    #         if 'context' in signature.parameters and 'self.fail(' in inspect.getsource(obj):
    #             print(name)


if __name__ == '__main__':
    options = Options()
    parser = get_parser()

    error_codes = get_error_codes()

    args = parser.parse_args()
    if args.list:
        for name in sorted(error_codes):
            print('  %s' % (name,))
        sys.exit(0)

    parsers = [
        ConfigFileOptionsParser(),
        ArgparseOptionsParser(parser, args)
    ]

    for p in parsers:
        p.apply(options)

    if args.select_all:
        options.select = set(error_codes)
        options.show_ignored = True

    # if options.select:
    #     options.select.add('invalid_syntax')

    overlap = options.select.intersection(options.ignore)
    if overlap:
        print('The same option must not be both selected and '
              'ignored: %s' % ', '.join(overlap), file=sys.stderr)
        sys.exit(PARSING_FAIL)

    _validate(options.select, error_codes)
    _validate(options.ignore, error_codes)
    unused = set(error_codes).difference(options.ignore).difference(options.select)
    _validate(unused, error_codes)

    sys.exit(main(args.paths, args.mypy_options, options))
