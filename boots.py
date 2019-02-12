from __future__ import print_function

import argparse
try:
    import configparser
except ImportError:
    import ConfigParser as configparser
import errno
import functools
import glob
import os
import os.path
import shlex
import shutil
import stat
import subprocess
import sys
import time
try:
    from urllib.request import urlopen
except ImportError:
    from urllib2 import urlopen


py3 = sys.version_info[0] == 3


class ExitError(Exception):
    pass


def resolve_path(*path):
    return os.path.normpath(os.path.abspath(os.path.join(*path)))


def check_call(command, *args, **kwargs):
    command = list(command)
    print('Launching: ')
    for arg in command:
        print('    {}'.format(arg))

    return subprocess.check_call(command, *args, **kwargs)


def check_output(command, *args, **kwargs):
    command = list(command)
    print('Launching: ')
    for arg in command:
        print('    {}'.format(arg))

    return subprocess.check_output(command, *args, **kwargs)


def read_dot_env(path):
    env = {}
    with open(path) as f:
        for line in f:
            line = line.strip()

            if line.startswith('#'):
                continue

            k, _, v = line.partition('=')
            env[k] = v

    return env


def create(group, configuration):
    d = {
        'linux': linux_create,
        'win32': windows_create,
    }

    dispatch(d, group=group, configuration=configuration)


def common_create(
    group,
    python,
    venv_bin,
    requirements_platform,
    symlink,
    configuration,
):
    if os.path.exists(configuration.venv_path):
        raise ExitError(
            'venv already exists. if you know it is safe, remove it with:\n'
            '    python {} rm'.format(os.path.basename(__file__))
        )

    env = dict(os.environ)
    env.update(read_dot_env(configuration.dot_env))
    pip_src = env.get('PIP_SRC')
    if pip_src is not None:
        try:
            os.makedirs(pip_src)
        except OSError as e:
            if e.errno == errno.EEXIST:
                pass
            else:
                raise

    check_call(
        [
            python,
            '-m', 'venv',
            '--prompt', configuration.venv_prompt,
            configuration.venv_path,
        ],
        cwd=configuration.project_root,
        env=env,
    )

    if symlink:
        os.symlink(venv_bin, configuration.venv_common_bin)

    requirements_path = os.path.join(
        configuration.requirements_path,
        '{}.{}.txt'.format(configuration.pre_group, requirements_platform),
    )
    check_call(
        [
            configuration.venv_python,
            '-m', 'pip',
            'install',
            '--requirement', requirements_path,
        ],
        cwd=configuration.project_root,
        env=env,
    )

    if group is None:
        return

    sync_requirements(
        group=group,
        requirements_platform=requirements_platform,
        configuration=configuration,
    )


def sync_requirements(group, requirements_platform, configuration):
    filename = group

    filename = '{}.{}.txt'.format(filename, requirements_platform)
    path = os.path.join(configuration.requirements_path, filename)

    env = dict(os.environ)
    env.update(read_dot_env(configuration.dot_env))

    sync_requirements_file(
        env=env,
        requirements=path,
        configuration=configuration,
    )

    requirements_path = os.path.join(
        configuration.requirements_path,
        'local.txt',
    )
    check_call(
        [
            configuration.venv_python,
            '-m', 'pip',
            'install',
            '--no-deps',
            '--requirement', requirements_path,
        ],
        cwd=configuration.project_root,
        env=env,
    )


def sync_requirements_file(env, requirements, configuration):
    check_call(
        [
            os.path.join(configuration.venv_common_bin, 'pip-sync'),
            requirements,
        ],
        cwd=configuration.project_root,
        env=env,
    )


def linux_create(group, configuration):
    venv_bin = os.path.join(configuration.venv_path, 'bin')
    common_create(
        group=group,
        python='python3.7',
        venv_bin=venv_bin,
        requirements_platform='linux',
        symlink=True,
        configuration=configuration,
    )


def windows_create(group, configuration):
    python_path = check_output(
        [
            'py',
            '-3.7-32',
            '-c', 'import sys; print(sys.executable)',
        ],
        cwd=configuration.project_root,
    )
    if py3:
        python_path = python_path.decode()
    python_path = python_path.strip()

    common_create(
        group=group,
        python=python_path,
        venv_bin=configuration.venv_common_bin,
        requirements_platform='windows',
        symlink=False,
        configuration=configuration,
    )


def rm(ignore_missing, configuration):
    try:
        rmtree(configuration.venv_path)
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise

        if not ignore_missing:
            raise ExitError(
                'venv not found at: {}'.format(configuration.venv_path),
            )


def compile_dispatch(configuration):
    d = {
        'linux': functools.partial(
            common_compile,
            requirements_platform='linux',
        ),
        'win32': functools.partial(
            common_compile,
            requirements_platform='windows',
        ),
    }

    dispatch(d, configuration=configuration)


def common_compile(requirements_platform, configuration):
    if not venv_existed(configuration=configuration):
        create(group=None, configuration=configuration)

    in_paths = tuple(
        os.path.join(configuration.requirements_path, filename)
        for filename in glob.glob(
            os.path.join(configuration.requirements_path, '*.in'),
        )
    )

    for in_path in in_paths:
        stem = os.path.splitext(in_path)[0]
        group = os.path.basename(stem)

        out_path = '{}.{}.txt'.format(
            stem,
            requirements_platform,
        )

        extras = []
        if group == configuration.pre_group:
            extras.append('--allow-unsafe')

        check_call(
            [
                os.path.join(configuration.venv_common_bin, 'pip-compile'),
                '--output-file', out_path,
                in_path,
            ] + extras,
            cwd=configuration.project_root,
        )


def venv_existed(configuration):
    return os.path.exists(configuration.venv_path)


def ensure(group, quick, configuration):
    d = {
        'linux': functools.partial(
            common_ensure,
            requirements_platform='linux',
        ),
        'win32': functools.partial(
            common_ensure,
            requirements_platform='windows',
        ),
    }

    dispatch(d, group=group, quick=quick, configuration=configuration)


def common_ensure(group, quick, requirements_platform, configuration):
    existed = venv_existed(configuration=configuration)

    if not existed:
        create(group=group, configuration=configuration)
    elif not quick:
        sync_requirements(
            group=group,
            requirements_platform=requirements_platform,
            configuration=configuration,
        )

    check(configuration=configuration)

    if existed:
        print('venv already present and passes some basic checks')
    else:
        print('venv created and passed some basic checks')


def clean_path(path):
    return os.path.normpath(os.path.abspath(path))


def check(configuration):
    activate = os.path.join(configuration.venv_common_bin, 'activate')
    expected_name = 'VIRTUAL_ENV'

    # try:
    with open(activate) as f:
        for line in f:
            line = line.strip()
            try:
                name, original_venv_path = line.split('=', 1)
            except ValueError:
                continue

            if name == expected_name:
                original_venv_path, = shlex.split(original_venv_path)
                break
        else:
            raise Exception(
                '{} assignment not found '
                'in "{}"'.format(expected_name, activate),
            )
    # except OSError as e:
    #     if e.errno == errno.ENOENT:
    #
    #
    #     raise

    if clean_path(configuration.venv_path) != clean_path(original_venv_path):
        raise ExitError(
            'venv should be at "{}" but has been moved to "{}"'.format(
                original_venv_path,
                configuration.venv_path,
            ),
        )

    # epyq = os.path.join(configuration.venv_common_bin, 'epyq')

    executables = []

    for executable in executables:
        try:
            check_call(
                [
                    executable,
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
            )
        except OSError as e:
            if e.errno == errno.ENOENT:
                raise ExitError(
                    'required file "{}" not found'.format(executable),
                )
            elif e.errno == errno.EACCES:
                raise ExitError(
                    'required file "{}" not runnable'.format(executable),
                )

            raise


def strap(url, configuration):
    response = urlopen(url)

    with open(resolve_path(__file__), 'wb') as f:
        f.write(response.read())


def add_group_option(parser, default):
    parser.add_argument(
        '--group',
        default=default,
        help=(
            'Select a specific requirements group'
            ' (stem of a file in requirements/)'
        ),
    )


def dispatch(d, *args, **kwargs):
    for name, f in d.items():
        if sys.platform.startswith(name):
            f(*args, **kwargs)
            break
    else:
        raise ExitError('Platform not supported: {}'.format(sys.platform))


def add_subparser(subparser, *args, **kwargs):
    return subparser.add_parser(
        *args,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        **kwargs
    )


class Configuration:
    configuration_defaults = {
        'project_root': '',
        'default_group': 'base',
        'pre_group': 'pre',
        'requirements_path': 'requirements',
        'dot_env': '.env',
        'venv_path': 'venv',
        'venv_common_bin': 'Scripts',
        'venv_python': 'python',
        'venv_prompt': None,
        'update_url': (
            'https://raw.githubusercontent.com'
            '/altendky/boots/master/boots.py'
        )
    }

    def __init__(
            self,
            project_root,
            default_group,
            pre_group,
            requirements_path,
            dot_env,
            venv_path,
            venv_common_bin,
            venv_python,
            venv_prompt,
            update_url,
    ):
        self.project_root = project_root
        self.default_group = default_group
        self.pre_group = pre_group
        self.requirements_path = requirements_path
        self.dot_env = dot_env
        self.venv_path = venv_path
        self.venv_common_bin = venv_common_bin
        self.venv_python = venv_python
        self.venv_prompt = venv_prompt
        self.update_url = update_url

    @classmethod
    def from_setup_cfg(cls, path):
        config = configparser.ConfigParser()
        config.read(path)

        section_name = os.path.splitext(os.path.basename(__file__))[0]

        if config.has_section(section_name):
            section = dict(config.items(section_name))
        else:
            section = {}

        return cls.from_dict(
            d=section,
            reference_path=os.path.dirname(path),
        )

    @classmethod
    def from_dict(cls, d, reference_path):
        c = dict(cls.configuration_defaults)
        c['project_root'] = resolve_path(reference_path, c['project_root'])
        c.update(d)

        venv_path = resolve_path(
            reference_path,
            c['venv_path'],
        )

        venv_common_bin = resolve_path(
            venv_path,
            c['venv_common_bin'],
        )

        project_root = c['project_root']

        venv_prompt = c['venv_prompt']
        if venv_prompt is None:
            venv_prompt = '{} - {}'.format(
                os.path.basename(project_root),
                os.path.basename(venv_path),
            )

        return cls(
            project_root=project_root,
            default_group=c['default_group'],
            pre_group=c['pre_group'],
            requirements_path=resolve_path(
                reference_path,
                c['requirements_path'],
            ),
            dot_env=resolve_path(
                reference_path,
                c['dot_env'],
            ),
            venv_path=venv_path,
            venv_common_bin=venv_common_bin,
            venv_python=resolve_path(
                venv_common_bin,
                c['venv_python'],
            ),
            venv_prompt=venv_prompt,
            update_url=c['update_url'],
        )


def main():
    configuration = Configuration.from_setup_cfg(
        path=os.path.join(
            os.path.dirname(resolve_path(__file__)),
            'setup.cfg',
        ),
    )

    parser = argparse.ArgumentParser(
        description='Create and manage the venv',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.set_defaults(func=parser.print_help)
    subparsers = parser.add_subparsers()

    check_parser = add_subparser(
        subparsers,
        'check',
        description='Do some basic validity checks against the venv',
    )
    check_parser.set_defaults(func=check)

    create_parser = add_subparser(
        subparsers,
        'create',
        description='Create the venv',
    )
    add_group_option(create_parser, default=configuration.default_group)
    create_parser.set_defaults(func=create)

    ensure_parser = add_subparser(
        subparsers,
        'ensure',
        description='Create the venv if not already present',
    )
    add_group_option(ensure_parser, default=configuration.default_group)
    ensure_parser.add_argument(
        '--quick',
        action='store_true',
        help=(
            'Consider valid if venv directory exists, '
            'do not make sure that all packages are installed'
        ),
    )
    ensure_parser.set_defaults(func=ensure)

    rm_parser = add_subparser(
        subparsers,
        'rm',
        description='Remove the venv',
    )
    rm_parser.add_argument(
        '--ignore-missing',
        action='store_true',
        help='Do not raise an error if no venv is present',
    )
    rm_parser.set_defaults(func=rm)

    compile_parser = add_subparser(
        subparsers,
        'compile',
        description='pip-compile the requirements .in files',
    )
    compile_parser.set_defaults(func=compile_dispatch)

    strap_parser = add_subparser(
        subparsers,
        'strap',
        description='Strap on some new boots (self update)',
    )
    strap_parser.add_argument(
        '--url',
        default=configuration.update_url,
        help='Another URL to update from',
    )
    strap_parser.set_defaults(func=strap)

    args = parser.parse_args()

    reserved_parameters = {'func', 'configuration'}
    cleaned = {
        k: v
        for k, v in vars(args).items()
        if k not in reserved_parameters
    }

    os.environ['CUSTOM_COMPILE_COMMAND'] = 'python {} compile'.format(
        os.path.basename(__file__)
    )
    os.environ['PIP_DISABLE_PIP_VERSION_CHECK'] = '1'
    # https://github.com/pypa/pip/issues/5200#issuecomment-380131668
    # The flag sets the internal parameter to `False`, so you need to supply a
    # false value to the environment variable
    os.environ['PIP_NO_WARN_SCRIPT_LOCATION'] = '0'

    args.func(configuration=configuration, **cleaned)


# http://stackoverflow.com/a/21263493/228539
def del_rw(action, name, exc):
    os.chmod(name, stat.S_IWRITE)
    if os.path.isdir(name):
        os.rmdir(name)
    else:
        os.remove(name)


def rmtree(path, retries=4):
    for remaining in reversed(range(retries)):
        try:
            shutil.rmtree(path, onerror=del_rw)
        except OSError as e:
            if remaining == 0 or e.errno == errno.ENOENT:
                raise
        else:
            break

        print('{} remaining removal attempts'.format(remaining))
        time.sleep(0.5)


def _entry_point():
    try:
        sys.exit(main())
    except ExitError as e:
        sys.stderr.write(str(e) + '\n')
        sys.exit(1)


if __name__ == '__main__':
    _entry_point()
