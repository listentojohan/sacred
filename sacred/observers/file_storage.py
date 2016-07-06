#!/usr/bin/env python
# coding=utf-8
from __future__ import division, print_function, unicode_literals
import os
import os.path
import tempfile
import json
from datetime import datetime
from shutil import copyfile

from sacred.commandline_options import CommandLineOption
from sacred.dependencies import get_digest
from sacred.observers.base import RunObserver
from sacred import optional as opt


def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""

    if isinstance(obj, datetime):
        serial = obj.isoformat()
        return serial
    raise TypeError("Type not serializable")


class FileStorageObserver(RunObserver):
    VERSION = 'FileStorageObserver-0.7.0'

    def __init__(self, basedir, resource_dir=None, source_dir=None):
        if not os.path.exists(basedir):
            os.makedirs(basedir)
        self.basedir = basedir
        self.resource_dir = resource_dir or os.path.join(basedir, '_resources')
        self.source_dir = source_dir or os.path.join(basedir, '_sources')
        self.dir = None
        self.run_entry = None
        self.config = None
        self.info = None
        self.cout = ""

    def queued_event(self, ex_info, command, queue_time, config, meta_info,
                     _id):
        if _id is None:
            self.dir = tempfile.mkdtemp(prefix='run_', dir=self.basedir)
        else:
            self.dir = os.path.join(self.basedir, str(_id))
            os.mkdir(self.dir)

        self.run_entry = {
            'experiment': dict(ex_info),
            'command': command,
            'meta': meta_info,
            'status': 'QUEUED',
        }
        self.config = config
        self.info = {}

        self.save_json(self.run_entry, 'run.json')
        self.save_json(self.config, 'config.json')

        for s, m in ex_info['sources']:
            self.save_file(s)

        return os.path.relpath(self.dir, self.basedir) if _id is None else _id

    def save_sources(self, ex_info):
        base_dir = ex_info['base_dir']
        source_info = []
        for s, m in ex_info['sources']:
            abspath = os.path.join(base_dir, s)
            store_path, md5sum = self.find_or_save(abspath, self.source_dir)
            # assert m == md5sum
            source_info.append([s, os.path.relpath(store_path, self.basedir)])
        return source_info

    def started_event(self, ex_info, command, host_info, start_time, config,
                      meta_info, _id):
        if _id is None:
            self.dir = tempfile.mkdtemp(prefix='run_', dir=self.basedir)
        else:
            self.dir = os.path.join(self.basedir, str(_id))
            os.mkdir(self.dir)

        ex_info['sources'] = self.save_sources(ex_info)

        self.run_entry = {
            'experiment': dict(ex_info),
            'command': command,
            'host': dict(host_info),
            'start_time': start_time,
            'meta': meta_info,
            'status': 'RUNNING',
            'resources': [],
            'artifacts': [],
            'heartbeat': None
        }
        self.config = config
        self.info = {}
        self.cout = ""

        self.save_json(self.run_entry, 'run.json')
        self.save_json(self.config, 'config.json')
        self.save_cout()

        return os.path.relpath(self.dir, self.basedir) if _id is None else _id

    def find_or_save(self, filename, store_dir):
        if not os.path.exists(store_dir):
            os.makedirs(store_dir)
        source_name, ext = os.path.splitext(os.path.basename(filename))
        md5sum = get_digest(filename)
        store_name = source_name + '_' + md5sum + ext
        store_path = os.path.join(store_dir, store_name)
        if not os.path.exists(store_path):
            copyfile(filename, store_path)
        return store_path, md5sum

    def save_json(self, obj, filename):
        with open(os.path.join(self.dir, filename), 'w') as f:
            json.dump(obj, f, indent=2, sort_keys=True,
                      default=json_serial)

    def save_file(self, filename, target_name=None):
        target_name = target_name or os.path.basename(filename)
        copyfile(filename, os.path.join(self.dir, target_name))

    def save_cout(self):
        with open(os.path.join(self.dir, 'cout.txt'), 'w') as f:
            f.write(self.cout)

    def render_template(self):
        template_name = os.path.join(self.basedir, 'template.html')
        if opt.has_mako and os.path.exists(template_name):
            from mako.template import Template
            template = Template(filename=template_name)
            report = template.render(run=self.run_entry,
                                     config=self.config,
                                     info=self.info,
                                     cout=self.cout,
                                     savedir=self.dir)
            with open(os.path.join(self.dir, 'report.html'), 'w') as f:
                f.write(report)

    def heartbeat_event(self, info, cout_filename, beat_time):
        self.info = info
        self.run_entry['heartbeat'] = beat_time
        self.save_file(cout_filename, 'cout.txt')
        self.save_json(self.run_entry, 'run.json')
        self.save_json(self.info, 'info.json')

    def completed_event(self, stop_time, result):
        self.run_entry['stop_time'] = stop_time
        self.run_entry['result'] = result
        self.run_entry['status'] = 'COMPLETED'

        self.save_json(self.run_entry, 'run.json')
        self.render_template()

    def interrupted_event(self, interrupt_time, status):
        self.run_entry['stop_time'] = interrupt_time
        self.run_entry['status'] = status
        self.save_json(self.run_entry, 'run.json')
        self.render_template()

    def failed_event(self, fail_time, fail_trace):
        self.run_entry['stop_time'] = fail_time
        self.run_entry['status'] = 'FAILED'
        self.run_entry['fail_trace'] = fail_trace
        self.save_json(self.run_entry, 'run.json')
        self.render_template()

    def resource_event(self, filename):
        store_path, md5sum = self.find_or_save(filename, self.resource_dir)
        self.run_entry['resources'].append((filename, store_path))
        self.save_json(self.run_entry, 'run.json')

    def artifact_event(self, name, filename):
        self.save_file(filename, name)
        self.run_entry['artifacts'].append(name)
        self.save_json(self.run_entry, 'run.json')

    def __eq__(self, other):
        if isinstance(other, FileStorageObserver):
            return self.basedir == other.basedir
        return False

    def __ne__(self, other):
        return not self.__eq__(other)


class FileStorageOption(CommandLineOption):
    """Add a file-storage observer to the experiment."""

    short_flag = 'F'
    arg = 'BASEDIR'
    arg_description = "Base-directory to write the runs to"

    @classmethod
    def apply(cls, args, run):
        run.observers.append(FileStorageObserver(args))
