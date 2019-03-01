# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import shlex
import fileinput
from six import text_type

from keystoneauth1.exceptions.http import HttpError, HTTPClientError

from ..command import Command, Arg
from ..manager import CommandManager
from ..schema import SchemaError
from ..exceptions import CommandError, CommandNotFound, NotFound, Exists
from ..utils import printo


class Batch(Command):
    """ Execute commands from file(s) or from stdin
    """
    description = "Run commands from a batch file/stdin"
    files = Arg(nargs="*", help="Name of the batch file")

    def __call__(self, files=None):
        manager = CommandManager()
        try:
            for line in fileinput.input(files=files):
                if line[0] == '#':
                    continue
                action = shlex.split(line.rstrip())
                if len(action) < 1:
                    continue
                cmd = manager.get(action[0])
                args = action[1:]
                result = cmd.parse_and_call(*args)
                if result:
                    printo(result)
        except IOError:
            printo("Cannot read from file: {}".format(fileinput.filename()))
        except (HttpError, HTTPClientError, CommandError, CommandNotFound,
                SchemaError, NotFound, Exists) as e:
            printo(text_type(e))
        fileinput.close()
