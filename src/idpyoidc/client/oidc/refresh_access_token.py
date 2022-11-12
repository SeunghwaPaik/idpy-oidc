from idpyoidc.client.oauth2 import refresh_access_token
from idpyoidc.message import oidc


class RefreshAccessToken(refresh_access_token.RefreshAccessToken):
    msg_type = oidc.RefreshAccessTokenRequest
    response_cls = oidc.AccessTokenResponse
    error_msg = oidc.ResponseMessage

    def get_authn_method(self):
        _work_condition = self.client_get("service_context").work_condition
        try:
            return _work_condition.behaviour["token_endpoint_auth_method"]
        except KeyError:
            return self.default_authn_method
