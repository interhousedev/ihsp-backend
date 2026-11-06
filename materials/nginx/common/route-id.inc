# id.<domain>: Hydra's public endpoints, everything else is the static id app
# (login, consent and logout pages, security pages, Telegram mini app login).
# Hydra is rate-limited per client address (zones: default.conf.template). Clients register
# at api.<domain>/v1/oauth/mcp/register, never at Hydra's own endpoint (it is switched off).
location = /oauth2/register {
    return 404;
}

# Gemini generates its redirect URI per user: teach the client that URI, then let Hydra
# decide. A failed sync never blocks the authorization.
location = /_mcp_redirect_sync {
    internal;
    # An auth_request subrequest has no query of its own: take the client's.
    set $sync_query "";
    if ($request_uri ~ "\?(.*)$") {
        set $sync_query $1;
    }
    proxy_pass_request_body off;
    proxy_set_header Content-Length "";
    include /etc/nginx/ihsp/proxy.inc;
    proxy_pass $up_identity/v1/oauth/mcp/redirect-sync?$sync_query;
}

location = /oauth2/auth {
    include /etc/nginx/ihsp/proxy.inc;
    limit_req zone=ihsp_auth burst=20 nodelay;
    auth_request /_mcp_redirect_sync;
    error_page 500 = @hydra_auth;
    proxy_pass $up_hydra;
}

location @hydra_auth {
    include /etc/nginx/ihsp/proxy.inc;
    proxy_pass $up_hydra;
}

location ~ ^/(oauth2/|\.well-known/|userinfo$) {
    include /etc/nginx/ihsp/proxy.inc;
    limit_req zone=ihsp_auth burst=20 nodelay;
    proxy_pass $up_hydra;
}

location / {
    include /etc/nginx/ihsp/proxy.inc;
    proxy_pass $up_web;
}
