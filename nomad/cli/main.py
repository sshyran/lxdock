import argparse
import logging
import sys

from .. import __version__
from ..conf.exceptions import ConfigError
from ..exceptions import NomadException
from ..logging import console_stderr_handler, console_stdout_handler

from .exceptions import CLIError

logger = logging.getLogger(__name__)


class Nomad(object):
    """ Wrapper around the LXD-Nomad argument parser and the related actions. """

    def __init__(self):
        self._parsers = {}

        # Creates the argument parsers
        parser = argparse.ArgumentParser(
            description='Orchestrate and run multiple containers using LXD.', prog='nomad')
        parser.add_argument(
            '--version', action='version', version='%(prog)s {v}'.format(v=__version__))
        parser.add_argument('-v', '--verbose', action='store_true')
        self._parsers['main'] = parser

        subparsers = parser.add_subparsers(dest='action')

        # Creates the 'config' action.
        self._parsers['config'] = subparsers.add_parser(
            'config', help='Validate and show the Nomad file.',
            description='Validate and show the Nomad file of the current project.')
        self._parsers['config'].add_argument(
            '--containers', action='store_true', help='Display only container names, one per line.')

        # Creates the 'destroy' action.
        self._parsers['destroy'] = subparsers.add_parser(
            'destroy', help='Stop and remove containers.',
            description='Destroy all the containers of a project or destroy specific containers '
                        'if container names are specified.')
        self._parsers['destroy'].add_argument(
            '-f', '--force', action='store_true', help='Destroy without confirmation.')

        # Creates the 'halt' action.
        self._parsers['halt'] = subparsers.add_parser(
            'halt', help='Stop containers.',
            description='Stop all the containers of a project or stop specific containers if '
                        'container names are specified.')

        # Creates the 'help' action.
        self._parsers['help'] = subparsers.add_parser(
            'help', help='Show help information.',
            description='Show general help information or show help information about a specific '
                        'subcommand.')
        self._parsers['help'].add_argument('subcommand', nargs='?', help='Subcommand name.')

        # Creates the 'provision' action.
        self._parsers['provision'] = subparsers.add_parser(
            'provision', help='Provision containers.',
            description='Provision all the containers of a project or provision specific '
                        'containers if container names are specified.')

        # Creates the 'shell' action.
        self._parsers['shell'] = subparsers.add_parser(
            'shell', help='Open a shell in a container.',
            description='Open an interactive shell inside a specific container.')
        self._parsers['shell'].add_argument('name', nargs='?', help='Container name.')
        self._parsers['shell'].add_argument(
            '-u', '--username', help='Username to login as.')

        # Creates the 'status' action.
        self._parsers['status'] = subparsers.add_parser(
            'status', help='Show containers\' statuses.',
            description='Show the status of all the containers of a project or show the status of '
                        'specific containers if container names are specified.')

        # Creates the 'up' action.
        self._parsers['up'] = subparsers.add_parser(
            'up', help='Create, start and provision containers.',
            description='Create, start and provision all the containers of the project according '
                        'to your nomad file. If container names are specified, only the related '
                        'containers are created, started and provisioned.')

        # Add common arguments to the action parsers that can be used with one or more specific
        # containers.
        per_container_parsers = ['destroy', 'halt', 'provision', 'status', 'up', ]
        for pkey in per_container_parsers:
            self._parsers[pkey].add_argument('name', nargs='*', help='Container name.')

        # Parses the arguments
        args = parser.parse_args()

        # Displays the help if no action is specified
        if args.action is None:
            parser.print_help()
            sys.exit(1)

        # Handles verbosity
        if args.verbose:
            console_stdout_handler.setLevel(logging.DEBUG)
        else:
            console_stdout_handler.setLevel(logging.INFO)

        try:
            # use dispatch pattern to invoke method with same name
            getattr(self, args.action)(args)
        except (CLIError, ConfigError, NomadException) as e:
            if e.msg is not None:
                logger.error(e.msg)
                sys.exit(1)

    def config(self, args):
        # We have to display the Nomad file here, which can be useful for completion or other
        # automated operations. In order to speed up things, we'll just manually create our config
        # object and use it.
        if args.containers:
            logger.info('\n'.join([c['name'] for c in self.project_config.containers]))
            return

        logger.info(self.project_config.serialize())

    def destroy(self, args):
        from .utils import yesno
        # Builds a list of containers by ensuring that these containers are actually associated with
        # the considered project.
        container_names = args.name or [c.name for c in self.project.containers]
        containers = [self.project.get_container_by_name(name) for name in container_names]
        # At this point we are sure that the containers we are manipulating are defined for the
        # project because we used the `get_container_by_name` method, which raises an error if a
        # container is not defined for the considered project.
        existing_containers = [c for c in containers if c.exists]

        should_destroy = False
        if len(container_names) and not len(existing_containers):
            should_destroy = True
        else:
            # We display a confirmation input to the user only if there are existing containers for
            # the considered project. Otherwise we just go through the destroy methods of the
            # containers and let the logger tell the user that the containers were not created.
            logging.warning(
                'The following containers will be removed: {}'.format(', '.join(container_names)))
            if len(container_names) and (args.force or yesno('Are you sure?')):
                should_destroy = True

        if should_destroy:
            self.project.destroy(container_names=args.name)

    def halt(self, args):
        self.project.halt(container_names=args.name)

    def help(self, args):
        try:
            assert args.subcommand is not None
            self._parsers[args.subcommand].print_help()
        except AssertionError:
            self._parsers['main'].print_help()
        except KeyError:
            # args.subcommand is not a valid subcommand!
            raise CLIError('No such command: {}'.format(args.subcommand))

    def provision(self, args):
        self.project.provision(container_names=args.name)

    def shell(self, args):
        self.project.shell(container_name=args.name, username=args.username)

    def status(self, args):
        self.project.status(container_names=args.name)

    def up(self, args):
        self.project.up(container_names=args.name)

    ##################################
    # UTILITY METHODS AND PROPERTIES #
    ##################################

    @property
    def project(self):
        """ Initializes a LXD-Nomad project instance and returns it. """
        from .project import get_project
        if not hasattr(self, '_project'):
            self._project = get_project()
        return self._project

    @property
    def project_config(self):
        """ Initializes a `Config` instance and returns it. """
        from ..conf import Config
        if not hasattr(self, '_project_config'):
            self._project_config = Config.from_base_dir()
        return self._project_config


def main():
    # Setup logging
    root_logger = logging.getLogger()
    root_logger.addHandler(console_stdout_handler)
    root_logger.addHandler(console_stderr_handler)
    root_logger.setLevel(logging.DEBUG)
    # Disables requests logging
    logging.getLogger('requests').propagate = False
    logging.getLogger('ws4py').propagate = False

    # Run the Nomad orchestration tool!
    Nomad()
