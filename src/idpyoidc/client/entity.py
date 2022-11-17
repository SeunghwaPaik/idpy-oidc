import logging
import os
from typing import Optional
from typing import Union

from cryptojwt import KeyJar
from cryptojwt.key_jar import init_key_jar

from idpyoidc.client.client_auth import client_auth_setup
from idpyoidc.client.configure import Configuration
from idpyoidc.client.configure import get_configuration
from idpyoidc.client.defaults import DEFAULT_OAUTH2_SERVICES
from idpyoidc.client.defaults import DEFAULT_OIDC_SERVICES
from idpyoidc.client.service import init_services
from idpyoidc.client.service_context import ServiceContext

logger = logging.getLogger(__name__)

RESPONSE_TYPES2GRANT_TYPES = {
    "code": ["authorization_code"],
    "id_token": ["implicit"],
    "id_token token": ["implicit"],
    "code id_token": ["authorization_code", "implicit"],
    "code token": ["authorization_code", "implicit"],
    "code id_token token": ["authorization_code", "implicit"],
}


def response_types_to_grant_types(response_types):
    _res = set()

    for response_type in response_types:
        _rt = response_type.split(" ")
        _rt.sort()
        try:
            _gt = RESPONSE_TYPES2GRANT_TYPES[" ".join(_rt)]
        except KeyError:
            logger.warning("No such response type combination: {}".format(response_types))
        else:
            _res.update(set(_gt))

    return list(_res)


def _set_jwks(service_context, config: Configuration, keyjar: Optional[KeyJar]):
    _key_conf = config.get("key_conf") or config.conf.get('key_conf')

    if _key_conf:
        keys_args = {k: v for k, v in _key_conf.items() if k != "uri_path"}
        _keyjar = init_key_jar(**keys_args)
        service_context.set_preference("jwks", _keyjar.export_jwks())
    elif keyjar:
        service_context.set_preference("jwks", keyjar.export_jwks())


def set_jwks_uri_or_jwks(service_context, config, jwks_uri, keyjar):
    # lots of different ways to configure the RP's keys
    if jwks_uri:
        service_context.set_preference("jwks_uri", jwks_uri)
    else:
        if config.get("jwks_uri"):
            service_context.set_preference("jwks_uri", jwks_uri)
        else:
            _set_jwks(service_context, config, keyjar)


class Entity(object):

    def __init__(
            self,
            keyjar: Optional[KeyJar] = None,
            config: Optional[Union[dict, Configuration]] = None,
            services: Optional[dict] = None,
            jwks_uri: Optional[str] = "",
            httpc_params: Optional[dict] = None,
            client_type: Optional[str] = "oauth2"
    ):
        self.extra = {}
        if httpc_params:
            self.httpc_params = httpc_params
        else:
            self.httpc_params = {"verify": True}

        config = get_configuration(config)

        if keyjar:
            _kj = keyjar.copy()
        else:
            _kj = None

        self._service_context = ServiceContext(
            keyjar=keyjar, config=config, jwks_uri=jwks_uri, httpc_params=self.httpc_params,
            client_type=client_type, client_get=self.client_get
        )

        if config:
            _srvs = config.conf.get("services")
        else:
            _srvs = None

        if not _srvs:
            if services:
                _srvs = services
            elif client_type == "oauth2":
                _srvs = DEFAULT_OAUTH2_SERVICES
            else:
                _srvs = DEFAULT_OIDC_SERVICES

        self._service = init_services(service_definitions=_srvs, client_get=self.client_get)

        self.setup_client_authn_methods(config)

        jwks_uri = jwks_uri or self._service_context.get("jwks_uri")
        set_jwks_uri_or_jwks(self._service_context, config, jwks_uri, self._service_context.keyjar)

        # Deal with backward compatibility
        self.backward_compatibility(config)

        self._service_context.work_condition.load_conf(config.conf,
                                                       supports=self._service_context.supports())

        self._service_context.construct_uris(self._service_context.issuer,
                                             self._service_context.hash_seed,
                                             config.conf.get("callback"))

    def client_get(self, what, *arg):
        _func = getattr(self, "get_{}".format(what), None)
        if _func:
            return _func(*arg)
        return None

    def get_services(self, *arg):
        return self._service

    def get_service_context(self, *arg):
        return self._service_context

    def get_service(self, service_name, *arg):
        try:
            return self._service[service_name]
        except KeyError:
            return None

    def get_service_by_endpoint_name(self, endpoint_name, *arg):
        for service in self._service.values():
            if service.endpoint_name == endpoint_name:
                return service

        return None

    def get_entity(self):
        return self

    def get_client_id(self):
        _val = self._service_context.work_condition.get_usage('client_id')
        if _val:
            return _val
        else:
            return self._service_context.work_condition.get_preference('client_id')

    def setup_client_authn_methods(self, config):
        self._service_context.client_authn_method = client_auth_setup(
            config.get("client_authn_methods")
        )

    def backward_compatibility(self, config):
        _work_condition = self._service_context.work_condition
        _uris = config.get("redirect_uris")
        if _uris:
             _work_condition.set_preference("redirect_uris", _uris)

        _dir = config.conf.get("requests_dir")
        if _dir:
            _work_condition.set_preference('requests_dir', _dir)

        _pref = config.get("client_preferences", {})
        for key, val in _pref.items():
            _work_condition.set_preference(key, val)

        auth_request_args = config.conf.get("request_args", {})
        if auth_request_args:
            authz_serv = self.get_service('authorization')
            authz_serv.default_request_args.update(auth_request_args)

    def config_args(self):
        res = {}
        for id, service in self._service.items():
            res[id] = {
                "preference": service.supports(),
            }
        res[""] = {
            "preference": self._service_context.work_condition.supports,
        }
        return res

    def get_callback_uris(self):
        res = []
        for service in self._service.values():
            for _callback in service.callback_uris():
                _uri = self._service_context.work_condition.get_preference(_callback)
                if _uri:
                    res[_callback] = _uri
        # res.extend(self._service_context.work_condition.callback_uris)
        return res

    def prefers(self):
        return self._service_context.work_condition.prefers()

    def use(self):
        return self._service_context.work_condition.get_use()