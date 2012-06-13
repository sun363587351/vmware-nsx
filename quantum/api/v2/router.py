# Copyright (c) 2012 OpenStack, LLC.
#
# Licensed under the Apache License, Version 2.0 (the 'License');
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an 'AS IS' BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
import urlparse

import routes as routes_mapper
import webob
import webob.dec
import webob.exc

from quantum import manager
from quantum import wsgi
from quantum.api.v2 import base


LOG = logging.getLogger(__name__)
HEX_ELEM = '[0-9A-Fa-f]'
UUID_PATTERN = '-'.join([HEX_ELEM + '{8}', HEX_ELEM + '{4}',
                         HEX_ELEM + '{4}', HEX_ELEM + '{4}',
                         HEX_ELEM + '{12}'])
COLLECTION_ACTIONS = ['index', 'create']
MEMBER_ACTIONS = ['show', 'update', 'delete']
REQUIREMENTS = {'id': UUID_PATTERN, 'format': 'xml|json'}


ATTR_NOT_SPECIFIED = object()

# Note: a default of ATTR_NOT_SPECIFIED indicates that an
# attribute is not required, but will be generated by the plugin
# if it is not specified.  Particularly, a value of ATTR_NOT_SPECIFIED
# is different from an attribute that has been specified with a value of
# None.  For example, if 'gateway_ip' is ommitted in a request to
# create a subnet, the plugin will receive ATTR_NOT_SPECIFIED
# and the default gateway_ip will be generated.
# However, if gateway_ip is specified as None, this means that
# the subnet does not have a gateway IP.

RESOURCE_ATTRIBUTE_MAP = {
    'networks': {
        'id': {'allow_post': False, 'allow_put': False},
        'name': {'allow_post': True, 'allow_put': True},
        'subnets': {'allow_post': True, 'allow_put': True, 'default': []},
        'admin_state_up': {'allow_post': True, 'allow_put': True,
                           'default': True},
        'status': {'allow_post': False, 'allow_put': False},
        'tenant_id': {'allow_post': True, 'allow_put': True},
    },
    'ports': {
        'id': {'allow_post': False, 'allow_put': False},
        'network_id': {'allow_post': True, 'allow_put': False},
        'admin_state_up': {'allow_post': True, 'allow_put': True,
                           'default': True},
        'mac_address': {'allow_post': True, 'allow_put': False,
                        'default': ATTR_NOT_SPECIFIED},
        'fixed_ips_v4': {'allow_post': True, 'allow_put': True,
                         'default': ATTR_NOT_SPECIFIED},
        'fixed_ips_v6': {'allow_post': True, 'allow_put': True,
                         'default': ATTR_NOT_SPECIFIED},
        'host_routes': {'allow_post': True, 'allow_put': True,
                        'default': ATTR_NOT_SPECIFIED},
        'device_id': {'allow_post': True, 'allow_put': True, 'default': ''},
        'tenant_id': {'allow_post': True, 'allow_put': True},
    },
    'subnets': {
        'id': {'allow_post': False, 'allow_put': False},
        'ip_version': {'allow_post': True, 'allow_put': False},
        'network_id': {'allow_post': True, 'allow_put': False},
        'cidr': {'allow_post': True, 'allow_put': False},
        'gateway_ip': {'allow_post': True, 'allow_put': True,
                       'default': ATTR_NOT_SPECIFIED},
        'dns_namesevers': {'allow_post': True, 'allow_put': True,
                           'default': ATTR_NOT_SPECIFIED},
        'additional_host_routes': {'allow_post': True, 'allow_put': True,
                                   'default': ATTR_NOT_SPECIFIED},
    }
}


class Index(wsgi.Application):
    def __init__(self, resources):
        self.resources = resources

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        metadata = {'application/xml': {
                        'attributes': {
                            'resource': ['name', 'collection'],
                            'link': ['href', 'rel'],
                           }
                       }
                   }

        layout = []
        for name, collection in self.resources.iteritems():
            href = urlparse.urljoin(req.path_url, collection)
            resource = {'name': name,
                        'collection': collection,
                        'links': [{'rel': 'self',
                                   'href': href}]}
            layout.append(resource)
        response = dict(resources=layout)
        content_type = req.best_match_content_type()
        body = wsgi.Serializer(metadata=metadata).serialize(response,
                                                            content_type)
        return webob.Response(body=body, content_type=content_type)


class APIRouter(wsgi.Router):

    @classmethod
    def factory(cls, global_config, **local_config):
        return cls(global_config, **local_config)

    def __init__(self, conf, **local_config):
        mapper = routes_mapper.Mapper()
        plugin_provider = manager.get_plugin_provider(conf)
        plugin = manager.get_plugin(plugin_provider)

        # NOTE(jkoelker) Merge local_conf into conf after the plugin
        #                is discovered
        conf.update(local_config)
        col_kwargs = dict(collection_actions=COLLECTION_ACTIONS,
                          member_actions=MEMBER_ACTIONS)

        resources = {'network': 'networks',
                     'subnet': 'subnets',
                     'port': 'ports'}

        def _map_resource(collection, resource, params):
            controller = base.create_resource(collection, resource,
                                              plugin, conf,
                                              params)
            mapper_kwargs = dict(controller=controller,
                                 requirements=REQUIREMENTS,
                                 **col_kwargs)
            return mapper.collection(collection, resource,
                                     **mapper_kwargs)

        mapper.connect('index', '/', controller=Index(resources))
        for resource in resources:
            _map_resource(resources[resource], resource,
                          RESOURCE_ATTRIBUTE_MAP.get(resources[resource],
                                                 dict()))

        super(APIRouter, self).__init__(mapper)
