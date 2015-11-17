import json
from uuid import UUID
try:
    from UserDict import UserDict
    from UserList import UserList
except ImportError:
    from collections import UserDict, UserList

from prompt_toolkit.completion import Completer, Completion

from .utils import Path, ShellContext, Observable


class ResourceEncoder(json.JSONEncoder):

    def default(self, obj):
        if isinstance(obj, Path):
            return str(obj)
        if isinstance(obj, Resource):
            return obj.data
        if isinstance(obj, Collection):
            return obj.data
        return super(ResourceEncoder, self).default(obj)


class ResourceCompleter(Completer):
    """
    Simple autocompletion on a list of resources.
    """
    def __init__(self):
        self.resources = {}
        ResourceBase.register('created', self.add_resource)

    def add_resource(self, resource):
        self.resources[resource.path] = resource

    def get_completions(self, document, complete_event):
        path_before_cursor = document.get_word_before_cursor(WORD=True).lower()

        def resource_matches(*args):
            return any([path_before_cursor in f for f in args])

        def resource_sort(resource):
            # Make the relative paths of the resource appear first in
            # the list
            if resource.type == ShellContext.current_path.base:
                return "_"
            return resource.type

        for res in sorted(self.resources.values(), key=resource_sort):
            rel_path = str(res.path.relative_to(ShellContext.current_path))
            if rel_path in ('.', '/', ''):
                continue
            if resource_matches(rel_path, res.fq_name):
                yield Completion(str(rel_path),
                                 -len(path_before_cursor),
                                 display_meta=res.fq_name)


class ResourceBase(Observable):
    session = None

    def __new__(cls, *args, **kwargs):
        if cls.session is None:
            raise ValueError("ContrailAPISession must be initialized first")
        return super(ResourceBase, cls).__new__(cls, *args, **kwargs)

    def __repr__(self):
        try:
            return repr(self.data)
        except AttributeError:
            return self.__class__.__name__


class Collection(ResourceBase, UserList):

    def __init__(self, type, fetch=False, recursive=1,
                 fields=None, filters=None, parent_uuid=None,
                 **kwargs):
        UserList.__init__(self)
        self.type = type
        self.fields = fields or []
        self.filters = filters or []
        self.parent_uuid = list(self._sanitize_parent_uuid(parent_uuid))
        self.path = Path('/' + type)
        self.meta = dict(kwargs)
        if fetch:
            self.fetch(recursive=recursive)
        self.emit('created', self)

    @property
    def href(self):
        url = self.session.base_url + str(self.path)
        if self.type:
            url = url + 's'
        return url

    @property
    def fq_name(self):
        return ""

    def __len__(self):
        if not self.data:
            return self.session.get(self.href, count=True)[self._contrail_name]["count"]
        return super(Collection, self).__len__()

    @property
    def _contrail_name(self):
        if self.type:
            return self.type + 's'
        return self.type

    def _sanitize_parent_uuid(self, parent_uuid):
        if parent_uuid is None:
            raise StopIteration
        if isinstance(parent_uuid, str):
            parent_uuid = [parent_uuid]
        for p in parent_uuid:
            try:
                UUID(p, version=4)
            except ValueError:
                continue
            yield p

    def filter(self, field_name, field_value):
        self.filters.append((field_name, field_value))

    def _fetch_params(self, fields, filters, parent_uuid):
        params = {}
        fields_str = ",".join(self.fields + (fields or []))
        filters_str = ",".join(['%s==%s' % (f, json.dumps(v))
                                for f, v in self.filters + (filters or [])])
        parent_uuid_str = ",".join(self.parent_uuid +
                                   list(self._sanitize_parent_uuid(parent_uuid)))
        if fields_str:
            params['fields'] = fields_str
        if filters_str:
            params['filters'] = filters_str
        if parent_uuid_str:
            params['parent_id'] = parent_uuid_str

        return params

    def fetch(self, recursive=1, fields=None, filters=None, parent_uuid=None):
        """
        Get Collection from API server

        @param recursive: level of recursion
        @type recursive: int
        @param fields: list of field names to fetch
        @type fields: [str]
        @param filters: list of filters
        @tpye filters: [(name, value), ...]
        @param parent_uuid: filter by parent_uuid
        @type parent_uuid: v4UUID str or list of v4UUID str
        """

        params = self._fetch_params(fields, filters, parent_uuid)
        data = self.session.get(self.href, **params)

        if not self.type:
            self.data = [Collection(col["link"]["name"],
                                    fetch=recursive - 1 > 0,
                                    recursive=recursive - 1,
                                    **col["link"])
                         for col in data['links']
                         if col["link"]["rel"] == "collection"]
        else:
            self.data = [Resource(self.type,
                                  fetch=recursive - 1 > 0,
                                  recursive=recursive - 1,
                                  **res)
                         for res_type, res_list in data.items()
                         for res in res_list]


class RootCollection(Collection):

    def __init__(self, **kwargs):
        return super(RootCollection, self).__init__('', **kwargs)


class Resource(ResourceBase, UserDict):

    def __init__(self, type, fetch=False, recursive=1, **kwargs):
        """Init an API Resource

        @param type: type of the resource
        @type type: str
        @param fetch: get data from the server
        @type fetch: boolean
        @param recursive: recursive level to fetch resource data
        @param recursion: int

        Either:
        @param uuid: uuid of the resource
        @type uuid: v4UUID str
        Or:
        @param fq_name: fq name of the resource
        @type fq_name: str (domain:project:identifier)
        """
        self.type = type
        path = Path("/" + type)
        fq_name = kwargs.get('fq_name', None)
        uuid = kwargs.get('uuid', None)

        if uuid is not None:
            assert UUID(uuid, version=4)
            path = path / uuid
        elif fq_name is not None:
            uuid = self.session.fqname_to_id(fq_name)
            if uuid is None:
                raise ValueError("%s doesn't exists" % fq_name)
            path = path / uuid
            kwargs["uuid"] = uuid

        if fq_name is not None and isinstance(fq_name, str):
            kwargs["fq_name"] = fq_name.split(":")

        kwargs["path"] = path
        UserDict.__init__(self, **kwargs)
        if path.is_resource and fetch:
            self.fetch(recursive=recursive)
        self.emit('created', self)

    @property
    def href(self):
        return self.session.base_url + str(self.path)

    @property
    def path(self):
        return self.data.get("path")

    @property
    def uuid(self):
        return self.data.get("uuid")

    @property
    def fq_name(self):
        return ":".join(self.data.get("fq_name", self.data.get("to", [])))

    def save(self):
        if self.path.is_collection:
            self.session.post(self.href, data=self.data)
        else:
            self.session.put(self.href, data=self.data)

    def fetch(self, recursive=1):
        """Fetch resource data from the server

        @param recursive: level of recursion for fetching resources
        @type recursive: int
        """
        data = self.session.get(self.href)[self.type]
        # Find other linked resources
        data = self._walk_resource(data, recursive=recursive)
        self.data.update(data)

    def delete(self):
        return self.session.delete(self.href)

    def _walk_resource(self, data, recursive=1):
        for attr, value in list(data.items()):
            if attr.endswith('refs'):
                res_type = "-".join([c for c in attr.split('_')
                                     if c not in ('back', 'refs')])
                for idx, r in enumerate(data[attr]):
                    data[attr][idx]['fq_name'] = data[attr][idx]['to']
                    del data[attr][idx]['to']
                    data[attr][idx] = Resource(res_type,
                                               fetch=recursive - 1 > 0,
                                               recursive=recursive - 1,
                                               **data[attr][idx])
            if type(data[attr]) is dict:
                data[attr] = self._walk_resource(data[attr],
                                                 recursive=recursive)
        return data

    @property
    def back_refs(self):
        """Return back_refs resources of
        the current resource

        @rtype: Resource generator
        """
        for attr, value in self.data.items():
            if attr.endswith(('back_refs', 'loadbalancer_members')):
                for back_ref in value:
                    yield back_ref

    def __str__(self):
        if hasattr(self, 'data'):
            return str(self.data)
        return str({})